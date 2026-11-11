"""Custom roles: built from the catalogue, enforced like built-in ones, and
never a way to hand out more than you hold."""
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from Data.models import AuditLog
from Middlewares.rbac import ROLE_PERMISSIONS, get_user_permissions, has_permission, normalise_permissions
from Organisations.models import Organisations
from Users.models import CustomRole, SecuritySettings, User
from Users.test.test_sso_flow import start_flow
from Utils.edition import LICENSE_REQUIRED
from Utils.testing import licensed


class NormaliseTest(SimpleTestCase):
    def test_adds_what_every_role_holds_and_implied_reads(self):
        self.assertEqual(normalise_permissions(['batch.analyze']),
                         ['batch.analyze', 'batch.read', 'org.read', 'self.manage'])

    def test_refuses_platform_and_unknown(self):
        for bad in (['platform.manage'], ['ai_catalogue.manage'], ['nope'], 'batch.read'):
            with self.assertRaises(ValueError):
                normalise_permissions(bad)


class CustomRoleBase(APITestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Acme')
        self.admin = self.member('admin@acme.test', 'admin')
        self.analyst_role = CustomRole.objects.create(
            organisation=self.org, name='Analyst',
            permissions=normalise_permissions(['batch.analyze', 'issue.update', 'project.read', 'issue.read']))

    def member(self, email, role, custom=None):
        return User.objects.create_user(username=email[:20], email=email, password='x', organisation=self.org,
                                        role=role, custom_role=custom, is_active=True)

    def as_user(self, user):
        self.client.force_authenticate(user=user)
        return self.client


class EnforcementTest(CustomRoleBase):
    def test_holder_gets_exactly_the_role(self):
        analyst = self.member('an@acme.test', 'custom', self.analyst_role)
        self.assertTrue(has_permission(analyst, 'batch.analyze'))
        self.assertFalse(has_permission(analyst, 'project.write'))
        self.assertFalse(has_permission(analyst, 'platform.manage'))
        c = self.as_user(analyst)
        self.assertEqual(c.get('/api/projects/').status_code, 200)
        self.assertEqual(c.post('/api/projects/', {}, format='json').status_code, 403)
        self.assertEqual(c.get('/api/organisation/team/').status_code, 403)
        self.assertNotEqual(c.post('/api/data/batches/reanalyze/', {}, format='json').status_code, 403)

    def test_payload_names_the_role(self):
        analyst = self.member('an@acme.test', 'custom', self.analyst_role)
        data = self.as_user(analyst).get('/api/auth/profile').data
        self.assertEqual((data['role'], data['role_key'], data['role_name']),
                         ('custom', f'custom:{self.analyst_role.pk}', 'Analyst'))
        self.assertIn('batch.analyze', data['permissions'])

    def test_role_of_another_organisation_is_refused(self):
        other = Organisations.objects.create(name='Other')
        foreign = CustomRole.objects.create(organisation=other, name='X', permissions=['org.read'])
        with self.assertRaises(ValidationError):
            self.member('x@acme.test', 'custom', foreign)


class RoleListTest(CustomRoleBase):
    url = '/api/organisation/roles/'

    def test_list(self):
        self.member('an@acme.test', 'custom', self.analyst_role)
        data = self.as_user(self.member('v@acme.test', 'viewer')).get(self.url).data
        self.assertEqual([r['key'] for r in data['builtin']], ['viewer', 'user', 'admin'])
        self.assertEqual(data['custom'][0]['member_count'], 1)
        codes = {c['code'] for c in data['catalogue']}
        self.assertIn('batch.analyze', codes)
        self.assertNotIn('platform.manage', codes)

    def test_listing_is_read_only_in_community(self):
        c = self.as_user(self.admin)
        self.assertEqual(c.post(self.url, {'name': 'X', 'permissions': []}, format='json').status_code, 405)


@licensed('custom_roles')
class NoEscalationTest(CustomRoleBase):
    """A member managing the team through a custom role can't reach above it."""

    def setUp(self):
        super().setUp()
        self.manager_role = CustomRole.objects.create(
            organisation=self.org, name='Team lead',
            permissions=normalise_permissions(ROLE_PERMISSIONS['viewer'] + ['team.manage', 'project.write', 'issue.update']))
        self.lead = self.member('lead@acme.test', 'custom', self.manager_role)
        self.c = self.as_user(self.lead)

    def test_cannot_hand_out_a_role_with_a_permission_they_lack(self):
        bare = CustomRole.objects.create(organisation=self.org, name='Bare',
                                         permissions=normalise_permissions(['team.manage']))
        c = self.as_user(self.member('bare@acme.test', 'custom', bare))
        # Viewer includes chat.use and batch.read, which "Bare" lacks.
        r = c.post('/api/organisation/team/', {'user': {'email': 'n@acme.test', 'role': 'viewer'}}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_cannot_invite_or_promote_to_admin(self):
        r = self.c.post('/api/organisation/team/', {'user': {'email': 'n@acme.test', 'role': 'admin'}}, format='json')
        self.assertEqual(r.status_code, 403)
        viewer = self.member('v@acme.test', 'viewer')
        r = self.c.put(f'/api/organisation/member/{viewer.pk}/', {'role': 'admin'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_cannot_change_or_remove_someone_above_them(self):
        self.assertEqual(self.c.put(f'/api/organisation/member/{self.admin.pk}/', {'role': 'viewer'}, format='json').status_code, 403)
        self.assertEqual(self.c.delete(f'/api/organisation/member/{self.admin.pk}/').status_code, 403)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, 'admin')

    @patch('Organisations.views.send_invitation_link')
    def test_can_hand_out_what_they_hold(self, _send):
        r = self.c.post('/api/organisation/team/', {'user': {'email': 'n@acme.test', 'role': 'viewer'}}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        newcomer = User.objects.get(email='n@acme.test')
        self.assertEqual(newcomer.organisation, self.org)
        r = self.c.put(f'/api/organisation/member/{newcomer.pk}/', {'role': self.manager_role.key}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        newcomer.refresh_from_db()
        self.assertEqual((newcomer.role, newcomer.custom_role), ('custom', self.manager_role))

    def test_admin_assigns_custom_roles(self):
        viewer = self.member('v@acme.test', 'viewer')
        c = self.as_user(self.admin)
        self.assertEqual(c.put(f'/api/organisation/member/{viewer.pk}/', {'role': self.analyst_role.key}, format='json').status_code, 200)
        other_org_role = CustomRole.objects.create(organisation=Organisations.objects.create(name='O'), name='Z')
        self.assertEqual(c.put(f'/api/organisation/member/{viewer.pk}/', {'role': other_org_role.key}, format='json').status_code, 400)

    def test_sso_rules_cannot_escalate(self):
        sec_role = CustomRole.objects.create(organisation=self.org, name='Security',
                                             permissions=normalise_permissions(ROLE_PERMISSIONS['viewer'] + ['settings.manage']))
        holder = self.member('sec@acme.test', 'custom', sec_role)
        c = self.as_user(holder)
        r = c.put('/api/auth/sso/config', {'sso_role_mappings': [{'group': 'mine', 'role': 'admin'}]}, format='json')
        self.assertEqual(r.status_code, 400)
        r = c.put('/api/auth/sso/config', {'sso_role_mappings': [{'group': 'mine', 'role': sec_role.key}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)


class SSOCustomRoleTest(CustomRoleBase):
    def test_group_maps_to_a_custom_role(self):
        SecuritySettings.objects.create(
            organisation=self.org, sso_enabled=True, sso_provider='oidc', sso_client_id='c',
            sso_discovery_url='https://idp.example.com/.well-known/openid-configuration',
            sso_domains=['acme.test'], sso_role_mappings=[{'group': 'analysts', 'role': self.analyst_role.key}])
        with patch('Users.sso_views.SSOService') as Service:
            Service.return_value.exchange_code_for_token.return_value = {'access_token': 't'}
            Service.return_value.get_user_info.return_value = {'email': 'new@acme.test', 'email_verified': True, 'groups': ['analysts']}
            self.client.get(reverse('sso-callback'), {'code': 'c', 'state': start_flow(self.client, self.org.id)})
        user = User.objects.get(email='new@acme.test')
        self.assertEqual((user.role, user.custom_role), ('custom', self.analyst_role))
        self.assertIn('batch.analyze', get_user_permissions(user))


class WithoutLicenseTest(CustomRoleBase):
    """Without an Enterprise license, custom roles that exist keep working and
    can be taken away; handing one out is refused."""

    def test_existing_holders_keep_their_permissions(self):
        analyst = self.member('an@acme.test', 'custom', self.analyst_role)
        self.assertTrue(has_permission(analyst, 'batch.analyze'))

    def test_giving_a_custom_role_is_refused(self):
        viewer = self.member('v@acme.test', 'viewer')
        r = self.as_user(self.admin).put(f'/api/organisation/member/{viewer.pk}/',
                                         {'role': self.analyst_role.key}, format='json')
        self.assertEqual((r.status_code, r.data['code'], r.data['feature']), (403, LICENSE_REQUIRED, 'custom_roles'))
        viewer.refresh_from_db()
        self.assertEqual(viewer.role, 'viewer')

    @patch('Organisations.views.send_invitation_link')
    def test_inviting_with_a_custom_role_is_refused(self, _send):
        r = self.as_user(self.admin).post('/api/organisation/team/', {
            'user': {'email': 'n@acme.test', 'role': self.analyst_role.key}}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(User.objects.filter(email='n@acme.test').exists())

    def test_keeping_the_current_custom_role_and_moving_to_a_built_in_one_work(self):
        analyst = self.member('an@acme.test', 'custom', self.analyst_role)
        c = self.as_user(self.admin)
        r = c.put(f'/api/organisation/member/{analyst.pk}/', {'role': self.analyst_role.key, 'first_name': 'Ann'},
                  format='json')
        self.assertEqual(r.status_code, 200, r.data)
        r = c.put(f'/api/organisation/member/{analyst.pk}/', {'role': 'user'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        analyst.refresh_from_db()
        self.assertEqual((analyst.role, analyst.custom_role), ('user', None))

    def test_new_sso_rule_to_a_custom_role_is_refused_existing_ones_stay(self):
        c = self.as_user(self.admin)
        r = c.put('/api/auth/sso/config', {'sso_role_mappings': [{'group': 'g', 'role': self.analyst_role.key}]},
                  format='json')
        self.assertEqual(r.status_code, 400)
        SecuritySettings.objects.update_or_create(
            organisation=self.org, defaults={'sso_role_mappings': [{'group': 'g', 'role': self.analyst_role.key}]})
        r = c.put('/api/auth/sso/config', {'sso_role_mappings': [{'group': 'g', 'role': self.analyst_role.key},
                                                                  {'group': 'ops', 'role': 'user'}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        r = c.put('/api/auth/sso/config', {'sso_role_mappings': [{'group': 'ops', 'role': 'user'}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
