"""
Role matrix for write routes that once relied on "signed in" alone.

Viewers are read-only; users can triage and add projects; only admins
change org settings or delete. Found by the 2026-10-19 security review.
"""
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from Data.models import AIAnalyzedBatch, Issue
from Organisations.models import Organisations
from Projects.models import Project
from providers.models import GitlabProject
from Users.models import User

# (method, path, body). '{issue}' is replaced by the issue id.
VIEWER_BLOCKED = [
    ('PUT', '/api/organisation/onboarding/status/', {'step': 'project'}),
    ('POST', '/api/organisation/onboarding/skip/', {}),
    ('POST', '/api/organisation/onboarding/resume/', {}),
    ('POST', '/api/chat/analyze-batch/', {'batch_id': 'B1'}),
    ('POST', '/api/data/batches/B1/postmortem/', {}),
    ('POST', '/api/providers/', {'name': 'x'}),
    ('PUT', '/api/providers/1/', {'name': 'x'}),
    ('DELETE', '/api/providers/1/', {}),
    ('POST', '/api/providers/webhook-set/', {'project_id': '42'}),
    ('POST', '/api/providers/webhook-del/', {'project_id': '42'}),
    ('POST', '/api/providers/verify-project/', {}),
    ('POST', '/api/providers/verify-github/', {}),
    ('POST', '/api/providers/verify-bitbucket/', {}),
    ('POST', '/api/providers/verify-azure-devops/', {}),
    ('POST', '/api/notification/issues/{issue}/acknowledge/', {}),
    ('POST', '/api/data/issues/{issue}/resolve/', {}),
    ('POST', '/api/data/issues/bulk-action/', {'issue_ids': ['{issue}'], 'action': 'resolve'}),
]
ADMIN_ONLY = [
    ('DELETE', '/api/providers/1/', {}),
    ('PUT', '/api/auth/sso/config', {'enabled': False}),
    ('PUT', '/api/organisation/info/', {'website': 'https://x.example'}),
    ('PUT', '/api/data/settings/security/', {'session_timeout_minutes': 60}),
    ('PUT', '/api/data/settings/retention-policy/', {'retention_days': 30}),
    ('DELETE', '/api/data/delete-old-batches/', {}),
]


class RoleMatrixTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Matrix Org')
        project = Project.objects.create(name='matrix', organisation=self.org)
        batch = AIAnalyzedBatch.objects.create(batch_id='B1', project=project, organisation=self.org,
                                               timestamp=timezone.now(), data={'logs': []})
        self.issue = Issue.objects.create(batch=batch, project=project, organisation=self.org, severity='CRITICAL',
                                          description='d', root_cause='r', fingerprint='f', component='c')
        self.users = {role: User.objects.create_user(username=role, email=f'{role}@matrix.example', password='x',
                                                     organisation=self.org, role=role, is_active=True)
                      for role in ('viewer', 'user', 'admin')}

    def call(self, role, method, path, body):
        client = APIClient()
        client.force_authenticate(user=self.users[role])
        path = path.replace('{issue}', str(self.issue.id))
        body = {k: ([self.issue.id] if v == ['{issue}'] else v) for k, v in body.items()}
        with mock.patch('ai_model.tasks.analyze_batch.delay'), \
             mock.patch('ai_model.postmortem.generate_postmortem_draft', return_value='# draft'):
            return getattr(client, method.lower())(path, body, format='json').status_code

    def test_viewer_cannot_write(self):
        for method, path, body in VIEWER_BLOCKED:
            with self.subTest(method=method, path=path):
                self.assertEqual(self.call('viewer', method, path, body), 403)

    def test_user_cannot_do_admin_things(self):
        for method, path, body in ADMIN_ONLY:
            with self.subTest(method=method, path=path):
                self.assertEqual(self.call('user', method, path, body), 403)

    def test_user_can_triage(self):
        self.assertEqual(self.call('user', 'POST', '/api/data/issues/{issue}/resolve/', {}), 200)
        self.assertEqual(self.call('user', 'POST', '/api/notification/issues/{issue}/acknowledge/', {}), 200)


class GitLabWebhookTenancyTest(TestCase):
    """A user must never act on another organisation's GitLab project with its stored token."""

    def setUp(self):
        victim = Organisations.objects.create(name='Victim Org')
        self.project = GitlabProject.objects.create(
            gitlab_url='https://gitlab.example/victim/app', username='v', name='app',
            project_id='4242', access_token='victim-token', organisation=victim)
        other = Organisations.objects.create(name='Other Org')
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.create_user(
            username='o', email='other@tenancy.example', password='x', organisation=other, role='admin', is_active=True))

    def test_cannot_set_webhook_on_another_orgs_project(self):
        with mock.patch('providers.views.requests.post') as post:
            response = self.client.post('/api/providers/webhook-set/', {'project_id': '4242'}, format='json')
        self.assertEqual(response.status_code, 404)
        post.assert_not_called()

    def test_cannot_delete_webhooks_on_another_orgs_project(self):
        with mock.patch('providers.views.requests.get') as get, mock.patch('providers.views.requests.delete') as delete:
            response = self.client.post('/api/providers/webhook-del/', {'project_id': '4242'}, format='json')
        self.assertEqual(response.status_code, 404)
        get.assert_not_called()
        delete.assert_not_called()


