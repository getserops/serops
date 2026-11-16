"""API defaults a fresh client trips over (phase 3 client test C1,
2026-11-16)."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from Organisations.models import Organisations
from integrations.models import ObservabilityIntegration
from providers.models import ProviderIntegration


class ApiDefaultsTest(APITestCase):
    def setUp(self):
        org = Organisations.objects.create(name='C1 Org')
        self.admin = get_user_model().objects.create_user(
            username='c1admin', email='c1@example.com', password='Test123!x',
            organisation=org, role='admin', is_active=True)
        self.client.force_authenticate(self.admin)

    def test_observability_integration_without_capabilities_gets_the_providers(self):
        r = self.client.post('/api/integrations/observability/', {
            'provider': 'loki', 'display_name': 'Loki', 'host': 'http://loki.monitoring:3100'}, format='json')
        self.assertIn(r.status_code, (200, 201), r.content)
        self.assertEqual(ObservabilityIntegration.objects.get(pk=r.json()['id']).capabilities, ['logs'])

    def test_explicit_capabilities_are_kept(self):
        r = self.client.post('/api/integrations/observability/', {
            'provider': 'datadog', 'display_name': 'DD', 'host': 'https://api.datadoghq.eu',
            'capabilities': ['logs']}, format='json')
        self.assertIn(r.status_code, (200, 201), r.content)
        self.assertEqual(ObservabilityIntegration.objects.get(pk=r.json()['id']).capabilities, ['logs'])

    @patch('providers.views.ProviderIntegrationViewSet._provider_for')
    def test_credentials_object_is_the_token(self, _):
        r = self.client.post('/api/providers/integrations/', {
            'name': 'GH', 'provider_type': 'github', 'base_url': 'https://api.github.com',
            'credentials': {'access_token': 'ghp_example_not_real'}}, format='json')
        self.assertIn(r.status_code, (200, 201), r.content)
        self.assertEqual(ProviderIntegration.objects.get(pk=r.json()['id']).get_access_token(),
                         'ghp_example_not_real')

    def test_credentials_without_a_token_is_refused(self):
        r = self.client.post('/api/providers/integrations/', {
            'name': 'GH', 'provider_type': 'github', 'base_url': 'https://api.github.com',
            'credentials': {'user': 'x'}}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('credentials', r.json())
