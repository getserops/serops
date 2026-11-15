"""
AI cost-visibility tracking.

Records every AI API call (tokens + estimated cost) per organisation so
admins can see what each model is costing them. This is observability —
there is no quota enforcement, no blocking, no billing logic.

Pricing lookup (2026-08-31): resolves via the ``AIModelProvider``
DB row (``price_input_per_million`` / ``price_output_per_million``).
Previous implementation hardcoded a ``PRICING_PER_MILLION_TOKENS``
dict in this module — that dict fell out of sync with model IDs
during the Day 1 rework and produced wrong cost reports. Keeping
prices on the provider row makes drift impossible.

Model name comes from the adapter response (the exact ID sent to
the provider), while our DB key is the *provider* name (``gemini``,
``claude``, …). Resolution walks: exact-match on ``default_model``
first, then falls back to searching by provider name substring
inside the model ID (``gemini-3.5-flash`` contains ``gemini``).
Unknown models fall back to a conservative mid-tier estimate so
nothing is silently reported as free.

Known Anthropic model IDs (2026-11) are priced from ``KNOWN_MODEL_PRICES``
first: one provider row carries one price, and an organisation that
points the Claude row at Opus or Haiku would otherwise be charged at
Sonnet's rate (Opus 5.5 is twice that, Haiku 5.5 a twentieth).

Prompt caching: Anthropic bills cache writes at 1.25x the input price
(5-minute TTL, the only one SerOps uses) and cache reads at a fraction
that depends on the model. ``tokens_input`` may be a ``PromptTokens``
carrying those shares; a plain int is priced as uncached input.
"""

import logging
from decimal import Decimal

from django.db.models import Count, Sum

from .models import AITokenUsage
from .token_counts import cache_parts

logger = logging.getLogger(__name__)


# Conservative fallback used only when the model ID doesn't map to a
# known ``AIModelProvider`` row. Prefer over-reporting cost to under-
# reporting — silent zeros hide real spend.
_FALLBACK_PRICE_INPUT = Decimal('0.02')
_FALLBACK_PRICE_OUTPUT = Decimal('0.08')

# Anthropic list prices, USD per 1M tokens: (input, output, cache-read
# ratio of the input price). Source: Anthropic's model and pricing
# pages, 2026-11. Haiku 5.5 is the price for prompts up to 100K tokens
# (SerOps prompts stay well under it).
KNOWN_MODEL_PRICES = {
    'claude-opus-5-5': (Decimal('4.00'), Decimal('20.00'), Decimal('0.05')),
    'claude-sonnet-5-5': (Decimal('2.00'), Decimal('10.00'), Decimal('0.10')),
    'claude-haiku-5-5': (Decimal('0.10'), Decimal('0.50'), Decimal('0.10')),
    'claude-opus-5': (Decimal('5.00'), Decimal('25.00'), Decimal('0.10')),
    'claude-sonnet-5': (Decimal('2.00'), Decimal('10.00'), Decimal('0.10')),
}
CACHE_WRITE_RATIO = Decimal('1.25')
DEFAULT_CACHE_READ_RATIO = Decimal('0.10')


