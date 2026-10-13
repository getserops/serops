"""
Tests for Services app views: ServiceViewSet, SCMServiceViewSet,
InfraServiceViewSet, CustomServiceViewSet.

Previously 0 view tests existed — only model tests.
"""

from unittest.mock import patch, MagicMock

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from Organisations.models import Organisations
from Users.models import User
from Projects.models import Project
from Services.models import Service, SCMService, InfraService, CustomService


class ServiceViewTestBase(APITestCase):
    """Shared setUp for Service view tests."""

    def setUp(self):
        self.org = Organisations.objects.create(
            name='Svc Org', website='https://svc.com',
        )
        self.admin = User.objects.create_user(
            username='svcadmin', email='sa@test.com',
            password='Test123!', organisation=self.org,
            role='admin', is_active=True,
        )
        self.viewer = User.objects.create_user(
            username='svcviewer', email='sv@test.com',
            password='Test123!', organisation=self.org,
            role='viewer', is_active=True,
        )

        self.project = Project.objects.create(
            name='svc-project', organisation=self.org,
        )

    def _auth(self, user):
        self.client.force_authenticate(user=user)


class TestServiceViewSet(ServiceViewTestBase):
    """Tests for the polymorphic /services/all/ endpoint."""

    def setUp(self):
        super().setUp()
        self.list_url = reverse('service-list')

    @patch('Services.serializers.ServiceListSerializer.get_service_type', return_value={'type': 'test'})
    def test_list_services(self, _mock_service_type):
        SCMService.objects.create(
            project=self.project, name='my-scm',
            provider='gitlab', external_id='ext-1', access_token='tok',
        )
        self._auth(self.admin)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)

    def test_create_scm_service(self):
        self._auth(self.admin)
        response = self.client.post(self.list_url, {
            'project': self.project.pk,
            'name': 'new-scm',
            'category': 'scm',
            'provider': 'github',
            'external_id': 'gh-1',
            'access_token': 'secret-tok',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_infra_service(self):
        self._auth(self.admin)
        response = self.client.post(self.list_url, {
            'project': self.project.pk,
            'name': 'new-infra',
            'category': 'infrastructure',
            'infra_type': 'database',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_custom_service(self):
        self._auth(self.admin)
        response = self.client.post(self.list_url, {
            'project': self.project.pk,
            'name': 'new-custom',
            'category': 'custom',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch('Services.serializers.ServiceListSerializer.get_service_type', return_value={'type': 'test'})
    def test_filter_by_project(self, _mock_service_type):
        SCMService.objects.create(
            project=self.project, name='proj-scm',
            provider='gitlab', external_id='e-2', access_token='tok',
        )
        self._auth(self.admin)
        response = self.client.get(self.list_url, {'project': self.project.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('Services.serializers.ServiceListSerializer.get_service_type', return_value={'type': 'test'})
    def test_filter_by_category(self, _mock_service_type):
        SCMService.objects.create(
            project=self.project, name='cat-scm',
            provider='gitlab', external_id='e-3', access_token='tok',
        )
        self._auth(self.admin)
        response = self.client.get(self.list_url, {'category': 'scm'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_delete_service(self):
        svc = CustomService.objects.create(
            project=self.project, name='del-me',
        )
        self._auth(self.admin)
        url = reverse('service-detail', kwargs={'pk': svc.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_viewer_readonly(self):
        self._auth(self.viewer)
        response = self.client.post(self.list_url, {
            'project': self.project.pk,
            'name': 'nope',
            'category': 'custom',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TestSCMServiceViewSet(ServiceViewTestBase):
    """Tests for /services/scm/ endpoint."""

    def setUp(self):
        super().setUp()
        self.list_url = reverse('scm-service-list')
        self.scm = SCMService.objects.create(
            project=self.project, name='test-scm',
            provider='gitlab', external_id='scm-ext-1',
            access_token='secret', default_branch='main',
        )

    def test_list_scm_services(self):
        self._auth(self.admin)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_scm_service(self):
        """access_token write-only (not in response)."""
        self._auth(self.admin)
        response = self.client.post(self.list_url, {
            'project': self.project.pk,
            'name': 'new-scm-2',
            'provider': 'github',
            'external_id': 'scm-ext-2',
            'access_token': 'tok-secret',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn('access_token', response.data)

    def test_unique_provider_external_id(self):
        """Duplicate (provider, external_id) rejected."""
        self._auth(self.admin)
        response = self.client.post(self.list_url, {
            'project': self.project.pk,
            'name': 'dup-scm',
            'provider': 'gitlab',
            'external_id': 'scm-ext-1',
            'access_token': 'tok',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch.object(SCMService, 'get_provider_client', create=True)
    def test_setup_webhook_action(self, mock_client):
        mock_client.return_value = MagicMock()
        self._auth(self.admin)
        url = reverse('scm-service-setup-webhook', kwargs={'pk': self.scm.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.scm.refresh_from_db()
        self.assertTrue(self.scm.webhook_enabled)

    def test_viewer_readonly(self):
        self._auth(self.viewer)
        response = self.client.post(self.list_url, {
            'project': self.project.pk,
            'name': 'nope',
            'provider': 'gitlab',
            'external_id': 'nope-1',
            'access_token': 'tok',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TestInfraServiceViewSet(ServiceViewTestBase):
    """Tests for /services/infra/ endpoint."""

    def setUp(self):
        super().setUp()
        self.list_url = reverse('infra-service-list')

    def test_create_infra_service(self):
        """connection_string write-only."""
        self._auth(self.admin)
        response = self.client.post(self.list_url, {
            'project': self.project.pk,
            'name': 'pg-db',
            'infra_type': 'database',
            'provider': 'postgresql',
            'connection_string': 'postgres://localhost:5432/db',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn('connection_string', response.data)

    def test_health_check_action(self):
        """last_health_check updated."""
        infra = InfraService.objects.create(
            project=self.project, name='redis-cache',
            infra_type='cache', provider='redis',
        )
        self._auth(self.admin)
        url = reverse('infra-service-health-check', kwargs={'pk': infra.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        infra.refresh_from_db()
        self.assertIsNotNone(infra.last_health_check)
        self.assertEqual(infra.health_status, 'healthy')

    def test_list_infra_services(self):
        InfraService.objects.create(
            project=self.project, name='infra-1',
            infra_type='cache',
        )
        self._auth(self.admin)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_readonly(self):
        self._auth(self.viewer)
        response = self.client.post(self.list_url, {
            'project': self.project.pk,
            'name': 'nope',
            'infra_type': 'database',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TestCustomServiceViewSet(ServiceViewTestBase):
    """Tests for /services/custom/ endpoint."""

    def setUp(self):
        super().setUp()
        self.list_url = reverse('custom-service-list')

    def test_create_custom_service(self):
        """api_key write-only."""
        self._auth(self.admin)
        response = self.client.post(self.list_url, {
            'project': self.project.pk,
            'name': 'my-custom',
            'api_key': 'sk-secret-key',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn('api_key', response.data)

    def test_list_custom_services(self):
        CustomService.objects.create(
            project=self.project, name='custom-1',
        )
        self._auth(self.admin)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_readonly(self):
        self._auth(self.viewer)
        response = self.client.post(self.list_url, {
            'project': self.project.pk,
            'name': 'nope',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
