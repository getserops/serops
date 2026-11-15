"""SCIM conformance: the request sequences Microsoft Entra ID and Okta send.

No SCIM test client runs in CI without network access to a vendor, so this
replays the requests the vendors document, in their order and shape:

- Entra ID: "Tutorial: Develop and plan provisioning for a SCIM endpoint
  in Microsoft Entra ID", sections "User operations" and "Group operations"
  (the requests its SCIM validator and provisioning service send:
  capitalised ops, "False" as a string, excludedAttributes=members,
  emails[type eq "work"].value paths, the enterprise extension).
- Okta: "SCIM 2.0 protocol reference" and "Build a SCIM provisioning
  integration" (lower-case ops, PATCH without a path, PUT to update users,
  members[value eq "…"] removal, paging with startIndex/count).
"""
import uuid

from django.test import override_settings
from rest_framework.test import APITestCase

from Data.models import AuditLog
from Organisations.models import Organisations, Team, TeamMembership
from Users.models import SecuritySettings, User
from Utils.testing import licensed
from ee.scim import service
from ee.tests.test_scim import PATCH, USER, ScimClient

GROUP = 'urn:ietf:params:scim:schemas:core:2.0:Group'
ENTERPRISE = 'urn:ietf:params:scim:schemas:extension:enterprise:2.0:User'


@override_settings(API_URL='http://localhost:8000/api')  # as deployed; never the environment's
class ConformanceBase(APITestCase):
    def setUp(self):
        patcher = licensed('scim')
        patcher.start()
        self.addCleanup(patcher.stop)
        from django.core.cache import cache
        cache.clear()
        self.org = Organisations.objects.create(name='Contoso')
        User.objects.create_user(username='admin', email='admin@contoso.test', password='x', organisation=self.org,
                                 role='admin', is_active=True)
        self.team = Team.objects.create(organisation=self.org, name='On-call')
        SecuritySettings.objects.create(
            organisation=self.org, sso_default_role='deny', sso_sync_role=True,
            sso_role_mappings=[{'group': 'SerOps Users', 'role': 'user'}],
            sso_team_mappings=[{'group': 'SerOps Users', 'team_id': self.team.pk}])
        _, raw = service.create_token(self.org, 'idp', None)
        self.idp = ScimClient(raw)

    def ok(self, response, status=200):
        self.assertEqual(response.status_code, status, response.json_body)
        if response.content:
            self.assertEqual(response['Content-Type'], 'application/scim+json')
        return response.json_body


