"""SCIM 2.0 provisioning (Enterprise, feature ``scim``): endpoints, tokens, access rules, CV-01."""
import json

from django.core.cache import cache
from knox.models import AuthToken
from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from Data.models import AuditLog
from Organisations.models import Organisations, Team, TeamMembership
from Users.models import SecuritySettings, User
from Utils.edition import LICENSE_REQUIRED
from Utils.testing import licensed
from ee.models import ScimGroup, ScimIdentity, ScimToken
from ee.scim import service

BASE = '/api/ee/scim/v2'
SCIM = 'application/scim+json'
PATCH = 'urn:ietf:params:scim:api:messages:2.0:PatchOp'
USER = 'urn:ietf:params:scim:schemas:core:2.0:User'


class ScimClient:
    """What an identity provider sends: a bearer token and SCIM JSON."""

    def __init__(self, raw_token):
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {raw_token}')

    def _send(self, method, path, body=None):
        # Okta and Entra ID send both headers on every request.
        kwargs = {'content_type': SCIM, 'HTTP_ACCEPT': SCIM}
        if body is not None:
            kwargs['data'] = json.dumps(body)
        response = getattr(self.client, method)(f'{BASE}{path}', **kwargs)
        response.json_body = json.loads(response.content) if response.content else None
        return response

    def get(self, path):
        return self._send('get', path)

    def post(self, path, body):
        return self._send('post', path, body)

    def put(self, path, body):
        return self._send('put', path, body)

    def patch(self, path, operations):
        return self._send('patch', path, {'schemas': [PATCH], 'Operations': operations})

    def delete(self, path):
        return self._send('delete', path)


def user_body(email, **extra):
    return {'schemas': [USER], 'userName': email, 'name': {'givenName': 'Ada', 'familyName': 'Lovelace'},
            'emails': [{'value': email, 'type': 'work', 'primary': True}], 'active': True, **extra}


@override_settings(API_URL='http://localhost:8000/api')  # as deployed; never the environment's
class ScimBase(APITestCase):
    licensed = True

    def setUp(self):
        if self.licensed:
            patcher = licensed('scim')
            patcher.start()
            self.addCleanup(patcher.stop)
        cache.clear()
        self.org = Organisations.objects.create(name='Acme')
        self.admin = User.objects.create_user(username='admin', email='admin@acme.test', password='x',
                                              organisation=self.org, role='admin', is_active=True)
        self.sre = Team.objects.create(organisation=self.org, name='SRE')
        self.sec = SecuritySettings.objects.create(
            organisation=self.org, sso_default_role='viewer', sso_sync_role=True,
            sso_role_mappings=[{'group': 'serops-admins', 'role': 'admin'}, {'group': 'serops-users', 'role': 'user'}],
            sso_team_mappings=[{'group': 'sre', 'team_id': self.sre.pk}],
        )
        self.token, raw = service.create_token(self.org, 'Entra ID', self.admin)
        self.scim = ScimClient(raw)

    def create_user(self, email='ada@acme.test', **extra):
        r = self.scim.post('/Users', user_body(email, **extra))
        self.assertEqual(r.status_code, 201, r.json_body)
        return r.json_body['id']

    def create_group(self, name, members=(), external_id=''):
        r = self.scim.post('/Groups', {'displayName': name, 'externalId': external_id,
                                       'members': [{'value': m} for m in members]})
        self.assertEqual(r.status_code, 201, r.json_body)
        return r.json_body['id']

    def user(self, email='ada@acme.test'):
        return User.objects.get(email=email)


