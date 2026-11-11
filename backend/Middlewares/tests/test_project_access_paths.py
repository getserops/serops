"""Per-project access on paths the route walkers can't see: ids in bodies,
notifications, chat context, and the access helpers themselves."""
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from Data.models import AIAnalyzedBatch, Issue
from Middlewares import project_access
from Organisations.models import Organisations, Team, TeamMembership
from Projects.models import Project, ProjectTeamAccess
from Users.models import User


class AccessBase(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Acme')
        self.admin = self.user('admin', 'admin')
        self.member = self.user('member', 'user')
        self.viewer = self.user('viewer', 'viewer')
        self.open = Project.objects.create(name='open', organisation=self.org)
        self.secret = Project.objects.create(name='secret', organisation=self.org, access_mode='restricted')
        self.team = Team.objects.create(organisation=self.org, name='Payments')
        self.batches = {}
        self.issues = {}
        for p in (self.open, self.secret):
            b = AIAnalyzedBatch.objects.create(batch_id=f'b-{p.name}', project=p, organisation=self.org,
                                               timestamp=timezone.now(), data={})
            self.batches[p.name] = b
            self.issues[p.name] = Issue.objects.create(batch=b, project=p, organisation=self.org, severity='CRITICAL',
                                                       description='d', root_cause='r', fingerprint=f'fp-{p.name}',
                                                       component='c')

    def user(self, name, role):
        return User.objects.create_user(username=name, email=f'{name}@acme.test', password='x', organisation=self.org,
                                        role=role, is_active=True)

    def grant(self, user, project, role):
        TeamMembership.objects.get_or_create(team=self.team, user=user)
        ProjectTeamAccess.objects.update_or_create(project=project, team=self.team, defaults={'role': role})

    def client_for(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c


class HelperTest(AccessBase):
    def test_permissions_by_mode_and_grant(self):
        perms = project_access.project_permissions
        self.assertEqual(perms(self.admin, self.secret), project_access.PROJECT_SCOPED)
        self.assertEqual(perms(self.member, self.secret), set())
        self.assertIn('project.write', perms(self.member, self.open))
        self.grant(self.viewer, self.secret, 'user')
        self.viewer._project_grants = None
        self.assertIn('issue.update', perms(self.viewer, self.secret))
        self.assertNotIn('project.write', perms(self.viewer, self.open))

    def test_an_organisation_without_access_rules_pays_nothing(self):
        Project.objects.filter(pk=self.secret.pk).update(access_mode='organisation')
        org = Organisations.objects.get(pk=self.org.pk)
        member = User.objects.select_related('organisation').get(pk=self.member.pk)
        self.assertFalse(project_access.uses_access_control(org))
        self.assertIsNone(project_access.accessible_project_ids(member, 'batch.read'))


class BodyIdTest(AccessBase):
    def test_bulk_issue_actions_only_reach_accessible_projects(self):
        r = self.client_for(self.member).post('/api/data/issues/bulk-action/', {
            'issue_ids': [self.issues['secret'].id], 'action': 'resolve'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.issues['secret'].refresh_from_db()
        self.assertNotEqual(self.issues['secret'].status, 'RESOLVED')

    def test_grant_on_one_project_doesnt_write_another(self):
        # Viewer in the organisation, User on "secret" through a team.
        self.grant(self.viewer, self.secret, 'user')
        c = self.client_for(self.viewer)
        r = c.post('/api/data/issues/bulk-action/', {'issue_ids': [self.issues['open'].id], 'action': 'resolve'},
                   format='json')
        self.assertEqual(r.status_code, 400)
        r = c.post('/api/data/issues/bulk-action/', {'issue_ids': [self.issues['secret'].id], 'action': 'resolve'},
                   format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def test_project_creation_needs_the_organisation_role(self):
        self.grant(self.viewer, self.secret, 'admin')
        r = self.client_for(self.viewer).post('/api/projects/', {'name': 'new'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_investigation_needs_access_to_the_project(self):
        r = self.client_for(self.member).post('/api/data/investigations/', {'project_id': self.secret.id}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('invalid_project', r.content.decode())

    def test_subscription_to_a_restricted_project_is_refused(self):
        r = self.client_for(self.member).post('/api/notification/subscriptions/', {'project': self.secret.id},
                                              format='json')
        self.assertEqual(r.status_code, 400)


class NotificationTest(AccessBase):
    def test_subscribers_without_access_are_skipped(self):
        from notifications.dispatcher import NotificationDispatcher
        from notifications.models import ProjectSubscription
        ProjectSubscription.objects.create(user=self.member, project=self.secret)
        self.grant(self.viewer, self.secret, 'viewer')
        ProjectSubscription.objects.create(user=self.viewer, project=self.secret)
        ProjectSubscription.objects.create(user=self.member, project=self.open)
        self.assertEqual([s.user for s in NotificationDispatcher.subscriptions_for(self.secret)], [self.viewer])
        self.assertEqual([s.user for s in NotificationDispatcher.subscriptions_for(self.open)], [self.member])


class ChatTest(AccessBase):
    def prompts_for(self, user):
        AIAnalyzedBatch.objects.filter(pk=self.batches['secret'].pk).update(
            data={'logs': [{'_source': {'message': 'SECRET-LOG-LINE payment failed', 'service_name': 'pay'}}]})
        with patch('ai_model.views.process_ai_request', return_value='{"answer": "ok"}') as ai:
            self.client_for(user).post('/api/chat/generate-text/', {
                'type': 'chat', 'ai_model': 'gemini', 'batch_id': 'b-secret',
                'prompt': {'message': 'show the error logs'}}, format='json')
        return ' '.join(str(c.args[0]) for c in ai.call_args_list)

    def test_chat_context_follows_project_access(self):
        self.assertIn('SECRET-LOG-LINE', self.prompts_for(self.admin))
        self.assertNotIn('SECRET-LOG-LINE', self.prompts_for(self.member))
