"""
Tests for the unified ObservabilityIntegration model, API, and registry.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from rest_framework.test import APITestCase, APIClient

from integrations.models import ObservabilityIntegration, ADAPTER_MAP, _available_capabilities
from integrations.registry import IntegrationRegistry
from integrations.serializers import ObservabilityIntegrationSerializer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_org(name='test-org'):
    """Create a test Organisation."""
    from Organisations.models import Organisations
    return Organisations.objects.create(name=name)


def _create_user(org, username='testuser', role='admin'):
    """Create a test User linked to an org."""
    from Users.models import User
    user = User.objects.create_user(
        username=username,
        password='testpass123',
        email=f'{username}@test.com',
        organisation=org,
        role=role,
    )
    return user


# ---------------------------------------------------------------------------
# Model Tests
# ---------------------------------------------------------------------------

class ObservabilityIntegrationModelTests(TestCase):
    """Unit tests for the ObservabilityIntegration model."""

    def setUp(self):
        self.org = _create_org()

    def test_create_log_only_integration(self):
        integration = ObservabilityIntegration.objects.create(
            organisation=self.org,
            provider='elasticsearch',
            display_name='Elasticsearch',
            capabilities=['logs'],
            host='http://es:9200',
        )
        self.assertEqual(integration.capabilities, ['logs'])
        self.assertIn('ElasticsearchLogProvider', integration.log_adapter_class)
        self.assertEqual(integration.metric_adapter_class, '')

    def test_create_metric_only_integration(self):
        integration = ObservabilityIntegration.objects.create(
            organisation=self.org,
            provider='prometheus',
            display_name='Prometheus',
            capabilities=['metrics'],
            host='http://prom:9090',
        )
        self.assertEqual(integration.capabilities, ['metrics'])
        self.assertEqual(integration.log_adapter_class, '')
        self.assertIn('PrometheusMetricProvider', integration.metric_adapter_class)

    def test_create_dual_capability_integration(self):
        integration = ObservabilityIntegration.objects.create(
            organisation=self.org,
            provider='datadog',
            display_name='Datadog',
            capabilities=['logs', 'metrics'],
            host='https://api.datadoghq.com',
        )
        self.assertEqual(integration.capabilities, ['logs', 'metrics'])
        self.assertIn('DatadogLogProvider', integration.log_adapter_class)
        self.assertIn('DatadogMetricProvider', integration.metric_adapter_class)

    def test_unique_together_prevents_duplicates(self):
        ObservabilityIntegration.objects.create(
            organisation=self.org,
            provider='datadog',
            display_name='Datadog',
            capabilities=['logs'],
        )
        with self.assertRaises(Exception):
            ObservabilityIntegration.objects.create(
                organisation=self.org,
                provider='datadog',
                display_name='Datadog 2',
                capabilities=['metrics'],
            )

    def test_different_providers_same_org(self):
        """An org can have ES for logs AND Prometheus for metrics."""
        es = ObservabilityIntegration.objects.create(
            organisation=self.org,
            provider='elasticsearch',
            display_name='ES',
            capabilities=['logs'],
        )
        prom = ObservabilityIntegration.objects.create(
            organisation=self.org,
            provider='prometheus',
            display_name='Prom',
            capabilities=['metrics'],
        )
        self.assertEqual(
            ObservabilityIntegration.objects.filter(organisation=self.org).count(),
            2,
        )

    def test_get_config(self):
        integration = ObservabilityIntegration.objects.create(
            organisation=self.org,
            provider='elasticsearch',
            display_name='ES',
            capabilities=['logs'],
            host='http://es:9200',
            username='elastic',
            extra_config={'default_index': 'logs-*'},
        )
        integration.set_password('secret')
        integration.save(update_fields=['password'])
        config = integration.get_config()
        self.assertEqual(config['host'], 'http://es:9200')
        self.assertEqual(config['username'], 'elastic')
        self.assertEqual(config['password'], 'secret')
        self.assertEqual(config['default_index'], 'logs-*')

    def test_adapter_auto_set_on_save(self):
        """Adapter classes are auto-populated from ADAPTER_MAP on save."""
        integration = ObservabilityIntegration(
            organisation=self.org,
            provider='cloudwatch',
            display_name='CW',
            capabilities=['logs', 'metrics'],
        )
        # Before save, adapter fields are empty
        self.assertEqual(integration.log_adapter_class, '')
        self.assertEqual(integration.metric_adapter_class, '')

        integration.save()

        self.assertIn('CloudWatchLogProvider', integration.log_adapter_class)
        self.assertIn('CloudWatchMetricProvider', integration.metric_adapter_class)

    def test_available_capabilities_helper(self):
        self.assertEqual(_available_capabilities('elasticsearch'), ['logs'])
        self.assertEqual(_available_capabilities('prometheus'), ['metrics'])
        self.assertIn('logs', _available_capabilities('datadog'))
        self.assertIn('metrics', _available_capabilities('datadog'))
        self.assertEqual(_available_capabilities('unknown'), [])


# ---------------------------------------------------------------------------
# Serializer Tests
# ---------------------------------------------------------------------------

class ObservabilitySerializerTests(TestCase):
    """Test capability validation in the serializer."""

    def setUp(self):
        self.org = _create_org('ser-org')

    def test_rejects_invalid_capability_for_provider(self):
        data = {
            'provider': 'elasticsearch',
            'display_name': 'ES',
            'capabilities': ['metrics'],  # ES doesn't support metrics
        }
        serializer = ObservabilityIntegrationSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('capabilities', serializer.errors)

    def test_accepts_valid_capability(self):
        data = {
            'provider': 'elasticsearch',
            'display_name': 'ES',
            'capabilities': ['logs'],
            'host': 'http://es:9200',
        }
        serializer = ObservabilityIntegrationSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_rejects_empty_capabilities(self):
        data = {
            'provider': 'datadog',
            'display_name': 'DD',
            'capabilities': [],
        }
        serializer = ObservabilityIntegrationSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_password_is_write_only(self):
        integration = ObservabilityIntegration.objects.create(
            organisation=self.org,
            provider='elasticsearch',
            display_name='ES',
            capabilities=['logs'],
            password='supersecret',
        )
        serializer = ObservabilityIntegrationSerializer(integration)
        self.assertNotIn('password', serializer.data)

    def test_adapter_class_is_read_only(self):
        """adapter_class cannot be injected via API."""
        data = {
            'provider': 'elasticsearch',
            'display_name': 'ES',
            'capabilities': ['logs'],
            'log_adapter_class': 'evil.module.Backdoor',
        }
        serializer = ObservabilityIntegrationSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        # log_adapter_class should not be in validated_data (read_only)
        self.assertNotIn('log_adapter_class', serializer.validated_data)


# ---------------------------------------------------------------------------
# Registry Tests
# ---------------------------------------------------------------------------

class RegistryTests(TestCase):
    """Test that the registry correctly resolves providers from the unified model."""

    def setUp(self):
        self.org = _create_org('reg-org')
        IntegrationRegistry.clear_cache()

    def tearDown(self):
        IntegrationRegistry.clear_cache()

    @patch('integrations.registry.IntegrationRegistry._load_adapter')
    def test_get_log_provider_for_org_with_integration(self, mock_load):
        mock_provider = MagicMock()
        mock_load.return_value = mock_provider

        ObservabilityIntegration.objects.create(
            organisation=self.org,
            provider='loki',
            display_name='Loki',
            capabilities=['logs'],
            host='http://loki:3100',
        )

        provider = IntegrationRegistry.get_log_provider_for_org(self.org)
        self.assertEqual(provider, mock_provider)
        mock_load.assert_called_once()
        call_args = mock_load.call_args
        self.assertIn('LokiLogProvider', call_args[0][0])

    def test_get_log_provider_raises_when_not_configured(self):
        with self.assertRaises(ValueError) as ctx:
            IntegrationRegistry.get_log_provider_for_org(self.org)
        self.assertIn('No Log Integration configured', str(ctx.exception))

    @patch('integrations.registry.IntegrationRegistry._load_adapter')
    def test_get_metric_provider_for_org_with_integration(self, mock_load):
        mock_provider = MagicMock()
        mock_load.return_value = mock_provider

        ObservabilityIntegration.objects.create(
            organisation=self.org,
            provider='datadog',
            display_name='Datadog',
            capabilities=['logs', 'metrics'],
            host='https://api.datadoghq.com',
        )

        provider = IntegrationRegistry.get_metric_provider_for_org(self.org)
        call_args = mock_load.call_args
        self.assertIn('DatadogMetricProvider', call_args[0][0])

    def test_get_metric_provider_raises_when_not_configured(self):
        with self.assertRaises(ValueError) as ctx:
            IntegrationRegistry.get_metric_provider_for_org(self.org)
        self.assertIn('No Metric Integration configured', str(ctx.exception))

    def test_cache_scoped_by_org(self):
        """Two orgs don't share cached adapters."""
        org2 = _create_org('reg-org-2')
        IntegrationRegistry.clear_cache()

        key1 = IntegrationRegistry._make_cache_key('x.y.Z', {'a': 1}, org_id=self.org.id)
        key2 = IntegrationRegistry._make_cache_key('x.y.Z', {'a': 1}, org_id=org2.id)
        self.assertNotEqual(key1, key2)

    def test_clear_cache_per_org(self):
        IntegrationRegistry._cache['path:org=1:default'] = 'a'
        IntegrationRegistry._cache['path:org=2:default'] = 'b'

        IntegrationRegistry.clear_cache(org_id=1)

        self.assertNotIn('path:org=1:default', IntegrationRegistry._cache)
        self.assertIn('path:org=2:default', IntegrationRegistry._cache)


