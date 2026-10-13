"""
AI Service Module

Provides unified interface for AI providers via the adapter plugin system.
All provider-specific logic lives in adapters (ai_model/adapters/).

Keys are resolved from ``OrganisationAPIKey`` exclusively. The env-var
fallback that used to live in :func:`get_api_key_for_org` was removed
2026-08-30 — on multi-tenant self-host instances a shared env-var key
would silently mix quota/billing across orgs, and it made the "you
haven't set up a provider yet" state indistinguishable from "you've
set one up but the key is invalid". Callers that get ``(None, None)``
back should raise :class:`~ai_model.exceptions.NoAIProviderConfigured`.
"""

import logging
import random
import time

from .adapters.base import AIServiceError

logger = logging.getLogger(__name__)


def classify_error(error_msg: str) -> str:
    """Classify an error message into a known error type"""
    error_lower = error_msg.lower()

    if '429' in error_msg or 'quota' in error_lower or 'rate limit' in error_lower:
        return 'quota_exceeded'
    elif '401' in error_msg or '403' in error_msg or 'unauthorized' in error_lower or 'api key' in error_lower:
        return 'auth_error'
    elif 'timeout' in error_lower or 'timed out' in error_lower:
        return 'timeout'
    elif 'connection' in error_lower or 'network' in error_lower or 'refused' in error_lower:
        return 'network_error'
    elif 'blocked' in error_lower or 'safety' in error_lower or 'harmful' in error_lower:
        return 'content_blocked'
    else:
        return 'unknown'


# =============================================================================
# API Key Management
# =============================================================================

def get_api_key_for_org(organisation, provider_name: str) -> tuple:
    """Resolve the API key + base URL + extra_config for an org's provider.

    Returns ``(api_key, base_url, extra_config)``; any of the first two
    may be ``None``. ``extra_config`` is always a dict (possibly empty).

    Keys come from ``OrganisationAPIKey`` only. There is no env-var
    fallback: on multi-tenant self-host instances a shared env-var key
    would silently pool quota/billing across orgs, and the onboarding
    wizard needs to be able to distinguish "no key configured yet"
    from "key configured but rejected by provider" — an env-var
    fallback collapses both cases.

    ``extra_config`` carries provider-specific auth quirks (e.g. the
    Anthropic ``workspace_id`` required for workspace-scoped keys —
    without it the API returns HTTP 400 with an "API key is not
    scoped to a workspace" error).

    Ollama-style keyless providers legitimately return ``(None, url, {})``
    when no ``OrganisationAPIKey`` row is stored; adapters that don't
    need a key handle that case themselves.
    """
    if not organisation:
        return None, None, {}

    try:
        from org_settings.models import OrganisationAPIKey, AIModelProvider
        from org_settings.encryption import decrypt_api_key

        provider = AIModelProvider.objects.filter(name=provider_name).first()
        if not provider:
            return None, None, {}

        api_key_obj = OrganisationAPIKey.objects.filter(
            organisation=organisation,
            provider=provider,
            is_active=True,
        ).first()

        if not api_key_obj:
            return None, None, {}

        decrypted = None
        if api_key_obj.api_key:
            decrypted = decrypt_api_key(api_key_obj.api_key)

        return decrypted, api_key_obj.base_url, api_key_obj.extra_config or {}
    except Exception as e:
        logger.warning(f"Could not fetch org API key for {provider_name}: {e}")
        return None, None, {}


def get_org_ai_config(organisation):
    """Return the org's AI provider configuration.

    Returns ``(primary_provider, fallback_provider, use_custom_keys)``.
    ``primary_provider`` is ``None`` when the org hasn't picked one —
    callers must handle that (typically by raising
    ``NoAIProviderConfigured``) rather than silently defaulting to a
    provider the user never chose. That silent-default behaviour was
    the old failure mode: an org with no AI settings would suddenly
    burn tokens against a global default without opting in.
    """
    try:
        from org_settings.models import OrganisationAISettings

        settings = OrganisationAISettings.objects.filter(
            organisation=organisation
        ).select_related('default_provider', 'fallback_provider').first()

        if settings:
            primary = settings.default_provider.name if settings.default_provider else None
            fallback = settings.fallback_provider.name if settings.fallback_provider else None
            return primary, fallback, settings.use_custom_keys
    except Exception as e:
        logger.warning(f"Could not fetch org AI settings: {e}")

    return None, None, False


# =============================================================================
# Retry policy (RCA audit finding #2, PR-AUDIT5)
# =============================================================================

