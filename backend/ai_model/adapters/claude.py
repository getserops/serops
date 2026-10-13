"""
Adapter for Anthropic Claude API.
"""

import anthropic
import logging
from .base import BaseProviderAdapter, AIServiceError

logger = logging.getLogger(__name__)

# Default model — verified against platform.claude.com 2026-08-30.
# Sonnet 5 is the current balanced tier; older 3.x IDs (previously
# seeded as ``claude-3-sonnet``) return 404 from the current API.
DEFAULT_MODEL = 'claude-sonnet-5'


# Minimum static-prefix size (tokens) below which Claude Sonnet 5's
# prompt cache silently skips write. Estimated by chars-per-token
# heuristic (~4). Under this size, ``cache_control`` is a no-op —
# we still send it (harmless) but log a hint so ops can spot when a
# refactor accidentally shrinks the prefix below the threshold.
_CLAUDE_CACHE_MIN_CHARS = 4096  # ~1024 tokens


def _extract_text(content) -> str:
    """Join the TEXT blocks of a Claude response, skipping the rest.

    `content[0].text` is wrong for any response that leads with a non-text
    block. Extended thinking puts a ThinkingBlock first — it carries
    `.thinking`, not `.text` — so indexing block zero raised
    "'ThinkingBlock' object has no attribute 'text'", the adapter reported a
    failure, and SerOps silently fell back to its secondary provider. Observed
    on claude-sonnet via the batch-analysis path: Claude was unusable while
    the API key and quota were both fine.

    Tool-use and redacted-thinking blocks have the same shape problem, so the
    fix is to select text blocks rather than assume a position.
    """
    if not content:
        return ''
    parts = [getattr(block, 'text', None) for block in content]
    return ''.join(p for p in parts if isinstance(p, str))