class ScimAuthTest(ScimBase):
    def test_no_or_wrong_token(self):
        anon = APIClient()
        self.assertEqual(anon.get(f'{BASE}/Users').status_code, 401)
        self.assertEqual(ScimClient('serops_scim_wrong').get('/Users').status_code, 401)

    def test_revoked_token(self):
        self.token.revoked_at = self.token.created_at
        self.token.save()
        self.assertEqual(self.scim.get('/Users').status_code, 401)

    def test_a_user_session_token_is_not_a_scim_token(self):
        _, knox = AuthToken.objects.create(self.admin)
        self.assertEqual(ScimClient(knox).get('/Users').status_code, 401)

    def test_errors_are_scim_errors(self):
        r = self.scim.get('/Users/00000000-0000-0000-0000-000000000000')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r['Content-Type'], SCIM)
        self.assertEqual(r.json_body['schemas'], ['urn:ietf:params:scim:api:messages:2.0:Error'])

    def test_token_is_scoped_to_its_organisation(self):
        other = Organisations.objects.create(name='Other')
        theirs = User.objects.create_user(username='bob', email='bob@other.test', password='x', organisation=other,
                                          role='admin', is_active=True)
        identity = service.identity_for(theirs)
        self.assertEqual(self.scim.get(f'/Users/{identity.scim_id}').status_code, 404)
        self.assertEqual(self.scim.get('/Users?filter=userName eq "bob@other.test"').json_body['totalResults'], 0)
        r = self.scim.post('/Users', user_body('bob@other.test'))
        self.assertEqual((r.status_code, r.json_body['scimType']), (409, 'uniqueness'))

    def test_token_value_is_stored_hashed(self):
        self.assertTrue(ScimToken.objects.filter(token_hash__regex=r'^[0-9a-f]{64}$').exists())
        self.assertFalse(ScimToken.objects.filter(token_hash__startswith='serops_scim_').exists())


class ScimWithoutLicenseTest(ScimBase):
    licensed = False

    def test_every_endpoint_refuses(self):
        for path in ('/ServiceProviderConfig', '/Users', '/Groups'):
            self.assertEqual(self.scim.get(path).status_code, 403, path)
        self.assertEqual(self.scim.post('/Users', user_body('ada@acme.test')).status_code, 403)
        self.assertFalse(User.objects.filter(email='ada@acme.test').exists())

    def test_tokens_cannot_be_created_but_can_be_revoked(self):
        c = APIClient()
        c.force_authenticate(self.admin)
        r = c.post('/api/ee/scim/tokens/', {'name': 'x'}, format='json')
        self.assertEqual((r.status_code, r.data['code']), (403, LICENSE_REQUIRED))
        self.assertFalse(c.get('/api/ee/scim/tokens/').data['licensed'])
        self.assertEqual(c.delete(f'/api/ee/scim/tokens/{self.token.pk}/').status_code, 204)


class ScimDiscoveryTest(ScimBase):
    def test_service_provider_config(self):
        r = self.scim.get('/ServiceProviderConfig')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json_body['patch']['supported'])
        self.assertFalse(r.json_body['bulk']['supported'])
        self.assertEqual(r.json_body['authenticationSchemes'][0]['type'], 'oauthbearertoken')

    def test_schemas_and_resource_types(self):
        self.assertEqual(self.scim.get('/Schemas').json_body['totalResults'], 2)
        self.assertEqual(self.scim.get(f'/Schemas/{USER}').json_body['name'], 'User')
        self.assertEqual({t['id'] for t in self.scim.get('/ResourceTypes').json_body['Resources']}, {'User', 'Group'})
        self.assertEqual(self.scim.get('/ResourceTypes/Group').json_body['endpoint'], '/Groups')

    def test_accept_headers_identity_providers_send(self):
        # Okta's "Test Connector Configuration" got 406 Not Acceptable before
        # SCIM had a renderer for application/scim+json (live test 2026-11-15).
        token = self.scim.client._credentials['HTTP_AUTHORIZATION']
        for accept in ('application/scim+json', 'application/scim+json; charset=utf-8',
                       'application/json', 'application/scim+json, application/json', '*/*', None):
            client = APIClient()
            headers = {'HTTP_AUTHORIZATION': token}
            if accept:
                headers['HTTP_ACCEPT'] = accept
            for path in ('/Users?startIndex=1&count=2', '/ServiceProviderConfig'):
                with self.subTest(accept=accept, path=path):
                    r = client.get(f'{BASE}{path}', **headers)
                    self.assertEqual(r.status_code, 200, r.content)
                    self.assertEqual(r['Content-Type'], SCIM)
                    json.loads(r.content)
        # Errors are SCIM JSON too, whatever the Accept header.
        r = APIClient().get(f'{BASE}/Users', HTTP_ACCEPT='application/scim+json')
        self.assertEqual(r.status_code, 401)
        self.assertEqual(json.loads(r.content)['status'], '401')


