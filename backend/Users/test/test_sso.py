from unittest.mock import patch, MagicMock
from django.urls import reverse
from django.core import signing
from django.conf import settings
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

    def test_update_sso_config_saml(self):
        response = self.client.put(self.url, {
            'sso_enabled': True,
            'sso_provider': 'saml',
            'saml_entity_id': 'https://idp.example.com/entity',
            'saml_sso_url': 'https://idp.example.com/sso',
            'saml_x509_cert': 'MIIC...',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.sec_settings.refresh_from_db()
        self.assertEqual(self.sec_settings.saml_entity_id, 'https://idp.example.com/entity')

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

    def test_sso_init_saml_returns_400(self):
        """SAML is intentionally unsupported — the view rejects with 400
        and a hint pointing the admin at OIDC."""
        self.sec_settings.sso_provider = 'saml'
        self.sec_settings.save()
        response = self.client.post(self.url, {'email': 'ssoinit@example.com'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('SAML is not supported', response.data['error'])

    def test_sso_init_sso_not_enabled(self):
        self.sec_settings.sso_enabled = False
        self.sec_settings.sso_provider = 'none'
        self.sec_settings.save()
        response = self.client.post(self.url, {'email': 'ssoinit@example.com'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_sso_init_user_not_found(self):
        response = self.client.post(self.url, {'email': 'unknown@example.com'}, format='json')
        self.assertEqual(response.status_code, 404)

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

    def test_sso_callback_missing_code(self):
        state = signing.dumps({'org_id': self.org.id})
        response = self.client.get(self.url, {'state': state})
        self.assertEqual(response.status_code, 400)

    def test_sso_callback_invalid_state(self):
        response = self.client.get(self.url, {'code': 'authcode123', 'state': 'invalid-state'})
        self.assertEqual(response.status_code, 400)


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