class AITokenUsageService:
    """Helpers for recording and aggregating AI cost data."""

    @staticmethod
    def _model_id(model_name):
        """The model ID behind ``model_name``.

        The analysis task records the *provider* that answered (``claude``),
        not the model, so a provider name resolves to that row's model.
        """
        name = (model_name or '').strip().lower()
        if name in KNOWN_MODEL_PRICES:
            return name
        try:
            from org_settings.models import AIModelProvider
            row = AIModelProvider.objects.filter(name=name).only('default_model').first()
            if row and row.default_model:
                return row.default_model.strip().lower()
        except Exception as exc:
            logger.warning("Provider lookup failed for %r: %s", model_name, exc)
        return name

    @staticmethod
    def _resolve_provider_prices(model_name):
        """Return ``(price_in, price_out)`` Decimals for the given model ID.

        Looks up the ``AIModelProvider`` whose ``default_model`` matches
        exactly, then falls back to substring-matching the provider
        ``name`` inside the model ID (so both ``gemini-3.5-flash`` and
        ``gemini-3.7-flash`` route to the ``gemini`` row's prices when
        the exact ID isn't seeded). Returns the module fallback if
        neither lookup succeeds.

        Lazy import of the provider model avoids Django app-registry
        ordering issues at import time.
        """
        known = KNOWN_MODEL_PRICES.get(AITokenUsageService._model_id(model_name))
        if known:
            return known[0], known[1]
        try:
            from org_settings.models import AIModelProvider

            provider = AIModelProvider.objects.filter(default_model=model_name).first()
            if not provider and model_name:
                # Substring fallback: e.g. 'gemini-3.7-flash' -> the
                # 'gemini' provider row. Iterates providers, cheapest
                # possible query since the catalog is <10 rows.
                for candidate in AIModelProvider.objects.all():
                    if candidate.name and candidate.name in model_name.lower():
                        provider = candidate
                        break

            if provider is not None:
                # A provider row with both prices at 0 is legitimate
                # (Ollama = local inference; cost is real electrons
                # not dollars). Return the row's prices as-is rather
                # than falling through to the module fallback, which
                # would misreport free local inference as $0.02/M.
                return (
                    Decimal(provider.price_input_per_million),
                    Decimal(provider.price_output_per_million),
                )
        except Exception as exc:
            # A pricing lookup failing must never break AI analysis —
            # this whole module is cost observability, not billing.
            logger.warning("Provider pricing lookup failed for %r: %s", model_name, exc)

        return _FALLBACK_PRICE_INPUT, _FALLBACK_PRICE_OUTPUT

    @classmethod
    def _estimate_cost(cls, model_name: str, tokens_input: int, tokens_output: int) -> Decimal:
        price_in, price_out = cls._resolve_provider_prices(model_name)
        known = KNOWN_MODEL_PRICES.get(cls._model_id(model_name))
        read_ratio = known[2] if known else DEFAULT_CACHE_READ_RATIO
        uncached, cache_write, cache_read = cache_parts(tokens_input)
        million = Decimal(1_000_000)
        cost_in = (
            Decimal(uncached) + Decimal(cache_write) * CACHE_WRITE_RATIO + Decimal(cache_read) * read_ratio
        ) / million * price_in
        cost_out = (Decimal(tokens_output) / million) * price_out
        return cost_in + cost_out

    @classmethod
    def log_usage(
        cls,
        organisation,
        batch,
        tokens_input: int,
        tokens_output: int,
        model_name: str,
        usage_type: str = 'batch_analysis',
    ) -> AITokenUsage:
        """Record one AI API call.

        Returns the created AITokenUsage row. Never raises — cost tracking
        must not break AI analysis if anything is wrong with the inputs.
        """
        try:
            cost = cls._estimate_cost(model_name, tokens_input, tokens_output)
            usage = AITokenUsage.objects.create(
                organisation=organisation,
                batch=batch,
                model_name=model_name,
                tokens_input=int(tokens_input),
                tokens_output=int(tokens_output),
                tokens_total=int(tokens_input) + int(tokens_output),
                cost_usd=cost,
                usage_type=usage_type,
            )
            logger.info(
                f"AI usage logged for {organisation.name}: "
                f"{usage.tokens_total} tokens, ${cost:.6f} ({model_name})"
            )
            return usage
        except Exception as e:
            logger.warning(f"Could not log AI usage for {organisation}: {e}")
            return None

    @classmethod
    def estimate_tokens(cls, text: str) -> int:
        """Rough token count (~4 chars per token) for input length budgeting."""
        if not text:
            return 0
        return len(text) // 4

    @classmethod
    def get_usage_summary(cls, organisation, start_date=None, end_date=None) -> dict:
        """Aggregate usage stats for an organisation within an optional date range."""
        qs = AITokenUsage.objects.filter(organisation=organisation)
        if start_date:
            qs = qs.filter(timestamp__gte=start_date)
        if end_date:
            qs = qs.filter(timestamp__lte=end_date)

        stats = qs.aggregate(
            total_tokens=Sum('tokens_total'),
            total_cost=Sum('cost_usd'),
            total_calls=Count('id'),
        )
        return {
            'total_tokens': stats['total_tokens'] or 0,
            'total_cost_usd': float(stats['total_cost'] or 0),
            'total_calls': stats['total_calls'] or 0,
        }