# ---------------------------------------------------------------------------
# API Tests
# ---------------------------------------------------------------------------

class ObservabilityAPITests(APITestCase):
    """Integration tests for the ObservabilityIntegration ViewSet."""

    def setUp(self):
        self.org = _create_org('api-org')
        self.user = _create_user(self.org, 'apiuser')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.base_url = '/api/integrations/observability/'

    def test_list_empty(self):
        resp = self.client.get(self.base_url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, [])

    def test_create_integration(self):
        resp = self.client.post(self.base_url, {
            'provider': 'elasticsearch',
            'display_name': 'ES',
            'capabilities': ['logs'],
            'host': 'http://es:9200',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['provider'], 'elasticsearch')
        self.assertEqual(resp.data['capabilities'], ['logs'])

    def test_create_dual_capability(self):
        resp = self.client.post(self.base_url, {
            'provider': 'datadog',
            'display_name': 'Datadog',
            'capabilities': ['logs', 'metrics'],
            'host': 'https://api.datadoghq.com',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertIn('logs', resp.data['capabilities'])
        self.assertIn('metrics', resp.data['capabilities'])

    def test_reject_invalid_capability(self):
        resp = self.client.post(self.base_url, {
            'provider': 'elasticsearch',
            'display_name': 'ES',
            'capabilities': ['metrics'],
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_update_integration(self):
        integration = ObservabilityIntegration.objects.create(
            organisation=self.org,
            provider='elasticsearch',
            display_name='ES',
            capabilities=['logs'],
            host='http://old:9200',
        )
        resp = self.client.patch(
            f'{self.base_url}{integration.id}/',
            {'host': 'http://new:9200'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        integration.refresh_from_db()
        self.assertEqual(integration.host, 'http://new:9200')

    def test_delete_integration(self):
        integration = ObservabilityIntegration.objects.create(
            organisation=self.org,
            provider='prometheus',
            display_name='Prom',
            capabilities=['metrics'],
        )
        resp = self.client.delete(f'{self.base_url}{integration.id}/')
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(
            ObservabilityIntegration.objects.filter(pk=integration.id).exists()
        )

    def test_org_isolation(self):
        """Users can only see their own org's integrations."""
        other_org = _create_org('other-org')
        ObservabilityIntegration.objects.create(
            organisation=other_org,
            provider='loki',
            display_name='Loki',
            capabilities=['logs'],
        )
        resp = self.client.get(self.base_url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 0)

    def test_duplicate_provider_rejected(self):
        ObservabilityIntegration.objects.create(
            organisation=self.org,
            provider='datadog',
            display_name='Datadog',
            capabilities=['logs'],
        )
        resp = self.client.post(self.base_url, {
            'provider': 'datadog',
            'display_name': 'Datadog 2',
            'capabilities': ['metrics'],
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_available_providers(self):
        resp = self.client.get(f'{self.base_url}providers/')
        self.assertEqual(resp.status_code, 200)
        providers = resp.data
        codes = [p['code'] for p in providers]
        self.assertIn('elasticsearch', codes)
        self.assertIn('datadog', codes)
        # Check capabilities are returned
        dd = next(p for p in providers if p['code'] == 'datadog')
        self.assertIn('logs', dd['capabilities'])
        self.assertIn('metrics', dd['capabilities'])

    @patch('integrations.registry.IntegrationRegistry.get_log_provider')
    def test_health_check(self, mock_get):
        mock_provider = MagicMock()
        mock_provider.health_check.return_value = True
        mock_get.return_value = mock_provider

        integration = ObservabilityIntegration.objects.create(
            organisation=self.org,
            provider='elasticsearch',
            display_name='ES',
            capabilities=['logs'],
        )
        resp = self.client.post(f'{self.base_url}{integration.id}/health-check/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['integrations'][0]['healthy'])

    def test_unauthenticated_rejected(self):
        client = APIClient()  # no auth
        resp = client.get(self.base_url)
        self.assertEqual(resp.status_code, 401)
