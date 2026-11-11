"""Managing custom roles and per-project access (Enterprise).

Enforcement of both is Community and tested there (Middlewares/tests). Here:
the management API, its no-escalation guards, and what the license gates.
"""
from rest_framework.test import APITestCase

from Data.models import AuditLog
from Middlewares.rbac import ROLE_PERMISSIONS, has_permission, normalise_permissions
from Organisations.models import Organisations, Team, TeamMembership
from Projects.models import Project, ProjectTeamAccess
from Users.models import CustomRole, SecuritySettings, User
from Utils.edition import LICENSE_REQUIRED
from Utils.testing import licensed


class Base(APITestCase):
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


@licensed('custom_roles')
class RoleApiTest(Base):
    url = '/api/ee/roles/'

    def test_create_update_delete_and_audit(self):
        c = self.as_user(self.admin)
        r = c.post(self.url, {'name': 'Responder', 'description': 'On-call', 'permissions': ['issue.update']}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['permissions'], ['issue.read', 'issue.update', 'org.read', 'self.manage'])
        pk = r.data['id']
        self.assertEqual(c.put(f'{self.url}{pk}/', {'name': 'Responders'}, format='json').data['name'], 'Responders')
        self.assertEqual(c.delete(f'{self.url}{pk}/').status_code, 204)
        actions = set(AuditLog.objects.filter(organisation=self.org).values_list('action', flat=True))
        self.assertTrue({'ROLE_CREATE', 'ROLE_UPDATE', 'ROLE_DELETE'} <= actions)

    def test_editing_a_role_changes_its_holders_at_once(self):
        analyst = self.member('an@acme.test', 'custom', self.analyst_role)
        self.as_user(self.admin).put(f'{self.url}{self.analyst_role.pk}/', {'permissions': ['project.write']},
                                     format='json')
        analyst.refresh_from_db()
        self.assertTrue(has_permission(analyst, 'project.write'))
        self.assertFalse(has_permission(analyst, 'batch.analyze'))

    def test_names(self):
        c = self.as_user(self.admin)
        for name in ('', 'Admin', 'viewer', 'analyst', 'x' * 51):
            self.assertEqual(c.post(self.url, {'name': name, 'permissions': []}, format='json').status_code, 400, name)

    def test_in_use_roles_are_not_deleted(self):
        self.member('an@acme.test', 'custom', self.analyst_role)
        self.assertEqual(self.as_user(self.admin).delete(f'{self.url}{self.analyst_role.pk}/').status_code, 409)

    def test_roles_named_by_sso_are_not_deleted(self):
        SecuritySettings.objects.create(organisation=self.org,
                                        sso_role_mappings=[{'group': 'g', 'role': self.analyst_role.key}])
        self.assertEqual(self.as_user(self.admin).delete(f'{self.url}{self.analyst_role.pk}/').status_code, 409)

    def test_members_without_team_manage_cannot_write(self):
        c = self.as_user(self.member('u@acme.test', 'user'))
        self.assertEqual(c.post(self.url, {'name': 'X', 'permissions': []}, format='json').status_code, 403)

    def test_role_of_another_organisation_is_not_found(self):
        other = CustomRole.objects.create(organisation=Organisations.objects.create(name='O'), name='Z')
        c = self.as_user(self.admin)
        self.assertEqual(c.put(f'{self.url}{other.pk}/', {'name': 'Mine'}, format='json').status_code, 404)
        self.assertEqual(c.delete(f'{self.url}{other.pk}/').status_code, 404)


@licensed('custom_roles')
class RoleNoEscalationTest(Base):
    def setUp(self):
        super().setUp()
        self.manager_role = CustomRole.objects.create(
            organisation=self.org, name='Team lead',
            permissions=normalise_permissions(ROLE_PERMISSIONS['viewer'] + ['team.manage', 'project.write', 'issue.update']))
        self.c = self.as_user(self.member('lead@acme.test', 'custom', self.manager_role))

    def test_cannot_create_or_widen_a_role_beyond_their_own(self):
        r = self.c.post('/api/ee/roles/', {'name': 'Sneaky', 'permissions': ['settings.manage']}, format='json')
        self.assertEqual(r.status_code, 403)
        r = self.c.put(f'/api/ee/roles/{self.manager_role.pk}/', {'permissions': ['team.manage', 'settings.manage']},
                       format='json')
        self.assertEqual(r.status_code, 403)

    def test_cannot_edit_a_role_that_holds_more(self):
        # Analyst has batch.analyze, which the lead lacks.
        r = self.c.put(f'/api/ee/roles/{self.analyst_role.pk}/', {'name': 'Renamed'}, format='json')
        self.assertEqual(r.status_code, 403)


