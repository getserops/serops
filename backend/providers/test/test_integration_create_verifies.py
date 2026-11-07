"""A new integration is verified when it is created: the dialog's Test
connection runs before it exists, and an unverified integration cannot list
its repositories (found in the GitHub journey)."""
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from Organisations.models import Organisations
from providers.models import ProviderIntegration

User = get_user_model()


class CreateVerifiesTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Verify Org')
        self.admin = User.objects.create_user(
            username='verify-admin', email='verify-admin@example.com', password='Test123!',
            organisation=self.org, role='admin', is_active=True)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def create(self):
        return self.client.post('/api/providers/integrations/', {
            'name': 'Acme GitHub', 'provider_type': 'github', 'category': 'devops',
            'access_token': 'github_pat_x', 'base_url': 'https://github.com'}, format='json')

    @patch('providers.views.ProviderIntegrationViewSet._provider_for')
    def test_a_working_token_is_verified_on_creation(self, provider_for):
        provider_for.return_value = MagicMock(verify_connection=MagicMock(return_value={'username': 'acme'}))
        self.assertEqual(self.create().status_code, 201)
        self.assertTrue(ProviderIntegration.objects.get(name='Acme GitHub').is_verified)

    @patch('providers.views.ProviderIntegrationViewSet._provider_for')
    def test_a_bad_token_is_saved_as_failed(self, provider_for):
        provider_for.return_value = MagicMock(verify_connection=MagicMock(side_effect=Exception('Invalid GitHub access token')))
        self.assertEqual(self.create().status_code, 201)
        i = ProviderIntegration.objects.get(name='Acme GitHub')
        self.assertEqual((i.verification_status, i.verification_error), ('failed', 'Invalid GitHub access token'))