class EntraIdSequenceTest(ConformanceBase):
    def test_user_operations(self):
        tag = uuid.uuid4().hex[:8]
        user_name = f'Test_User_{tag}@contoso.test'
        # 1. Does the user exist?
        body = self.ok(self.idp.get(f'/Users?filter=userName eq "{user_name}"'))
        self.assertEqual(body['totalResults'], 0)
        # 2. Create.
        body = self.ok(self.idp.post('/Users', {
            'schemas': [USER, ENTERPRISE],
            'externalId': tag,
            'userName': user_name,
            'active': True,
            'emails': [{'primary': True, 'type': 'work', 'value': f'Test_User_{tag}@contoso.test'}],
            'meta': {'resourceType': 'User'},
            'name': {'formatted': 'givenName familyName', 'familyName': 'familyName', 'givenName': 'givenName'},
            'roles': [],
            ENTERPRISE: {'department': 'Ops', 'manager': {'value': 'x'}},
        }), 201)
        user_id = body['id']
        self.assertEqual(body['userName'], user_name)
        self.assertEqual(body['meta']['resourceType'], 'User')
        # 3. Get by id, and by a filter that matches nothing.
        self.assertEqual(self.ok(self.idp.get(f'/Users/{user_id}'))['externalId'], tag)
        self.assertEqual(self.ok(self.idp.get('/Users?filter=userName eq "non-existent user"'))['totalResults'], 0)
        # 4. Update by PATCH, as the validator does (several ops at once).
        body = self.ok(self.idp.patch(f'/Users/{user_id}', [
            {'op': 'Replace', 'path': 'emails[type eq "work"].value', 'value': f'updated_{tag}@contoso.test'},
            {'op': 'Replace', 'path': 'name.familyName', 'value': 'updatedFamilyName'},
            {'op': 'Add', 'path': f'{ENTERPRISE}:employeeNumber', 'value': '42'},
        ]))
        self.assertEqual(body['name']['familyName'], 'updatedFamilyName')
        self.assertEqual(body['emails'][0]['value'], f'updated_{tag}@contoso.test')
        # 5. Disable (the string "False", as Entra ID sends it).
        body = self.ok(self.idp.patch(f'/Users/{user_id}', [{'op': 'Replace', 'path': 'active', 'value': 'False'}]))
        self.assertFalse(body['active'])
        # 6. Delete (after the soft-delete period).
        self.ok(self.idp.delete(f'/Users/{user_id}'), 204)
        self.assertEqual(self.idp.get(f'/Users/{user_id}').status_code, 404)

    def test_group_operations(self):
        member = self.ok(self.idp.post('/Users', {
            'schemas': [USER], 'userName': 'member@contoso.test', 'active': True,
            'emails': [{'primary': True, 'type': 'work', 'value': 'member@contoso.test'}]}), 201)['id']
        # 1. Create the group (Entra ID sends members separately).
        body = self.ok(self.idp.post('/Groups', {
            'externalId': '8aa1a0c0-c4c3-4bc0-b4a5-2ef676900159', 'displayName': 'displayName',
            'meta': {'resourceType': 'Group'}, 'schemas': [GROUP]}), 201)
        group_id = body['id']
        self.assertEqual(body['members'], [])
        # 2. Get it without members, by id and by name.
        body = self.ok(self.idp.get(f'/Groups/{group_id}?excludedAttributes=members'))
        self.assertNotIn('members', body)
        body = self.ok(self.idp.get('/Groups?excludedAttributes=members&filter=displayName eq "displayName"'))
        self.assertEqual(body['totalResults'], 1)
        # 3. Rename it to a mapped group.
        self.ok(self.idp.patch(f'/Groups/{group_id}', [
            {'op': 'Replace', 'path': 'displayName', 'value': 'SerOps Users'}]), 204)
        # 4. Add a member: active, mapped role and team.
        self.ok(self.idp.patch(f'/Groups/{group_id}', [
            {'op': 'Add', 'path': 'members', 'value': [{'$ref': None, 'value': member}]}]), 204)
        user = User.objects.get(email='member@contoso.test')
        self.assertTrue(user.is_active)
        self.assertEqual(user.role, 'user')
        self.assertTrue(TeamMembership.objects.filter(user=user, team=self.team).exists())
        # 5. Remove the member: access, role and team go at once (deny default).
        self.ok(self.idp.patch(f'/Groups/{group_id}', [
            {'op': 'Remove', 'path': 'members', 'value': [{'$ref': None, 'value': member}]}]), 204)
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertFalse(TeamMembership.objects.filter(user=user, team=self.team).exists())
        # 6. Delete the group.
        self.ok(self.idp.delete(f'/Groups/{group_id}'), 204)
        self.assertEqual(self.idp.get(f'/Groups/{group_id}').status_code, 404)

    def test_connection_test(self):
        # "Test Connection" in the Entra ID portal asks for a user that does not exist.
        body = self.ok(self.idp.get(f'/Users?filter=userName eq "{uuid.uuid4()}"'))
        self.assertEqual((body['totalResults'], body['Resources']), (0, []))


