"""Claude prompt-cache tokens reach usage and cost, priced per model.

Anthropic's ``input_tokens`` is only the uncached part of the prompt; the
cached system prefix comes back as ``cache_creation_input_tokens`` and
``cache_read_input_tokens``. SerOps counted ``input_tokens`` alone, so AI
usage and the monthly budget cap saw less than was spent (RCA benchmark
v2, 2026-11-15).
"""
import pickle
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from ai_model.token_counts import PromptTokens, cache_parts
from ai_model.usage_tracking import AITokenUsageService


class PromptTokensTest(SimpleTestCase):
    def test_is_the_whole_prompt_and_keeps_its_parts(self):
        tokens = PromptTokens(100, 2000, 3000)
        self.assertEqual(tokens, 5100)
        self.assertEqual(cache_parts(tokens), (100, 2000, 3000))
        self.assertEqual(cache_parts(42), (42, 0, 0))
        self.assertEqual(cache_parts(None), (0, 0, 0))

    def test_survives_pickling_and_ignores_non_counts(self):
        self.assertEqual(cache_parts(pickle.loads(pickle.dumps(PromptTokens(1, 2, 3)))), (1, 2, 3))
        self.assertEqual(cache_parts(PromptTokens(10, MagicMock(), None)), (10, 0, 0))


class ClaudeAdapterUsageTest(SimpleTestCase):
    @patch('ai_model.adapters.claude.anthropic')
    def test_cache_writes_and_reads_are_counted(self, mock_anthropic):
        from ai_model.adapters.claude import ClaudeAdapter

        message = MagicMock()
        message.stop_reason = 'end_turn'
        message.content = [SimpleNamespace(type='text', text='ok')]
        message.usage = SimpleNamespace(input_tokens=1500, output_tokens=1900,
                                        cache_creation_input_tokens=2400, cache_read_input_tokens=0)
        mock_anthropic.Anthropic.return_value.messages.create.return_value = message

        text, error, tokens_in, tokens_out = ClaudeAdapter().generate(
            prompt='p', config={'default_model': 'claude-sonnet-5-5'}, api_key='sk-test', system_prefix='x' * 5000)
        self.assertIsNone(error)
        self.assertEqual((tokens_in, tokens_out), (3900, 1900))
        self.assertEqual(cache_parts(tokens_in), (1500, 2400, 0))


class CostEstimateTest(TestCase):
    def test_cache_writes_cost_more_and_reads_less(self):
        cost = AITokenUsageService._estimate_cost
        m = 1_000_000
        # Sonnet 5.5: $2 in, $10 out, write 1.25x, read 0.1x.
        self.assertEqual(cost('claude-sonnet-5-5', PromptTokens(m, 0, 0), 0), Decimal('2'))
        self.assertEqual(cost('claude-sonnet-5-5', PromptTokens(0, m, 0), 0), Decimal('2.5'))
        self.assertEqual(cost('claude-sonnet-5-5', PromptTokens(0, 0, m), 0), Decimal('0.2'))
        self.assertEqual(cost('claude-sonnet-5-5', 0, m), Decimal('10'))
        # Opus 5.5 reads at 0.05x of $4.
        self.assertEqual(cost('claude-opus-5-5', PromptTokens(0, 0, m), 0), Decimal('0.2'))
        self.assertEqual(cost('claude-opus-5-5', m, m), Decimal('24'))
        self.assertEqual(cost('claude-haiku-5-5', m, m), Decimal('0.6'))

    def test_known_models_are_priced_by_model_not_by_the_provider_row(self):
        from org_settings.models import AIModelProvider
        AIModelProvider.objects.update_or_create(name='claude', defaults={
            'default_model': 'claude-opus-5-5', 'adapter_class': 'ai_model.adapters.claude.ClaudeAdapter',
            'price_input_per_million': Decimal('2'), 'price_output_per_million': Decimal('10')})
        self.assertEqual(AITokenUsageService._estimate_cost('claude-opus-5-5', 1_000_000, 0), Decimal('4'))

    def test_a_provider_name_is_priced_by_its_model(self):
        # analyze_batch records the provider that answered ("claude"), not the model.
        from org_settings.models import AIModelProvider
        AIModelProvider.objects.update_or_create(name='claude', defaults={
            'default_model': 'claude-haiku-5-5', 'adapter_class': 'ai_model.adapters.claude.ClaudeAdapter',
            'price_input_per_million': Decimal('2'), 'price_output_per_million': Decimal('10')})
        self.assertEqual(AITokenUsageService._estimate_cost('claude', 1_000_000, 1_000_000), Decimal('0.6'))

    def test_log_usage_stores_the_whole_prompt(self):
        from Organisations.models import Organisations
        org = Organisations.objects.create(name='Acme')
        usage = AITokenUsageService.log_usage(org, None, PromptTokens(100, 200, 300), 50, 'claude-sonnet-5-5')
        usage.refresh_from_db()
        self.assertEqual((usage.tokens_input, usage.tokens_output, usage.tokens_total), (600, 50, 650))
        expected = (Decimal(100) + Decimal(200) * Decimal('1.25') + Decimal(300) * Decimal('0.1')) * 2 / 1_000_000 \
            + Decimal(50) * 10 / 1_000_000
        self.assertEqual(usage.cost_usd, expected.quantize(Decimal('0.000001')))


class NewInstallDefaultModelTest(TestCase):
    """org_settings 0022: only a Claude row nobody uses moves to Sonnet 5.5."""

    def _run(self):
        from importlib import import_module
        from django.apps import apps
        import_module('org_settings.migrations.0022_claude_sonnet_5_5_default').forwards(apps, None)

    def _row(self, model='claude-sonnet-5'):
        from org_settings.models import AIModelProvider
        row, _ = AIModelProvider.objects.update_or_create(name='claude', defaults={
            'default_model': model, 'adapter_class': 'ai_model.adapters.claude.ClaudeAdapter'})
        return row

    def test_unused_seeded_row_moves(self):
        row = self._row()
        self._run()
        row.refresh_from_db()
        self.assertEqual(row.default_model, 'claude-sonnet-5-5')

    def test_row_an_organisation_uses_keeps_its_model(self):
        from Organisations.models import Organisations
        from org_settings.models import OrganisationAISettings
        row = self._row()
        OrganisationAISettings.objects.create(organisation=Organisations.objects.create(name='Acme'), fallback_provider=row)
        self._run()
        row.refresh_from_db()
        self.assertEqual(row.default_model, 'claude-sonnet-5')

    def test_edited_row_keeps_its_model(self):
        row = self._row('claude-opus-5')
        self._run()
        row.refresh_from_db()
        self.assertEqual(row.default_model, 'claude-opus-5')
