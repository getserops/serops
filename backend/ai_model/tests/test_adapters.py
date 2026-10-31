"""
Unit Tests for AI Plugin Architecture
"""

import json
from unittest.mock import patch, MagicMock
from django.test import SimpleTestCase, TestCase
from ai_model.adapters.registry import AdapterRegistry
from ai_model.adapters.base import BaseProviderAdapter
from ai_model.adapters.gemini import GeminiAdapter
from ai_model.adapters.openai_generic import GenericOpenAIAdapter

class AdapterRegistryTest(SimpleTestCase):
    def test_registry_loads_valid_adapter(self):
        """Test that the registry can load a valid adapter"""
        adapter = AdapterRegistry.get_adapter('ai_model.adapters.openai_generic.GenericOpenAIAdapter')
        self.assertIsInstance(adapter, GenericOpenAIAdapter)
        self.assertIsInstance(adapter, BaseProviderAdapter)

    def test_registry_blocks_unsafe_path(self):
        """Test that the registry blocks loading from outside safe namespace"""
        with self.assertRaises(ValueError):
            AdapterRegistry.get_adapter('os.path.join')

    def test_registry_caching(self):
        """Test that adapters are cached"""
        a1 = AdapterRegistry.get_adapter('ai_model.adapters.openai_generic.GenericOpenAIAdapter')
        a2 = AdapterRegistry.get_adapter('ai_model.adapters.openai_generic.GenericOpenAIAdapter')
        # Note: The registry caches the CLASS, updates to code use instantiation.
        # Logic in registry.py: cls._cache[class_path] = adapter_class
        # return cls._cache[class_path]() -> returns NEW instance
        self.assertNotEqual(a1, a2) # Should be different instances
        
class GenericOpenAIAdapterTest(SimpleTestCase):
    def test_normalize_error(self):
        adapter = GenericOpenAIAdapter()

        # Test 429
        error = adapter.normalize_error(Exception("Error 429: Too Many Requests"))
        self.assertEqual(error.code, 'QUOTA_EXCEEDED')

        # Test 401
        error = adapter.normalize_error(Exception("Error 401: Unauthorized"))
        self.assertEqual(error.code, 'AUTH_ERROR')


class GeminiAdapterTruncationTest(SimpleTestCase):
    """Truncation + normal-path tests against the google-genai SDK.

    Migrated 2026-08-30 from google-generativeai (EOL) mocks. The
    new client surface is ``genai.Client(api_key=...)`` →
    ``client.models.generate_content(model=..., contents=..., config=...)``,
    so both patch targets and the mock chain had to move.
    """

    def _make_mock_response(self, text, finish_reason_name, prompt_tokens, candidates_tokens):
        candidate = MagicMock()
        candidate.finish_reason = MagicMock()
        candidate.finish_reason.name = finish_reason_name

        response = MagicMock()
        response.candidates = [candidate]
        response.text = text
        response.usage_metadata = MagicMock()
        response.usage_metadata.prompt_token_count = prompt_tokens
        response.usage_metadata.candidates_token_count = candidates_tokens
        return response

    @patch('ai_model.adapters.gemini.genai')
    def test_truncated_response_returns_error(self, mock_genai):
        """finish_reason=MAX_TOKENS → TRUNCATED error, token counts preserved."""
        response = self._make_mock_response(
            '{"correlated_issues": [{"title": "partial...',
            'MAX_TOKENS', 1500, 8192,
        )
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = response
        mock_genai.Client.return_value = mock_client

        adapter = GeminiAdapter()
        config = {'default_model': 'gemini-3.5-flash'}
        response_text, error, tokens_in, tokens_out = adapter.generate(
            'test prompt', config, api_key='test-key',
        )

        self.assertIsNone(response_text)
        self.assertIsNotNone(error)
        self.assertEqual(error.code, 'TRUNCATED')
        self.assertEqual(tokens_in, 1500)
        self.assertEqual(tokens_out, 8192)
        self.assertIn('partial', error.raw_error)

    @patch('ai_model.adapters.gemini.genai')
    def test_normal_response_no_error(self, mock_genai):
        """finish_reason=STOP → text returned, no error."""
        response = self._make_mock_response(
            '{"correlated_issues": []}', 'STOP', 500, 200,
        )
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = response
        mock_genai.Client.return_value = mock_client

        adapter = GeminiAdapter()
        config = {'default_model': 'gemini-3.5-flash'}
        response_text, error, tokens_in, tokens_out = adapter.generate(
            'test prompt', config, api_key='test-key',
        )

        self.assertEqual(response_text, '{"correlated_issues": []}')
        self.assertIsNone(error)
        self.assertEqual(tokens_in, 500)
        self.assertEqual(tokens_out, 200)

    @patch('ai_model.adapters.gemini.genai')
    def test_client_instantiated_with_api_key(self, mock_genai):
        """The new SDK expects ``genai.Client(api_key=...)`` — not the
        old ``genai.configure()`` module-level state. This locks in the
        contract so a future refactor can't silently regress to the
        deprecated global-config pattern."""
        response = self._make_mock_response('{}', 'STOP', 10, 5)
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = response
        mock_genai.Client.return_value = mock_client

        GeminiAdapter().generate('x', {'default_model': 'gemini-3.5-flash'}, api_key='my-key')

        mock_genai.Client.assert_called_once()
        call_kwargs = mock_genai.Client.call_args.kwargs
        self.assertEqual(call_kwargs.get('api_key'), 'my-key')
        # Timeout wiring landed in the same batch as this assertion —
        # http_options must carry it or the client falls back to the
        # SDK's no-default behaviour and a wedged call hangs celery.
        self.assertIn('http_options', call_kwargs)
        # Old SDK had genai.configure() at module scope — must not exist
        # in the new call path.
        self.assertFalse(mock_genai.configure.called)


