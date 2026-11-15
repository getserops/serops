"""SAML 2.0 single sign-on (Enterprise, feature ``saml``).

Responses come from a test identity provider (saml_idp.py) that signs and
encrypts them like Entra ID, Okta and Keycloak do, so these tests run the
real XML signature, decryption and condition checks.
"""
import datetime
from urllib.parse import parse_qs, urlsplit

from django.core.cache import cache
from django.test import override_settings
from onelogin.saml2.utils import OneLogin_Saml2_Utils
from rest_framework.test import APITestCase

from Data.models import AuditLog
from Organisations.models import Organisations, Team, TeamMembership
from Users.models import SecuritySettings, User
from Utils.edition import LICENSE_REQUIRED
from Utils.testing import licensed
from ee.models import SamlAssertion, SamlConfig
from ee.saml import service
from ee.tests.saml_idp import ENTITY_ID, SSO_URL, TestIdP, cert_body

ENTRA_GROUPS = 'http://schemas.microsoft.com/ws/2008/06/identity/claims/groups'
ENTRA_EMAIL = 'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress'


def ago(seconds):
    return datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=seconds)


# Our URLs come from API_URL, which ends in /api in every deployment (helm,
# quick-start, .env.example). Pinned here so the tests never depend on the
# environment: CI once set it without /api and every ACS post went to a 404.
@override_settings(API_URL='http://localhost:8000/api')
class SamlBase(APITestCase):
    idp = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.idp = TestIdP()
        cls.other_idp = TestIdP()

    def setUp(self):
        cache.clear()  # pending requests and the ACS throttle
        self.org = Organisations.objects.create(name='Acme')
        self.admin = User.objects.create_user(username='admin', email='admin@acme.test', password='pw-admin-123',
                                              organisation=self.org, role='admin', is_active=True)
        self.sre = Team.objects.create(organisation=self.org, name='SRE')
        self.sec = SecuritySettings.objects.create(
            organisation=self.org, sso_enabled=True, sso_provider='saml', sso_domains=['acme.test'],
            sso_groups_claim='groups', sso_default_role='viewer',
            sso_role_mappings=[{'group': 'serops-admins', 'role': 'admin'}, {'group': 'serops-users', 'role': 'user'}],
            sso_team_mappings=[{'group': 'sre', 'team_id': self.sre.pk}],
        )
        self.config = service.get_or_create_config(self.org)
        self.config.idp_entity_id, self.config.idp_sso_url, self.config.idp_certificates = \
            service.parse_idp_metadata(self.idp.metadata())
        self.config.save()

    @property
    def acs(self):
        return service.acs_url(self.config)

    @property
    def audience(self):
        return service.sp_entity_id(self.config)

    def acs_path(self):
        return urlsplit(self.acs).path

    def post(self, saml_response):
        return self.client.post(self.acs_path(), {'SAMLResponse': saml_response, 'RelayState': 'https://evil.test/'})

    def respond(self, **kwargs):
        kwargs.setdefault('acs', self.acs)
        kwargs.setdefault('audience', self.audience)
        return self.post(self.idp.response(**kwargs))

    def start(self, email='ada@acme.test'):
        """SP-initiated: the AuthnRequest ID we sent."""
        r = self.client.post('/api/auth/sso/init', {'email': email}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        url = urlsplit(r.data['auth_url'])
        self.assertEqual(f'{url.scheme}://{url.netloc}{url.path}', SSO_URL)
        xml = OneLogin_Saml2_Utils.decode_base64_and_inflate(parse_qs(url.query)['SAMLRequest'][0])
        from lxml import etree
        return etree.fromstring(xml).get('ID')

    def assertSignedIn(self, r):
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].endswith('/auth/callback'), r['Location'])
        self.assertIn('serops_sso_handoff', r.cookies)

    def assertFailed(self, r):
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].endswith('/login?sso=failed'), r['Location'])
        self.assertNotIn('serops_sso_handoff', r.cookies)


