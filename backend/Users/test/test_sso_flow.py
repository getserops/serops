"""
The OIDC callback belongs to the browser that started the sign-in.

The state used to be a signed organisation id, valid for any browser and any
number of callbacks, so an attacker could make a victim load the attacker's own
callback URL and sign the victim in to the attacker's account. There was no
nonce and no PKCE either.
"""
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import jwt
from django.core import signing
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from Organisations.models import Organisations
from Users.models import SecuritySettings, User
from Users.services.sso import SSOService
from Users.sso_views import SSO_FLOW_COOKIE, SSO_FLOW_SALT, _email_verified


def start_flow(client, org_id, nonce='the-nonce', verifier='the-verifier'):
    """Put a browser in the state /auth/sso/init leaves it in; returns the state."""
    state = signing.dumps({'org_id': org_id, 'flow': 'random'})
    client.cookies[SSO_FLOW_COOKIE] = signing.dumps(
        {'state': state, 'nonce': nonce, 'verifier': verifier}, salt=SSO_FLOW_SALT)
    return state


@override_settings(CORS_ALLOWED_ORIGINS=['https://app.test.local'], API_URL='https://app.test.local/api')
class FlowTestCase(APITestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Flow Org', website='https://flow.test')
        self.user = User.objects.create_user(
            username='flow', email='flow@example.com', password='TestPass123!',
            organisation=self.org, role='admin', is_active=True)
        self.settings = SecuritySettings.objects.create(
            organisation=self.org, sso_enabled=True, sso_provider='oidc', sso_client_id='client',
            sso_discovery_url='https://idp.example.com/.well-known/openid-configuration')
        self.settings.set_client_secret('secret')
        self.settings.save()

    def _idp(self, MockSSO, matches=True):
        sso = MockSSO.return_value
        sso.exchange_code_for_token.return_value = {'access_token': 'a', 'id_token': 'i'}
        sso.id_token_matches.return_value = matches
        sso.get_user_info.return_value = {'email': self.user.email, 'email_verified': True}
        return sso

    def _callback(self, state):
        return self.client.get('/api/auth/sso/callback', {'code': 'c', 'state': state})

    def assertFailed(self, response):
        self.assertEqual(response.status_code, 302)
        self.assertIn('sso=failed', response['Location'])
        self.assertNotIn('serops_sso_handoff', response.cookies)


class CallbackBindingTest(FlowTestCase):
    @patch('Users.sso_views.SSOService')
    def test_the_browser_that_started_the_flow_signs_in(self, MockSSO):
        sso = self._idp(MockSSO)
        response = self._callback(start_flow(self.client, self.org.id))
        self.assertTrue(response['Location'].endswith('/auth/callback'))
        sso.exchange_code_for_token.assert_called_once_with('c', code_verifier='the-verifier')
        sso.id_token_matches.assert_called_once_with({'access_token': 'a', 'id_token': 'i'}, 'the-nonce')

    @patch('Users.sso_views.SSOService')
    def test_another_browser_loading_the_callback_is_refused(self, MockSSO):
        sso = self._idp(MockSSO)
        state = signing.dumps({'org_id': self.org.id, 'flow': 'attackers'})
        self.assertFailed(self._callback(state))
        sso.exchange_code_for_token.assert_not_called()

    @patch('Users.sso_views.SSOService')
    def test_state_from_another_flow_is_refused(self, MockSSO):
        sso = self._idp(MockSSO)
        start_flow(self.client, self.org.id)
        self.assertFailed(self._callback(signing.dumps({'org_id': self.org.id, 'flow': 'other'})))
        sso.exchange_code_for_token.assert_not_called()

    @patch('Users.sso_views.SSOService')
    def test_flow_cookie_is_used_once(self, MockSSO):
        self._idp(MockSSO)
        response = self._callback(start_flow(self.client, self.org.id))
        self.assertEqual(response.cookies[SSO_FLOW_COOKIE].value, '')
        self.assertEqual(response.cookies[SSO_FLOW_COOKIE]['max-age'], 0)

    @patch('Users.sso_views.SSOService')
    def test_id_token_from_another_flow_is_refused(self, MockSSO):
        self._idp(MockSSO, matches=False)
        self.assertFailed(self._callback(start_flow(self.client, self.org.id)))


class InitTest(FlowTestCase):
    @patch('Users.sso_views.SSOService')
    def test_init_binds_the_flow_to_the_browser(self, MockSSO):
        MockSSO.return_value.get_authorization_url.return_value = ('https://idp.example.com/auth', 's')
        response = self.client.post('/api/auth/sso/init', {'email': self.user.email}, format='json')
        self.assertEqual(response.status_code, 200)
        kwargs = MockSSO.return_value.get_authorization_url.call_args.kwargs
        cookie = response.cookies[SSO_FLOW_COOKIE]
        self.assertTrue(cookie['httponly'])
        self.assertTrue(cookie['secure'])
        self.assertEqual(cookie['samesite'], 'Lax')
        self.assertEqual(cookie['path'], '/api/auth/sso/callback')
        flow = signing.loads(cookie.value, salt=SSO_FLOW_SALT)
        self.assertEqual(flow, {'state': kwargs['state'], 'nonce': kwargs['nonce'], 'verifier': kwargs['code_verifier']})
        self.assertNotIn(kwargs['code_verifier'], str(response.data))


class ServiceTest(SimpleTestCase):
    def _service(self):
        sso = SSOService('client', 'secret', 'https://idp.example.com/d', 'https://app/cb')
        sso.metadata = {'authorization_endpoint': 'https://idp.example.com/auth'}
        return sso

    def test_authorization_url_carries_nonce_and_pkce(self):
        url, _ = self._service().get_authorization_url(state='s', nonce='n', code_verifier='v' * 64)
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query['nonce'], ['n'])
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertNotEqual(query['code_challenge'], ['v' * 64])

    def _id_token(self, **claims):
        return {'id_token': jwt.encode(claims, 'k' * 32, algorithm='HS256')}

    def test_id_token_for_this_flow_matches(self):
        self.assertTrue(self._service().id_token_matches(self._id_token(nonce='n', aud='client'), 'n'))
        self.assertTrue(self._service().id_token_matches(self._id_token(nonce='n', aud=['x', 'client']), 'n'))

    def test_wrong_or_missing_nonce_does_not_match(self):
        self.assertFalse(self._service().id_token_matches(self._id_token(nonce='other', aud='client'), 'n'))
        self.assertFalse(self._service().id_token_matches(self._id_token(aud='client'), 'n'))

    def test_token_for_another_client_does_not_match(self):
        self.assertFalse(self._service().id_token_matches(self._id_token(nonce='n', aud='someone-else'), 'n'))

    def test_no_id_token_does_not_match(self):
        self.assertFalse(self._service().id_token_matches({'access_token': 'a'}, 'n'))


class EmailVerifiedTest(SimpleTestCase):
    KEYCLOAK = 'https://kc.example.com/realms/x/.well-known/openid-configuration'
    ENTRA = 'https://login.microsoftonline.com/t/v2.0/.well-known/openid-configuration'

    def test_true_passes(self):
        self.assertTrue(_email_verified({'email_verified': True}, self.KEYCLOAK))
        self.assertTrue(_email_verified({'email_verified': 'true'}, self.KEYCLOAK))

    def test_false_is_refused_even_as_a_string(self):
        self.assertFalse(_email_verified({'email_verified': False}, self.KEYCLOAK))
        self.assertFalse(_email_verified({'email_verified': 'false'}, self.ENTRA))

    def test_missing_claim_is_refused(self):
        self.assertFalse(_email_verified({}, self.KEYCLOAK))

    def test_missing_claim_is_accepted_from_a_provider_that_omits_it(self):
        self.assertTrue(_email_verified({}, self.ENTRA))