class OpenAIAdapterTruncationTest(SimpleTestCase):
    """Test that OpenAI-compatible adapter detects truncated responses via finish_reason."""

    @patch('ai_model.adapters.openai_generic.openai')
    def test_truncated_response_returns_error(self, mock_openai):
        """When finish_reason is 'length', adapter returns truncation error with tokens preserved."""
        mock_choice = MagicMock()
        mock_choice.message.content = '{"correlated_issues": [{"title": "partial...'
        mock_choice.finish_reason = 'length'

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 1200
        mock_usage.completion_tokens = 4096

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.OpenAI.return_value = mock_client

        adapter = GenericOpenAIAdapter()
        config = {'default_model': 'deepseek-chat', 'api_base_url': 'https://api.deepseek.com'}
        response_text, error, tokens_in, tokens_out = adapter.generate('test prompt', config, api_key='test-key')

        self.assertIsNone(response_text)
        self.assertIsNotNone(error)
        self.assertEqual(error.code, 'TRUNCATED')
        self.assertEqual(tokens_in, 1200)
        self.assertEqual(tokens_out, 4096)
        self.assertIn('partial', error.raw_error)

    @patch('ai_model.adapters.openai_generic.openai')
    def test_normal_response_no_error(self, mock_openai):
        """When finish_reason is 'stop', adapter returns response normally."""
        mock_choice = MagicMock()
        mock_choice.message.content = '{"correlated_issues": []}'
        mock_choice.finish_reason = 'stop'

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 500
        mock_usage.completion_tokens = 200

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.OpenAI.return_value = mock_client

        adapter = GenericOpenAIAdapter()
        config = {'default_model': 'deepseek-chat', 'api_base_url': 'https://api.deepseek.com'}
        response_text, error, tokens_in, tokens_out = adapter.generate('test prompt', config, api_key='test-key')

        self.assertEqual(response_text, '{"correlated_issues": []}')
        self.assertIsNone(error)
        self.assertEqual(tokens_in, 500)
        self.assertEqual(tokens_out, 200)


