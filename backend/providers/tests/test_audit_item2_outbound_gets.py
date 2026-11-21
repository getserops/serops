"""GET endpoints that called providers with stored credentials (audit 2026-11-20, item 2).

- health-check-all is a POST needing integration.use, like the single health
  check; the token owner's email stays with integration.manage holders.
- The GitLab pipeline-logs view refuses the demo account before any call or
  write.
- Observability ingest-health answers the demo account without reaching the
  store.
The route-wide check is Middlewares/tests/test_demo_get_no_outbound.py.
"""
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from integrations.models import ObservabilityIntegration
from Organisations.models import Organisations
from Projects.models import Project, ProjectService
from providers.models import GitlabProject, Pipeline, ProviderIntegration
from Users.models import User

RESULT = {'integration_id': 1, 'provider_type': 'github', 'name': 'gh', 'healthy': True,
          'latency_ms': 5, 'error': None,
          'details': {'username': 'octo', 'email': 'owner@corp.example', 'name': 'Octo'}}


class Base(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Item2 Org')
        self.users = {
            role: User.objects.create_user(username=f'i2{role}', email=f'i2{role}@test.com', password='Pass1234!',
                                           organisation=self.org, role=role, is_active=True)
            for role in ('admin', 'user', 'viewer')
        }
        self.client = APIClient()

    def as_(self, role):
        self.client.force_authenticate(user=self.users[role])


class HealthCheckAllTest(Base):
    URL = '/api/providers/integrations/health-check-all/'

    def test_get_is_gone(self):
        self.as_('admin')
        self.assertEqual(self.client.get(self.URL).status_code, 405)

    @patch('providers.services.IntegrationHealthService.check_all_for_org', return_value=[RESULT])
    def test_post_needs_integration_use(self, _check):
        self.as_('viewer')
        self.assertEqual(self.client.post(self.URL).status_code, 403)
        _check.assert_not_called()

    @patch('providers.services.IntegrationHealthService.check_all_for_org', return_value=[RESULT])
    def test_owner_email_only_with_integration_manage(self, _check):
        self.as_('user')
        r = self.client.post(self.URL)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('email', r.json()['results'][0]['details'])
        self.assertEqual(r.json()['results'][0]['details']['username'], 'octo')
        self.as_('admin')
        self.assertEqual(self.client.post(self.URL).json()['results'][0]['details']['email'], 'owner@corp.example')


class SingleHealthCheckEmailTest(Base):
    def test_owner_email_hidden_without_manage(self):
        integ = ProviderIntegration.objects.create(organisation=self.org, provider_type='github', name='gh')
        with patch('providers.services.IntegrationHealthService.check_health', return_value=dict(RESULT)):
            self.as_('user')
            r = self.client.post(f'/api/providers/integrations/{integ.id}/health-check/')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('email', r.json()['details'])


class DemoGuardsTest(Base):
    def setUp(self):
        super().setUp()
        self.demo = User.objects.create_user(username='i2demo', email='i2demo@test.com', password='Pass1234!',
                                             organisation=self.org, role='admin', is_active=True, is_demo=True)
        self.client.force_authenticate(user=self.demo)

    @patch('providers.views.requests.get')
    def test_pipeline_logs_refused_for_demo(self, get):
        project = Project.objects.create(name='shop', organisation=self.org)
        repo = GitlabProject.objects.create(gitlab_url='https://gitlab.example', username='u', name='shop',
                                            project_id='4242', access_token='t', organisation=self.org)
        ProjectService.objects.create(project=project, name='shop', gitlab_project=repo)
        pipeline = Pipeline.objects.create(organisation=self.org, project=repo, pipeline_id='p1',
                                           status='failed', branch='main')
        r = self.client.get(f'/api/providers/{repo.id}/pipelines/{pipeline.id}/logs/')
        self.assertEqual(r.status_code, 403)
        get.assert_not_called()

    @patch('integrations.views.collect_ingest_health')
    def test_ingest_health_answers_demo_without_the_store(self, collect):
        obs = ObservabilityIntegration.objects.create(organisation=self.org, provider='loki',
                                                      host='https://loki.example', display_name='loki', capabilities=['logs'])
        obs.set_password('live' + '-looking')
        obs.save()
        r = self.client.get(f'/api/integrations/observability/{obs.id}/ingest-health/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['demo'])
        collect.assert_not_called()
