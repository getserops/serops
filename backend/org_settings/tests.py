from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from Organisations.models import Organisations
from org_settings.models import SentinelConfig, AIModelProvider

User = get_user_model()


class SentinelConfigModelTest(TestCase):
    """Tests for the SentinelConfig model."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Sentinel Model Org')

    def test_create_with_defaults(self):
        config = SentinelConfig.objects.create(organisation=self.org)
        self.assertFalse(config.active_mode)
        self.assertEqual(config.error_spike_multiplier, 0)
        self.assertEqual(config.z_score_threshold, 0)
        self.assertEqual(config.max_quiet_batches, 12)

    def test_str_shadow_mode(self):
        config = SentinelConfig.objects.create(organisation=self.org)
        self.assertIn('shadow', str(config))
        self.assertIn(self.org.name, str(config))

    def test_str_active_mode(self):
        config = SentinelConfig.objects.create(organisation=self.org, active_mode=True)
        self.assertIn('active', str(config))

    def test_one_to_one_constraint(self):
        SentinelConfig.objects.create(organisation=self.org)
        with self.assertRaises(Exception):
            SentinelConfig.objects.create(organisation=self.org)


class SentinelConfigAPITest(TestCase):
    """Tests for SentinelConfigView API."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Sentinel API Org')
        self.user = User.objects.create_user(
            username='sentinelapi', email='sentinelapi@test.com',
            password='testpass123', organisation=self.org, role='admin'
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_get_creates_default_config(self):
        response = self.client.get('/api/settings/sentinel/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['active_mode'])
        self.assertEqual(data['max_quiet_batches'], 12)
        # Verify config was created in DB
        self.assertTrue(SentinelConfig.objects.filter(organisation=self.org).exists())

    def test_put_updates_config(self):
        # First GET to create
        self.client.get('/api/settings/sentinel/')
        # Now PUT to update
        response = self.client.put(
            '/api/settings/sentinel/',
            {'active_mode': True, 'max_quiet_batches': 20},
            format='json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['active_mode'])
        self.assertEqual(data['max_quiet_batches'], 20)

        # Verify persisted
        config = SentinelConfig.objects.get(organisation=self.org)
        self.assertTrue(config.active_mode)
        self.assertEqual(config.max_quiet_batches, 20)


# =============================================================================
# AI Provider Refactor Tests
# =============================================================================


class AIModelProviderModelTest(TestCase):
    """Tests for the refactored AIModelProvider model (no PROVIDER_CHOICES)."""

    def test_create_custom_provider_no_choices_constraint(self):
        """New providers can be created via DB without code changes."""
        provider = AIModelProvider.objects.create(
            name='mistral',
            display_name='Mistral AI',
            adapter_class='ai_model.adapters.openai_generic.GenericOpenAIAdapter',
            default_model='mistral-large-latest',
            env_key_name='MISTRAL_API_KEY',
            is_active=True,
        )
        self.assertEqual(provider.name, 'mistral')
        self.assertTrue(provider.is_active)
        self.assertEqual(provider.env_key_name, 'MISTRAL_API_KEY')

    def test_system_provider_flag(self):
        """System providers can be flagged via is_system."""
        provider = AIModelProvider.objects.create(
            name='test_sys',
            display_name='Test System',
            is_system=True,
        )
        self.assertTrue(provider.is_system)

    def test_env_fields_default_empty(self):
        """env_key_name and env_url_name default to empty string."""
        provider = AIModelProvider.objects.create(
            name='test_env',
            display_name='Test Env',
        )
        self.assertEqual(provider.env_key_name, '')
        self.assertEqual(provider.env_url_name, '')
        self.assertFalse(provider.is_system)


class AIProviderDeleteProtectionTest(TestCase):
    """Tests for DB-driven system provider delete protection."""

    def setUp(self):
        self.org = Organisations.objects.create(name='AI Delete Org')
        self.user = User.objects.create_user(
            username='aideluser', email='aidel@test.com',
            password='testpass123', organisation=self.org, role='admin',
            # The catalogue is shared by every organisation: only platform staff change it.
            is_staff=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_cannot_delete_system_provider(self):
        """System providers (is_system=True) cannot be deleted."""
        provider = AIModelProvider.objects.create(
            name='gemini_test',
            display_name='Gemini Test',
            is_system=True,
        )
        response = self.client.delete(f'/api/settings/ai/providers/{provider.id}/')
        self.assertEqual(response.status_code, 403)
        self.assertIn('Cannot delete system provider', response.json()['error'])
        # Verify not deleted
        self.assertTrue(AIModelProvider.objects.filter(pk=provider.pk).exists())

    def test_can_delete_non_system_provider(self):
        """Non-system providers can be deleted."""
        provider = AIModelProvider.objects.create(
            name='custom_provider',
            display_name='Custom Provider',
            is_system=False,
        )
        response = self.client.delete(f'/api/settings/ai/providers/{provider.id}/')
        self.assertEqual(response.status_code, 204)
        self.assertFalse(AIModelProvider.objects.filter(pk=provider.pk).exists())


class AIProviderKeyLookupTest(TestCase):
    """Tests for OrganisationAPIKey-only resolution in get_api_key_for_org.

    The env-var fallback was removed 2026-08-30 — these tests lock in
    the new behaviour so a future refactor can't silently restore
    cross-org key pooling. See ai_model/ai_service.py for reasoning.
    """

    def test_env_var_is_never_read_even_when_set(self):
        """A populated env var must not leak into resolution — the whole
        point of dropping the fallback was that shared env vars pool
        billing across orgs on multi-tenant self-host."""
        AIModelProvider.objects.create(
            name='testprov',
            display_name='Test Provider',
            env_key_name='TEST_PROV_API_KEY',
            env_url_name='TEST_PROV_URL',
        )
        with patch.dict('os.environ', {'TEST_PROV_API_KEY': 'sk-should-be-ignored'}):
            from ai_model.ai_service import get_api_key_for_org
            api_key, base_url, _extra = get_api_key_for_org(None, 'testprov')
            self.assertIsNone(api_key)
            self.assertIsNone(base_url)

    def test_no_org_returns_none(self):
        """No organisation → no key. Anonymous callers cannot pull
        credentials out of thin air."""
        AIModelProvider.objects.create(name='noorg', display_name='No Org')
        from ai_model.ai_service import get_api_key_for_org
        api_key, base_url, _extra = get_api_key_for_org(None, 'noorg')
        self.assertIsNone(api_key)
        self.assertIsNone(base_url)


class AIUnifiedGenerationTest(TestCase):
    """Tests for generate_text_unified without legacy fallback."""

    def test_unknown_provider_returns_error(self):
        """Non-existent provider returns error, no legacy fallback."""
        from ai_model.ai_service import generate_text_unified
        response, error, t_in, t_out = generate_text_unified(
            'test prompt', provider='nonexistent_provider'
        )
        self.assertIsNone(response)
        self.assertIsNotNone(error)
        self.assertEqual(error.code, 'PROVIDER_NOT_SUPPORTED')
        self.assertEqual(t_in, 0)
        self.assertEqual(t_out, 0)


class ClaudeAdapterTest(TestCase):
    """Tests for the ClaudeAdapter."""

    def test_generate_no_api_key(self):
        """Returns auth error when no API key provided."""
        from ai_model.adapters.claude import ClaudeAdapter
        adapter = ClaudeAdapter()
        response, error, t_in, t_out = adapter.generate(
            'test prompt', {'default_model': 'claude-sonnet-4-20250514'}, api_key=None
        )
        self.assertIsNone(response)
        self.assertEqual(error.code, 'AUTH_MISSING')

    @patch('ai_model.adapters.claude.anthropic')
    def test_generate_success(self, mock_anthropic):
        """Successful generation returns text and token counts."""
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text='Hello world')]
        mock_message.stop_reason = 'end_turn'
        mock_message.usage.input_tokens = 10
        mock_message.usage.output_tokens = 5

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        mock_anthropic.Anthropic.return_value = mock_client

        from ai_model.adapters.claude import ClaudeAdapter
        adapter = ClaudeAdapter()
        response, error, t_in, t_out = adapter.generate(
            'test prompt', {'default_model': 'claude-sonnet-4-20250514'}, api_key='sk-test'
        )
        self.assertEqual(response, 'Hello world')
        self.assertIsNone(error)
        self.assertEqual(t_in, 10)
        self.assertEqual(t_out, 5)

    @patch('ai_model.adapters.claude.anthropic')
    def test_generate_truncated(self, mock_anthropic):
        """Truncated response returns error with token counts."""
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text='partial response')]
        mock_message.stop_reason = 'max_tokens'
        mock_message.usage.input_tokens = 100
        mock_message.usage.output_tokens = 8192

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        mock_anthropic.Anthropic.return_value = mock_client

        from ai_model.adapters.claude import ClaudeAdapter
        adapter = ClaudeAdapter()
        response, error, t_in, t_out = adapter.generate(
            'test prompt', {'default_model': 'claude-sonnet-4-20250514'}, api_key='sk-test'
        )
        self.assertIsNone(response)
        self.assertEqual(error.code, 'TRUNCATED')
        self.assertEqual(t_in, 100)
        self.assertEqual(t_out, 8192)


