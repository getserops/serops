from unittest.mock import patch, MagicMock
from django.urls import reverse
from django.core import signing
from django.conf import settings
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from Users.models import User, SecuritySettings
from Organisations.models import Organisations


# =============================================================================
# SSOConfigView
# =============================================================================

class TestSSOConfigView(APITestCase):
    """Tests for SSO configuration GET/PUT."""

    def setUp(self):
        self.url = reverse('sso-config')
        self.org = Organisations.objects.create(name='SSO Org', website='https://sso.com')
        self.user = User.objects.create_user(
            username='ssouser',
            email='sso@example.com',
            password='TestPass123!',
            organisation=self.org,
            role='admin',
            is_active=True,
        )
        self.sec_settings = SecuritySettings.objects.create(
            organisation=self.org,
            sso_enabled=True,
            sso_provider='oidc',
            sso_client_id='test-client-id',
            sso_discovery_url='https://idp.example.com/.well-known/openid-configuration',
        )
        self.client.force_authenticate(user=self.user)

    def test_get_sso_config(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['sso_enabled'])
        self.assertEqual(response.data['sso_provider'], 'oidc')
        self.assertEqual(response.data['sso_client_id'], 'test-client-id')

    def test_update_sso_config_oidc(self):
        response = self.client.put(self.url, {
            'sso_enabled': True,
            'sso_provider': 'oidc',
            'sso_client_id': 'updated-client-id',
            'sso_discovery_url': 'https://new-idp.example.com/.well-known/openid-configuration',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.sec_settings.refresh_from_db()
        self.assertEqual(self.sec_settings.sso_client_id, 'updated-client-id')

    def test_saml_is_rejected(self):
        response = self.client.put(self.url, {'sso_enabled': True, 'sso_provider': 'saml'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.sec_settings.refresh_from_db()
        self.assertEqual(self.sec_settings.sso_provider, 'oidc')

    def test_disabling_sso_turns_it_off(self):
        response = self.client.put(self.url, {'sso_enabled': True, 'sso_provider': 'none'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.sec_settings.refresh_from_db()
        self.assertFalse(self.sec_settings.sso_enabled)

    def test_get_reports_the_redirect_uri(self):
        response = self.client.get(self.url)
        self.assertEqual(response.data['sso_redirect_uri'], f'{settings.API_URL}/auth/sso/callback')
        self.assertNotIn('saml_entity_id', response.data)

    def test_get_sso_config_for_a_new_organisation(self):
        # A fresh install's first visit to Settings → Security used to 404.
        self.sec_settings.delete()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['sso_enabled'])

    def test_sso_config_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (401, 403))


# =============================================================================
# SSOInitView
# =============================================================================

class TestSSOInitView(APITestCase):
    """Tests for SSO login initiation."""

    def setUp(self):
        self.url = reverse('sso-init')
        self.org = Organisations.objects.create(name='SSO Init Org', website='https://ssoinit.com')
        self.user = User.objects.create_user(
            username='ssoinituser',
            email='ssoinit@example.com',
            password='TestPass123!',
            organisation=self.org,
            role='admin',
            is_active=True,
        )
        self.sec_settings = SecuritySettings.objects.create(
            organisation=self.org,
            sso_enabled=True,
            sso_provider='oidc',
            sso_client_id='test-client',
            sso_discovery_url='https://idp.example.com/.well-known/openid-configuration',
        )
        self.sec_settings.set_client_secret('test-secret')
        self.sec_settings.save()

    @patch('Users.sso_views.SSOService')
    def test_sso_init_oidc_success(self, MockSSOService):
        mock_instance = MockSSOService.return_value
        mock_instance.get_authorization_url.return_value = ('https://idp.example.com/auth?client_id=test', 'state123')

        response = self.client.post(self.url, {'email': 'ssoinit@example.com'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('auth_url', response.data)

    @patch('Users.sso_views.SSOService')
    def test_email_match_ignores_case(self, MockSSOService):
        MockSSOService.return_value.get_authorization_url.return_value = ('https://idp.example.com/auth', 's')
        response = self.client.post(self.url, {'email': 'SSOInit@Example.com'}, format='json')
        self.assertEqual(response.status_code, 200)

    def _assert_unavailable(self, email='ssoinit@example.com'):
        response = self.client.post(self.url, {'email': email}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {'error': 'SSO is not available for this account.'})

    def test_sso_init_sso_not_enabled(self):
        self.sec_settings.sso_enabled = False
        self.sec_settings.sso_provider = 'none'
        self.sec_settings.save()
        self._assert_unavailable()

    def test_unknown_email_looks_like_sso_off(self):
        # A different answer for unknown emails would let anyone list accounts.
        self._assert_unavailable('unknown@example.com')

    def test_organisation_without_security_settings(self):
        # The demo returned 500 "SecuritySettings matching query does not exist."
        self.sec_settings.delete()
        self._assert_unavailable()

    def test_demo_and_inactive_accounts_cannot_use_sso(self):
        self.user.is_demo = True
        self.user.save(update_fields=['is_demo'])
        self._assert_unavailable()
        self.user.is_demo, self.user.is_active = False, False
        self.user.save(update_fields=['is_demo', 'is_active'])
        self._assert_unavailable()

    @patch('Users.sso_views.SSOService')
    def test_idp_errors_are_not_echoed(self, MockSSOService):
        MockSSOService.return_value.get_authorization_url.side_effect = RuntimeError('db password=hunter2')
        response = self.client.post(self.url, {'email': 'ssoinit@example.com'}, format='json')
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('hunter2', str(response.data))

    @override_settings(DEMO_ONLY_LOGIN=True)
    def test_refused_on_a_demo_only_host(self):
        response = self.client.post(self.url, {'email': 'ssoinit@example.com'}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['error'], 'demo_only')

    def test_sso_init_missing_email(self):
        response = self.client.post(self.url, {}, format='json')
        self.assertEqual(response.status_code, 400)


# =============================================================================
# SSOCallbackView
# =============================================================================

class TestSSOCallbackView(APITestCase):
    """Tests for SSO callback handling."""

    def setUp(self):
        self.url = reverse('sso-callback')
        self.org = Organisations.objects.create(name='SSO CB Org', website='https://ssocb.com')
        self.user = User.objects.create_user(
            username='ssocbuser',
            email='ssocb@example.com',
            password='TestPass123!',
            organisation=self.org,
            role='admin',
            is_active=True,
        )
        self.sec_settings = SecuritySettings.objects.create(
            organisation=self.org,
            sso_enabled=True,
            sso_provider='oidc',
            sso_client_id='test-client',
            sso_discovery_url='https://idp.example.com/.well-known/openid-configuration',
        )
        self.sec_settings.set_client_secret('test-secret')
        self.sec_settings.save()

    @patch('Users.sso_views.SSOService')
    def test_sso_callback_existing_user(self, MockSSOService):
        mock_sso = MockSSOService.return_value
        mock_sso.exchange_code_for_token.return_value = {'access_token': 'abc123'}
        mock_sso.get_user_info.return_value = {
            'email': 'ssocb@example.com',
            'given_name': 'SSO',
            'family_name': 'User',
        }

        state = signing.dumps({'org_id': self.org.id})
        response = self.client.get(self.url, {'code': 'authcode123', 'state': state})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].endswith('/auth/callback'))
        self.assertIn('serops_sso_handoff', response.cookies)

    @patch('Users.sso_views.SSOService')
    def test_sso_callback_creates_new_user(self, MockSSOService):
        mock_sso = MockSSOService.return_value
        mock_sso.exchange_code_for_token.return_value = {'access_token': 'abc123'}
        mock_sso.get_user_info.return_value = {
            'email': 'newssuser@example.com',
            'given_name': 'New',
            'family_name': 'SSO',
        }

        state = signing.dumps({'org_id': self.org.id})
        response = self.client.get(self.url, {'code': 'authcode123', 'state': state})
        self.assertEqual(response.status_code, 302)
        new_user = User.objects.get(email='newssuser@example.com')
        self.assertEqual(new_user.role, 'viewer')
        self.assertEqual(new_user.organisation_id, self.org.id)

    def _assert_failed(self, response):
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].endswith('/login?sso=failed'), response['Location'])
        self.assertNotIn('serops_sso_handoff', response.cookies)

    def _callback_as(self, MockSSOService, **user_info):
        mock_sso = MockSSOService.return_value
        mock_sso.exchange_code_for_token.return_value = {'access_token': 'abc123'}
        mock_sso.get_user_info.return_value = user_info
        state = signing.dumps({'org_id': self.org.id})
        return self.client.get(self.url, {'code': 'authcode123', 'state': state})

    def test_sso_callback_missing_code(self):
        state = signing.dumps({'org_id': self.org.id})
        self._assert_failed(self.client.get(self.url, {'state': state}))

    def test_sso_callback_invalid_state(self):
        self._assert_failed(self.client.get(self.url, {'code': 'authcode123', 'state': 'invalid-state'}))

    @patch('Users.sso_views.SSOService')
    def test_cannot_sign_in_as_a_member_of_another_organisation(self, MockSSOService):
        # An admin points their org's SSO at an IdP they control; it asserts
        # the email of someone in a different organisation.
        other_org = Organisations.objects.create(name='Victim Org', website='https://victim.com')
        User.objects.create_user(
            username='victim', email='victim@example.com', password='TestPass123!',
            organisation=other_org, role='admin', is_active=True,
        )
        self._assert_failed(self._callback_as(MockSSOService, email='victim@example.com', email_verified=True))

    @patch('Users.sso_views.SSOService')
    def test_unverified_email_is_refused(self, MockSSOService):
        self._assert_failed(self._callback_as(MockSSOService, email='ssocb@example.com', email_verified=False))

    @patch('Users.sso_views.SSOService')
    def test_inactive_user_is_refused(self, MockSSOService):
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        self._assert_failed(self._callback_as(MockSSOService, email='ssocb@example.com'))

    @patch('Users.sso_views.SSOService')
    def test_sso_switched_off_after_the_flow_started(self, MockSSOService):
        self.sec_settings.sso_enabled = False
        self.sec_settings.save()
        self._assert_failed(self._callback_as(MockSSOService, email='ssocb@example.com'))

    @patch('Users.sso_views.SSOService')
    def test_idp_failure_redirects_to_login(self, MockSSOService):
        MockSSOService.return_value.exchange_code_for_token.side_effect = RuntimeError('boom')
        state = signing.dumps({'org_id': self.org.id})
        self._assert_failed(self.client.get(self.url, {'code': 'authcode123', 'state': state}))

    @patch('Users.sso_views.SSOService')
    def test_new_sso_user_has_no_usable_password(self, MockSSOService):
        response = self._callback_as(
            MockSSOService, email='a.very.long.name.for.sso@example.com', email_verified=True)
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email='a.very.long.name.for.sso@example.com')
        self.assertFalse(user.has_usable_password())
        self.assertLessEqual(len(user.username), 20)

    @override_settings(DEMO_ONLY_LOGIN=True)
    @patch('Users.sso_views.SSOService')
    def test_refused_on_a_demo_only_host(self, MockSSOService):
        self._assert_failed(self._callback_as(MockSSOService, email='ssocb@example.com'))


# =============================================================================
# SSOService (unit tests)
# =============================================================================

from django.test import SimpleTestCase


class TestSSOService(SimpleTestCase):
    """Unit tests for SSOService OIDC methods."""

    METADATA = {
        'authorization_endpoint': 'https://idp.example.com/auth',
        'token_endpoint': 'https://idp.example.com/token',
        'userinfo_endpoint': 'https://idp.example.com/userinfo',
    }

    def _make_service(self):
        from Users.services.sso import SSOService
        sso = SSOService(
            client_id='test-client',
            client_secret='test-secret',
            discovery_url='https://idp.example.com/.well-known/openid-configuration',
            redirect_uri='https://app.example.com/callback',
        )
        sso.metadata = self.METADATA  # Pre-set to skip HTTP fetch
        return sso

    @patch('Users.services.sso.OAuth2Session')
    def test_get_authorization_url(self, MockOAuth2Session):
        mock_client = MockOAuth2Session.return_value
        mock_client.create_authorization_url.return_value = (
            'https://idp.example.com/auth?client_id=test&state=test-state',
            'test-state',
        )
        sso = self._make_service()
        url, state = sso.get_authorization_url(state='test-state')
        self.assertIn('https://idp.example.com/auth', url)
        self.assertIsNotNone(state)

    @patch('Users.services.sso.OAuth2Session')
    def test_exchange_code_for_token(self, MockOAuth2Session):
        mock_client = MockOAuth2Session.return_value
        mock_client.fetch_token.return_value = {
            'access_token': 'test-token',
            'token_type': 'Bearer',
        }
        sso = self._make_service()
        token = sso.exchange_code_for_token('auth-code-123')
        self.assertIn('access_token', token)