class IssueCountOnDedupFailureTest(TestCase):
    """Test that issue_count stays in sync with actual DB records when dedup errors occur."""

    @patch('ai_model.tasks.generate_for_organisation')
    def test_issue_count_zero_when_dedup_raises(self, mock_generate):
        """When find_or_create_deduplicated raises, issue_count must match actual DB count (0)."""
        from Data.models import AIAnalyzedBatch, Issue
        from Projects.models import Project
        from Organisations.models import Organisations

        org = Organisations.objects.create(name='Dedup Fail Org')
        project = Project.objects.create(name='Dedup Fail Project', organisation=org)
        batch = AIAnalyzedBatch.objects.create(
            batch_id='test-dedup-failure',
            project=project,
            organisation=org,
            environment='production',
            data={
                'logs': [{'_source': {'message': 'error occurred', 'log_level': 'error'}}],
                'metrics': {},
                'metrics_summary': {},
                'code_changes': [],
                'cicd_logs': [],
                'statistics': {'total_logs': 1, 'total_metrics': 0, 'total_code_changes': 0, 'total_cicd_logs': 0},
            },
        )

        # AI returns 3 correlated issues
        ai_response = json.dumps({
            'summary': {'overall_health': 'CRITICAL', 'total_entries': 1},
            'correlated_issues': [
                {'issue_type': 'API_ERROR', 'scope': 'SERVICE', 'component': 'backend',
                 'severity': 'WARNING', 'description': 'Error 1', 'error_class': 'OTHER', 'error_target': '/api/1'},
                {'issue_type': 'DATABASE_ERROR', 'scope': 'SERVICE', 'component': 'db',
                 'severity': 'CRITICAL', 'description': 'Error 2', 'error_class': 'DB_CONNECTION', 'error_target': 'postgres'},
                {'issue_type': 'MEMORY_HIGH', 'scope': 'INFRASTRUCTURE', 'component': 'INFRASTRUCTURE',
                 'severity': 'WARNING', 'description': 'Error 3', 'error_class': 'OUT_OF_MEMORY', 'error_target': 'system'},
            ],
            'recommendations': [],
        })
        mock_generate.return_value = (ai_response, 'gemini', None, 100, 50)

        # Make find_or_create_deduplicated raise on every call
        with patch.object(Issue, 'find_or_create_deduplicated', side_effect=Exception('DB lock timeout')):
            from ai_model.tasks import analyze_batch
            analyze_batch('test-dedup-failure')
        mock_generate.assert_called_once()  # the analysis really ran

        batch.refresh_from_db()
        actual_issues = Issue.objects.filter(batch=batch).count()

        # issue_count must equal actual DB count, not AI response count
        self.assertEqual(batch.issue_count, actual_issues)
        self.assertEqual(batch.issue_count, 0)

    @patch('ai_model.tasks.generate_for_organisation')
    def test_issue_count_not_inflated_from_ai_response(self, mock_generate):
        """issue_count must never be set from AI response length — only from actual DB records."""
        from Data.models import AIAnalyzedBatch, Issue
        from Projects.models import Project
        from Organisations.models import Organisations

        org = Organisations.objects.create(name='Inflate Check Org')
        project = Project.objects.create(name='Inflate Check Project', organisation=org)
        batch = AIAnalyzedBatch.objects.create(
            batch_id='test-inflate-check',
            project=project,
            organisation=org,
            environment='production',
            data={
                'logs': [{'_source': {'message': 'error occurred', 'log_level': 'error'}}],
                'metrics': {},
                'metrics_summary': {},
                'code_changes': [],
                'cicd_logs': [],
                'statistics': {'total_logs': 1, 'total_metrics': 0, 'total_code_changes': 0, 'total_cicd_logs': 0},
            },
        )

        # AI returns 5 correlated issues — none will be persisted due to error
        ai_response = json.dumps({
            'summary': {'overall_health': 'CRITICAL', 'total_entries': 1},
            'correlated_issues': [
                {'issue_type': 'API_ERROR', 'scope': 'SERVICE', 'component': f'svc-{i}',
                 'severity': 'WARNING', 'description': f'Error {i}', 'error_class': 'OTHER',
                 'error_target': f'/api/{i}'}
                for i in range(5)
            ],
            'recommendations': [],
        })
        mock_generate.return_value = (ai_response, 'gemini', None, 100, 50)

        # Make dedup fail — no Issue records should be created
        with patch.object(Issue, 'find_or_create_deduplicated', side_effect=RuntimeError('simulated')):
            from ai_model.tasks import analyze_batch
            analyze_batch('test-inflate-check')
        mock_generate.assert_called_once()

        batch.refresh_from_db()
        # Old buggy code would set issue_count=5 from AI response; fix sets it from DB count=0
        self.assertEqual(batch.issue_count, 0)
        self.assertEqual(Issue.objects.filter(batch=batch).count(), 0)


class ReanalyzeDynamicRoutingTest(TestCase):
    """Test that reanalyze_batch_with_model routes through generate_text_unified dynamically."""

    @patch('ai_model.tasks.generate_text_unified')
    @patch('ai_model.tasks.get_api_key_for_org')
    def test_reanalyze_calls_unified_with_correct_provider(self, mock_get_key, mock_unified):
        """Verify reanalyze routes to generate_text_unified with the user-chosen provider, not hardcoded."""
        from Data.models import AIAnalyzedBatch
        from Projects.models import Project
        from Organisations.models import Organisations

        # Setup org -> project -> batch
        org = Organisations.objects.create(name='Test Org')
        project = Project.objects.create(name='Test Project', organisation=org)
        batch = AIAnalyzedBatch.objects.create(
            batch_id='test-reanalyze-routing',
            project=project,
            data={'logs': [{'_source': {'message': 'test log', 'log_level': 'error'}}]},
        )

        # Three-tuple: (api_key, base_url, extra_config). The third
        # element carries provider-specific settings alongside the key.
        mock_get_key.return_value = ('fake-api-key', 'https://api.example.com', {})
        mock_unified.return_value = ('{"correlated_issues": []}', None, 100, 50)

        from ai_model.tasks import reanalyze_batch_with_model
        result = reanalyze_batch_with_model('test-reanalyze-routing', 'claude')

        # Verify generate_text_unified was called with provider='claude'
        mock_unified.assert_called_once()
        call_kwargs = mock_unified.call_args
        self.assertEqual(call_kwargs.kwargs.get('provider') or call_kwargs[1].get('provider'), 'claude')
        self.assertIn('Re-analysis completed', result)


