"""SAML sign-in against a real Keycloak (integration).

Skipped unless SEROPS_TEST_KEYCLOAK_URL points at a Keycloak whose master
admin is admin / SEROPS_TEST_KEYCLOAK_PASSWORD (backend/docker-compose.yml,
profile "sso"). The test creates its own realm, SAML client, groups and
user, signs in through Keycloak's real login form, posts Keycloak's
response to our ACS, and deletes the realm at the end.

    docker-compose --profile sso up -d keycloak
    SEROPS_TEST_KEYCLOAK_URL=http://keycloak:8080 python manage.py test ee.tests.test_saml_keycloak
"""
import html
import os
import re
import unittest
from urllib.parse import urljoin, urlsplit

import requests
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APITestCase

from Data.models import AuditLog
from Organisations.models import Organisations, Team, TeamMembership
from Users.models import SecuritySettings, User
from Utils.testing import licensed
from ee.saml import service

KEYCLOAK = os.environ.get('SEROPS_TEST_KEYCLOAK_URL', '').rstrip('/')
ADMIN_PASSWORD = os.environ.get('SEROPS_TEST_KEYCLOAK_PASSWORD', 'local-test-only')
REALM = 'serops-saml-it'
USER_PASSWORD = 'It-only-Passw0rd!'


def _form(page):
    """(action, {name: value}) of the first form in a Keycloak page."""
    action = re.search(r'<form[^>]*action="([^"]+)"', page)
    fields = dict(re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', page))
    return html.unescape(action.group(1)) if action else None, {k: html.unescape(v) for k, v in fields.items()}


@unittest.skipUnless(KEYCLOAK, 'SEROPS_TEST_KEYCLOAK_URL not set')
@override_settings(API_URL='http://localhost:8000/api')
class KeycloakSamlTest(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        token = requests.post(f'{KEYCLOAK}/realms/master/protocol/openid-connect/token', data={
            'grant_type': 'password', 'client_id': 'admin-cli', 'username': 'admin', 'password': ADMIN_PASSWORD,
        }, timeout=30)
        token.raise_for_status()
        cls.admin = requests.Session()
        cls.admin.headers['Authorization'] = f"Bearer {token.json()['access_token']}"
        cls.api = f'{KEYCLOAK}/admin/realms'
        cls.admin.delete(f'{cls.api}/{REALM}', timeout=30)
        cls.admin.post(cls.api, json={'realm': REALM, 'enabled': True}, timeout=30).raise_for_status()
        for group in ('serops-users', 'sre', 'finance'):
            cls.admin.post(f'{cls.api}/{REALM}/groups', json={'name': group}, timeout=30).raise_for_status()

    @classmethod
    def tearDownClass(cls):
        cls.admin.delete(f'{cls.api}/{REALM}', timeout=30)
        super().tearDownClass()

    def setUp(self):
        patcher = licensed('saml')
        patcher.start()
        self.addCleanup(patcher.stop)
        cache.clear()
        self.org = Organisations.objects.create(name='Acme')
        self.sre = Team.objects.create(organisation=self.org, name='SRE')
        SecuritySettings.objects.create(
            organisation=self.org, sso_enabled=True, sso_provider='saml', sso_domains=['acme.test'],
            sso_groups_claim='groups', sso_default_role='deny',
            sso_role_mappings=[{'group': 'serops-users', 'role': 'user'}],
            sso_team_mappings=[{'group': 'sre', 'team_id': self.sre.pk}],
        )
        self.config = service.get_or_create_config(self.org)
        self.client_uuid = self._create_client()
        self.username = f'ada{self.org.pk}'
        self.email = f'{self.username}@acme.test'
        self._create_user(groups=['serops-users', 'sre'])
        # Our side reads Keycloak's metadata from its URL, like an admin would.
        admin_user = User.objects.create_user(username='admin', email='admin@acme.test', password='x',
                                              organisation=self.org, role='admin', is_active=True)
        self.client.force_authenticate(admin_user)
        r = self.client.put('/api/ee/saml/config/', {
            'idp_metadata_url': f'{KEYCLOAK}/realms/{REALM}/protocol/saml/descriptor'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['configured'])
        self.client.force_authenticate(None)

    def tearDown(self):
        self.admin.delete(f'{self.api}/{REALM}/clients/{self.client_uuid}', timeout=30)

    # --- Keycloak set-up -----------------------------------------------------

    def _create_client(self, **attributes):
        attrs = {
            'saml.assertion.signature': 'true',     # sign the assertion (we require it)
            'saml.server.signature': 'true',        # and the response
            'saml.client.signature': 'false',       # our AuthnRequests are not signed
            'saml_name_id_format': 'email',
            'saml.force.name.id.format': 'true',
            'saml.signature.algorithm': 'RSA_SHA256',
            'saml_assertion_consumer_url_post': service.acs_url(self.config),
            'saml_idp_initiated_sso_url_name': f'serops{self.org.pk}',
            **attributes,
        }
        body = {
            'clientId': service.sp_entity_id(self.config), 'protocol': 'saml', 'enabled': True,
            'redirectUris': [service.acs_url(self.config)], 'attributes': attrs, 'frontchannelLogout': False,
            'protocolMappers': [
                {'name': 'groups', 'protocol': 'saml', 'protocolMapper': 'saml-group-membership-mapper',
                 'config': {'attribute.name': 'groups', 'full.path': 'false', 'single': 'false',
                            'attribute.nameformat': 'Basic'}},
                *({'name': prop, 'protocol': 'saml', 'protocolMapper': 'saml-user-property-mapper',
                   'config': {'user.attribute': prop, 'attribute.name': prop, 'attribute.nameformat': 'Basic'}}
                  for prop in ('email', 'firstName', 'lastName')),
            ],
        }
        r = self.admin.post(f'{self.api}/{REALM}/clients', json=body, timeout=30)
        r.raise_for_status()
        return r.headers['Location'].rsplit('/', 1)[-1]

    def _update_client(self, **attributes):
        url = f'{self.api}/{REALM}/clients/{self.client_uuid}'
        client = self.admin.get(url, timeout=30).json()
        client['attributes'].update(attributes)
        self.admin.put(url, json=client, timeout=30).raise_for_status()

    def _create_user(self, groups):
        r = self.admin.post(f'{self.api}/{REALM}/users', json={
            'username': self.username, 'email': self.email, 'emailVerified': True, 'enabled': True,
            'firstName': 'Ada', 'lastName': 'Lovelace',
            'credentials': [{'type': 'password', 'value': USER_PASSWORD, 'temporary': False}],
        }, timeout=30)
        r.raise_for_status()
        self.user_id = r.headers['Location'].rsplit('/', 1)[-1]
        all_groups = {g['name']: g['id'] for g in self.admin.get(f'{self.api}/{REALM}/groups', timeout=30).json()}
        for g in groups:
            self.admin.put(f'{self.api}/{REALM}/users/{self.user_id}/groups/{all_groups[g]}', timeout=30)

    # --- The browser ----------------------------------------------------------

    def _keycloak_login(self, browser, url):
        """Follow ``url`` through Keycloak's login form; Keycloak's auto-post form back to us."""
        page = browser.get(url, timeout=30)
        page.raise_for_status()
        action, fields = _form(page.text)
        if 'SAMLResponse' not in fields:
            self.assertIsNotNone(action, page.text[:500])
            page = browser.post(urljoin(page.url, action), data={
                'username': self.username, 'password': USER_PASSWORD, 'credentialId': ''}, timeout=30)
            page.raise_for_status()
            action, fields = _form(page.text)
        self.assertIn('SAMLResponse', fields, page.text[:800])
        self.assertEqual(action, service.acs_url(self.config))
        return fields['SAMLResponse']

    def _post_acs(self, saml_response):
        return self.client.post(urlsplit(service.acs_url(self.config)).path, {'SAMLResponse': saml_response})

    def _sp_initiated(self, browser=None):
        browser = browser or requests.Session()
        r = self.client.post('/api/auth/sso/init', {'email': self.email}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['auth_url'].startswith(f'{KEYCLOAK}/realms/{REALM}/protocol/saml?SAMLRequest='))
        return self._keycloak_login(browser, r.data['auth_url'])

    def assertSignedIn(self, r):
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].endswith('/auth/callback'), r['Location'])

    # --- Tests --------------------------------------------------------------

    def test_sp_initiated_sign_in_roles_teams_and_replay(self):
        saml_response = self._sp_initiated()
        self.assertSignedIn(self._post_acs(saml_response))
        user = User.objects.get(email=self.email)
        self.assertEqual((user.role, user.first_name, user.last_name), ('user', 'Ada', 'Lovelace'))
        self.assertTrue(TeamMembership.objects.filter(user=user, team=self.sre).exists())
        self.assertTrue(AuditLog.objects.filter(action='SSO_PROVISION', details__source='saml').exists())
        # The same response a second time: refused.
        r = self._post_acs(saml_response)
        self.assertTrue(r['Location'].endswith('/login?sso=failed'))

    def test_idp_initiated(self):
        browser = requests.Session()
        url = f'{KEYCLOAK}/realms/{REALM}/protocol/saml/clients/serops{self.org.pk}'
        self.assertSignedIn(self._post_acs(self._keycloak_login(browser, url)))

    def test_encrypted_assertion(self):
        self._update_client(**{'saml.encrypt': 'true', 'saml.encryption.certificate': self.config.sp_certificate})
        saml_response = self._sp_initiated()
        import base64
        self.assertIn(b'EncryptedAssertion', base64.b64decode(saml_response))
        self.assertSignedIn(self._post_acs(saml_response))

    def test_no_mapped_group_is_denied(self):
        self.admin.delete(f'{self.api}/{REALM}/users/{self.user_id}', timeout=30)
        self._create_user(groups=['finance'])
        r = self._post_acs(self._sp_initiated())
        self.assertTrue(r['Location'].endswith('/login?sso=denied'), r['Location'])

    def test_unsigned_assertion_from_keycloak_is_refused(self):
        self._update_client(**{'saml.assertion.signature': 'false'})
        r = self._post_acs(self._sp_initiated())
        self.assertTrue(r['Location'].endswith('/login?sso=failed'), r['Location'])
