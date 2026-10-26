"""Tests for the AI cost-hygiene pass (Commit 1 of the audit follow-up).

Three concerns, one test module:

1. **Pricing lookup** — moved from a hardcoded module dict to columns
   on ``AIModelProvider``. Verify it resolves correctly for known
   models, degrades to substring match for unknown variants, and
   falls through to a conservative default when the row is missing.

2. **Severity filter** — non-destructive helper `_filter_logs_for_ai`
   that drops INFO/DEBUG before Smart Aggregation. Verify keeps
   correct levels, drops correct levels, and catches
   error-shaped-body-with-wrong-level (log-shipper edge case).

3. **preprocess_logs deletion** — confirm the standalone task is
   gone (module attribute lookup fails). The manual-trigger view now
   goes straight to ``analyze_batch``.
"""

from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import SimpleTestCase, TestCase

from ai_model.tasks import _filter_logs_for_ai
from ai_model.usage_tracking import AITokenUsageService


class FilterLogsForAITest(SimpleTestCase):
    """Non-destructive severity filter — no DB, no mocks needed."""

    def _log(self, level, message='irrelevant'):
        return {'level': level, 'message': message, 'component': 'svc', 'timestamp': ''}

    def test_keeps_error_level(self):
        logs = [self._log('ERROR', 'boom')]
        self.assertEqual(_filter_logs_for_ai(logs), logs)

    def test_keeps_warning_critical_fatal_alert(self):
        for lvl in ('WARNING', 'CRITICAL', 'FATAL', 'ALERT', 'EMERG', 'SEVERE'):
            with self.subTest(level=lvl):
                logs = [self._log(lvl, 'x')]
                self.assertEqual(len(_filter_logs_for_ai(logs)), 1, f"{lvl} should be kept")

    def test_drops_info_and_debug(self):
        logs = [self._log('INFO', 'ok'), self._log('DEBUG', 'noise')]
        self.assertEqual(_filter_logs_for_ai(logs), [])

    def test_keeps_info_with_error_body(self):
        """Some shippers tag exceptions as INFO — message body catches it."""
        logs = [self._log('INFO', 'Traceback (most recent call last): ...')]
        self.assertEqual(len(_filter_logs_for_ai(logs)), 1)

    def test_keeps_info_with_permission_denied(self):
        logs = [self._log('INFO', 'PERMISSION DENIED for user root')]
        self.assertEqual(len(_filter_logs_for_ai(logs)), 1)

    def test_case_insensitive_level(self):
        logs = [self._log('error', 'x'), self._log('Warning', 'y')]
        self.assertEqual(len(_filter_logs_for_ai(logs)), 2)

    def test_empty_input(self):
        self.assertEqual(_filter_logs_for_ai([]), [])
        self.assertEqual(_filter_logs_for_ai(None), [])

    def test_does_not_mutate_input(self):
        """Filter returns a new list — original untouched (used for
        audit trail in batch.data)."""
        original = [self._log('INFO', 'x'), self._log('ERROR', 'y')]
        original_ref = original.copy()
        _filter_logs_for_ai(original)
        self.assertEqual(original, original_ref)

    def test_keeps_the_recovery_of_a_failure(self):
        """A failed-then-retried request must reach the AI with its recovery,
        or a transient blip reads as an incident (RCA benchmark h09)."""
        failed = self._log('WARN', 'request to pricing-svc failed (connection reset), retrying (1/3)')
        healed = self._log('INFO', 'request to pricing-svc succeeded on retry 1')
        self.assertEqual(_filter_logs_for_ai([failed, healed, self._log('INFO', 'cache warmed')]), [failed, healed])

    def test_recovery_chatter_of_a_quiet_service_still_drops(self):
        noisy = {'level': 'INFO', 'message': 'reconnected to broker', 'component': 'other', 'timestamp': ''}
        self.assertEqual(_filter_logs_for_ai([self._log('ERROR', 'boom'), noisy]), [self._log('ERROR', 'boom')])

    def test_missing_level_defaults_dropped(self):
        """A log without a ``level`` key shouldn't crash; treated as low-severity."""
        logs = [{'message': 'no-level log'}]
        self.assertEqual(_filter_logs_for_ai(logs), [])


