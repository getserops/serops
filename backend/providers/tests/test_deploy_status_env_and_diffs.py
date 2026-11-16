"""Phase 3 review SC-04 / SC-05 / SC-08 (providers side)."""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from Organisations.models import Organisations
from Projects.models import Project, ProjectService, SCMBinding
from providers.code_change_service import CodeChangeService
from providers.deployment_service import DeploymentService, canonical_environment
from providers.models import CodeChange, Deployment, ProviderIntegration


class Base(TestCase):
    def setUp(self):
        self.now = timezone.now().replace(microsecond=0)
        self.org = Organisations.objects.create(name='prov-org')

    def _commit(self, sha, repo='org/repo', files=None):
        return CodeChange.objects.create(
            organisation=self.org, provider='github', project_id=repo, commit_sha=sha, commit_message='m',
            author_name='dev', timestamp=self.now - timedelta(hours=1), branch='main',
            diff_summary={'files': files or []})


class EnvironmentNamesTest(Base):
    def test_canonical_names(self):
        self.assertEqual(canonical_environment('PROD'), 'production')
        self.assertEqual(canonical_environment('stg'), 'staging')
        self.assertEqual(canonical_environment('dev'), 'development')
        self.assertEqual(canonical_environment(' QA '), 'qa')

    def test_a_qa_deploy_is_recorded_and_found_by_a_qa_batch(self):
        change = self._commit('a' * 40)
        DeploymentService.create_deployment(change, 'qa', deployed_at=self.now - timedelta(minutes=5))
        found = DeploymentService.get_deployments_for_batch(
            environment='QA', start_time=self.now - timedelta(hours=1), end_time=self.now,
            organisation_id=self.org.id)
        self.assertEqual([c.commit_sha for c in found], ['a' * 40])

    def test_a_prod_batch_finds_production_deploys(self):
        change = self._commit('b' * 40)
        DeploymentService.create_deployment(change, 'production', deployed_at=self.now - timedelta(minutes=5))
        found = DeploymentService.get_deployments_for_batch(
            environment='prod', start_time=self.now - timedelta(hours=1), end_time=self.now,
            organisation_id=self.org.id)
        self.assertEqual(len(found), 1)


class FailedPipelineTest(Base):
    def _window(self):
        changes = DeploymentService.get_deployments_for_batch(
            environment='production', start_time=self.now - timedelta(hours=1), end_time=self.now,
            organisation_id=self.org.id, only_successful=False)
        return CodeChangeService.prepare_changes_for_ai(changes, environment='production')

    def test_a_failed_pipeline_is_not_presented_as_a_deploy(self):
        change = self._commit('c' * 40)
        Deployment.objects.create(code_change=change, environment='production', status='failed',
                                  deployed_at=self.now - timedelta(minutes=5))
        out = self._window()[0]
        self.assertNotIn('deployed_to', out)
        self.assertNotIn('deployed_at', out)
        self.assertEqual(out['pipeline_status'], 'failed')

    def test_failed_then_successful_counts_as_deployed_at_the_success(self):
        change = self._commit('d' * 40)
        Deployment.objects.create(code_change=change, environment='production', status='failed',
                                  deployed_at=self.now - timedelta(minutes=20))
        ok = Deployment.objects.create(code_change=change, environment='production', status='success',
                                       deployed_at=self.now - timedelta(minutes=5))
        out = self._window()[0]
        self.assertEqual(out['deployed_at'], ok.deployed_at.isoformat())
        self.assertNotIn('pipeline_status', out)

    def test_the_prompt_says_not_deployed(self):
        from ai_model.diff_selection import build_code_changes_section
        change = self._commit('e' * 40)
        Deployment.objects.create(code_change=change, environment='production', status='failed',
                                  deployed_at=self.now - timedelta(minutes=5))
        section = build_code_changes_section(self._window(), [])
        self.assertIn('NOT deployed: pipeline failed', section)


class BindingDiffsTest(Base):
    def setUp(self):
        super().setUp()
        project = Project.objects.create(name='p', organisation=self.org)
        svc = ProjectService.objects.create(project=project, name='api')
        gh = ProviderIntegration.objects.create(organisation=self.org, name='GH', provider_type='github')
        self.binding = SCMBinding.objects.create(project_service=svc, integration=gh, repository_id='org/repo')

    def test_a_webhook_commit_gets_its_diff_through_the_binding_provider(self):
        from providers.tasks import fetch_binding_commit_diffs
        change = self._commit('f' * 40, files=[{'path': 'config/app.yaml'}])
        provider = MagicMock()
        provider.get_commit_diff.return_value = {
            'files': [{'path': 'config/app.yaml', 'diff_preview': '-timeout: 30\n+timeout: 3'}],
            'total_additions': 1, 'total_deletions': 1}
        with patch.object(SCMBinding, 'get_provider', return_value=provider):
            result = fetch_binding_commit_diffs.run(self.binding.pk, [change.pk])
        self.assertEqual(result['fetched'], 1)
        change.refresh_from_db()
        self.assertTrue(change.diff_fetched)
        self.assertIn('+timeout: 3', change.diff_summary['files'][0]['diff_preview'])

    def test_an_empty_diff_keeps_the_push_file_list(self):
        from providers.tasks import fetch_binding_commit_diffs
        change = self._commit('1' * 40, files=[{'path': 'config/app.yaml'}])
        provider = MagicMock()
        provider.get_commit_diff.return_value = {'files': [], 'total_additions': 0, 'total_deletions': 0}
        with patch.object(SCMBinding, 'get_provider', return_value=provider):
            fetch_binding_commit_diffs.run(self.binding.pk, [change.pk])
        change.refresh_from_db()
        self.assertFalse(change.diff_fetched)
        self.assertEqual(change.diff_summary['files'][0]['path'], 'config/app.yaml')

    def test_another_repositorys_commit_is_not_fetched_with_this_binding(self):
        from providers.tasks import fetch_binding_commit_diffs
        other = self._commit('2' * 40, repo='org/other')
        provider = MagicMock()
        with patch.object(SCMBinding, 'get_provider', return_value=provider):
            fetch_binding_commit_diffs.run(self.binding.pk, [other.pk])
        provider.get_commit_diff.assert_not_called()

    def test_the_scm_webhook_queues_the_diff_fetch(self):
        from providers.webhook_service import WebhookService
        provider = MagicMock()
        provider.parse_webhook_payload.return_value = [{
            'sha': '3' * 40, 'message': 'tune timeout', 'author_name': 'dev', 'author_email': 'd@x',
            'timestamp': self.now.isoformat(), 'branch': 'main', 'files_modified': ['config/app.yaml']}]
        with patch.object(SCMBinding, 'get_provider', return_value=provider), \
                patch('providers.tasks.fetch_binding_commit_diffs.delay') as delay:
            WebhookService.process_scm_payload(self.binding, {}, 'push')
        delay.assert_called_once()
        self.assertEqual(delay.call_args.args[0], self.binding.pk)