class ScimUsersTest(ScimBase):
    def test_create_get_and_audit(self):
        scim_id = self.create_user(externalId='ext-1')
        user = self.user()
        self.assertEqual((user.first_name, user.last_name, user.role, user.organisation_id, user.is_active),
                         ('Ada', 'Lovelace', 'viewer', self.org.pk, True))
        self.assertFalse(user.has_usable_password())
        r = self.scim.get(f'/Users/{scim_id}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json_body['userName'], r.json_body['externalId'], r.json_body['active']),
                         ('ada@acme.test', 'ext-1', True))
        self.assertNotEqual(r.json_body['id'], str(user.pk))
        log = AuditLog.objects.get(organisation=self.org, action='SCIM_USER_CREATE')
        self.assertEqual((log.details['source'], log.details['scim_token']), ('scim', 'Entra ID'))
        self.assertIsNone(log.user)

    def test_duplicate_username(self):
        self.create_user()
        self.assertEqual(self.scim.post('/Users', user_body('ada@acme.test')).status_code, 409)

    def test_existing_member_is_found_and_linked(self):
        member = User.objects.create_user(username='m', email='grace@acme.test', password='x',
                                          organisation=self.org, role='admin', is_active=True)
        r = self.scim.get('/Users?filter=userName eq "Grace@acme.test"')
        self.assertEqual(r.json_body['totalResults'], 1)
        r = self.scim.post('/Users', user_body('grace@acme.test'))
        # Already listed with an id: posting it again is a conflict.
        self.assertEqual(r.status_code, 409)
        ScimIdentity.objects.filter(user=member).delete()
        r = self.scim.post('/Users', user_body('grace@acme.test'))
        self.assertEqual(r.status_code, 201)
        member.refresh_from_db()
        self.assertEqual(member.pk, User.objects.get(email='grace@acme.test').pk)

    def test_list_filter_and_pagination(self):
        for i in range(5):
            self.create_user(f'u{i}@acme.test', externalId=f'e{i}')
        r = self.scim.get('/Users?startIndex=2&count=2')
        body = r.json_body
        self.assertEqual((body['totalResults'], body['itemsPerPage'], body['startIndex']), (6, 2, 2))
        self.assertEqual(self.scim.get('/Users?filter=externalId eq "e3"').json_body['Resources'][0]['userName'],
                         'u3@acme.test')
        self.assertEqual(self.scim.get('/Users?filter=userName eq "nobody@acme.test"').json_body['totalResults'], 0)
        self.assertEqual(self.scim.get('/Users?filter=userName co "u"').status_code, 400)
        self.assertEqual(self.scim.get('/Users?filter=title eq "x"').json_body['scimType'], 'invalidFilter')

    def test_put_replaces(self):
        scim_id = self.create_user()
        r = self.scim.put(f'/Users/{scim_id}', {**user_body('ada@acme.test'), 'name': {'givenName': 'Augusta'}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((self.user().first_name, self.user().last_name), ('Augusta', ''))

    def test_patch_entra_style(self):
        scim_id = self.create_user()
        r = self.scim.patch(f'/Users/{scim_id}', [
            {'op': 'Replace', 'path': 'name.familyName', 'value': 'King'},
            {'op': 'Replace', 'path': 'emails[type eq "work"].value', 'value': 'ada.king@acme.test'},
            {'op': 'Add', 'path': 'urn:ietf:params:scim:schemas:extension:enterprise:2.0:User:department',
             'value': 'Maths'},
        ])
        self.assertEqual(r.status_code, 200, r.json_body)
        self.assertEqual(User.objects.get(email='ada.king@acme.test').last_name, 'King')

    def test_patch_okta_style_without_path(self):
        scim_id = self.create_user()
        r = self.scim.patch(f'/Users/{scim_id}', [{'op': 'replace', 'value': {'active': False}}])
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json_body['active'])
        self.assertFalse(self.user().is_active)

    def test_bad_patch(self):
        scim_id = self.create_user()
        self.assertEqual(self.scim.patch(f'/Users/{scim_id}', [{'op': 'move', 'path': 'x'}]).status_code, 400)
        self.assertEqual(self.scim.patch(f'/Users/{scim_id}', []).status_code, 400)
        self.assertEqual(self.scim.patch(f'/Users/{scim_id}', [{'op': 'replace', 'path': 'active',
                                                                'value': 'maybe'}]).status_code, 400)

    def test_email_change_to_another_account_refused(self):
        scim_id = self.create_user()
        r = self.scim.patch(f'/Users/{scim_id}', [{'op': 'replace', 'path': 'emails[type eq "work"].value',
                                                   'value': 'admin@acme.test'}])
        self.assertEqual(r.status_code, 409)

    def test_deny_default_creates_inactive_until_a_mapped_group(self):
        self.sec.sso_default_role = 'deny'
        self.sec.save()
        scim_id = self.create_user()
        self.assertFalse(self.user().is_active)
        self.create_group('serops-users', [scim_id])
        user = self.user()
        self.assertTrue(user.is_active)
        self.assertEqual(user.role, 'user')


class ScimDeprovisionTest(ScimBase):
    """Deprovisioning ends every session and token of the person in the same request."""

    def setUp(self):
        super().setUp()
        self.scim_id = self.create_user()
        self.user_obj = self.user()
        _, self.session_token = AuthToken.objects.create(self.user_obj)
        _, self.api_token = AuthToken.objects.create(self.user_obj)

    def assertLockedOut(self):
        c = APIClient()
        for token in (self.session_token, self.api_token):
            c.credentials(HTTP_AUTHORIZATION=f'Token {token}')
            self.assertEqual(c.get('/api/auth/profile').status_code, 401)
        self.assertFalse(AuthToken.objects.filter(user=self.user_obj).exists())
        self.assertFalse(User.objects.get(pk=self.user_obj.pk).is_active)

    def test_tokens_work_before(self):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Token {self.session_token}')
        self.assertEqual(c.get('/api/auth/profile').status_code, 200)

    def test_active_false(self):
        self.scim.patch(f'/Users/{self.scim_id}', [{'op': 'Replace', 'path': 'active', 'value': 'False'}])
        self.assertLockedOut()
        log = AuditLog.objects.get(action='SCIM_USER_DEACTIVATE')
        self.assertEqual(log.details['tokens_revoked'], 2)

    def test_delete(self):
        self.assertEqual(self.scim.delete(f'/Users/{self.scim_id}').status_code, 204)
        self.assertLockedOut()
        self.assertEqual(self.scim.get(f'/Users/{self.scim_id}').status_code, 404)
        self.assertTrue(AuditLog.objects.filter(action='SCIM_USER_DELETE').exists())

    def test_reactivate(self):
        self.scim.patch(f'/Users/{self.scim_id}', [{'op': 'replace', 'path': 'active', 'value': False}])
        self.scim.patch(f'/Users/{self.scim_id}', [{'op': 'replace', 'path': 'active', 'value': True}])
        self.assertTrue(self.user().is_active)

    def test_last_admin_is_never_deprovisioned(self):
        admin_id = str(service.identity_for(self.admin).scim_id)
        r = self.scim.delete(f'/Users/{admin_id}')
        self.assertEqual(r.status_code, 409)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)