class OktaSequenceTest(ConformanceBase):
    def test_user_lifecycle(self):
        # 1. Test connector configuration.
        self.ok(self.idp.get('/ServiceProviderConfig'))
        self.ok(self.idp.get('/Users?startIndex=1&count=1'))
        # 2. Look up, then create.
        self.assertEqual(self.ok(self.idp.get(
            '/Users?filter=userName%20eq%20%22jane.doe%40contoso.test%22&startIndex=1&count=100'))['totalResults'], 0)
        body = self.ok(self.idp.post('/Users', {
            'schemas': [USER], 'userName': 'jane.doe@contoso.test',
            'name': {'givenName': 'Jane', 'familyName': 'Doe'},
            'emails': [{'primary': True, 'value': 'jane.doe@contoso.test', 'type': 'work'}],
            'displayName': 'Jane Doe', 'locale': 'en-US', 'externalId': '00ujl29u0le5T6Aj10h7',
            'groups': [], 'password': 'not-stored-1!', 'active': True}), 201)
        user_id = body['id']
        user = User.objects.get(email='jane.doe@contoso.test')
        self.assertFalse(user.has_usable_password())  # Okta's password is never kept.
        # Deny default and no group yet: created inactive.
        self.assertFalse(user.is_active)
        # 3. Update with PUT (Okta's default).
        body = self.ok(self.idp.put(f'/Users/{user_id}', {
            'schemas': [USER], 'id': user_id, 'userName': 'jane.doe@contoso.test',
            'name': {'givenName': 'Janet', 'familyName': 'Doe'},
            'emails': [{'primary': True, 'value': 'jane.doe@contoso.test', 'type': 'work'}],
            'active': True}))
        self.assertEqual(body['name']['givenName'], 'Janet')
        # 4. Deactivate with a PATCH without a path.
        body = self.ok(self.idp.patch(f'/Users/{user_id}', [{'op': 'replace', 'value': {'active': False}}]))
        self.assertFalse(body['active'])
        # 5. Reactivate.
        self.ok(self.idp.patch(f'/Users/{user_id}', [{'op': 'replace', 'value': {'active': True}}]))

    def test_group_push(self):
        ids = [self.ok(self.idp.post('/Users', {
            'schemas': [USER], 'userName': f'u{i}@contoso.test', 'active': True,
            'emails': [{'primary': True, 'value': f'u{i}@contoso.test'}]}), 201)['id'] for i in range(3)]
        # 1. Push a group with members.
        body = self.ok(self.idp.post('/Groups', {
            'schemas': [GROUP], 'displayName': 'SerOps Users',
            'members': [{'value': ids[0], 'display': 'u0@contoso.test'}, {'value': ids[1], 'display': 'u1@contoso.test'}],
        }), 201)
        group_id = body['id']
        self.assertEqual(User.objects.filter(email__in=['u0@contoso.test', 'u1@contoso.test'], is_active=True).count(), 2)
        # 2. List groups page by page.
        body = self.ok(self.idp.get('/Groups?startIndex=1&count=100'))
        self.assertEqual(body['totalResults'], 1)
        # 3. Add, remove (members[value eq] path), rename (no path).
        self.ok(self.idp.patch(f'/Groups/{group_id}', [
            {'op': 'add', 'path': 'members', 'value': [{'value': ids[2], 'display': 'u2@contoso.test'}]}]), 204)
        self.ok(self.idp.patch(f'/Groups/{group_id}', [
            {'op': 'remove', 'path': f'members[value eq "{ids[0]}"]'}]), 204)
        self.assertFalse(User.objects.get(email='u0@contoso.test').is_active)
        self.ok(self.idp.patch(f'/Groups/{group_id}', [
            {'op': 'replace', 'value': {'id': group_id, 'displayName': 'SerOps Users'}}]), 204)
        # 4. Replace all members with PUT.
        body = self.ok(self.idp.put(f'/Groups/{group_id}', {
            'schemas': [GROUP], 'id': group_id, 'displayName': 'SerOps Users', 'members': [{'value': ids[0]}]}))
        self.assertEqual([m['value'] for m in body['members']], [ids[0]])
        self.assertEqual(set(User.objects.filter(email__startswith='u', is_active=True).values_list('email', flat=True)),
                         {'u0@contoso.test'})
        # 5. Delete the group: nobody is left in a mapped group.
        self.ok(self.idp.delete(f'/Groups/{group_id}'), 204)
        self.assertFalse(User.objects.filter(email__startswith='u', is_active=True).exists())
        self.assertGreaterEqual(AuditLog.objects.filter(action__startswith='SCIM_').count(), 8)