@licensed('saml')
class SamlSignInTest(SamlBase):
    def test_sp_initiated_creates_the_account_with_role_and_team(self):
        request_id = self.start()
        r = self.respond(in_response_to=request_id, groups=['serops-users', 'sre'],
                         attributes={'firstName': 'Ada', 'lastName': 'Lovelace'})
        self.assertSignedIn(r)
        user = User.objects.get(email='ada@acme.test')
        self.assertEqual((user.role, user.organisation_id, user.first_name, user.last_name),
                         ('user', self.org.pk, 'Ada', 'Lovelace'))
        self.assertFalse(user.has_usable_password())
        self.assertTrue(TeamMembership.objects.filter(user=user, team=self.sre, source='sso').exists())
        log = AuditLog.objects.get(organisation=self.org, action='SSO_PROVISION')
        self.assertEqual(log.details['source'], 'saml')
        # The sign-in itself is in the audit log, like a password login.
        login = AuditLog.objects.get(organisation=self.org, action='LOGIN')
        self.assertEqual((login.user, login.details['source'], login.details['email']), (user, 'saml', 'ada@acme.test'))
        # The handoff cookie is exchanged for a token like after OIDC.
        self.client.cookies['serops_sso_handoff'] = r.cookies['serops_sso_handoff'].value
        exchanged = self.client.post('/api/auth/sso/exchange')
        self.assertEqual(exchanged.status_code, 200)
        self.assertEqual(exchanged.data['user']['email'], 'ada@acme.test')

    def test_relay_state_never_redirects_elsewhere(self):
        r = self.respond(groups=['serops-users'])
        self.assertNotIn('evil.test', r['Location'])

    def test_idp_initiated_when_allowed(self):
        self.assertSignedIn(self.respond(groups=['serops-users']))

    def test_idp_initiated_refused_when_not_allowed(self):
        self.config.allow_idp_initiated = False
        self.config.save()
        self.assertFailed(self.respond(groups=['serops-users']))
        # SP-initiated still works.
        self.assertSignedIn(self.respond(in_response_to=self.start(), groups=['serops-users']))

    def test_expired_assertion(self):
        self.assertFailed(self.respond(issued=ago(900), lifetime=300))

    def test_clock_skew_tolerated(self):
        # Issued two minutes "in the future" by an IdP whose clock is ahead.
        self.assertSignedIn(self.respond(issued=ago(-120)))

    def test_clock_far_ahead_refused(self):
        self.assertFailed(self.respond(issued=ago(-900)))

    def test_older_than_max_age_even_if_the_idp_says_valid(self):
        self.assertFailed(self.respond(issued=ago(service.MAX_ASSERTION_AGE_SECONDS + service.CLOCK_SKEW_SECONDS + 60),
                                       lifetime=3600))

    def test_unsigned_assertion(self):
        self.assertFailed(self.respond(sign_assertion=False))

    def test_signed_response_around_unsigned_assertion(self):
        self.assertFailed(self.respond(sign_assertion=False, sign_response=True))

    def test_signed_response_and_assertion(self):
        self.assertSignedIn(self.respond(sign_response=True))

    def test_signed_by_another_key(self):
        self.assertFailed(self.respond(key=self.other_idp.key, cert=self.other_idp.cert))

    def test_tampered_after_signing(self):
        import base64
        raw = base64.b64decode(self.idp.response(acs=self.acs, audience=self.audience, email='ada@acme.test'))
        tampered = raw.replace(b'ada@acme.test', b'admin@acme.test')
        self.assertFailed(self.post(base64.b64encode(tampered).decode()))
        self.assertFalse(AuditLog.objects.filter(action='LOGIN', user=self.admin).exists())

    def test_sha1_signature_refused(self):
        self.assertFailed(self.respond(digest_sha1=True))

    def test_wrong_audience(self):
        self.assertFailed(self.respond(audience='https://other-sp.test/metadata/'))

    def test_wrong_issuer(self):
        self.assertFailed(self.respond(issuer='https://evil-idp.test/'))

    def test_wrong_destination(self):
        self.assertFailed(self.respond(destination='https://other-sp.test/acs/'))

    def test_replayed_assertion(self):
        response = self.idp.response(acs=self.acs, audience=self.audience, groups=['serops-users'])
        self.assertSignedIn(self.post(response))
        self.assertFailed(self.post(response))
        self.assertEqual(SamlAssertion.objects.count(), 1)

    def test_replay_survives_a_new_response_with_the_same_assertion_id(self):
        self.assertSignedIn(self.respond(assertion_id='_fixed'))
        self.assertFailed(self.respond(assertion_id='_fixed'))

    def test_unknown_in_response_to(self):
        self.assertFailed(self.respond(in_response_to='_never-sent'))

    def test_request_id_is_single_use(self):
        request_id = self.start()
        self.assertSignedIn(self.respond(in_response_to=request_id))
        self.assertFailed(self.respond(in_response_to=request_id))

    def test_request_of_another_organisation(self):
        other = Organisations.objects.create(name='Other')
        cache.set(service._request_key('_theirs'), other.pk, 60)
        self.assertFailed(self.respond(in_response_to='_theirs'))

    def test_encrypted_assertion(self):
        self.assertSignedIn(self.respond(encrypt_to=self.config.sp_certificate, groups=['serops-users']))

    def test_encryption_required(self):
        self.config.want_assertions_encrypted = True
        self.config.save()
        self.assertFailed(self.respond())
        self.assertSignedIn(self.respond(encrypt_to=self.config.sp_certificate))

    def test_email_from_attribute_with_opaque_nameid(self):
        # Entra ID's default NameID can be a persistent opaque ID.
        r = self.respond(nameid='AAAAAAAAAAAAAAAAAAAAAOpaqueId', email='ignored',
                         attributes={ENTRA_EMAIL: 'grace@acme.test'})
        self.assertSignedIn(r)
        self.assertTrue(User.objects.filter(email='grace@acme.test').exists())

    def test_no_email_anywhere(self):
        self.assertFailed(self.respond(nameid='opaque-id', email='x'))

    def test_groups_split_over_repeated_attributes(self):
        # Keycloak's group mapper: one <Attribute Name="groups"> per group.
        import base64
        raw = base64.b64decode(self.idp.response(acs=self.acs, audience=self.audience, sign_assertion=False,
                                                 groups=['serops-users', 'sre'])).decode()
        raw = raw.replace('<saml:AttributeValue xsi:type="xs:string">serops-users</saml:AttributeValue>',
                          '<saml:AttributeValue xsi:type="xs:string">serops-users</saml:AttributeValue>'
                          '</saml:Attribute><saml:Attribute Name="groups">')
        # Re-sign the edited assertion as the IdP would.
        from lxml import etree
        from onelogin.saml2.constants import OneLogin_Saml2_Constants as C
        from onelogin.saml2.utils import OneLogin_Saml2_Utils
        doc = etree.fromstring(raw.encode())
        assertion = doc.find('{urn:oasis:names:tc:SAML:2.0:assertion}Assertion')
        signed = OneLogin_Saml2_Utils.add_sign(etree.tostring(assertion).decode(), self.idp.key, self.idp.cert,
                                               sign_algorithm=C.RSA_SHA256, digest_algorithm=C.SHA256)
        doc.replace(assertion, etree.fromstring(signed))
        self.assertSignedIn(self.post(base64.b64encode(etree.tostring(doc)).decode()))
        user = User.objects.get(email='ada@acme.test')
        self.assertEqual(user.role, 'user')
        self.assertTrue(TeamMembership.objects.filter(user=user, team=self.sre).exists())

    def test_entra_groups_claim(self):
        self.sec.sso_groups_claim = ENTRA_GROUPS
        self.sec.save()
        self.assertSignedIn(self.respond(groups=['serops-admins'], groups_attribute=ENTRA_GROUPS))
        self.assertEqual(User.objects.get(email='ada@acme.test').role, 'admin')

    def test_deny_default(self):
        self.sec.sso_default_role = 'deny'
        self.sec.save()
        r = self.respond(groups=['finance'])
        self.assertTrue(r['Location'].endswith('/login?sso=denied'))
        self.assertTrue(AuditLog.objects.filter(action='SSO_DENIED', details__source='saml').exists())
        self.assertFalse(AuditLog.objects.filter(action='LOGIN').exists())

    def test_sync_role_and_teams_at_each_sign_in(self):
        self.sec.sso_sync_role = True
        self.sec.save()
        self.assertSignedIn(self.respond(groups=['serops-admins', 'sre']))
        user = User.objects.get(email='ada@acme.test')
        self.assertEqual(user.role, 'admin')
        self.assertSignedIn(self.respond(groups=['serops-users']))
        user.refresh_from_db()
        self.assertEqual(user.role, 'user')
        self.assertFalse(TeamMembership.objects.filter(user=user, team=self.sre).exists())

    def test_member_of_another_organisation_refused(self):
        other = Organisations.objects.create(name='Other')
        User.objects.create_user(username='bob', email='bob@acme.test', password='x', organisation=other,
                                 role='admin', is_active=True)
        self.assertFailed(self.respond(email='bob@acme.test'))

    def test_unlisted_domain_without_account(self):
        self.assertFailed(self.respond(email='eve@elsewhere.test'))

    def test_saml_off_or_oidc_selected(self):
        self.sec.sso_provider = 'oidc'
        self.sec.save()
        self.assertFailed(self.respond())

    def test_failures_are_audited_without_the_assertion(self):
        self.respond(audience='https://other-sp.test/metadata/')
        log = AuditLog.objects.get(organisation=self.org, action='SSO_DENIED')
        self.assertEqual(log.details['source'], 'saml')
        self.assertNotIn('Signature', str(log.details))

    def test_garbage(self):
        self.assertFailed(self.post('not base64 at all'))
        self.assertFailed(self.post(''))

    def test_unknown_sp_id(self):
        r = self.client.post('/api/ee/saml/00000000-0000-0000-0000-000000000000/acs/', {'SAMLResponse': 'x'})
        self.assertFailed(r)


