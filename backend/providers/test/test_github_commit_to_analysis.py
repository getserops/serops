"""A GitHub commit reaches the analysis without webhooks (found in the GitHub
journey: the repository sync rejected every commit, and the Actions poll
failed every minute, so no deployment was ever recorded)."""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from Organisations.models import Organisations
from Projects.models import CICDBinding, Project, ProjectService
from providers.code_change_service import CodeChangeService
from providers.deployment_service import DeploymentService
from providers.models import CodeChange, Deployment, ProviderIntegration
from providers.webhook_base import detect_environment_generic

SHA = '725e3e65' + '0' * 32


class GitHubCommitToAnalysisTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Shop Org')
        project = Project.objects.create(name='shop', organisation=self.org)
        self.service = ProjectService.objects.create(project=project, name='payments')
        self.integration = ProviderIntegration.objects.create(
            organisation=self.org, name='Acme GitHub', provider_type='github')
        self.binding = CICDBinding.objects.create(
            project_service=self.service, integration=self.integration,
            pipeline_id='acme/payments', binding_type='deploy')

    def test_the_sync_saves_github_commits_with_their_organisation(self):
        """GitHub's commits API gives branch None; the column is required."""
        saved = CodeChangeService.save_commits_from_webhook(
            provider='github', project_id='1443', gitlab_project=None,
            organisation=self.org, default_branch='main',
            commits=[{'sha': SHA, 'message': 'payments: lower db pool to 2', 'author_name': 'dev',
                      'author_email': 'dev@acme.test', 'timestamp': timezone.now().isoformat(), 'branch': None}])
        self.assertEqual(len(saved), 1)
        self.assertEqual((saved[0].organisation, saved[0].branch), (self.org, 'main'))

    def _poll(self, conclusion='success'):
        now = timezone.now()
        provider = MagicMock()
        provider.list_recent_pipelines.return_value = [{
            'id': '41513845404', 'status': conclusion, 'ref': 'main', 'sha': SHA,
            'updated_at': now.isoformat(), 'message': 'payments: lower db pool to 2',
            'author_name': 'dev', 'author_email': 'dev@acme.test', 'timestamp': now.isoformat()}]
        with patch.object(CICDBinding, 'get_provider', return_value=provider):
            from providers.tasks import sync_recent_deployments
            return sync_recent_deployments(hours=2)

    def test_a_polled_actions_run_records_the_commit_and_its_deployment(self):
        stats = self._poll()
        self.assertEqual(stats['errors'], [])
        change = CodeChange.objects.get(commit_sha=SHA)
        self.assertEqual((change.commit_message, change.author_name, change.organisation),
                         ('payments: lower db pool to 2', 'dev', self.org))
        env = detect_environment_generic(branch='main', project_id='acme/payments')
        self.assertTrue(Deployment.objects.filter(code_change=change, environment=env, status='success').exists())
        # The analysis of that environment and window picks it up.
        now = timezone.now()
        found = DeploymentService.get_deployments_for_batch(
            environment=env, start_time=now - timedelta(minutes=15), end_time=now + timedelta(minutes=1),
            organisation_id=self.org.id)
        self.assertEqual([c.commit_sha for c in found], [SHA])

    def test_another_organisations_commit_with_the_same_sha_is_not_reused(self):
        other = Organisations.objects.create(name='Other Org')
        CodeChange.objects.create(provider='github', project_id='x/y', organisation=other, commit_sha=SHA,
                                  commit_message='theirs', author_name='them', timestamp=timezone.now(), branch='main')
        self._poll()
        self.assertEqual(CodeChange.objects.filter(commit_sha=SHA, organisation=self.org).count(), 1)
        self.assertEqual(CodeChange.objects.get(organisation=other).commit_message, 'theirs')
