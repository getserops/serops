"""The settings page sends the Jenkins / Bitbucket username (and the Azure
DevOps organization) inside ``credentials`` next to ``access_token``. The
serializer refused or dropped it, so Jenkins could never authenticate
(phase 3 client test C3)."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from Organisations.models import Organisations
from providers.models import ProviderIntegration

User = get_user_model()


@patch('providers.views.ProviderIntegrationViewSet._provider_for')
class CredentialFieldsTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Cred Org')
        self.admin = User.objects.create_user(
            username='cred-admin', email='cred-admin@example.com', password='Test123!',
            organisation=self.org, role='admin', is_active=True)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _create(self, **body):
        base = {'name': 'Jenkins', 'provider_type': 'jenkins', 'base_url': 'https://jenkins.example.com'}
        base.update(body)
        r = self.client.post('/api/providers/integrations/', base, format='json')
        self.assertIn(r.status_code, (200, 201), r.content)
        return ProviderIntegration.objects.get(pk=r.json()['id'])

    def test_settings_page_shape_keeps_the_username(self, _):
        integ = self._create(access_token='jenkins-api-token-example', credentials={'username': 'ci-bot'})
        creds = integ.get_credentials()
        self.assertEqual(creds.get('username'), 'ci-bot')
        self.assertEqual(integ.get_access_token(), 'jenkins-api-token-example')

    def test_token_inside_credentials_with_username(self, _):
        integ = self._create(credentials={'api_token': 'jenkins-api-token-example', 'username': 'ci-bot'})
        self.assertEqual(integ.get_credentials().get('username'), 'ci-bot')
        self.assertEqual(integ.get_access_token(), 'jenkins-api-token-example')

    def test_azure_organization_is_kept(self, _):
        integ = self._create(provider_type='azure_devops', base_url='https://dev.azure.com',
                             access_token='ado-pat-example', credentials={'organization': 'acme'})
        self.assertEqual(integ.provider_organization(), 'acme')

    def test_new_token_keeps_the_username(self, _):
        integ = self._create(access_token='old-token-example', credentials={'username': 'ci-bot'})
        r = self.client.patch(f'/api/providers/integrations/{integ.pk}/',
                              {'access_token': 'new-token-example'}, format='json')
        self.assertIn(r.status_code, (200, 202), r.content)
        integ.refresh_from_db()
        self.assertEqual(integ.get_access_token(), 'new-token-example')
        self.assertEqual(integ.get_credentials().get('username'), 'ci-bot')

    def test_new_username_keeps_the_token(self, _):
        integ = self._create(access_token='token-example', credentials={'username': 'ci-bot'})
        r = self.client.patch(f'/api/providers/integrations/{integ.pk}/',
                              {'credentials': {'username': 'deploy-bot'}}, format='json')
        self.assertIn(r.status_code, (200, 202), r.content)
        integ.refresh_from_db()
        self.assertEqual(integ.get_access_token(), 'token-example')
        self.assertEqual(integ.get_credentials().get('username'), 'deploy-bot')
