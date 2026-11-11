"""
A restricted project stays out of reach of members outside its teams.

Same walk as test_tenant_coverage, inside one organisation: a member with
the User role, in no team, calls every API route. Everything of the
restricted project carries MARKER; lists must not show it and routes with
one of its ids (TARGETS) must fail. A second walk as a Viewer whose team
has the User role on the project checks the grant works: reads succeed
and writes are not refused for lack of permission.
"""
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from Middlewares.tests.test_tenant_coverage import (TARGETS, _offline, api_routes, fill, implemented,
                                                     route_params)

MARKER = 'zzrestricted'

# Seeds that belong to the restricted project (the other TARGETS entries are
# organisation-level or another user's objects).
PROJECT_SEEDS = {
    'project', 'project_service', 'batch', 'issue', 'investigation', 'scm_binding', 'cicd_binding',
    'deployment', 'scm_service', 'infra_service', 'custom_service',
}


class ProjectScopeBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        from Data.models import AIAnalyzedBatch, Investigation, Issue
        from integrations.models import Cluster
        from Organisations.models import Organisations, Team, TeamMembership
        from Projects.models import (CICDBinding, Project, ProjectDeployment, ProjectEnvironment, ProjectService,
                                     ProjectTeamAccess, SCMBinding)
        from providers.models import ProviderIntegration
        from Services.models import CustomService, InfraService, SCMService
        from Users.models import User

        now = timezone.now()
        m = MARKER
        org = Organisations.objects.create(name='Scoped org')
        owner = User.objects.create_user(username='owner', email='owner@s.example', password='x', organisation=org,
                                         role='admin', is_active=True)
        cls.outsider = User.objects.create_user(username='outsider', email='outsider@s.example', password='x',
                                                organisation=org, role='user', is_active=True)
        cls.granted = User.objects.create_user(username='granted', email='granted@s.example', password='x',
                                               organisation=org, role='viewer', is_active=True)
        open_project = Project.objects.create(name='open-shop', organisation=org)
        project = Project.objects.create(name=f'{m}-payments', organisation=org, access_mode='restricted')
        team = Team.objects.create(organisation=org, name='Payments')
        TeamMembership.objects.create(team=team, user=cls.granted)
        ProjectTeamAccess.objects.create(project=project, team=team, role='user')

        service = ProjectService.objects.create(project=project, name=f'{m}-checkout')
        ProjectService.objects.create(project=open_project, name='open-web')
        env = ProjectEnvironment.objects.create(project=project, name='production')
        batch = AIAnalyzedBatch.objects.create(
            batch_id=f'{m}-batch-1', project=project, organisation=org, timestamp=now,
            data={'logs': [f'{m} log line']}, analysis_text=f'{m} analysis')
        issue = Issue.objects.create(
            batch=batch, project=project, organisation=org, severity='CRITICAL', description=f'{m} redis down',
            root_cause=f'{m} root cause', fingerprint=f'{m}-fp', component=f'{m}-redis')
        integration = ProviderIntegration.objects.create(name='gitlab', provider_type='gitlab', organisation=org)
        cluster = Cluster.objects.create(organisation=org, name='prod-cluster')
        cls.seed = {
            'project': project.id,
            'project_service': service.id,
            'batch': batch.batch_id,
            'issue': issue.id,
            'investigation': Investigation.objects.create(
                organisation=org, project=project, requested_by=owner, environment=env,
                window_start=now, window_end=now).id,
            'scm_binding': SCMBinding.objects.create(
                project_service=service, integration=integration, repository_id=f'{m}/repo').id,
            'cicd_binding': CICDBinding.objects.create(
                project_service=service, integration=integration, pipeline_id=f'{m}-pipeline').id,
            'deployment': ProjectDeployment.objects.create(project=project, cluster=cluster, namespace=f'{m}-ns').id,
            'scm_service': SCMService.objects.create(
                project=project, name=f'{m}-scm', category='scm', provider='gitlab', external_id='1',
                access_token='t').id,
            'infra_service': InfraService.objects.create(
                project=project, name=f'{m}-redis-infra', category='infra', infra_type='redis').id,
            'custom_service': CustomService.objects.create(project=project, name=f'{m}-custom', category='custom').id,
        }

    def setUp(self):
        self.client = APIClient(raise_request_exception=False)
        # A real token, as a browser sends it: cached responses (cache_page)
        # vary on the Authorization header, which force_authenticate lacks.
        from django.core.cache import cache
        from knox.models import AuthToken
        cache.clear()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + AuthToken.objects.create(self.caller())[1])
        for target in ('requests.Session.request', 'httpx.Client.send'):
            patcher = mock.patch(target, side_effect=_offline)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch('celery.app.task.Task.apply_async', return_value=mock.MagicMock(id='stub'))
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, method, url, query=None):
        if method in ('GET', 'HEAD'):
            return self.client.get(url, query or {})
        return getattr(self.client, method.lower())(url, {}, format='json')

    def leaked(self, response):
        return MARKER in response.content.decode('utf-8', 'replace').lower()

    def project_routes(self):
        """(pattern, callback, cls, url) for routes filled with the project's objects."""
        for pattern, callback, cls in api_routes():
            target = TARGETS.get(pattern)
            if not route_params(pattern) or not isinstance(target, dict):
                continue
            keys = {v for v in target.values() if not v.startswith('=')}
            if not keys or not keys <= PROJECT_SEEDS:
                continue
            values = {k: v[1:] if v.startswith('=') else self.seed[v] for k, v in target.items()}
            yield pattern, callback, cls, fill(pattern, values)


