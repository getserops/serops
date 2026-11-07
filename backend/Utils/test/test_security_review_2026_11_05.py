"""
Internal security review of main, 2026-11-05: each test pins one fix.
"""
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from django.core import signing
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from Organisations.models import Organisations
from Users.models import SecuritySettings, User


class GoogleKeyTest(SimpleTestCase):
    KEY = {'type': 'service_account', 'project_id': 'p', 'private_key': 'k', 'client_email': 'a@p.iam.gserviceaccount.com'}

    def load(self, **extra):
        from integrations.adapters.gcp_logging import _checked_key_info
        return _checked_key_info({**self.KEY, **extra})

    def test_a_token_uri_other_than_googles_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'token_uri'):
            self.load(token_uri='http://internal-svc:8080/admin')

    def test_another_universe_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'universe_domain'):
            self.load(universe_domain='evil.example')

    def test_googles_endpoint_is_accepted(self):
        self.assertEqual(self.load(token_uri='https://oauth2.googleapis.com/token')['token_uri'],
                         'https://oauth2.googleapis.com/token')
        self.assertEqual(self.load()['token_uri'], 'https://oauth2.googleapis.com/token')

    def test_the_health_check_never_echoes_the_error_text(self):
        from integrations.adapters.gcp_logging import _health_reason
        reason = _health_reason(Exception('500 internal-secret-body'), 'p', 'Logs Viewer')
        self.assertNotIn('internal-secret-body', reason)


class RedactionFormsTest(SimpleTestCase):
    def redact(self, text):
        from Utils.data_redaction import DataRedactionService
        return DataRedactionService().redact(text)[0]

    def test_escaped_json_arrow_and_url_encoded_secrets_are_masked(self):
        for line in (r'{\"password\": \"Hunter2Secret\"}', r'{\"client_secret\":\"abcdEFGH12345678\"}',
                     'db_password => Hunter2Secret', 'PASSWORD%3DHunter2Secret',
                     '{"log":"{\\"password\\":\\"Hunter2Secret\\"}"}'):
            self.assertNotIn('Hunter2Secret', self.redact(line), line)
            self.assertNotIn('abcdEFGH12345678', self.redact(line), line)

    def test_prose_stays_readable(self):
        self.assertEqual(self.redact('password reset failed for user 42'), 'password reset failed for user 42')


class KubernetesStateScopeTest(SimpleTestCase):
    def test_no_namespace_means_no_cluster_wide_query(self):
        from integrations.kubernetes_state import fetch_kubernetes_state
        prom = MagicMock()
        prom.query_range_expr.return_value = []
        out = fetch_kubernetes_state(prom, {'project_name': 'shop'}, datetime(2026, 11, 5, tzinfo=timezone.utc),
                                     datetime(2026, 11, 5, 0, 15, tzinfo=timezone.utc))
        exprs = [c.args[0] for c in prom.query_range_expr.call_args_list]
        self.assertTrue(all('kube_' not in e for e in exprs), exprs)
        self.assertEqual(out['restarts'], {})

    def test_label_values_are_escaped(self):
        from integrations.kubernetes_state import fetch_kubernetes_state
        prom = MagicMock()
        prom.query_range_expr.return_value = []
        fetch_kubernetes_state(prom, {'project_name': 'a"} or vector(1) #'}, datetime(2026, 11, 5, tzinfo=timezone.utc),
                               datetime(2026, 11, 5, 0, 15, tzinfo=timezone.utc))
        self.assertIn('project_name="a\\"} or vector(1) #"', prom.query_range_expr.call_args_list[0].args[0])