class SamlWithoutLicenseTest(SamlBase):
    """Inert without the license: no sign-in, no metadata, and nobody locked out."""

    def test_acs_refuses_a_valid_response(self):
        self.assertFailed(self.respond(groups=['serops-users']))
        self.assertFalse(User.objects.filter(email='ada@acme.test').exists())

    def test_init_gives_the_generic_answer(self):
        r = self.client.post('/api/auth/sso/init', {'email': 'admin@acme.test'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_metadata_404(self):
        self.assertEqual(self.client.get(urlsplit(service.sp_entity_id(self.config)).path).status_code, 404)

    def test_enforcement_does_not_apply(self):
        self.sec.sso_enforced = True
        self.sec.save()
        User.objects.create_user(username='m', email='m@acme.test', password='pw-member-123',
                                 organisation=self.org, role='user', is_active=True)
        r = self.client.post('/api/auth/login', {'email': 'm@acme.test', 'password': 'pw-member-123'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def test_config_readable_not_writable(self):
        self.client.force_authenticate(self.admin)
        r = self.client.get('/api/ee/saml/config/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['licensed'])
        r = self.client.put('/api/ee/saml/config/', {'email_attribute': 'mail'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data['code'], LICENSE_REQUIRED)

    def test_cannot_switch_to_saml(self):
        self.sec.sso_provider = 'oidc'
        self.sec.save()
        self.client.force_authenticate(self.admin)
        r = self.client.put('/api/auth/sso/config', {'sso_provider': 'saml', 'sso_enabled': True}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data['code'], LICENSE_REQUIRED)

    def test_can_switch_away_from_saml(self):
        self.client.force_authenticate(self.admin)
        r = self.client.put('/api/auth/sso/config', {'sso_provider': 'none', 'sso_enabled': False}, format='json')
        self.assertEqual(r.status_code, 200, r.data)


@licensed('saml')
class SamlEnforcedTest(SamlBase):
    def setUp(self):
        super().setUp()
        self.sec.sso_enforced = True
        self.sec.save()
        self.member = User.objects.create_user(username='m', email='m@acme.test', password='pw-member-123',
                                               organisation=self.org, role='user', is_active=True)

    def login(self, email, password):
        return self.client.post('/api/auth/login', {'email': email, 'password': password}, format='json')

    def test_members_must_use_sso(self):
        r = self.login('m@acme.test', 'pw-member-123')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data['code'], 'sso_required')

    def test_wrong_password_answer_unchanged(self):
        # Enforcement is checked after the password: it reveals nothing.
        self.assertEqual(self.login('m@acme.test', 'wrong').status_code, 401)

    def test_admins_keep_a_way_in(self):
        self.assertEqual(self.login('admin@acme.test', 'pw-admin-123').status_code, 200)

    def test_off_when_sso_is_off(self):
        self.sec.sso_enabled = False
        self.sec.save()
        self.assertEqual(self.login('m@acme.test', 'pw-member-123').status_code, 200)

    def test_turning_sso_off_clears_enforcement(self):
        self.client.force_authenticate(self.admin)
        self.client.put('/api/auth/sso/config', {'sso_provider': 'none', 'sso_enabled': False}, format='json')
        self.sec.refresh_from_db()
        self.assertFalse(self.sec.sso_enforced)


@licensed('saml')
class SamlConfigApiTest(SamlBase):
    url = '/api/ee/saml/config/'

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.admin)

    def test_get_shows_what_to_register_at_the_idp(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['licensed'] and r.data['configured'] and r.data['active'])
        self.assertEqual(r.data['acs_url'], f'http://localhost:8000/api/ee/saml/{self.config.sp_id}/acs/')
        self.assertEqual(r.data['sp_entity_id'], f'http://localhost:8000/api/ee/saml/{self.config.sp_id}/metadata/')
        self.assertEqual(r.data['idp_entity_id'], ENTITY_ID)
        self.assertEqual(len(r.data['idp_certificates']), 1)
        self.assertIn('sha256', r.data['idp_certificates'][0])
        self.assertNotIn('sp_private_key_encrypted', r.data)
        self.assertNotIn('PRIVATE KEY', str(r.data))

    def test_metadata_xml(self):
        idp = TestIdP()
        r = self.client.put(self.url, {'idp_metadata_xml': idp.metadata('https://new-idp.test/', 'https://new-idp.test/sso')},
                            format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.config.refresh_from_db()
        self.assertEqual(self.config.idp_entity_id, 'https://new-idp.test/')
        self.assertEqual(self.config.idp_certificates, [cert_body(idp.cert)])
        self.assertTrue(AuditLog.objects.filter(action='SETTINGS_CHANGE', details__setting='saml').exists())

    def test_metadata_url_is_fetched_with_the_outbound_guard(self):
        from unittest import mock

        with mock.patch.object(service, 'fetch_idp_metadata', return_value=self.idp.metadata().encode()) as fetch:
            r = self.client.put(self.url, {'idp_metadata_url': 'https://login.example.test/federationmetadata.xml'},
                                format='json')
        self.assertEqual(r.status_code, 200, r.data)
        fetch.assert_called_once()
        r = self.client.put(self.url, {'idp_metadata_url': 'http://169.254.169.254/latest/meta-data'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_not_metadata(self):
        for bad in ('<html/>', '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>'):
            self.assertEqual(self.client.put(self.url, {'idp_metadata_xml': bad}, format='json').status_code, 400, bad)

    def test_manual_values(self):
        r = self.client.put(self.url, {'idp_entity_id': 'urn:idp', 'idp_sso_url': 'https://idp.test/sso',
                                       'idp_certificate': self.other_idp.cert}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.client.put(self.url, {'idp_certificate': 'not a cert'}, format='json').status_code, 400)
        self.assertEqual(self.client.put(self.url, {'idp_sso_url': 'javascript:alert(1)'}, format='json').status_code, 400)

    def test_flags_and_attributes(self):
        r = self.client.put(self.url, {'email_attribute': 'mail', 'want_assertions_encrypted': True,
                                       'allow_idp_initiated': False}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['email_attribute'], r.data['want_assertions_encrypted'], r.data['allow_idp_initiated']),
                         ('mail', True, False))

    def test_needs_admin_permissions(self):
        viewer = User.objects.create_user(username='v', email='v@acme.test', password='x', organisation=self.org,
                                          role='viewer', is_active=True)
        self.client.force_authenticate(viewer)
        self.assertEqual(self.client.put(self.url, {'email_attribute': 'x'}, format='json').status_code, 403)

    def test_sp_metadata_endpoint(self):
        r = self.client.get(urlsplit(service.sp_entity_id(self.config)).path)
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn(f'entityID="{service.sp_entity_id(self.config)}"', body)
        self.assertIn(f'Location="{service.acs_url(self.config)}"', body)
        self.assertIn('use="encryption"', body)
        self.assertNotIn('PRIVATE', body)

    def test_switch_to_saml_with_license(self):
        self.sec.sso_provider = 'oidc'
        self.sec.save()
        r = self.client.put('/api/auth/sso/config', {'sso_provider': 'saml', 'sso_enabled': True,
                                                     'sso_enforced': True}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.sec.refresh_from_db()
        self.assertEqual((self.sec.sso_provider, self.sec.sso_enforced), ('saml', True))

    def test_sp_key_is_encrypted_at_rest_and_rotated(self):
        from io import StringIO

        from django.core.management import call_command
        raw = SamlConfig.objects.values_list('sp_private_key_encrypted', flat=True).get(pk=self.config.pk)
        self.assertNotIn('PRIVATE KEY', raw)
        out = StringIO()
        call_command('rotate_secrets', '--dry-run', stdout=out)
        self.assertIn('secret(s)', out.getvalue())


class SamlWiringTest(APITestCase):
    """The routes are always there, and a missing library stops the backend (CI saw silent 404s)."""

    def test_routes_are_registered(self):
        from django.urls import resolve, reverse

        from ee.saml.views import SamlAcsView, SamlMetadataView
        sp = '94ac2e90-3191-47de-b6e1-01aeea7c3932'
        self.assertIs(resolve(reverse('ee-saml-acs', args=[sp])).func.view_class, SamlAcsView)
        self.assertIs(resolve(reverse('ee-saml-metadata', args=[sp])).func.view_class, SamlMetadataView)
        self.assertEqual(reverse('ee-saml-acs', args=[sp]), f'/api/ee/saml/{sp}/acs/')

    @override_settings(API_URL='https://serops.example.com/api')
    def test_our_urls_resolve_under_the_documented_api_url(self):
        from django.urls import resolve

        from ee.saml.views import SamlAcsView
        org = Organisations.objects.create(name='Wiring')
        config = service.get_or_create_config(org)
        self.assertIs(resolve(urlsplit(service.acs_url(config)).path).func.view_class, SamlAcsView)

    def test_missing_library_fails_startup_loudly(self):
        import builtins
        from unittest import mock

        from django.core.exceptions import ImproperlyConfigured

        from ee.apps import load_saml_protocol
        real_import = builtins.__import__

        def no_saml(name, *args, **kwargs):
            if name == 'ee.saml.service' or name.startswith('onelogin'):
                raise ImportError(f'No module named {name!r}')
            return real_import(name, *args, **kwargs)

        import sys
        with mock.patch.dict(sys.modules), mock.patch('builtins.__import__', no_saml):
            sys.modules.pop('ee.saml.service', None)
            with self.assertRaisesMessage(ImproperlyConfigured, 'cannot load python3-saml/xmlsec'):
                load_saml_protocol()

    def test_api_url_without_api_suffix_is_flagged(self):
        from ee.checks import saml_urls
        with override_settings(API_URL='http://localhost:8000'):
            self.assertEqual([m.id for m in saml_urls(None)], ['ee.W001'])
        with override_settings(API_URL='http://localhost:8000/api/'):
            self.assertEqual(saml_urls(None), [])
