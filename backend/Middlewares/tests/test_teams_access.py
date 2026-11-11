"""Teams and project access through the API, the escalation guards, and
SSO groups filling teams."""
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from Data.models import AuditLog
from Middlewares.rbac import ROLE_PERMISSIONS, normalise_permissions
from Organisations.models import Organisations, Team, TeamMembership
from Projects.models import Project, ProjectTeamAccess
from Users.models import CustomRole, SecuritySettings, User
from Users.test.test_sso_flow import start_flow


class Base(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Acme')
        self.admin = self.user('admin', 'admin')
        self.member = self.user('member', 'user')
        self.payments = Project.objects.create(name='payments', organisation=self.org)
        self.web = Project.objects.create(name='web', organisation=self.org)

    def user(self, name, role, custom=None):
        return User.objects.create_user(username=name, email=f'{name}@acme.test', password='x', organisation=self.org,
                                        role=role, custom_role=custom, is_active=True)

    def as_user(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c


class TeamApiTest(Base):
    def test_create_list_update_delete(self):
        c = self.as_user(self.admin)
        r = c.post('/api/organisation/teams/', {'name': 'Payments', 'member_ids': [self.member.id]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        tid = r.data['id']
        self.assertEqual([m['email'] for m in r.data['members']], ['member@acme.test'])
        self.assertEqual(c.get('/api/organisation/teams/').data['teams'][0]['name'], 'Payments')
        r = c.put(f'/api/organisation/teams/{tid}/', {'member_ids': [], 'name': 'Pay'}, format='json')
        self.assertEqual((r.data['name'], r.data['members']), ('Pay', []))
        self.assertEqual(c.delete(f'/api/organisation/teams/{tid}/').status_code, 204)
        actions = set(AuditLog.objects.values_list('action', flat=True))
        self.assertTrue({'TEAM_CREATE', 'TEAM_UPDATE', 'TEAM_DELETE'} <= actions)

    def test_members_must_be_of_the_organisation(self):
        stranger = User.objects.create_user(username='s', email='s@other.test', password='x',
                                            organisation=Organisations.objects.create(name='Other'))
        r = self.as_user(self.admin).post('/api/organisation/teams/', {'name': 'X', 'member_ids': [stranger.id]},
                                          format='json')
        self.assertEqual(r.status_code, 400)

    def test_names_are_unique(self):
        Team.objects.create(organisation=self.org, name='SRE')
        self.assertEqual(self.as_user(self.admin).post('/api/organisation/teams/', {'name': 'sre'}, format='json').status_code, 400)


class ProjectGrantsTest(Base):
    def setUp(self):
        super().setUp()
        self.team = Team.objects.create(organisation=self.org, name='Payments')
        TeamMembership.objects.create(team=self.team, user=self.member)

    def test_project_list_carries_per_project_permissions(self):
        ProjectTeamAccess.objects.create(project=self.payments, team=self.team, role='admin')
        projects = {p['name']: p for p in self.as_user(self.member).get('/api/projects/').data}
        self.assertIn('project.delete', projects['payments']['permissions'])
        self.assertNotIn('project.delete', projects['web']['permissions'])

    def test_cannot_join_a_team_with_more_project_access(self):
        lead_role = CustomRole.objects.create(organisation=self.org, name='Lead', permissions=normalise_permissions(
            ROLE_PERMISSIONS['viewer'] + ['team.manage']))
        lead = self.user('lead', 'custom', lead_role)
        ProjectTeamAccess.objects.create(project=self.payments, team=self.team, role='admin')
        r = self.as_user(lead).put(f'/api/organisation/teams/{self.team.id}/',
                                   {'member_ids': [self.member.id, lead.id]}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.as_user(lead).delete(f'/api/organisation/teams/{self.team.id}/').status_code, 403)


class SSOTeamSyncTest(Base):
    def setUp(self):
        super().setUp()
        self.team = Team.objects.create(organisation=self.org, name='Payments')
        self.sec = SecuritySettings.objects.create(
            organisation=self.org, sso_enabled=True, sso_provider='oidc', sso_client_id='c',
            sso_discovery_url='https://idp.example.com/.well-known/openid-configuration',
            sso_team_mappings=[{'group': 'payments-eng', 'team_id': self.team.id}])

    def sign_in(self, email, groups):
        with patch('Users.sso_views.SSOService') as Service:
            Service.return_value.exchange_code_for_token.return_value = {'access_token': 't'}
            Service.return_value.get_user_info.return_value = {'email': email, 'email_verified': True, 'groups': groups}
            self.client.get(reverse('sso-callback'), {'code': 'c', 'state': start_flow(self.client, self.org.id)})

    def test_group_membership_follows_the_provider(self):
        self.sign_in('member@acme.test', ['payments-eng'])
        self.assertEqual(TeamMembership.objects.get(team=self.team, user=self.member).source, 'sso')
        self.sign_in('member@acme.test', [])
        self.assertFalse(TeamMembership.objects.filter(team=self.team, user=self.member).exists())

    def test_manual_members_are_left_alone(self):
        TeamMembership.objects.create(team=self.team, user=self.member, source='manual')
        self.sign_in('member@acme.test', [])
        self.assertTrue(TeamMembership.objects.filter(team=self.team, user=self.member).exists())

    def test_mapped_team_cannot_be_deleted(self):
        self.assertEqual(self.as_user(self.admin).delete(f'/api/organisation/teams/{self.team.id}/').status_code, 409)

    def test_rules_cannot_escalate(self):
        ProjectTeamAccess.objects.create(project=self.payments, team=self.team, role='admin')
        sec_role = CustomRole.objects.create(organisation=self.org, name='Sec', permissions=normalise_permissions(
            ROLE_PERMISSIONS['viewer'] + ['settings.manage']))
        r = self.as_user(self.user('sec', 'custom', sec_role)).put(
            '/api/auth/sso/config', {'sso_team_mappings': [{'group': 'mine', 'team_id': self.team.id}]}, format='json')
        self.assertEqual(r.status_code, 400)