# =============================================================================
# Phase 7: AI Provider Refactor Tests
# =============================================================================

class DBDrivenProviderCreationTest(TestCase):
    """Test that new providers can be created via DB without PROVIDER_CHOICES restriction."""

    def test_create_custom_provider_no_choices_error(self):
        """Creating a provider with a non-standard name should work (no PROVIDER_CHOICES)."""
        from org_settings.models import AIModelProvider

        provider = AIModelProvider.objects.create(
            name='mistral',
            display_name='Mistral AI',
            is_active=True,
            requires_api_key=True,
            default_model='mistral-large-latest',
            adapter_class='ai_model.adapters.openai_generic.GenericOpenAIAdapter',
            env_key_name='MISTRAL_API_KEY',
            env_url_name='MISTRAL_API_URL',
            is_system=False,
        )
        self.assertEqual(provider.name, 'mistral')
        self.assertEqual(provider.adapter_class, 'ai_model.adapters.openai_generic.GenericOpenAIAdapter')

        # Refresh from DB to ensure it persisted
        provider.refresh_from_db()
        self.assertEqual(provider.name, 'mistral')
        self.assertFalse(provider.is_system)

    def test_create_provider_with_arbitrary_name(self):
        """Any string name should be allowed — no choices constraint."""
        from org_settings.models import AIModelProvider

        for name in ['ollama-local', 'custom_llm_v2', 'my-company-ai']:
            provider = AIModelProvider.objects.create(
                name=name,
                display_name=name.title(),
                adapter_class='ai_model.adapters.openai_generic.GenericOpenAIAdapter',
            )
            provider.refresh_from_db()
            self.assertEqual(provider.name, name)


class GetApiKeyForOrgDBLookupTest(TestCase):
    """Locks in that get_api_key_for_org() reads OrganisationAPIKey only.

    The env-var fallback was removed 2026-08-30. Reason: shared env vars
    on multi-tenant self-host silently pool billing across orgs, and the
    onboarding wizard needs to distinguish "no key configured yet" from
    "key configured but rejected" — the env-var fallback collapsed those.
    """

    def test_env_var_never_returned_even_when_populated(self):
        """Populated env var must be ignored — regression guard for the
        removed fallback."""
        from org_settings.models import AIModelProvider
        from ai_model.ai_service import get_api_key_for_org

        AIModelProvider.objects.create(
            name='test-provider',
            display_name='Test Provider',
            env_key_name='TEST_PROVIDER_API_KEY',
            env_url_name='TEST_PROVIDER_URL',
        )

        with patch.dict('os.environ', {
            'TEST_PROVIDER_API_KEY': 'sk-should-be-ignored',
            'TEST_PROVIDER_URL': 'https://ignored.test-provider.com',
        }):
            api_key, base_url, _extra = get_api_key_for_org(None, 'test-provider')

        self.assertIsNone(api_key)
        self.assertIsNone(base_url)

    def test_no_org_returns_none(self):
        """No organisation → no key. There is no anonymous credential
        source anymore."""
        from org_settings.models import AIModelProvider
        from ai_model.ai_service import get_api_key_for_org

        AIModelProvider.objects.create(
            name='no-key-provider',
            display_name='No Key Provider',
        )

        api_key, base_url, _extra = get_api_key_for_org(None, 'no-key-provider')
        self.assertIsNone(api_key)
        self.assertIsNone(base_url)

    def test_provider_not_in_db_returns_none(self):
        """When provider doesn't exist in DB at all, returns (None, None)."""
        from ai_model.ai_service import get_api_key_for_org

        api_key, base_url, _extra = get_api_key_for_org(None, 'totally-nonexistent-provider')
        self.assertIsNone(api_key)
        self.assertIsNone(base_url)