class AIServiceErrorConsolidationTest(TestCase):
    """Tests for the consolidated AIServiceError class."""

    def test_from_type_known_error(self):
        """from_type creates error with correct code and message."""
        from ai_model.adapters.base import AIServiceError
        error = AIServiceError.from_type('quota_exceeded', 'raw details')
        self.assertEqual(error.code, 'QUOTA_EXCEEDED')
        self.assertEqual(error.error_type, 'quota_exceeded')
        self.assertEqual(error.raw_error, 'raw details')
        self.assertIn('rate limit', error.message.lower())

    def test_from_type_unknown_error(self):
        """from_type with unknown type falls back to UNKNOWN_ERROR."""
        from ai_model.adapters.base import AIServiceError
        error = AIServiceError.from_type('totally_new_error_type')
        self.assertEqual(error.code, 'UNKNOWN_ERROR')

    def test_direct_constructor(self):
        """Direct 5-param constructor still works for adapters."""
        from ai_model.adapters.base import AIServiceError
        error = AIServiceError('auth_error', 'AUTH_MISSING', 'No key', 'Add key')
        self.assertEqual(error.code, 'AUTH_MISSING')
        self.assertEqual(error.message, 'No key')

    def test_to_dict(self):
        """to_dict returns expected structure."""
        from ai_model.adapters.base import AIServiceError
        error = AIServiceError.from_type('timeout', 'connection timed out')
        d = error.to_dict()
        self.assertEqual(d['error_code'], 'TIMEOUT')
        self.assertIn('timed out', d['error_message'].lower())
        self.assertEqual(d['raw_error'], 'connection timed out')

    def test_str_representation(self):
        """__str__ returns code: message format."""
        from ai_model.adapters.base import AIServiceError
        error = AIServiceError.from_type('auth_error')
        self.assertIn('AUTH_ERROR', str(error))

    def test_get_display_status(self):
        """get_display_status returns FAILED (CODE) format."""
        from ai_model.adapters.base import AIServiceError
        error = AIServiceError.from_type('network_error')
        self.assertEqual(error.get_display_status(), 'FAILED (NETWORK_ERROR)')

    def test_get_user_message(self):
        """get_user_message returns combined message + action."""
        from ai_model.adapters.base import AIServiceError
        error = AIServiceError.from_type('content_blocked')
        msg = error.get_user_message()
        self.assertIn('blocked', msg.lower())


