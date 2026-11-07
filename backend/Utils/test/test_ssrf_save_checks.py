"""User-configured URLs that were saved without the outbound URL check.

Security review 2026-11, finding 3 ("an unvalidated base_url").
"""

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from Organisations.models import Organisations
from Users.models import User

METADATA = 'http://169.254.169.254/latest/meta-data/'


class AIBaseUrlTest(SimpleTestCase):

    def test_an_ai_provider_base_url_on_the_metadata_endpoint_is_refused(self):
        from org_settings.serializers import APIKeyCreateUpdateSerializer
        serializer = APIKeyCreateUpdateSerializer(data={'provider_id': 1, 'base_url': METADATA})
        self.assertFalse(serializer.is_valid())
        self.assertIn('base_url', serializer.errors)

    def test_a_local_ollama_base_url_is_still_accepted(self):
        from org_settings.serializers import APIKeyCreateUpdateSerializer
        serializer = APIKeyCreateUpdateSerializer(
            data={'provider_id': 1, 'base_url': 'http://localhost:11434/v1/'})
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_the_adapter_refuses_a_metadata_base_url_at_call_time(self):
        from ai_model.adapters.openai_generic import GenericOpenAIAdapter
        text, error, _, _ = GenericOpenAIAdapter().generate(
            'hi', {'name': 'ollama', 'api_base_url': METADATA, 'default_model': 'llama3'}, api_key=None)
        self.assertIsNone(text)
        self.assertEqual(error.code, 'BASE_URL_REFUSED')


class GitLabProjectUrlTest(TestCase):

    def test_updating_a_gitlab_project_to_the_metadata_endpoint_is_refused(self):
        from providers.serializer import ProjectSerializer
        serializer = ProjectSerializer(data={
            'gitlab_url': METADATA, 'username': 'u', 'name': 'n', 'project_id': '1',
            'access_token': 't',
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('gitlab_url', serializer.errors)


class DatadogSiteTest(SimpleTestCase):

    def test_a_site_outside_datadogs_domains_falls_back_to_the_default(self):
        from integrations.adapters.datadog_logs import datadog_site
        for raw in ('x@169.254.169.254', 'evil.example.com', 'datadoghq.com.evil.io'):
            self.assertEqual(datadog_site({'extra_config': {'site': raw}}), 'datadoghq.com')

    def test_datadog_regional_sites_are_kept(self):
        from integrations.adapters.datadog_logs import datadog_site
        for raw in ('us5.datadoghq.com', 'datadoghq.eu', 'ap1.datadoghq.com', 'ddog-gov.com'):
            self.assertEqual(datadog_site({'site': raw}), raw)


class SSODiscoveryUrlTest(TestCase):

    def test_an_sso_discovery_url_on_the_metadata_endpoint_is_refused(self):
        org = Organisations.objects.create(name='SSOOrg')
        admin = User.objects.create_user(
            username='ssoadmin', email='a@sso.test', password='Pass1234!',
            organisation=org, role='admin', is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.put('/api/auth/sso/config', {
            'sso_provider': 'oidc', 'sso_client_id': 'c', 'sso_discovery_url': METADATA,
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('sso_discovery_url', response.json()['error'])