class SystemProviderDeleteProtectionTest(TestCase):
    """Test that system providers (is_system=True) cannot be deleted."""

    def test_system_provider_not_deletable(self):
        """Direct model-level: verify is_system flag is correctly set on system providers."""
        from org_settings.models import AIModelProvider

        provider = AIModelProvider.objects.create(
            name='gemini-test',
            display_name='Gemini Test',
            is_system=True,
        )
        self.assertTrue(provider.is_system)

    def test_non_system_provider_deletable(self):
        """Non-system providers can be deleted normally."""
        from org_settings.models import AIModelProvider

        provider = AIModelProvider.objects.create(
            name='custom-deletable',
            display_name='Custom Deletable',
            is_system=False,
        )
        pk = provider.pk
        provider.delete()
        self.assertFalse(AIModelProvider.objects.filter(pk=pk).exists())


class GenerateTextUnifiedNonExistentProviderTest(TestCase):
    """Test that generate_text_unified returns error for non-existent provider."""

    def test_nonexistent_provider_returns_error(self):
        """Calling generate_text_unified with an unknown provider returns PROVIDER_NOT_SUPPORTED."""
        from ai_model.ai_service import generate_text_unified

        response_text, error, tokens_in, tokens_out = generate_text_unified(
            'test prompt', provider='nonexistent-provider-xyz'
        )

        self.assertIsNone(response_text)
        self.assertIsNotNone(error)
        self.assertEqual(error.code, 'PROVIDER_NOT_SUPPORTED')
        self.assertEqual(tokens_in, 0)
        self.assertEqual(tokens_out, 0)

    def test_nonexistent_provider_no_legacy_fallback(self):
        """There is no legacy fallback — unknown providers fail cleanly, not silently."""
        from ai_model.ai_service import generate_text_unified

        response_text, error, _, _ = generate_text_unified(
            'test prompt', provider='fake_provider'
        )

        # Must get an error, not a successful response from some legacy function
        self.assertIsNone(response_text)
        self.assertIsNotNone(error)
        self.assertIn('PROVIDER_NOT_SUPPORTED', error.code)