class IntegrationHostChangeTest(TestCase):
    def setUp(self):
        from integrations.models import ObservabilityIntegration
        self.org = Organisations.objects.create(name='HostOrg')
        self.admin = User.objects.create_user(username='hostadmin', email='hostadmin@example.com', password='x',
                                              organisation=self.org, role='admin', is_active=True)
        self.integration = ObservabilityIntegration.objects.create(
            organisation=self.org, provider='elasticsearch', display_name='ES', capabilities=['logs'],
            host='https://es.example.com:9200', username='elastic')
        self.integration.set_password('stored-password')
        self.integration.save()
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.url = f'/api/integrations/observability/{self.integration.pk}/'

    @patch('Utils.url_validator.validate_outbound_url', return_value=None)
    def test_a_new_host_needs_the_password_again(self, _):
        response = self.client.patch(self.url, {'host': 'https://attacker.example.com:9200'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('host', response.data)
        self.integration.refresh_from_db()
        self.assertEqual(self.integration.host, 'https://es.example.com:9200')

    def test_other_edits_keep_the_stored_password(self):
        response = self.client.patch(self.url, {'display_name': 'Logs'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.integration.refresh_from_db()
        self.assertEqual(self.integration.get_password(), 'stored-password')


class ActivationLinkTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='ActOrg')
        self.user = User.objects.create_user(username='act', email='act@example.com', password='x',
                                             organisation=self.org, role='admin', is_active=False)

    def get(self, token):
        return self.client.get(reverse('activate', kwargs={'token': token}))

    def test_an_unsalted_never_expiring_token_is_refused(self):
        self.assertEqual(self.get(signing.dumps(self.user.pk)).status_code, 400)

    def test_an_account_that_signed_in_before_is_not_reactivated(self):
        from Utils.email_utils import ACTIVATION_SALT
        from django.utils import timezone
        User.objects.filter(pk=self.user.pk).update(last_login=timezone.now())
        self.assertEqual(self.get(signing.dumps(self.user.pk, salt=ACTIVATION_SALT)).status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_a_new_account_is_activated(self):
        from Utils.email_utils import ACTIVATION_SALT
        self.assertEqual(self.get(signing.dumps(self.user.pk, salt=ACTIVATION_SALT)).status_code, 200)


@override_settings(ALERT_WEBHOOK_SECRETS={'alertmanager': 'shared-global'})
class AlertWebhookGlobalSecretTest(TestCase):
    BODY = {'alerts': [{'status': 'firing', 'fingerprint': 'f1', 'labels': {'alertname': 'X'}, 'annotations': {}}]}

    def post(self, org):
        return APIClient().post(f'/api/webhooks/alerts/alertmanager/{org.pk}/', self.BODY, format='json',
                                HTTP_AUTHORIZATION='Bearer shared-global')

    def test_the_global_secret_works_on_a_single_organisation_install(self):
        org = Organisations.objects.create(name='Only')
        self.assertNotEqual(self.post(org).status_code, 401)

    def test_the_global_secret_is_refused_with_several_organisations(self):
        victim = Organisations.objects.create(name='Victim')
        Organisations.objects.create(name='Attacker')
        self.assertEqual(self.post(victim).status_code, 401)


@override_settings(CORS_ALLOWED_ORIGINS=['https://app.test.local'])
class SSOAccountCreationTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='SSO Create Org')
        self.security = SecuritySettings.objects.create(
            organisation=self.org, sso_enabled=True, sso_provider='oidc', sso_client_id='client',
            sso_discovery_url='https://idp.example.com/.well-known/openid-configuration')
        self.security.set_client_secret('s')
        self.security.save()

    @patch('Users.sso_views.SSOService')
    def callback(self, email, MockSSO):
        MockSSO.return_value.exchange_code_for_token.return_value = 'idp-token'
        MockSSO.return_value.get_user_info.return_value = {'email': email}
        return APIClient().get('/api/auth/sso/callback', {
            'code': 'c', 'state': signing.dumps({'org_id': self.org.id})})

    def test_no_listed_domain_creates_no_account(self):
        self.callback('ceo@victimcorp.com')
        self.assertFalse(User.objects.filter(email='ceo@victimcorp.com').exists())

    def test_a_listed_domain_creates_the_account(self):
        self.security.sso_domains = ['acme.io']
        self.security.save()
        self.callback('new@acme.io')
        self.assertTrue(User.objects.filter(email='new@acme.io', organisation=self.org).exists())


class SSODomainsOnSharedInstallTest(APITestCase):
    def setUp(self):
        org = Organisations.objects.create(name='Tenant A')
        Organisations.objects.create(name='Tenant B')
        self.admin = User.objects.create_user(username='ta', email='ta@example.com', password='x',
                                              organisation=org, role='admin', is_active=True)
        self.url = reverse('sso-config')

    def test_an_org_admin_cannot_claim_domains(self):
        self.client.force_authenticate(self.admin)
        response = self.client.put(self.url, {'sso_provider': 'oidc', 'sso_domains': ['victimcorp.com']}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_the_operator_can(self):
        self.admin.is_staff = True
        self.admin.save()
        self.client.force_authenticate(self.admin)
        response = self.client.put(self.url, {'sso_provider': 'oidc', 'sso_domains': ['acme.io']}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
