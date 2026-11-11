"""
Enterprise access review, 2026-11-05: what a member outside a restricted
project could still read or change. Each test pins one fix; the fixture is
the guard test's (a restricted project whose objects carry MARKER).
"""
from django.utils import timezone

from Middlewares.tests.test_project_scope_coverage import MARKER, ProjectScopeBase


class OutsiderReviewTest(ProjectScopeBase):
    """The outsider: organisation role 'user', in no team of the project."""

    def caller(self):
        return self.outsider

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from Data.models import AIAnalyzedBatch, Issue
        from integrations.models import Cluster
        from Projects.models import Project
        from providers.models import Pipeline
        restricted = Project.objects.get(pk=cls.seed['project'])
        org = restricted.organisation
        open_project = Project.objects.get(organisation=org, name='open-shop')
        now = timezone.now()
        # A resolved incident of the restricted project, and an open issue of
        # the open project that reads like it.
        Issue.objects.create(
            batch=AIAnalyzedBatch.objects.get(batch_id=cls.seed['batch']), project=restricted, organisation=org,
            severity='CRITICAL', status='RESOLVED', resolved_at=now, fingerprint=f'{MARKER}-resolved',
            description='redis connection refused, checkout failing', component='redis',
            root_cause=f'{MARKER} secret root cause', resolution_fix=f'{MARKER} secret fix')
        open_batch = AIAnalyzedBatch.objects.create(batch_id='open-batch-1', project=open_project, organisation=org,
                                                    timestamp=now, data={}, analysis_text='')
        cls.open_issue = Issue.objects.create(
            batch=open_batch, project=open_project, organisation=org, severity='HIGH', fingerprint='open-fp',
            description='redis connection refused, cart failing', component='redis', root_cause='redis down')
        # A pipeline of the restricted project's CI/CD binding.
        Pipeline.objects.create(organisation=org, pipeline_id='9001', status='failed', branch=f'{MARKER}-branch',
                                external_project_id=f'{MARKER}-pipeline', cicd_provider='gitlab')
        cls.cluster = Cluster.objects.get(organisation=org, name='prod-cluster')
        restricted.cluster = cls.cluster
        restricted.save(update_fields=['cluster'])

    def test_issues_of_a_restricted_batch(self):
        response = self.client.get(f"/api/data/issues/{self.seed['batch']}/")
        self.assertEqual(response.status_code, 404)
        # The 404 repeats the id the caller sent (it carries the marker);
        # none of the batch's issues may come back.
        body = response.content.decode()
        self.assertNotIn('redis down', body)
        self.assertNotIn('root cause', body)

    def test_similar_issues_skip_restricted_projects(self):
        response = self.client.get(f'/api/data/issues/{self.open_issue.pk}/similar/', {'limit': 20})
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertFalse(self.leaked(response))

    def test_pipelines_of_a_restricted_project(self):
        response = self.client.get('/api/providers/pipelines/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.leaked(response))

    def test_cluster_workloads_skip_restricted_projects(self):
        response = self.client.get(f'/api/integrations/clusters/{self.cluster.pk}/workloads/')
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertFalse(self.leaked(response))


class GrantedViewerReviewTest(ProjectScopeBase):
    """A viewer whose team is admin of the restricted project only."""

    def caller(self):
        return self.granted

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from Projects.models import ProjectTeamAccess
        from providers.models import GitlabProject
        ProjectTeamAccess.objects.filter(project_id=cls.seed['project']).update(role='admin')
        org = ProjectTeamAccess.objects.get(project_id=cls.seed['project']).project.organisation
        cls.repo = GitlabProject.objects.create(organisation=org, gitlab_url='https://gitlab.example.com/x/y',
                                                username='u', name='other-team-repo', project_id='777',
                                                access_token='t')

    def test_a_grant_does_not_open_organisation_wide_legacy_writes(self):
        self.assertEqual(self.client.delete(f'/api/providers/{self.repo.pk}/').status_code, 403)
        self.assertEqual(self.client.post('/api/providers/webhook-set/', {}, format='json').status_code, 403)


class SSOIdentityProviderTest(ProjectScopeBase):
    """A custom role with settings.manage, below admin."""

    def caller(self):
        from Users.models import CustomRole, User
        if not hasattr(self, '_manager'):
            role = CustomRole.objects.create(organisation=self.outsider.organisation, name='Settings manager',
                                             permissions=['settings.manage', 'org.read'])
            self._manager = User.objects.create_user(
                username='settingsmgr', email='settingsmgr@s.example', password='x',
                organisation=self.outsider.organisation, role='custom', custom_role=role, is_active=True)
        return self._manager

    def test_cannot_point_sso_at_another_identity_provider(self):
        response = self.client.put('/api/auth/sso/config', {
            'sso_enabled': True, 'sso_provider': 'oidc', 'sso_client_id': 'attacker',
            'sso_discovery_url': 'https://idp.attacker.example/.well-known/openid-configuration'}, format='json')
        self.assertEqual(response.status_code, 403, response.content[:300])