class OutsiderTest(ProjectScopeBase):
    def caller(self):
        return self.outsider

    def test_lists_do_not_show_the_restricted_project(self):
        s = self.seed
        queries = [{}, {'project': s['project'], 'project_id': s['project'], 'service': s['project_service'],
                        'service_id': s['project_service'], 'batch_id': s['batch'], 'batch': s['batch'],
                        'issue_id': s['issue']}]
        leaks = []
        for pattern, callback, cls in api_routes():
            if route_params(pattern) or 'GET' not in implemented(callback, cls):
                continue
            for query in queries:
                response = self.call('GET', fill(pattern, {}), query)
                if 200 <= response.status_code < 300 and self.leaked(response):
                    leaks.append(f'GET {fill(pattern, {})}{" (with ids)" if query else ""}')
        self.assertEqual(leaks, [], '\nRestricted project data shown to an outsider:\n' + '\n'.join(leaks))

    def test_objects_of_the_restricted_project_are_out_of_reach(self):
        leaks = []
        for pattern, callback, cls, url in self.project_routes():
            for method in implemented(callback, cls):
                response = self.call(method, url)
                ok = 200 <= response.status_code < 300
                if ok and (method not in ('GET', 'HEAD', 'OPTIONS') or self.leaked(response)):
                    leaks.append(f'{method} {url} -> {response.status_code}')
        self.assertEqual(leaks, [], '\nOutsider reached the restricted project:\n' + '\n'.join(leaks))


class GrantedViewerTest(ProjectScopeBase):
    """A Viewer whose team has the User role on the project."""

    def caller(self):
        return self.granted

    def test_reads_work(self):
        s = self.seed
        for url in (f'/api/projects/{s["project"]}/', f'/api/data/batches/{s["batch"]}/', '/api/data/issues/',
                    '/api/projects/'):
            response = self.call('GET', url)
            self.assertEqual(response.status_code, 200, url)
            self.assertTrue(self.leaked(response), f'{url} hides the granted project')

    def test_writes_are_not_refused_for_permission(self):
        refused = []
        s = self.seed
        for method, url in (('PUT', f'/api/projects/{s["project"]}/'), ('POST', f'/api/data/issues/{s["issue"]}/resolve/'),
                            ('POST', f'/api/data/batches/{s["batch"]}/postmortem/')):
            if self.call(method, url).status_code in (403, 404):
                refused.append(f'{method} {url}')
        self.assertEqual(refused, [], '\nThe grant did not apply:\n' + '\n'.join(refused))

    def test_grant_is_only_for_that_project(self):
        from Projects.models import Project
        open_project = Project.objects.get(name='open-shop')
        # Viewer on the open project: read yes, write no.
        self.assertEqual(self.call('GET', f'/api/projects/{open_project.id}/').status_code, 200)
        self.assertIn(self.call('PUT', f'/api/projects/{open_project.id}/').status_code, (403, 404))
        self.assertIn(self.call('DELETE', f'/api/projects/{self.seed["project"]}/').status_code, (403, 404))
