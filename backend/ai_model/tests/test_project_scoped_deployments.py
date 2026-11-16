"""Phase 3 review SC-03: the commits the RCA sees come from the project's own
repositories and deploys, whatever the provider, not from every repository
of the organisation."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from ai_model.tasks import _deployed_code_changes, _project_deployments
from Organisations.models import Organisations
from Projects.models import CICDBinding, Project, ProjectService, SCMBinding
from providers.models import CodeChange, Deployment, ProviderIntegration


class ProjectScopedDeploymentsTest(TestCase):
    def setUp(self):
        self.now = timezone.now().replace(microsecond=0)
        self.org = Organisations.objects.create(name='two-teams')
        gh = ProviderIntegration.objects.create(organisation=self.org, name='GH', provider_type='github')
        self.a = Project.objects.create(name='team-a', organisation=self.org)
        self.b = Project.objects.create(name='team-b', organisation=self.org)
        self.svc_a = ProjectService.objects.create(project=self.a, name='api-a')
        self.svc_b = ProjectService.objects.create(project=self.b, name='api-b')
        SCMBinding.objects.create(project_service=self.svc_a, integration=gh, repository_id='org/a')
        SCMBinding.objects.create(project_service=self.svc_b, integration=gh, repository_id='org/b')

    def _commit(self, repo, sha, hours_ago, branch='main'):
        return CodeChange.objects.create(
            organisation=self.org, provider='github', project_id=repo, commit_sha=sha, commit_message=sha,
            author_name='dev', timestamp=self.now - timedelta(hours=hours_ago), branch=branch)

    def _deploy(self, change, minutes_ago, service=None, env='production', status='success'):
        return Deployment.objects.create(
            code_change=change, environment=env, status=status, project_service=service,
            deployed_at=self.now - timedelta(minutes=minutes_ago))

    def test_another_projects_deploy_and_commits_are_not_this_projects(self):
        a_head = self._commit('org/a', 'a' * 40, hours_ago=2)
        self._commit('org/a', 'c' * 40, hours_ago=3)
        self._deploy(a_head, minutes_ago=120)
        b_head = self._commit('org/b', 'b' * 40, hours_ago=1)
        b_deploy = self._deploy(b_head, minutes_ago=10)

        deploys = list(_project_deployments(self.b, 'production'))
        self.assertEqual(deploys, [b_deploy])
        out = _deployed_code_changes(self.b, 'production', deploys, self.now)
        self.assertEqual({c['sha'] for c in out}, {'bbbbbbbb'})

    def test_a_gitops_deploy_recorded_for_the_service_is_found(self):
        """Argo CD / Flux deploys have no pipeline: found by their service."""
        argo = ProviderIntegration.objects.create(organisation=self.org, name='Argo', provider_type='argocd')
        CICDBinding.objects.create(project_service=self.svc_b, integration=argo,
                                   pipeline_id='payments', binding_type='deploy')
        rev = CodeChange.objects.create(
            organisation=self.org, provider='argocd', project_id='gitops', commit_sha='d' * 40,
            commit_message='sync', author_name='argo', timestamp=self.now, branch='main')
        deploy = self._deploy(rev, minutes_ago=5, service=self.svc_b)
        self.assertIn(deploy, list(_project_deployments(self.b, 'production')))
        self.assertNotIn(deploy, list(_project_deployments(self.a, 'production')))

    def test_prod_batch_finds_production_deploys(self):
        head = self._commit('org/b', 'e' * 40, hours_ago=1)
        deploy = self._deploy(head, minutes_ago=10)
        self.assertEqual(list(_project_deployments(self.b, 'prod')), [deploy])

    def test_a_cherry_picked_head_with_an_old_date_still_ships(self):
        """The head keeps its old author date: the range (prev, head] is
        inverted, but the head itself went live."""
        prev = self._commit('org/b', 'f' * 40, hours_ago=1)
        self._deploy(prev, minutes_ago=50)
        picked = self._commit('org/b', '1' * 40, hours_ago=30)
        deploy = self._deploy(picked, minutes_ago=5)
        out = _deployed_code_changes(self.b, 'production', [deploy], self.now)
        self.assertIn('11111111', {c['sha'] for c in out})