class ScimGroupsTest(ScimBase):
    def test_create_list_filter_get(self):
        ada = self.create_user()
        gid = self.create_group('serops-users', [ada], external_id='0b1c-objectid')
        r = self.scim.get('/Groups?filter=displayName eq "serops-users"&excludedAttributes=members')
        self.assertEqual(r.json_body['totalResults'], 1)
        self.assertNotIn('members', r.json_body['Resources'][0])
        r = self.scim.get(f'/Groups/{gid}')
        self.assertEqual([m['value'] for m in r.json_body['members']], [ada])
        self.assertEqual(self.scim.get('/Groups?filter=externalId eq "0b1c-objectid"').json_body['totalResults'], 1)
        self.assertEqual(self.scim.post('/Groups', {'displayName': 'SEROPS-USERS'}).status_code, 409)

    def test_unknown_member_refused(self):
        r = self.scim.post('/Groups', {'displayName': 'g', 'members': [{'value': '00000000-0000-0000-0000-000000000000'}]})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(ScimGroup.objects.exists())

    def test_membership_gives_role_and_team(self):
        ada = self.create_user()
        gid = self.create_group('sre')
        self.scim.patch(f'/Groups/{gid}', [{'op': 'Add', 'path': 'members', 'value': [{'value': ada}]}])
        self.assertTrue(TeamMembership.objects.filter(user=self.user(), team=self.sre, source='sso').exists())
        admins = self.create_group('serops-admins', [ada])
        self.assertEqual(self.user().role, 'admin')
        self.assertTrue(AuditLog.objects.filter(action='TEAM_ROLE_CHANGE', details__source='scim').exists())
        self.scim.patch(f'/Groups/{admins}', [{'op': 'remove', 'path': f'members[value eq "{ada}"]'}])
        self.assertEqual(self.user().role, 'viewer')

    def test_external_id_matches_rules(self):
        # Entra ID group claims carry object IDs: rules written with them match SCIM groups too.
        self.sec.sso_role_mappings = [{'group': '6f1e-object-id', 'role': 'user'}]
        self.sec.save()
        ada = self.create_user()
        self.create_group('Platform engineers', [ada], external_id='6f1e-object-id')
        self.assertEqual(self.user().role, 'user')

    def test_put_replaces_members_and_renames(self):
        ada, bob = self.create_user(), self.create_user('bob@acme.test')
        gid = self.create_group('team-a', [ada])
        r = self.scim.put(f'/Groups/{gid}', {'displayName': 'sre', 'members': [{'value': bob}]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([m['value'] for m in r.json_body['members']], [bob])
        self.assertTrue(TeamMembership.objects.filter(user=self.user('bob@acme.test'), team=self.sre).exists())
        self.assertFalse(TeamMembership.objects.filter(user=self.user(), team=self.sre).exists())

    def test_rename_by_patch_reapplies_rules(self):
        ada = self.create_user()
        gid = self.create_group('ops', [ada])
        r = self.scim.patch(f'/Groups/{gid}', [{'op': 'Replace', 'path': 'displayName', 'value': 'serops-users'}])
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self.user().role, 'user')

    def test_delete_group_takes_its_access_away(self):
        ada = self.create_user()
        gid = self.create_group('serops-users', [ada])
        self.assertEqual(self.user().role, 'user')
        self.assertEqual(self.scim.delete(f'/Groups/{gid}').status_code, 204)
        self.assertEqual(self.user().role, 'viewer')
        self.assertEqual(self.scim.get(f'/Groups/{gid}').status_code, 404)
        self.assertTrue(AuditLog.objects.filter(action='SCIM_GROUP_DELETE').exists())

    def test_removing_a_non_member_is_not_an_error(self):
        ada = self.create_user()
        gid = self.create_group('g')
        r = self.scim.patch(f'/Groups/{gid}', [{'op': 'Remove', 'path': 'members', 'value': [{'value': ada}]}])
        self.assertEqual(r.status_code, 204)


class CV01RegressionTest(ScimBase):
    """CV-01 (FINDINGS-REGISTER row 105): removing a person from every mapped
    group must revoke their role, team and access at once, not at their next
    sign-in (found live on AKS, 2026-11-12)."""

    def setUp(self):
        super().setUp()
        self.sec.sso_default_role = 'deny'  # only members of a mapped group may use SerOps
        self.sec.save()
        self.carol = self.create_user('carol@acme.test')
        self.viewers = self.create_group('serops-users', [self.carol])
        self.sre_group = self.create_group('sre', [self.carol])
        self.user_obj = self.user('carol@acme.test')
        _, self.token = AuthToken.objects.create(self.user_obj)

    def test_cv01_removal_from_mapped_group_revokes_role_team_and_tokens(self):
        self.assertTrue(self.user_obj.is_active)
        self.assertEqual(self.user_obj.role, 'user')
        self.assertTrue(TeamMembership.objects.filter(user=self.user_obj, team=self.sre).exists())

        # Removed from the team group: the team goes, in that request.
        self.scim.patch(f'/Groups/{self.sre_group}', [{'op': 'Remove', 'path': 'members',
                                                        'value': [{'value': self.carol}]}])
        self.assertFalse(TeamMembership.objects.filter(user=self.user_obj, team=self.sre).exists())

        # Removed from the last mapped group: access and every token go, in that request.
        self.scim.patch(f'/Groups/{self.viewers}', [{'op': 'Remove', 'path': 'members',
                                                     'value': [{'value': self.carol}]}])
        user = self.user('carol@acme.test')
        self.assertFalse(user.is_active)
        self.assertFalse(AuthToken.objects.filter(user=user).exists())
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Token {self.token}')
        self.assertEqual(c.get('/api/auth/profile').status_code, 401)
        log = AuditLog.objects.get(action='SCIM_USER_DEACTIVATE')
        self.assertEqual(log.details['reason'], 'in no mapped group')

        # Added back: access returns (with no old token).
        self.scim.patch(f'/Groups/{self.viewers}', [{'op': 'Add', 'path': 'members', 'value': [{'value': self.carol}]}])
        self.assertTrue(self.user('carol@acme.test').is_active)

    def test_cv01_sso_denied_sign_in_revokes_existing_tokens(self):
        """Without SCIM: the next SSO sign-in that the rules refuse ends the
        tokens the person already holds (Users/sso_views.complete_sign_in)."""
        from django.test import RequestFactory

        from Users.sso_views import complete_sign_in
        request = RequestFactory().get('/')
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        response = complete_sign_in(request, self.sec, email='carol@acme.test', groups=['finance'], source='sso')
        self.assertTrue(response['Location'].endswith('/login?sso=denied'))
        self.assertFalse(AuthToken.objects.filter(user=self.user_obj).exists())
        self.assertEqual(AuditLog.objects.filter(action='SSO_DENIED').latest('pk').details['tokens_revoked'], 1)


class ScimTokenApiTest(ScimBase):
    url = '/api/ee/scim/tokens/'

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.admin)

    def test_create_shows_the_token_once(self):
        r = self.client.post(self.url, {'name': 'Okta'}, format='json')
        self.assertEqual(r.status_code, 201)
        raw = r.data['token']
        self.assertTrue(raw.startswith('serops_scim_'))
        listed = self.client.get(self.url).data
        self.assertEqual(listed['base_url'], 'http://localhost:8000/api/ee/scim/v2')
        self.assertNotIn(raw, json.dumps(listed))
        self.assertEqual(ScimClient(raw).get('/Users').status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action='SCIM_TOKEN_CREATE').exists())

    def test_revoke_takes_effect_at_once(self):
        r = self.client.post(self.url, {'name': 'Okta'}, format='json')
        client = ScimClient(r.data['token'])
        self.assertEqual(self.client.delete(f"{self.url}{r.data['id']}/").status_code, 204)
        self.assertEqual(client.get('/Users').status_code, 401)
        self.assertTrue(AuditLog.objects.filter(action='SCIM_TOKEN_REVOKE').exists())

    def test_only_admins(self):
        user = User.objects.create_user(username='u', email='u@acme.test', password='x', organisation=self.org,
                                        role='user', is_active=True)
        self.client.force_authenticate(user)
        self.assertEqual(self.client.post(self.url, {'name': 'x'}, format='json').status_code, 403)

    def test_other_organisations_tokens(self):
        other = Organisations.objects.create(name='Other')
        theirs, _ = service.create_token(other, 'theirs', None)
        self.assertEqual(self.client.delete(f'{self.url}{theirs.pk}/').status_code, 404)
        self.assertNotIn('theirs', json.dumps(self.client.get(self.url).data))