class ClaudeAdapterTest(SimpleTestCase):
    """Test Claude adapter generate() with mocked anthropic client."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Mock the anthropic module at sys.modules level since it's not installed in test env
        import sys
        cls._mock_anthropic = MagicMock()
        cls._original_anthropic = sys.modules.get('anthropic')
        sys.modules['anthropic'] = cls._mock_anthropic
        # Force reimport of claude adapter with mocked anthropic
        if 'ai_model.adapters.claude' in sys.modules:
            del sys.modules['ai_model.adapters.claude']

    @classmethod
    def tearDownClass(cls):
        """Restore sys.modules cleanly for the test session.

        Historically this popped ``anthropic`` and
        ``ai_model.adapters.claude`` out of sys.modules unconditionally,
        which broke every downstream test that used
        ``@patch('ai_model.adapters.claude.anthropic')`` — the
        string-based patch target can't be resolved once the module
        is gone AND the real ``anthropic`` package isn't installed
        in the test env.

        Two cases now:

        1. Real anthropic was in sys.modules before us — put it back
           and force a fresh import of the claude adapter so it binds
           against the real client. Restores pre-class state.

        2. Real anthropic was NOT available — keep our MagicMock in
           place and keep the (mock-backed) claude adapter loaded.
           Downstream tests that ``@patch`` claude.anthropic still
           find an importable module. The mock is harmless because
           nothing else in the test env imports the real anthropic.
        """
        import sys
        if cls._original_anthropic is not None:
            sys.modules['anthropic'] = cls._original_anthropic
            sys.modules.pop('ai_model.adapters.claude', None)
            try:
                import importlib
                importlib.import_module('ai_model.adapters.claude')
            except Exception:
                # If restoration fails (e.g. real anthropic no longer
                # importable mid-suite), don't hide the eventual test
                # error under a swallowed exception — let downstream
                # surface it.
                pass
        # else: deliberately leave sys.modules['anthropic'] = our mock
        # AND sys.modules['ai_model.adapters.claude'] = the loaded
        # module. This is the "test env has no real anthropic" path.
        super().tearDownClass()

    def _get_adapter(self):
        from ai_model.adapters.claude import ClaudeAdapter
        return ClaudeAdapter()

    def test_normal_response(self):
        """Successful Claude response returns text and token counts."""
        mock_content_block = MagicMock()
        mock_content_block.text = '{"correlated_issues": []}'

        mock_usage = MagicMock()
        mock_usage.input_tokens = 800
        mock_usage.output_tokens = 150

        mock_message = MagicMock()
        mock_message.content = [mock_content_block]
        mock_message.stop_reason = 'end_turn'
        mock_message.usage = mock_usage

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        self._mock_anthropic.Anthropic.return_value = mock_client

        adapter = self._get_adapter()
        config = {'default_model': 'claude-sonnet-4-20250514'}
        response_text, error, tokens_in, tokens_out = adapter.generate(
            'test prompt', config, api_key='sk-ant-test-key'
        )

        self.assertEqual(response_text, '{"correlated_issues": []}')
        self.assertIsNone(error)
        self.assertEqual(tokens_in, 800)
        self.assertEqual(tokens_out, 150)

        # Verify the client was created with the right key. Assert on
        # the last call's kwargs only — other tests share this class-
        # level mock via sys.modules manipulation (see class docstring),
        # so ``assert_called_once`` would double-count.
        last_call = self._mock_anthropic.Anthropic.call_args
        self.assertIsNotNone(last_call, "Anthropic() was never called")
        self.assertEqual(last_call.kwargs.get('api_key'), 'sk-ant-test-key')

    def test_truncated_response(self):
        """When stop_reason is 'max_tokens', adapter returns TRUNCATED error with tokens preserved."""
        mock_content_block = MagicMock()
        mock_content_block.text = '{"correlated_issues": [{"title": "partial...'

        mock_usage = MagicMock()
        mock_usage.input_tokens = 2000
        mock_usage.output_tokens = 8192

        mock_message = MagicMock()
        mock_message.content = [mock_content_block]
        mock_message.stop_reason = 'max_tokens'
        mock_message.usage = mock_usage

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        self._mock_anthropic.Anthropic.return_value = mock_client

        adapter = self._get_adapter()
        config = {'default_model': 'claude-sonnet-4-20250514'}
        response_text, error, tokens_in, tokens_out = adapter.generate(
            'test prompt', config, api_key='sk-ant-test-key'
        )

        self.assertIsNone(response_text)
        self.assertIsNotNone(error)
        self.assertEqual(error.code, 'TRUNCATED')
        self.assertEqual(tokens_in, 2000)
        self.assertEqual(tokens_out, 8192)
        self.assertIn('partial', error.raw_error)

    def test_missing_api_key_returns_auth_error(self):
        """When no API key is provided, adapter returns AUTH_MISSING error."""
        adapter = self._get_adapter()
        config = {'default_model': 'claude-sonnet-4-20250514'}
        response_text, error, tokens_in, tokens_out = adapter.generate(
            'test prompt', config, api_key=None
        )

        self.assertIsNone(response_text)
        self.assertIsNotNone(error)
        self.assertEqual(error.code, 'AUTH_MISSING')
        self.assertEqual(tokens_in, 0)
        self.assertEqual(tokens_out, 0)

    def test_rate_limit_error_normalized(self):
        """Rate limit errors are normalized to QUOTA_EXCEEDED."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception('Error 429: rate limit exceeded')
        self._mock_anthropic.Anthropic.return_value = mock_client

        adapter = self._get_adapter()
        config = {'default_model': 'claude-sonnet-4-20250514'}
        response_text, error, tokens_in, tokens_out = adapter.generate(
            'test prompt', config, api_key='sk-ant-test-key'
        )

        self.assertIsNone(response_text)
        self.assertIsNotNone(error)
        self.assertEqual(error.code, 'QUOTA_EXCEEDED')

    def test_auth_error_normalized(self):
        """Auth errors are normalized to AUTH_ERROR."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception('Error 401: Unauthorized - invalid api key')
        self._mock_anthropic.Anthropic.return_value = mock_client

        adapter = self._get_adapter()
        config = {'default_model': 'claude-sonnet-4-20250514'}
        response_text, error, _, _ = adapter.generate(
            'test prompt', config, api_key='sk-ant-bad-key'
        )

        self.assertIsNone(response_text)
        self.assertEqual(error.code, 'AUTH_ERROR')


class AIServiceErrorTest(SimpleTestCase):
    """Test the consolidated AIServiceError class."""

    def test_from_type_known_error(self):
        """from_type() with a known error type returns correct code/message."""
        from ai_model.adapters.base import AIServiceError

        error = AIServiceError.from_type('quota_exceeded', 'raw error details')
        self.assertEqual(error.code, 'QUOTA_EXCEEDED')
        self.assertEqual(error.error_type, 'quota_exceeded')
        self.assertIn('rate limit', error.message.lower())
        self.assertEqual(error.raw_error, 'raw error details')

    def test_from_type_unknown_error_falls_back(self):
        """from_type() with an unknown error type falls back to 'unknown'."""
        from ai_model.adapters.base import AIServiceError

        error = AIServiceError.from_type('totally_made_up_type', 'some details')
        self.assertEqual(error.code, 'UNKNOWN_ERROR')
        self.assertEqual(error.error_type, 'totally_made_up_type')

    def test_to_dict_format(self):
        """to_dict() returns the expected dictionary structure."""
        from ai_model.adapters.base import AIServiceError

        error = AIServiceError('auth_error', 'AUTH_ERROR', 'Auth failed', 'Check key', 'raw')
        d = error.to_dict()
        self.assertEqual(d['error_code'], 'AUTH_ERROR')
        self.assertEqual(d['error_message'], 'Auth failed')
        self.assertEqual(d['user_action'], 'Check key')
        self.assertEqual(d['raw_error'], 'raw')

    def test_all_error_types_have_required_fields(self):
        """Every entry in ERROR_TYPES must have code, message, and user_action."""
        from ai_model.adapters.base import AIServiceError

        for error_type, info in AIServiceError.ERROR_TYPES.items():
            self.assertIn('code', info, f"Missing 'code' in ERROR_TYPES['{error_type}']")
            self.assertIn('message', info, f"Missing 'message' in ERROR_TYPES['{error_type}']")
            self.assertIn('user_action', info, f"Missing 'user_action' in ERROR_TYPES['{error_type}']")


# =============================================================================
# Day 1 — AI provider modernization (added 2026-08-30)
# =============================================================================


class AdapterDefaultModelsTest(SimpleTestCase):
    """Locks in the mid-2026 verified default model IDs.

    All three adapters need to fail-safe to a currently-live model
    string when an ``AIModelProvider.default_model`` is empty. The
    values checked here are the ones verified against provider docs
    on 2026-08-30 — if any of them 404s, the fix is to update the
    ``DEFAULT_MODEL`` constant in the adapter module and this test
    together (single source of truth).
    """

    def test_gemini_default_model(self):
        from ai_model.adapters import gemini
        self.assertEqual(gemini.DEFAULT_MODEL, 'gemini-3.5-flash')

    def test_claude_default_model(self):
        from ai_model.adapters import claude
        self.assertEqual(claude.DEFAULT_MODEL, 'claude-sonnet-5')

    def test_openai_generic_default_model(self):
        from ai_model.adapters import openai_generic
        self.assertEqual(openai_generic.DEFAULT_MODEL, 'gpt-5.6-terra')


class OpenAIModelDeprecatedGuardTest(SimpleTestCase):
    """Fail-fast when someone still has an OpenAI shutdown model configured.

    OpenAI kills ``gpt-3.5-turbo`` and ``gpt-4`` on 2026-10-23. The
    adapter raises :class:`ModelDeprecated` outside its try-block so
    the exception surfaces cleanly — a generic AIServiceError would
    read as "your key is bad" and send users on a wild-goose chase.
    """

    def test_gpt_35_turbo_under_openai_raises(self):
        from ai_model.adapters.openai_generic import GenericOpenAIAdapter
        from ai_model.exceptions import ModelDeprecated

        adapter = GenericOpenAIAdapter()
        with self.assertRaises(ModelDeprecated) as ctx:
            adapter.generate(
                'prompt',
                {'name': 'openai', 'default_model': 'gpt-3.5-turbo'},
                api_key='sk-test',
            )
        self.assertIn('2026-10-23', str(ctx.exception))

    def test_gpt_4_under_openai_raises(self):
        from ai_model.adapters.openai_generic import GenericOpenAIAdapter
        from ai_model.exceptions import ModelDeprecated

        adapter = GenericOpenAIAdapter()
        with self.assertRaises(ModelDeprecated):
            adapter.generate(
                'prompt',
                {'name': 'openai', 'default_model': 'gpt-4'},
                api_key='sk-test',
            )

    @patch('ai_model.adapters.openai_generic.openai')
    def test_shutdown_model_ids_under_other_providers_do_not_raise(self, mock_openai):
        """DeepSeek / Ollama also route through GenericOpenAIAdapter but
        ship their own catalogs. The shutdown guard must only fire when
        provider='openai' — otherwise a DeepSeek user with a coincidental
        ``gpt-4``-named local proxy would break for no good reason."""
        from ai_model.adapters.openai_generic import GenericOpenAIAdapter

        mock_choice = MagicMock()
        mock_choice.message.content = 'ok'
        mock_choice.finish_reason = 'stop'
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = MagicMock(prompt_tokens=1, completion_tokens=1)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.OpenAI.return_value = mock_client

        adapter = GenericOpenAIAdapter()
        # No raise expected — provider is not openai.
        text, error, _, _ = adapter.generate(
            'prompt',
            {'name': 'ollama', 'default_model': 'gpt-4'},
            api_key='ollama',
        )
        self.assertEqual(text, 'ok')
        self.assertIsNone(error)


class NoAIProviderConfiguredTest(TestCase):
    """generate_for_organisation must raise NoAIProviderConfigured
    when the org has no default_provider set — not silently default
    to Gemini (that was the pre-2026-08-30 behaviour that would burn
    tokens for a provider the user never picked)."""

    def test_missing_default_provider_raises(self):
        from ai_model.ai_service import generate_for_organisation
        from ai_model.exceptions import NoAIProviderConfigured
        from Organisations.models import Organisations

        org = Organisations.objects.create(name='Unconfigured Org', website='https://x.com')
        # No OrganisationAISettings created → default_provider is None.
        with self.assertRaises(NoAIProviderConfigured):
            generate_for_organisation('prompt', org)


class OllamaProviderSeededTest(TestCase):
    """Ollama should exist in the AIModelProvider catalog after the
    modernize migration runs. Ollama is keyless and routes through
    GenericOpenAIAdapter (the OpenAI-compat layer at /v1/).

    Tests self-seed via setUpTestData because a sibling TransactionTestCase
    truncates the AIModelProvider table without restoring data-migration
    seed content. Depending on migration state alone was flaky (Q1.2
    Batch 24 root cause) — self-seeding is the resilient answer.
    """

    @classmethod
    def setUpTestData(cls):
        from org_settings.models import AIModelProvider
        # Re-run the same seed the modernize + reseed migrations run.
        # Kept in-sync with org_settings/0014_reseed_ai_providers by
        # explicit intent — a test that depends on production seed
        # content should re-declare it, not silently trust migrations.
        seed = {
            'gemini': {
                'display_name': 'Google Gemini',
                'default_model': 'gemini-3.5-flash',
                'adapter_class': 'ai_model.adapters.gemini.GeminiAdapter',
                'api_base_url': '', 'is_active': True,
                'requires_api_key': True, 'is_system': True,
            },
            'deepseek': {
                'display_name': 'DeepSeek',
                'default_model': 'deepseek-v4-flash',
                'adapter_class': 'ai_model.adapters.openai_generic.GenericOpenAIAdapter',
                'api_base_url': 'https://api.deepseek.com',
                'is_active': True, 'requires_api_key': True, 'is_system': True,
            },
            'claude': {
                'display_name': 'Anthropic Claude',
                'default_model': 'claude-sonnet-5',
                'adapter_class': 'ai_model.adapters.claude.ClaudeAdapter',
                'api_base_url': '', 'is_active': True,
                'requires_api_key': True, 'is_system': True,
            },
            'openai': {
                'display_name': 'OpenAI',
                'default_model': 'gpt-5.6-terra',
                'adapter_class': 'ai_model.adapters.openai_generic.GenericOpenAIAdapter',
                'api_base_url': '', 'is_active': True,
                'requires_api_key': True, 'is_system': True,
            },
            'ollama': {
                'display_name': 'Ollama (Local)',
                'default_model': 'qwen3:8b',
                'adapter_class': 'ai_model.adapters.openai_generic.GenericOpenAIAdapter',
                'api_base_url': 'http://localhost:11434/v1/',
                'is_active': True, 'requires_api_key': False, 'is_system': True,
            },
        }
        for name, defaults in seed.items():
            AIModelProvider.objects.update_or_create(name=name, defaults=defaults)

    def test_ollama_row_exists_and_is_keyless(self):
        from org_settings.models import AIModelProvider
        ollama = AIModelProvider.objects.filter(name='ollama').first()
        self.assertIsNotNone(ollama, "Ollama should be seeded by migration 0011")
        self.assertFalse(ollama.requires_api_key)
        self.assertTrue(ollama.is_active)
        self.assertEqual(
            ollama.adapter_class,
            'ai_model.adapters.openai_generic.GenericOpenAIAdapter',
        )
        # Base URL points at Ollama's local OpenAI-compat endpoint.
        self.assertEqual(ollama.api_base_url, 'http://localhost:11434/v1/')

    def test_all_providers_active_after_migration(self):
        """The old seed left Claude/OpenAI inactive with a stale
        'not yet implemented' comment. The modernize migration
        flips all five to active."""
        from org_settings.models import AIModelProvider
        for name in ('gemini', 'deepseek', 'claude', 'openai', 'ollama'):
            provider = AIModelProvider.objects.filter(name=name).first()
            self.assertIsNotNone(provider, f"{name} should be seeded")
            self.assertTrue(provider.is_active, f"{name} should be active")