# Error types the retry loop treats as transient. Everything else
# (auth, content_blocked, truncated, quota_exceeded, provider_not_supported)
# is either permanent-until-user-action or a per-day quota that
# retrying will never fix — retrying those just wastes wall clock.
_RETRYABLE_ERROR_TYPES = frozenset({
    'server_error',   # provider 5xx (Gemini 503, Claude 529, etc.)
    'overloaded',     # provider capacity pressure
    'network_error',  # transient connection failure
    'timeout',        # request timed out — retry with fresh budget
})

# Two retries → three total attempts. Enough to survive typical
# provider capacity spikes (which usually last <30s) without holding
# the batch task for so long that Celery worker starves.
_MAX_RETRIES = 2

# Exponential backoff base + cap. Values chosen to sleep 2 s / 4 s
# between attempts, giving ~6 s total added wall clock in the worst
# case. Small jitter avoids retry-storm alignment across parallel
# batches.
_BACKOFF_BASE_SECONDS = 2.0
_BACKOFF_MAX_SECONDS = 8.0


def _should_retry(error) -> bool:
    """Return True when the error is transient enough to retry."""
    if error is None:
        return False
    return getattr(error, 'error_type', None) in _RETRYABLE_ERROR_TYPES


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with light jitter. ``attempt`` is 0-indexed."""
    base = _BACKOFF_BASE_SECONDS * (2 ** attempt)
    return min(base, _BACKOFF_MAX_SECONDS) + random.uniform(0, 0.5)


def _generate_with_retry(adapter, prompt, config, api_key, system_prefix, provider_name):
    """Call ``adapter.generate`` with retry on transient errors.

    Returns the ``(text, error, tokens_input, tokens_output)`` shape the
    adapters return. Token counts from the FIRST attempt are surfaced
    when we do end up retrying (some providers charge for the failed
    call — we don't want to lose that accounting).
    """
    first_tokens = (0, 0)
    error = None
    for attempt in range(_MAX_RETRIES + 1):
        text, error, tokens_in, tokens_out = adapter.generate(
            prompt, config, api_key=api_key, system_prefix=system_prefix,
        )
        if attempt == 0:
            first_tokens = (tokens_in, tokens_out)
        if text is not None or not _should_retry(error):
            return text, error, tokens_in, tokens_out
        if attempt < _MAX_RETRIES:
            delay = _backoff_delay(attempt)
            logger.warning(
                'ai_service: %s returned %s on attempt %d/%d; '
                'retrying after %.1fs',
                provider_name, getattr(error, 'code', 'unknown'),
                attempt + 1, _MAX_RETRIES + 1, delay,
            )
            time.sleep(delay)
    # Exhausted retries — return the LAST error with the FIRST attempt's
    # token counts (Gemini + OpenAI both bill on rejected requests).
    return None, error, first_tokens[0], first_tokens[1]


# =============================================================================
# Unified Interface (Plugin System)
# =============================================================================

def generate_text_unified(prompt, provider="gemini", model=None, api_key=None, base_url=None,
                          system_prefix=None, extra_config=None):
    """
    Generate text using any supported provider via the Plugin System.

    Strategy:
    1. Look up AIModelProvider in DB by name.
    2. Get config (DB defaults + override args).
    3. Load Adapter via Registry.
    4. Execute generation.

    Args:
        prompt: The per-call dynamic content.
        provider / model / api_key / base_url: routing config.
        system_prefix: Optional stable prefix for caching-aware adapters
            (see BaseProviderAdapter.generate docstring).
        extra_config: Optional per-org provider-specific config dict
            (e.g. ``{"workspace_id": "..."}`` for Anthropic workspace-
            scoped keys). Merged INTO the adapter config after DB
            defaults so per-org values win over provider defaults.

    Returns:
        tuple: (response_text, error, tokens_input, tokens_output)
               Returns (None, error, 0, 0) on failure
    """
    from org_settings.models import AIModelProvider
    from .adapters.registry import AdapterRegistry

    provider_name = provider.lower()

    try:
        # 1. Fetch DB Configuration
        provider_obj = AIModelProvider.objects.filter(name=provider_name).first()

        if not provider_obj:
            logger.error(f"Provider '{provider_name}' not found in DB.")
            return None, AIServiceError.from_type('provider_not_supported', f"Provider '{provider_name}' not registered"), 0, 0

        # 2. Prepare Config Dictionary. Per-org ``extra_config`` layered
        # last so a workspace_id (or any future auth-quirk field) set
        # on the OrganisationAPIKey overrides provider-level defaults.
        config = {
            'name': provider_obj.name,
            'api_base_url': base_url or provider_obj.api_base_url,
            'default_model': model or provider_obj.default_model,
            **provider_obj.rate_limits,
            **provider_obj.circuit_config,
            **(extra_config or {}),
        }

        # 3. Load Adapter
        adapter_class = provider_obj.adapter_class
        try:
            adapter = AdapterRegistry.get_adapter(adapter_class)
        except Exception as e:
            logger.error(f"Failed to load adapter {adapter_class} for {provider_name}: {e}")
            return None, AIServiceError.from_type('unknown', f"Adapter Error: {str(e)}"), 0, 0

        # 4. Execute — with retry on transient provider errors.
        # RCA audit finding #2 (PR-AUDIT5). Before this, a single
        # Gemini 503 (real Google capacity pressure) or a Claude
        # 529 overloaded response failed the batch immediately and
        # the operator had to click Reanalyze manually. Now we
        # transparently retry up to 2 times with exponential backoff
        # for known-transient error classes.
        response_text, error, tokens_input, tokens_output = _generate_with_retry(
            adapter, prompt, config, api_key, system_prefix, provider_name,
        )

        if error:
            # Pass the adapter's error through UNCHANGED.
            #
            # This used to rebuild it as
            # ``AIServiceError.from_type(error.error_type, ...)``, which threw
            # away everything the adapter had worked out and replaced it with
            # the generic ERROR_TYPES entry for that type:
            #
            #   * the partial body of a truncated response, so the salvage in
            #     ``analyze_batch`` could never fire — the response was
            #     discarded whole even after the adapter had preserved it;
            #   * adapter-specific codes and hints. Claude's
            #     AUTH_WORKSPACE_MISSING, which names ``workspace_id`` as the
            #     thing to set, degraded to a bare AUTH_ERROR whose advice is
            #     "check if API key is valid" — pointing the operator at a key
            #     that was fine.
            #
            # Adapters already return AIServiceError; normalise only if one
            # somehow returns something else.
            if not isinstance(error, AIServiceError):
                error = AIServiceError.from_type('unknown', str(error))
            return None, error, tokens_input, tokens_output

        return response_text, None, tokens_input, tokens_output

    except Exception as e:
        logger.exception(f"Unified generation failed for {provider_name}: {e}")
        return None, AIServiceError.from_type('unknown', str(e)), 0, 0


def generate_with_fallback(prompt, primary="gemini", fallback="deepseek",
                          primary_key=None, fallback_key=None,
                          system_prefix=None):
    """
    Generate text with smart fallback using circuit breaker awareness.

    Strategy:
    1. Check if primary circuit is OPEN -> skip to fallback immediately
    2. Try primary provider
    3. On quota/rate error -> fallback automatically
    4. Track success/failure for circuit state

    Args:
        system_prefix: forwarded to both primary and fallback adapters
            so the fallback path also benefits from prompt caching.

    Returns:
        tuple: (response_text, error) where error is AIServiceError or None
               If both fail, returns the error from the fallback attempt.
    """
    # --- Check if primary circuit is OPEN -> skip to fallback ---
    try:
        from .circuit_breaker import AICircuitBreaker
        primary_circuit = AICircuitBreaker(primary)
        can_use_primary, reason = primary_circuit.can_execute()

        if not can_use_primary and fallback:
            logger.info(f"Primary {primary} circuit {reason}, using fallback {fallback}")
            response, error, _, _ = generate_text_unified(
                prompt, provider=fallback, api_key=fallback_key,
                system_prefix=system_prefix,
            )
            if response is not None:
                return response, None
            return None, error
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Circuit check failed: {e}")

    # --- Try primary model ---
    response, error, _, _ = generate_text_unified(
        prompt, provider=primary, api_key=primary_key,
        system_prefix=system_prefix,
    )

    if response is not None:
        return response, None

    # --- Primary failed, check if we should fallback ---
    if not fallback:
        return None, error

    error_code = error.code if error else 'unknown'
    logger.warning(f"Primary {primary} failed ({error_code}). Trying fallback {fallback}...")

    # Try fallback
    response, fallback_error, _, _ = generate_text_unified(
        prompt, provider=fallback, api_key=fallback_key,
        system_prefix=system_prefix,
    )

    if response is not None:
        return response, None

    # Both failed
    fallback_code = fallback_error.code if fallback_error else 'N/A'
    logger.error(f"Both {primary} ({error_code}) and {fallback} ({fallback_code}) failed")

    if error and error.error_type != 'auth_error':
        return None, error
    return None, fallback_error or error


def generate_for_organisation(prompt, organisation, model=None, system_prefix=None):
    """Generate text using the org's configured AI provider.

    Main entry point for org-aware AI generation with token tracking.
    Returns ``(response_text, provider_used, error, tokens_input, tokens_output)``;
    on failure returns ``(None, None, error, 0, 0)``.

    Args:
        system_prefix: Optional stable static prompt prefix. Passed to
            the adapter which routes it to the provider's caching
            path (Claude ``cache_control``, OpenAI/DeepSeek system
            message). Batch-analysis callers pass this; chat callers
            leave it None.

    Raises :class:`~ai_model.exceptions.NoAIProviderConfigured` if the
    org has no ``default_provider`` set on its ``OrganisationAISettings``.
    Callers (batch analysis tasks, on-demand chat views) should catch
    this and surface a "no AI provider configured — set one in Settings"
    message rather than a generic AUTH error.
    """
    from .exceptions import NoAIProviderConfigured

    primary_provider, fallback_provider, _ = get_org_ai_config(organisation)

    if not primary_provider:
        raise NoAIProviderConfigured(
            f"Organisation {getattr(organisation, 'id', '?')} has no AI provider configured "
            "(OrganisationAISettings.default_provider is unset)."
        )

    # Q3.3 — cost cap pre-flight. Raises BudgetExceeded when the
    # org's calendar-month AITokenUsage.cost_usd already exceeds
    # ``monthly_budget_usd``. Cheap when no budget is set (fast-
    # path in BudgetTracker.check_budget). Callers (batch pipeline,
    # chat) catch and degrade to rule-based issue creation.
    try:
        from .budget import BudgetTracker
        BudgetTracker.enforce(organisation)
    except Exception as _budget_exc:
        # BudgetExceeded is expected — re-raise to caller.
        # Any other exception (tracker itself broken) is swallowed —
        # cost visibility failure must NEVER block AI calls.
        from .budget import BudgetExceeded
        if isinstance(_budget_exc, BudgetExceeded):
            raise
        logger.warning('BudgetTracker.enforce raised non-budget exc: %s', _budget_exc)

    primary_key, primary_url, primary_extra = get_api_key_for_org(organisation, primary_provider)
    if fallback_provider:
        fallback_key, fallback_url, fallback_extra = get_api_key_for_org(organisation, fallback_provider)
    else:
        fallback_key, fallback_url, fallback_extra = None, None, {}

    # Try primary provider
    response, error, tokens_input, tokens_output = generate_text_unified(
        prompt,
        provider=primary_provider,
        model=model,
        api_key=primary_key,
        base_url=primary_url,
        system_prefix=system_prefix,
        extra_config=primary_extra,
    )

    if response is not None:
        return response, primary_provider, None, tokens_input, tokens_output

    # A truncated response is NOT a provider failure — the primary answered,
    # it just ran out of room. Falling back would spend a second paid call to
    # replace an answer that is mostly complete and, when the fallback
    # succeeded, silently swap providers for a batch that already had a usable
    # diagnosis. Return it so ``analyze_batch`` can salvage the partial body.
    if error is not None and getattr(error, 'code', None) == 'TRUNCATED':
        logger.warning(
            'Primary provider %s truncated its response; not falling back — '
            'the partial analysis is salvageable.', primary_provider,
        )
        return None, primary_provider, error, tokens_input, tokens_output

    # Try fallback if configured
    if fallback_provider:
        logger.warning(f"Primary provider {primary_provider} failed for org, trying fallback {fallback_provider}")

        response, fallback_error, tokens_input, tokens_output = generate_text_unified(
            prompt,
            provider=fallback_provider,
            api_key=fallback_key,
            base_url=fallback_url,
            system_prefix=system_prefix,
            extra_config=fallback_extra,
        )

        if response is not None:
            return response, fallback_provider, None, tokens_input, tokens_output

        # Both failed. Report the PRIMARY's error, not the fallback's.
        #
        # This used to `return fallback_error or error`, which discarded the
        # real cause. Observed: Gemini returned 429 RESOURCE_EXHAUSTED (free
        # tier, 20 requests/day) and the configured fallback then failed auth
        # because its key was a leftover placeholder. The batch recorded
        # "FAILED (AUTH_ERROR)", sending the operator to check the key on a
        # provider that was not even the one they had selected — while the
        # actual problem, an exhausted quota on their primary, went unreported.
        #
        # The primary is the provider the operator chose, so its failure is
        # the actionable one. The fallback's code is appended so a broken
        # fallback is still visible rather than silently swallowed.
        if error is not None:
            if fallback_error is not None:
                error.message = (
                    f'{error.message} Fallback provider '
                    f'{fallback_provider} also failed ({fallback_error.code}).'
                )
            # Token counts are the FALLBACK attempt's, since they were
            # reassigned above. Either way they must not be zeroed: providers
            # bill for failed and truncated calls, and ``analyze_batch``'s
            # failure branch logs usage from these values — so hardcoding 0
            # meant a run of failures cost real money that never appeared in
            # usage reporting or counted against the org's monthly budget.
            return None, None, error, tokens_input, tokens_output

        return None, None, fallback_error, tokens_input, tokens_output

    return None, None, error, tokens_input, tokens_output