class SharedProviderCatalogueTest(TestCase):
    """The AI provider catalogue is shared by every organisation. On a multi-org
    install only platform staff change it; on a single-org install its admin can."""

    def setUp(self):
        from org_settings.models import AIModelProvider
        self.provider = AIModelProvider.objects.create(name='matrix-ai', display_name='Matrix AI')
        org = Organisations.objects.create(name='Catalogue Org')
        self.admin = User.objects.create_user(username='a', email='admin@catalogue.example', password='x',
                                              organisation=org, role='admin', is_active=True)
        self.staff = User.objects.create_user(username='s', email='staff@catalogue.example', password='x',
                                              organisation=org, role='admin', is_active=True, is_staff=True)
        # A second tenant: changing the shared catalogue would now affect someone else.
        self.other_org = Organisations.objects.create(name='Other Tenant')

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_org_admin_reads_but_cannot_change(self):
        client = self.client_for(self.admin)
        self.assertEqual(client.get('/api/settings/ai/providers/').status_code, 200)
        url = f'/api/settings/ai/providers/{self.provider.pk}/'
        self.assertEqual(client.patch(url, {'is_active': False}, format='json').status_code, 403)
        self.assertEqual(client.delete(url).status_code, 403)
        self.assertEqual(client.post('/api/settings/ai/providers/', {'name': 'evil', 'display_name': 'E'},
                                     format='json').status_code, 403)
        self.provider.refresh_from_db()
        self.assertTrue(self.provider.is_active)

    def test_single_org_admin_can_change(self):
        self.other_org.delete()
        url = f'/api/settings/ai/providers/{self.provider.pk}/'
        self.assertEqual(self.client_for(self.admin).patch(url, {'is_active': False}, format='json').status_code, 200)
        self.assertIn('ai_catalogue.manage', self.client_for(self.admin).get('/api/auth/profile').data['permissions'])

    def test_flag_is_false_for_multi_org_admin(self):
        self.assertNotIn('ai_catalogue.manage', self.client_for(self.admin).get('/api/auth/profile').data['permissions'])

    def test_staff_can_change(self):
        url = f'/api/settings/ai/providers/{self.provider.pk}/'
        response = self.client_for(self.staff).patch(url, {'is_active': False}, format='json')
        self.assertEqual(response.status_code, 200, getattr(response, 'data', None))

    def test_is_staff_cannot_be_self_granted(self):
        client = self.client_for(self.admin)
        client.post('/api/auth/profile', {'is_staff': True, 'first_name': 'A'}, format='json')
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_staff)
        self.assertIs(client.get('/api/auth/profile').data['is_staff'], False)


class SecondPassRoleTest(TestCase):
    """Second review pass (2026-10-20): integrations, deletions, settings reads."""

    def setUp(self):
        from providers.models import ProviderIntegration
        from Projects.models import ProjectService
        self.org = Organisations.objects.create(name='Second Pass Org')
        self.users = {r: User.objects.create_user(username=r, email=f'{r}@second.example.com', password='Xx-12345678',
                                                  organisation=self.org, role=r, is_active=True)
                      for r in ('viewer', 'user', 'admin')}
        self.integration = ProviderIntegration.objects.create(organisation=self.org, name='gh', provider_type='github')
        self.project = Project.objects.create(name='second', organisation=self.org)
        self.service = ProjectService.objects.create(project=self.project, name='svc')

    def code(self, role, method, path, body=None):
        client = APIClient(raise_request_exception=False)
        client.force_authenticate(user=self.users[role])
        return getattr(client, method)(path, body or {}, format='json').status_code

    def test_only_admins_manage_integration_credentials(self):
        for role in ('viewer', 'user'):
            with self.subTest(role=role):
                self.assertEqual(self.code(role, 'post', '/api/providers/integrations/', {'name': 'x'}), 403)
                self.assertEqual(self.code(role, 'post', '/api/providers/integrations/test/', {}), 403)
                self.assertEqual(self.code(role, 'delete', f'/api/providers/integrations/{self.integration.id}/'), 403)
        self.assertNotEqual(self.code('admin', 'post', '/api/providers/integrations/', {'name': 'x'}), 403)

    def test_viewers_cannot_verify_or_sync_integrations(self):
        self.assertEqual(self.code('viewer', 'post', f'/api/providers/integrations/{self.integration.id}/sync/'), 403)

    def test_only_admins_delete_projects_and_services(self):
        self.assertEqual(self.code('user', 'delete', f'/api/projects/services/{self.service.id}/'), 403)
        self.assertEqual(self.code('user', 'delete', f'/api/projects/{self.project.id}/'), 403)
        self.assertEqual(self.code('admin', 'delete', f'/api/projects/services/{self.service.id}/'), 204)

    def test_viewers_cannot_read_security_settings(self):
        for path in ('/api/data/settings/security/', '/api/auth/sso/config'):
            with self.subTest(path=path):
                self.assertEqual(self.code('viewer', 'get', path), 403)
                self.assertEqual(self.code('user', 'get', path), 200)
