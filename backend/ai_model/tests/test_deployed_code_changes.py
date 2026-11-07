"""
Commits handed to the correlator carry when they reached the environment.

Review v1.2.13: deployments selected the commits but the summaries only
held the commit time, so the correlator and prompt rule 14 timed the
incident against the commit. Both batch paths now stamp ``deployed_at``.
"""
from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from ai_model.tasks import _deployed_code_changes
from Organisations.models import Organisations
from Projects.models import Project
from providers.code_change_service import CodeChangeService
from providers.deployment_service import DeploymentService
from providers.models import CodeChange, Deployment, GitlabProject, Pipeline


class DeployedCodeChangesTests(TestCase):
    def setUp(self):
        self.now = timezone.now().replace(microsecond=0)
        self.org = Organisations.objects.create(name='deploy-time org')
        self.project = Project.objects.create(name='shop', organisation=self.org)
        repo = GitlabProject.objects.create(
            gitlab_url='https://gitlab.example', username='u', name='shop', project_id='4242',
            access_token='t', organisation=self.org)
        self.pipeline = Pipeline.objects.create(
            organisation=self.org, project=repo, pipeline_id='p1', status='success', branch='main')

    def _commit(self, sha, hours_ago):
        return CodeChange.objects.create(
            organisation=self.org, project_id='4242', commit_sha=sha, commit_message=sha,
            author_name='dev', timestamp=self.now - timedelta(hours=hours_ago), branch='main')

    def _deploy(self, change, minutes_ago, env='production'):
        return Deployment.objects.create(
            code_change=change, environment=env, pipeline=self.pipeline, status='success',
            deployed_at=self.now - timedelta(minutes=minutes_ago))

    def test_a_five_hour_old_commit_is_stamped_with_its_deploy_ten_minutes_ago(self):
        older = self._commit('a' * 40, hours_ago=6)
        head = self._commit('b' * 40, hours_ago=5)
        deploy = self._deploy(head, minutes_ago=10)

        out = _deployed_code_changes(self.project, 'production', [deploy], self.now)

        by_sha = {c['sha']: c for c in out}
        self.assertEqual(set(by_sha), {'aaaaaaaa', 'bbbbbbbb'})
        for c in out:
            self.assertEqual(c['deployed_at'], deploy.deployed_at.isoformat())
            self.assertEqual(c['deployed_to'], 'production')
        self.assertEqual(by_sha['aaaaaaaa']['timestamp'], older.timestamp.isoformat())

    def test_each_commit_gets_the_deploy_that_first_shipped_it(self):
        first = self._commit('c' * 40, hours_ago=5)
        second = self._commit('d' * 40, hours_ago=1)
        d1 = self._deploy(first, minutes_ago=200)
        d2 = self._deploy(second, minutes_ago=10)

        out = {c['sha']: c for c in _deployed_code_changes(self.project, 'production', [d2, d1], self.now)}

        self.assertEqual(out['cccccccc']['deployed_at'], d1.deployed_at.isoformat())
        self.assertEqual(out['dddddddd']['deployed_at'], d2.deployed_at.isoformat())

    def test_the_deploy_stamping_adds_no_per_commit_queries(self):
        head = self._commit('e' * 40, hours_ago=5)
        for i in range(5):
            self._commit(f'{i}' * 40, hours_ago=5.5 + i * 0.1)
        deploy = self._deploy(head, minutes_ago=10)
        with CaptureQueriesContext(connection) as few:
            _deployed_code_changes(self.project, 'production', [deploy], self.now)
        head2 = self._commit('f' * 40, hours_ago=0.5)
        deploy2 = self._deploy(head2, minutes_ago=5)
        for i in range(5):
            self._commit(f'{i}f' * 20, hours_ago=0.6 + i * 0.01)
        with CaptureQueriesContext(connection) as many:
            _deployed_code_changes(self.project, 'production', [deploy2], self.now)
        self.assertEqual(len(few), len(many))

    def test_batch_creation_stamps_the_deploy_to_the_batch_environment(self):
        change = self._commit('9' * 40, hours_ago=5)
        self._deploy(change, minutes_ago=40, env='staging')
        prod = self._deploy(change, minutes_ago=10)

        changes = DeploymentService.get_deployments_for_batch(
            environment='production', start_time=self.now - timedelta(hours=1), end_time=self.now,
            organisation_id=self.org.id, only_successful=False)
        out = CodeChangeService.prepare_changes_for_ai(changes, environment='production')

        self.assertEqual(out[0]['deployed_at'], prod.deployed_at.isoformat())
        self.assertEqual(out[0]['deployed_to'], 'production')

    def test_a_summary_without_deployment_info_has_no_deploy_fields(self):
        summary = self._commit('8' * 40, hours_ago=1).get_summary_for_ai()
        self.assertNotIn('deployed_at', summary)
        self.assertNotIn('deployed_to', summary)
