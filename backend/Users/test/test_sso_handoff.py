"""
Tests for the SSO HttpOnly cookie handoff (replaces token-in-URL).

We cover:
- the handoff cookie is set with the right security flags
- the cookie's path is scoped to /api/auth/sso/exchange (so it never
  travels with normal API requests)
- the redirect target has no token / user_email in the query string
- the exchange endpoint returns the token + user identity and clears
  the cookie
- exchange fails cleanly when the cookie is missing or stale
- the redirect target is always picked from CORS_ALLOWED_ORIGINS — it
  is never user-controlled
"""

from unittest.mock import patch

from django.test import TestCase, override_settings
from knox.models import AuthToken
from rest_framework import status
from rest_framework.test import APIClient

from Organisations.models import Organisations
from Users.models import User, SecuritySettings
from Users.sso_views import SSO_HANDOFF_COOKIE, _validated_frontend_url


@override_settings(CORS_ALLOWED_ORIGINS=['https://app.test.local'])
class SSOCallbackHandoffTest(TestCase):
    """SSOCallbackView must set the token in a cookie, not in the URL."""

    def setUp(self):
        self.org = Organisations.objects.create(name='SSO Org')
        self.user = User.objects.create_user(
            username='ssouser', email='sso@test.com',
            password='unused-for-sso', organisation=self.org,
            role='admin', is_active=True,
        )
        self.security = SecuritySettings.objects.create(
            organisation=self.org,
            sso_enabled=True,
            sso_provider='oidc',
            sso_client_id='client',
            sso_discovery_url='https://idp.example.com/.well-known/openid-configuration',
        )
        self.security.set_client_secret('secret-shh')
        self.security.save()
        self.client = APIClient()

    def _make_state(self):
        from django.core import signing
        return signing.dumps({'org_id': self.org.id})

    @patch('Users.sso_views.SSOService')
    def test_callback_sets_handoff_cookie_and_redirects_without_token(self, MockSSO):
        MockSSO.return_value.exchange_code_for_token.return_value = 'idp-token'
        MockSSO.return_value.get_user_info.return_value = {
            'email': self.user.email,
            'given_name': 'Test',
            'family_name': 'User',
        }

        response = self.client.get('/api/auth/sso/callback', {
            'code': 'auth-code',
            'state': self._make_state(),
        })

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        # Redirect target must come from the CORS allowlist, no token leak.
        self.assertEqual(response['Location'], 'https://app.test.local/auth/callback')
        self.assertNotIn('token', response['Location'])
        self.assertNotIn('user_email', response['Location'])

        # Cookie is set on the redirect.
        self.assertIn(SSO_HANDOFF_COOKIE, response.cookies)
        cookie = response.cookies[SSO_HANDOFF_COOKIE]
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Lax')
        self.assertEqual(cookie['path'], '/api/auth/sso/exchange')

    def _cookie(self, MockSSO):
        MockSSO.return_value.exchange_code_for_token.return_value = 'idp-token'
        MockSSO.return_value.get_user_info.return_value = {'email': self.user.email}
        response = self.client.get('/api/auth/sso/callback', {'code': 'c', 'state': self._make_state()})
        return response.cookies[SSO_HANDOFF_COOKIE]

    @override_settings(API_URL='https://serops.test.local/api')
    @patch('Users.sso_views.SSOService')
    def test_cookie_is_secure_on_https(self, MockSSO):
        self.assertTrue(self._cookie(MockSSO)['secure'])

    @override_settings(API_URL='http://serops.lab/api')
    @patch('Users.sso_views.SSOService')
    def test_cookie_works_on_a_plain_http_install(self, MockSSO):
        # A Secure cookie is dropped by the browser over http, so the
        # exchange step could never find it.
        self.assertFalse(self._cookie(MockSSO)['secure'])


class SSOExchangeTest(TestCase):
    """Exchange endpoint returns the token + user, clears the cookie."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Exch Org')
        self.user = User.objects.create_user(
            username='exchuser', email='exch@test.com',
            password='unused', organisation=self.org,
            role='admin', is_active=True,
        )
        self.client = APIClient()
        _, self.token = AuthToken.objects.create(self.user)

    def test_exchange_returns_token_and_user_when_cookie_present(self):
        self.client.cookies[SSO_HANDOFF_COOKIE] = self.token
        response = self.client.post('/api/auth/sso/exchange')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['token'], self.token)
        self.assertEqual(response.data['user']['email'], self.user.email)
        self.assertEqual(response.data['user']['role'], 'admin')
        # Cookie cleared.
        self.assertEqual(
            response.cookies[SSO_HANDOFF_COOKIE].value, ''
        )

    def test_exchange_400_when_no_cookie(self):
        response = self.client.post('/api/auth/sso/exchange')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_exchange_400_when_cookie_value_is_unknown_token(self):
        self.client.cookies[SSO_HANDOFF_COOKIE] = 'a-token-that-doesnt-exist'
        response = self.client.post('/api/auth/sso/exchange')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class FrontendUrlValidationTest(TestCase):
    """The redirect target is always picked from server-side settings."""

    @override_settings(CORS_ALLOWED_ORIGINS=['https://allowed.test'])
    def test_picks_first_cors_origin(self):
        self.assertEqual(_validated_frontend_url(), 'https://allowed.test')

    @override_settings(CORS_ALLOWED_ORIGINS=[], REACT_URL='https://react.test')
    def test_falls_back_to_react_url(self):
        self.assertEqual(_validated_frontend_url(), 'https://react.test')

    @override_settings(CORS_ALLOWED_ORIGINS=[], REACT_URL=None)
    def test_local_fallback_only_when_nothing_configured(self):
        self.assertEqual(_validated_frontend_url(), 'http://localhost:3003')