class ClaudeAdapter(BaseProviderAdapter):
    def generate(self, prompt: str, config: dict, api_key: str = None,
                 system_prefix: str = None) -> tuple:
        """
        Generate text using Anthropic Claude API.

        When ``system_prefix`` is supplied, it's sent as the ``system``
        parameter with ``cache_control={"type": "ephemeral"}`` — Sonnet 5's
        prompt cache returns cached prefix tokens at 10% of list price
        (5-min TTL, refreshed on every hit). See platform.claude.com
        prompt-caching docs.

        Returns:
            tuple: (response_text, error, tokens_input, tokens_output)
        """
        try:
            if not api_key:
                return None, AIServiceError('auth_error', 'AUTH_MISSING', 'No API Key provided'), 0, 0

            # Explicit request timeout — SDK default is 600s. Too long
            # for a celery worker to hang on a wedged endpoint.
            #
            # ``workspace_id`` (from OrganisationAPIKey.extra_config) is
            # required for Anthropic workspace-scoped keys — otherwise
            # every request fails HTTP 400 "This API key is not scoped
            # to a workspace, so this request must include the
            # anthropic-workspace-id header". E31-8 fix.
            default_headers = {}
            workspace_id = config.get('workspace_id')
            if workspace_id:
                default_headers['anthropic-workspace-id'] = workspace_id

            client = anthropic.Anthropic(
                api_key=api_key,
                timeout=config.get('timeout_seconds', 120),
                default_headers=default_headers or None,
            )
            model_name = config.get('default_model', DEFAULT_MODEL)

            # Build create() kwargs — system param only when we have a
            # prefix to cache. Sending an empty system block would be
            # noise on the wire.
            create_kwargs = {
                'model': model_name,
                # 8192 was not enough headroom for a real batch analysis, and
                # the shortfall is expensive: a response that hits the ceiling
                # is reported as TRUNCATED and the WHOLE analysis is discarded
                # — zero issues, empty narrative, tokens already paid for.
                # Observed on the chaos suite the moment container-lifecycle
                # data made answers richer: a five-issue analysis stopped at
                # ~7997 output tokens and was thrown away entirely.
                # Sonnet supports far more; a higher ceiling only costs money
                # when the model actually uses it.
                'max_tokens': config.get('max_tokens', 16384),
                'messages': [{"role": "user", "content": prompt}],
            }
            if system_prefix:
                if len(system_prefix) < _CLAUDE_CACHE_MIN_CHARS:
                    logger.info(
                        "Claude system_prefix is %s chars (~%s tokens) — below Sonnet 5 "
                        "cache-write threshold (~1024 tokens). cache_control accepted but "
                        "will not create a cached prefix. If this is a regression, restore "
                        "the removed prompt content.",
                        len(system_prefix), len(system_prefix) // 4,
                    )
                # cache_control on the system block flags it for
                # ephemeral (5-min TTL) caching. Subsequent calls
                # with the same prefix within the window pay 10% of
                # list price on those input tokens.
                create_kwargs['system'] = [{
                    'type': 'text',
                    'text': system_prefix,
                    'cache_control': {'type': 'ephemeral'},
                }]

            message = client.messages.create(**create_kwargs)

            # Extract token usage
            tokens_input = getattr(message.usage, 'input_tokens', 0)
            tokens_output = getattr(message.usage, 'output_tokens', 0)
            logger.debug(f"Claude token usage: {tokens_input} input, {tokens_output} output")

            # Check for truncation via stop_reason
            if message.stop_reason == 'max_tokens':
                partial_text = ''
                if message.content:
                    partial_text = _extract_text(message.content)
                logger.warning(
                    f"Claude response truncated (max_tokens) for model {model_name}. "
                    f"Tokens: {tokens_input} in, {tokens_output} out"
                )
                return None, AIServiceError(
                    'truncated', 'TRUNCATED',
                    'AI response was truncated (hit output token limit).',
                    'Try re-analyzing with a model that supports longer outputs.',
                    raw_error=partial_text[:2000],
                    partial_text=partial_text,
                ), tokens_input, tokens_output

            # Extract text from response
            response_text = _extract_text(message.content)

            return response_text, None, tokens_input, tokens_output

        except Exception as e:
            logger.error(f"Claude Adapter Error: {e}")
            return None, self.normalize_error(e), 0, 0

    def normalize_error(self, e: Exception) -> AIServiceError:
        msg = str(e).lower()
        # Timeout — anthropic SDK raises anthropic.APITimeoutError.
        if 'timeout' in msg or 'timed out' in msg:
            return AIServiceError.from_type('timeout', raw_error=str(e)[:500])
        # Rate limit
        if '429' in msg or 'rate' in msg:
            return AIServiceError.from_type('quota_exceeded', raw_error=str(e)[:500])
        # Workspace-scoped key missing header (Anthropic 400 with a
        # very specific message). Surfaces as auth_error but with a
        # more actionable hint so users know to set ``workspace_id``
        # on their OrganisationAPIKey.extra_config.
        if 'anthropic-workspace-id' in msg or 'not scoped to a workspace' in msg:
            return AIServiceError(
                'auth_error', 'AUTH_WORKSPACE_MISSING',
                'Anthropic API key is workspace-scoped but no workspace_id '
                'was configured. Set workspace_id in the API key '
                'settings (OrganisationAPIKey.extra_config.workspace_id).',
                raw_error=str(e)[:500],
            )
        # Auth
        if '401' in msg or 'auth' in msg or 'api key' in msg:
            return AIServiceError.from_type('auth_error', raw_error=str(e)[:500])
        # Overloaded — Claude Sonnet returns 529 during peak load; the
        # right response is a short backoff, not a fallback to another
        # provider. Distinguishing this from quota_exceeded matters
        # because we shouldn't count overload against user quota.
        if '529' in msg or 'overloaded' in msg:
            return AIServiceError.from_type('overloaded', raw_error=str(e)[:500])
        # 5xx server errors from the API
        if any(code in msg for code in ('500', '502', '503', '504')) or 'internal server error' in msg:
            return AIServiceError.from_type('server_error', raw_error=str(e)[:500])
        # Network layer
        if 'connection' in msg or 'network' in msg or 'name or service not known' in msg:
            return AIServiceError.from_type('network_error', raw_error=str(e)[:500])
        return AIServiceError('unknown', 'UNKNOWN_ERROR', f'Provider error: {str(e)[:100]}', raw_error=str(e)[:500])
