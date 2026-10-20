"""
Tests for ObservabilityIntegrationViewSet.

Covers CRUD, health_check action, available_providers action,
org isolation, and permission enforcement (admin-only writes).
"""

from unittest.mock import patch, MagicMock

from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from Organisations.models import Organisations
from Users.models import User
from integrations.models import ObservabilityIntegration


class TestObservabilityIntegrationViewSet(APITestCase):
    """Tests for /integrations/observability/ endpoints."""

    def setUp(self):
        self.org = Organisations.objects.create(
            name='Int Org', website='https://int.com',
        )
        self.other_org = Organisations.objects.create(
            name='Other Org', website='https://other.com',
        )
        self.admin = User.objects.create_user(
            username='intadmin', email='ia@test.com',
            password='Test123!', organisation=self.org,
            role='admin', is_active=True,
        )
        self.user = User.objects.create_user(
            username='intuser', email='iu@test.com',
            password='Test123!', organisation=self.org,
            role='user', is_active=True,
        )
        self.other_admin = User.objects.create_user(
            username='otheradmin', email='oa@test.com',
            password='Test123!', organisation=self.other_org,
            role='admin', is_active=True,
        )

        self.list_url = reverse('observability-integration-list')

        self.es_integration = ObservabilityIntegration.objects.create(
            organisation=self.org, provider='elasticsearch',
            display_name='Org ES', capabilities=['logs'],
            host='http://es:9200',
        )

    def _auth(self, user):
        self.client.force_authenticate(user=user)

    # --- List / Retrieve ---

    def test_list_integrations(self):
        self._auth(self.admin)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)

    def test_list_org_isolation(self):
        """Cannot see other org's integrations."""
        ObservabilityIntegration.objects.create(
            organisation=self.other_org, provider='loki',
            display_name='Other Loki', capabilities=['logs'],
        )
        self._auth(self.admin)
        response = self.client.get(self.list_url)
        providers = [i['provider'] for i in response.data]
        self.assertNotIn('loki', providers)

    def test_retrieve_integration(self):
        """Returns details, password NOT in response."""
        self._auth(self.admin)
        url = reverse('observability-integration-detail', kwargs={'pk': self.es_integration.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn('password', response.data)

    # --- Create ---

    def test_create_elasticsearch(self):
        self._auth(self.admin)
        self.es_integration.delete()
        response = self.client.post(self.list_url, {
            'provider': 'elasticsearch',
            'display_name': 'New ES',
            'capabilities': ['logs'],
            'host': 'http://es:9200',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_prometheus(self):
        """Prometheus (metrics-only) created."""
        self._auth(self.admin)
        response = self.client.post(self.list_url, {
            'provider': 'prometheus',
            'display_name': 'Prom',
            'capabilities': ['metrics'],
            'host': 'http://prom:9090',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_datadog_dual(self):
        """Dual-capability (log+metric) created."""
        self._auth(self.admin)
        response = self.client.post(self.list_url, {
            'provider': 'datadog',
            'display_name': 'DD',
            'capabilities': ['logs', 'metrics'],
            'host': 'https://api.datadoghq.com',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_duplicate_provider(self):
        """unique_together (org, provider) enforced — only one per org."""
        self._auth(self.admin)
        count_before = ObservabilityIntegration.objects.filter(
            organisation=self.org, provider='elasticsearch',
        ).count()
        self.assertEqual(count_before, 1)
        duplicate_rejected = False
        try:
            with transaction.atomic():
                response = self.client.post(self.list_url, {
                    'provider': 'elasticsearch',
                    'display_name': 'Dup ES',
                    'capabilities': ['logs'],
                }, format='json')
                # If we reach here, the view returned a response
                self.assertNotEqual(response.status_code, status.HTTP_201_CREATED)
                duplicate_rejected = True
        except IntegrityError:
            # DB constraint caught the duplicate — expected
            duplicate_rejected = True
        self.assertTrue(duplicate_rejected)

    # --- Update / Delete ---

    def test_update_integration(self):
        self._auth(self.admin)
        url = reverse('observability-integration-detail', kwargs={'pk': self.es_integration.pk})
        response = self.client.patch(url, {
            'display_name': 'Updated ES',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.es_integration.refresh_from_db()
        self.assertEqual(self.es_integration.display_name, 'Updated ES')

    def test_delete_integration(self):
        self._auth(self.admin)
        url = reverse('observability-integration-detail', kwargs={'pk': self.es_integration.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            ObservabilityIntegration.objects.filter(pk=self.es_integration.pk).exists()
        )

    # --- Custom actions ---

    @patch('integrations.views.IntegrationRegistry')
    def test_health_check_action(self, mock_registry):
        mock_provider = MagicMock()
        mock_provider.health_check.return_value = True
        mock_registry.get_log_provider.return_value = mock_provider
        self._auth(self.admin)
        url = reverse('observability-integration-health-check', kwargs={'pk': self.es_integration.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('integrations', response.data)

    def test_available_providers(self):
        """Returns all provider types."""
        self._auth(self.user)
        url = reverse('observability-integration-available-providers')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = [p['code'] for p in response.data]
        self.assertIn('elasticsearch', codes)
        self.assertIn('prometheus', codes)

    # --- Permissions ---

    def test_create_denied_non_admin(self):
        """integration.manage (admin) blocks create for regular user."""
        self._auth(self.user)
        response = self.client.post(self.list_url, {
            'provider': 'loki',
            'display_name': 'Loki',
            'capabilities': ['logs'],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_allowed_non_admin(self):
        """Non-admin can list (read)."""
        self._auth(self.user)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