class ScimRateLimitTest(ScimBase):
    def test_per_token(self):
        from unittest import mock

        from ee.scim.views import ScimTokenThrottle
        with mock.patch.object(ScimTokenThrottle, 'get_rate', return_value='3/min'):
            codes = [self.scim.get('/Users').status_code for _ in range(4)]
        self.assertEqual(codes, [200, 200, 200, 429])


@override_settings(API_URL='http://localhost:8000/api')  # as deployed; never the environment's
class ScimWiringTest(APITestCase):
    """The endpoints are always there, and a broken install stops the backend at startup."""

    def test_routes_are_registered(self):
        from django.urls import resolve

        from ee.scim import views
        self.assertIs(resolve(f'{BASE}/Users').func.view_class, views.UsersView)
        self.assertIs(resolve(f'{BASE}/Groups/abc').func.view_class, views.GroupDetailView)
        self.assertIs(resolve(f'{BASE}/ServiceProviderConfig').func.view_class, views.ServiceProviderConfigView)

    def test_broken_install_fails_startup_loudly(self):
        import builtins
        import sys
        from unittest import mock

        from django.core.exceptions import ImproperlyConfigured

        from ee.apps import load_scim
        real_import = builtins.__import__

        def broken(name, globals=None, locals=None, fromlist=(), level=0):
            if name == 'ee.scim' and fromlist and 'views' in fromlist:
                raise ImportError("cannot import name 'views' from 'ee.scim'")
            return real_import(name, globals, locals, fromlist, level)

        with mock.patch.dict(sys.modules), mock.patch('builtins.__import__', broken):
            with self.assertRaisesMessage(ImproperlyConfigured, 'SerOps Enterprise SCIM cannot load'):
                load_scim()