class AIProviderSerializerTest(TestCase):
    """Tests for AIModelProviderSerializer including new fields."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Serializer Org')
        self.user = User.objects.create_user(
            username='serializeruser', email='serializer@test.com',
            password='testpass123', organisation=self.org, role='admin'
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_serializer_includes_is_system(self):
        """API response includes is_system field."""
        AIModelProvider.objects.create(
            name='test_serial',
            display_name='Test Serial',
            is_system=True,
            env_key_name='TEST_KEY',
        )
        response = self.client.get('/api/settings/ai/providers/')
        self.assertEqual(response.status_code, 200)
        providers = response.json()
        test_prov = next(p for p in providers if p['name'] == 'test_serial')
        self.assertTrue(test_prov['is_system'])
        self.assertEqual(test_prov['env_key_name'], 'TEST_KEY')


class IssueSettingsMemoryAPITest(TestCase):
    """Tests for the past-incident memory fields on the IssueSettings API."""

    def setUp(self):
        from org_settings.models import IssueSettings
        self.IssueSettings = IssueSettings
        self.org = Organisations.objects.create(name='Memory Settings Org')
        self.admin = User.objects.create_user(
            username='memadmin', email='memadmin@test.com',
            password='testpass123', organisation=self.org, role='admin',
        )
        self.viewer = User.objects.create_user(
            username='memviewer', email='memviewer@test.com',
            password='testpass123', organisation=self.org, role='viewer',
        )
        self.client = APIClient()
        self.url = '/api/settings/issues/'

    def test_get_returns_memory_fields_with_defaults(self):
        """First GET creates the record and surfaces memory defaults."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['memory_enabled'])
        self.assertEqual(body['memory_window_days'], 90)
        self.assertEqual(body['memory_max_items'], 3)

    def test_put_persists_memory_fields(self):
        """PUT updates and persists each memory field."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.put(
            self.url,
            data={'memory_enabled': False, 'memory_window_days': 30, 'memory_max_items': 1},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body['memory_enabled'])
        self.assertEqual(body['memory_window_days'], 30)
        self.assertEqual(body['memory_max_items'], 1)
        # Round-trip through DB to be sure.
        record = self.IssueSettings.objects.get(organisation=self.org)
        self.assertFalse(record.memory_enabled)
        self.assertEqual(record.memory_window_days, 30)
        self.assertEqual(record.memory_max_items, 1)

    def test_put_rejects_out_of_range_window(self):
        """Validation guards against absurd window values."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.put(
            self.url, data={'memory_window_days': 0}, format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('memory_window_days', response.json())

    def test_put_rejects_out_of_range_max_items(self):
        """Validation guards against token-blowing item counts."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.put(
            self.url, data={'memory_max_items': 999}, format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('memory_max_items', response.json())

    def test_viewer_cannot_update(self):
        """Read-only roles cannot mutate org settings."""
        self.client.force_authenticate(user=self.viewer)
        response = self.client.put(
            self.url, data={'memory_enabled': False}, format='json',
        )
        # Requires(...) returns 403 (Permission denied) for non-admin roles.
        self.assertIn(response.status_code, (403, 401))


# =============================================================================
# has_working_smtp_config — env-only after 2026-09-01
# =============================================================================
# The SystemMailSettings model + views were removed. SMTP now comes
# exclusively from env vars (Grafana model). ``has_working_smtp_config``
# is the tiny boundary between "SMTP is configured" (send verification
# emails) and "not configured" (auto-activate first user).

from django.test import override_settings


class HasWorkingSmtpConfigTest(TestCase):
    """has_working_smtp_config is env-only after the 2026-09-01 removal."""

    @override_settings(EMAIL_HOST='smtp.env.example.com')
    def test_true_when_env_set(self):
        from notifications.services import has_working_smtp_config
        self.assertTrue(has_working_smtp_config())

    @override_settings(EMAIL_HOST=None)
    def test_false_when_env_unset(self):
        from notifications.services import has_working_smtp_config
        self.assertFalse(has_working_smtp_config())