class RoleLicenseTest(Base):
    """Without the license: no new or edited roles; deleting stays possible."""

    def test_create_and_edit_need_the_license(self):
        c = self.as_user(self.admin)
        r = c.post('/api/ee/roles/', {'name': 'Responder', 'permissions': ['issue.update']}, format='json')
        self.assertEqual((r.status_code, r.data['code'], r.data['feature']), (403, LICENSE_REQUIRED, 'custom_roles'))
        r = c.put(f'/api/ee/roles/{self.analyst_role.pk}/', {'name': 'Renamed'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(CustomRole.objects.filter(name__in=['Responder', 'Renamed']).exists())

    def test_unused_roles_can_still_be_deleted(self):
        self.assertEqual(self.as_user(self.admin).delete(f'/api/ee/roles/{self.analyst_role.pk}/').status_code, 204)

    def test_other_features_do_not_unlock_roles(self):
        with licensed('project_access'):
            r = self.as_user(self.admin).post('/api/ee/roles/', {'name': 'R', 'permissions': []}, format='json')
        self.assertEqual(r.status_code, 403)


class AccessBase(Base):
    def setUp(self):
        super().setUp()
        self.member_user = self.member('member@acme.test', 'user')
        self.payments = Project.objects.create(name='payments', organisation=self.org)
        self.web = Project.objects.create(name='web', organisation=self.org)
        self.team = Team.objects.create(organisation=self.org, name='Payments')
        TeamMembership.objects.create(team=self.team, user=self.member_user)

    def url(self, project):
        return f'/api/ee/projects/{project.id}/access/'


@licensed('project_access')
class ProjectAccessApiTest(AccessBase):
    def test_restrict_and_grant(self):
        c = self.as_user(self.admin)
        r = c.put(self.url(self.payments), {
            'access_mode': 'restricted', 'grants': [{'team_id': self.team.id, 'role': 'viewer'}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['grants'], [{'team_id': self.team.id, 'team_name': 'Payments', 'role': 'viewer'}])
        outsider = self.member('outsider@acme.test', 'user')
        self.assertEqual(self.as_user(outsider).get(f'/api/projects/{self.payments.id}/').status_code, 404)
        member_view = self.as_user(self.member_user).get(f'/api/projects/{self.payments.id}/')
        self.assertEqual(member_view.status_code, 200)
        self.assertEqual(member_view.data['permissions'], ['batch.read', 'issue.read', 'project.read'])
        self.assertEqual(self.as_user(self.member_user).put(f'/api/projects/{self.payments.id}/', {'name': 'x'},
                                                            format='json').status_code, 404)
        self.assertTrue(AuditLog.objects.filter(action='PROJECT_ACCESS_CHANGE').exists())

    def test_only_project_admins_change_access(self):
        lead_role = CustomRole.objects.create(organisation=self.org, name='Lead', permissions=normalise_permissions(
            ROLE_PERMISSIONS['user'] + ['team.manage']))
        lead = self.member('lead@acme.test', 'custom', lead_role)
        r = self.as_user(lead).put(self.url(self.web), {'access_mode': 'restricted'}, format='json')
        self.assertEqual(r.status_code, 403)
        # Admin of payments through a team: may change payments' access.
        lead_team = Team.objects.create(organisation=self.org, name='Leads')
        TeamMembership.objects.create(team=lead_team, user=lead)
        ProjectTeamAccess.objects.create(project=self.payments, team=lead_team, role='admin')
        c = self.as_user(User.objects.get(pk=lead.pk))  # access is computed once per request's user
        r = c.put(self.url(self.payments), {
            'access_mode': 'restricted', 'grants': [{'team_id': lead_team.id, 'role': 'admin'},
                                                    {'team_id': self.team.id, 'role': 'user'}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def test_grants_need_known_teams_and_roles(self):
        c = self.as_user(self.admin)
        other_team = Team.objects.create(organisation=Organisations.objects.create(name='O'), name='T')
        for grants in ([{'team_id': other_team.id, 'role': 'viewer'}], [{'team_id': self.team.id, 'role': 'owner'}]):
            self.assertEqual(c.put(self.url(self.payments), {'grants': grants}, format='json').status_code, 400)


class ProjectAccessLicenseTest(AccessBase):
    """Without the license nothing gets more restricted or more granted; a
    project can always be opened again and grants removed or lowered."""

    def restrict(self, role='user'):
        self.payments.access_mode = 'restricted'
        self.payments.save()
        ProjectTeamAccess.objects.create(project=self.payments, team=self.team, role=role)

    def test_restricting_needs_the_license(self):
        r = self.as_user(self.admin).put(self.url(self.web), {'access_mode': 'restricted'}, format='json')
        self.assertEqual((r.status_code, r.data['code'], r.data['feature']), (403, LICENSE_REQUIRED, 'project_access'))
        self.web.refresh_from_db()
        self.assertEqual(self.web.access_mode, 'organisation')

    def test_adding_or_raising_a_grant_needs_the_license(self):
        self.restrict('viewer')
        c = self.as_user(self.admin)
        r = c.put(self.url(self.payments), {'grants': [{'team_id': self.team.id, 'role': 'admin'}]}, format='json')
        self.assertEqual(r.status_code, 403)
        other = Team.objects.create(organisation=self.org, name='Other')
        r = c.put(self.url(self.payments), {'grants': [{'team_id': self.team.id, 'role': 'viewer'},
                                                       {'team_id': other.id, 'role': 'viewer'}]}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_restrictions_keep_applying(self):
        self.restrict()
        outsider = self.member('outsider@acme.test', 'user')
        self.assertEqual(self.as_user(outsider).get(f'/api/projects/{self.payments.id}/').status_code, 404)

    def test_lowering_removing_and_opening_always_work(self):
        self.restrict('admin')
        c = self.as_user(self.admin)
        r = c.put(self.url(self.payments), {'grants': [{'team_id': self.team.id, 'role': 'viewer'}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        r = c.put(self.url(self.payments), {'grants': []}, format='json')
        self.assertEqual((r.status_code, r.data['grants']), (200, []))
        r = c.put(self.url(self.payments), {'access_mode': 'organisation'}, format='json')
        self.assertEqual((r.status_code, r.data['access_mode']), (200, 'organisation'))
        self.assertEqual(c.get(self.url(self.payments)).status_code, 200)