class PricingResolutionTest(TestCase):
    """Pricing now resolves via AIModelProvider fields, not a hardcoded dict.

    Self-seeds the provider catalog (with prices) via setUpTestData
    for the same reason as OllamaProviderSeededTest — a sibling
    TransactionTestCase truncates the table without restoring
    data-migration content. Q1.2 (Batch 24) fix.
    """

    @classmethod
    def setUpTestData(cls):
        from decimal import Decimal
        from org_settings.models import AIModelProvider
        # Mirror the seed + pricing from org_settings/0011 + 0012 + 0014.
        for name, defaults in {
            'gemini':   {'default_model': 'gemini-3.5-flash',
                          'adapter_class': 'ai_model.adapters.gemini.GeminiAdapter',
                          'is_active': True, 'requires_api_key': True,
                          'price_input_per_million': Decimal('0.075'),
                          'price_output_per_million': Decimal('0.300')},
            'claude':   {'default_model': 'claude-sonnet-5',
                          'adapter_class': 'ai_model.adapters.claude.ClaudeAdapter',
                          'is_active': True, 'requires_api_key': True,
                          'price_input_per_million': Decimal('2.000'),
                          'price_output_per_million': Decimal('10.000')},
            'openai':   {'default_model': 'gpt-5.6-terra',
                          'adapter_class': 'ai_model.adapters.openai_generic.GenericOpenAIAdapter',
                          'is_active': True, 'requires_api_key': True,
                          'price_input_per_million': Decimal('2.000'),
                          'price_output_per_million': Decimal('12.000')},
            'deepseek': {'default_model': 'deepseek-v4-flash',
                          'adapter_class': 'ai_model.adapters.openai_generic.GenericOpenAIAdapter',
                          'api_base_url': 'https://api.deepseek.com',
                          'is_active': True, 'requires_api_key': True,
                          'price_input_per_million': Decimal('0.014'),
                          'price_output_per_million': Decimal('0.028')},
            'ollama':   {'default_model': 'qwen3:8b',
                          'adapter_class': 'ai_model.adapters.openai_generic.GenericOpenAIAdapter',
                          'api_base_url': 'http://localhost:11434/v1/',
                          'is_active': True, 'requires_api_key': False,
                          'price_input_per_million': Decimal('0.000'),
                          'price_output_per_million': Decimal('0.000')},
        }.items():
            AIModelProvider.objects.update_or_create(name=name, defaults=defaults)

    def test_known_model_uses_db_price(self):
        # gemini-3.5-flash is the seeded default_model for the
        # 'gemini' AIModelProvider (0011). Prices are set by 0012:
        # $0.075/M input, $0.30/M output.
        # 1M input tokens = $0.075 exactly.
        cost = AITokenUsageService._estimate_cost('gemini-3.5-flash', 1_000_000, 0)
        self.assertEqual(cost, Decimal('0.075000'))

    def test_output_tokens_priced_separately(self):
        # 1M output tokens on gemini = $0.30
        cost = AITokenUsageService._estimate_cost('gemini-3.5-flash', 0, 1_000_000)
        self.assertEqual(cost, Decimal('0.300000'))

    def test_substring_fallback_matches_provider_variant(self):
        """A model ID like ``gemini-3.7-flash`` isn't in the seed but
        contains ``gemini`` — should route to that provider's prices."""
        cost = AITokenUsageService._estimate_cost('gemini-3.7-flash', 1_000_000, 0)
        self.assertEqual(cost, Decimal('0.075000'))

    def test_unknown_model_uses_conservative_fallback(self):
        """A truly-unknown model falls back to the module default so
        cost is never silently reported as $0."""
        cost = AITokenUsageService._estimate_cost('totally-fake-model-2099', 1_000_000, 0)
        # Fallback input price is $0.02/M
        self.assertEqual(cost, Decimal('0.020000'))

    def test_ollama_is_free(self):
        """Ollama runs locally — 0 cost."""
        cost = AITokenUsageService._estimate_cost('qwen3:8b', 1_000_000, 1_000_000)
        # qwen3:8b is Ollama's seeded default; both prices should be 0.
        self.assertEqual(cost, Decimal('0'))

    def test_stale_hardcoded_dict_is_gone(self):
        """Regression guard: the removed PRICING_PER_MILLION_TOKENS dict
        should not reappear. This test locks in the new implementation."""
        import ai_model.usage_tracking as mod
        self.assertFalse(
            hasattr(mod, 'PRICING_PER_MILLION_TOKENS'),
            "Hardcoded pricing dict is back — it fell out of sync with "
            "model IDs during Day 1 and produced wrong cost reports. "
            "Prices must live on AIModelProvider fields, not this module.",
        )


class DeletedPreprocessLogsTest(SimpleTestCase):
    """Confirm the standalone preprocess_logs task is removed.

    The task destroyed ``batch.data['logs']`` in place, was only wired
    to the manual-trigger endpoint, and duplicated work that Smart
    Aggregation already does non-destructively. Its replacement is
    ``_filter_logs_for_ai`` (a helper, not a Celery task) called
    inline from ``analyze_batch``.
    """

    def test_preprocess_logs_symbol_removed(self):
        import ai_model.tasks as tasks_module
        self.assertFalse(
            hasattr(tasks_module, 'preprocess_logs'),
            "preprocess_logs task is back — it destroys batch.data and "
            "duplicates the inline severity filter. Use "
            "_filter_logs_for_ai inside analyze_batch instead.",
        )


class BatchAggregationStatsPersistedTest(TestCase):
    """When analyze_batch runs, the four new stat fields must be
    populated on AIAnalyzedBatch.

    We don't exercise the full analyze_batch here (too much mocking);
    we assert that the fields exist on the model and default to 0
    for new rows. The end-to-end persist path is covered indirectly
    by the existing analyze_batch tests once they run against the
    updated code.
    """

    def test_fields_present_and_zero_default(self):
        from Data.models import AIAnalyzedBatch
        from Organisations.models import Organisations

        org = Organisations.objects.create(name='Stats Org', website='https://x.com')
        batch = AIAnalyzedBatch.objects.create(
            batch_id='stats-batch-1', organisation=org,
        )
        # All four new counters exist and default to 0 for legacy /
        # freshly-created batches. Dashboard cards can skip zero-value
        # batches to avoid misleading "0 patterns" cards on batches
        # that predate this migration.
        self.assertEqual(batch.logs_raw_count, 0)
        self.assertEqual(batch.logs_after_severity_filter, 0)
        self.assertEqual(batch.logs_unique_patterns, 0)
        self.assertEqual(batch.logs_sent_to_ai, 0)

    def test_fields_are_writable(self):
        from Data.models import AIAnalyzedBatch
        from Organisations.models import Organisations

        org = Organisations.objects.create(name='Stats Org 2', website='https://y.com')
        batch = AIAnalyzedBatch.objects.create(
            batch_id='stats-batch-2', organisation=org,
            logs_raw_count=1000,
            logs_after_severity_filter=50,
            logs_unique_patterns=12,
            logs_sent_to_ai=13,  # 12 patterns + 1 aggregation header
        )
        batch.refresh_from_db()
        self.assertEqual(batch.logs_raw_count, 1000)
        self.assertEqual(batch.logs_after_severity_filter, 50)
        self.assertEqual(batch.logs_unique_patterns, 12)
        self.assertEqual(batch.logs_sent_to_ai, 13)
