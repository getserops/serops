"""Webhooks act only inside the authenticated binding's organisation.

Security review 2026-11, finding 2: a webhook request is authenticated per
binding (URL binding id + its secret), but the project, repository and commit
ids in the body are written by the sender. Lookups by those ids used to run
across all organisations, so a tenant holding its own webhook secret could
write to another organisation's pipelines, commits and deployments.
"""

import hashlib
import hmac
import json
from datetime import datetime, timezone as _tz
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from Organisations.models import Organisations
from Projects.models import CICDBinding, Project, ProjectService
from providers.code_change_service import CodeChangeService
from providers.models import CodeChange, Deployment, GitlabProject, Pipeline, ProviderIntegration
from providers.tests.signing_client import SigningAPIClient

_T0 = datetime(2026, 11, 1, 12, 0, tzinfo=_tz.utc)


def _tenant(name, provider_type, pipeline_id='', secret='s3cret'):
    org = Organisations.objects.create(name=name)
    project = Project.objects.create(name=f'{name}-proj', organisation=org)
    service = ProjectService.objects.create(project=project, name='api', service_type='application')
    integration = ProviderIntegration.objects.create(
        organisation=org, provider_type=provider_type, name=f'{name}-{provider_type}',
    )
    binding = CICDBinding.objects.create(
        project_service=service, integration=integration, pipeline_id=pipeline_id,
        is_active=True, webhook_secret=secret,
    )
    return org, binding


def _commit(org, sha='abc123def456', project_id='42', message='original'):
    return CodeChange.objects.create(
        organisation=org, provider='github', project_id=project_id, commit_sha=sha,
        commit_message=message, author_name='bob', timestamp=_T0, branch='main',
    )


class GitLabWebhookTenancyTest(TestCase):

    def setUp(self):
        self.victim, _ = _tenant('Victim', 'gitlab', pipeline_id='200', secret='victim-secret')
        self.victim_project = GitlabProject.objects.get(project_id='200')
        self.attacker, self.binding = _tenant('Attacker', 'gitlab', pipeline_id='100', secret='attacker-secret')
        self.client = APIClient()
        self.url = f'/api/webhooks/gitlab/{self.binding.pk}/'

    def _post(self, payload):
        return self.client.post(self.url, data=json.dumps(payload), content_type='application/json',
                                HTTP_X_GITLAB_TOKEN='attacker-secret')

    def test_a_pipeline_event_naming_another_orgs_project_is_rejected(self):
        response = self._post({
            'object_kind': 'pipeline', 'project': {'id': 200},
            'object_attributes': {'id': 9, 'status': 'success', 'ref': 'main', 'sha': 'abc'},
        })

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Pipeline.objects.exists())

    @patch('providers.tasks.process_push_event')
    def test_a_push_event_naming_another_orgs_project_is_rejected(self, task):
        response = self._post({
            'object_kind': 'push', 'project': {'id': 200}, 'ref': 'refs/heads/main',
            'commits': [{'id': 'f' * 40, 'message': 'x'}],
        })

        self.assertEqual(response.status_code, 403)
        task.delay.assert_not_called()

    def test_a_pipeline_event_for_its_own_project_belongs_to_the_bindings_org(self):
        with patch('providers.utils.store_cicd_logs_generic'):
            response = self._post({
                'object_kind': 'pipeline', 'project': {'id': 100},
                'object_attributes': {'id': 9, 'status': 'running', 'ref': 'main', 'sha': 'abc'},
            })

        self.assertEqual(response.status_code, 200)
        pipeline = Pipeline.objects.get()
        self.assertEqual(pipeline.organisation, self.attacker)
        self.assertEqual(pipeline.project, GitlabProject.objects.get(project_id='100'))

    def test_the_push_task_ignores_a_project_outside_the_given_org(self):
        from providers.tasks import process_push_event

        result = process_push_event(
            project_id='200', commits_data=[{'id': 'f' * 40, 'message': 'x'}],
            branch='main', organisation_id=self.attacker.id,
        )

        self.assertEqual(result['status'], 'skipped')
        self.assertFalse(CodeChange.objects.exists())

    def test_the_unbound_legacy_route_is_gone(self):
        response = self.client.post('/api/providers/webhook/', data='{}', content_type='application/json')
        self.assertEqual(response.status_code, 404)


class GitHubWebhookTenancyTest(TestCase):

    def setUp(self):
        self.victim, _ = _tenant('VictimGH', 'github')
        self.victim_commit = _commit(self.victim)
        self.attacker, self.binding = _tenant('AttackerGH', 'github', secret='gh-secret')

    def test_a_successful_run_never_deploys_another_orgs_commit(self):
        body = json.dumps({
            'action': 'completed',
            'workflow_run': {'id': 77, 'name': 'deploy', 'conclusion': 'success',
                             'head_branch': 'main', 'head_sha': 'abc123def456'},
            'repository': {'id': 42, 'full_name': 'victim/repo'},
        }).encode()
        signature = 'sha256=' + hmac.new(b'gh-secret', body, hashlib.sha256).hexdigest()

        with patch('providers.utils.store_cicd_logs_generic'):
            response = APIClient().post(
                f'/api/webhooks/github/{self.binding.pk}/', data=body, content_type='application/json',
                HTTP_X_HUB_SIGNATURE_256=signature, HTTP_X_GITHUB_EVENT='workflow_run',
            )

        self.assertEqual(response.status_code, 200, response.content)
        self.victim_commit.refresh_from_db()
        self.assertIsNone(self.victim_commit.pipeline)
        self.assertFalse(Deployment.objects.filter(code_change=self.victim_commit).exists())


class DeploymentWebhookTenancyTest(TestCase):

    def setUp(self):
        self.victim, _ = _tenant('VictimDep', 'github')
        self.victim_commit = _commit(self.victim)
        self.attacker, self.binding = _tenant('AttackerDep', 'github', secret='dep-secret')

    def test_a_deploy_of_a_sha_another_org_holds_gets_its_own_commit(self):
        response = SigningAPIClient('dep-secret').post(
            f'/api/providers/webhook/deployment/{self.binding.pk}/',
            {'commit_sha': 'abc123def456', 'environment': 'production'},
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(Deployment.objects.filter(code_change=self.victim_commit).exists())
        deployment = Deployment.objects.get()
        self.assertEqual(deployment.code_change.organisation, self.attacker)


class CodeChangeTenancyTest(TestCase):

    def test_the_same_commit_in_two_orgs_is_two_records(self):
        victim = Organisations.objects.create(name='VictimCC')
        attacker = Organisations.objects.create(name='AttackerCC')
        _commit(victim, project_id='shared/repo')

        CodeChangeService.save_commits_from_webhook(
            provider='github', project_id='shared/repo', organisation=attacker,
            commits=[{'sha': 'abc123def456', 'message': 'forged', 'author_name': 'eve',
                      'timestamp': _T0.isoformat(), 'branch': 'main'}],
        )

        self.assertEqual(CodeChange.objects.filter(commit_sha='abc123def456').count(), 2)
        original = CodeChange.objects.get(organisation=victim)
        self.assertEqual(original.commit_message, 'original')

    def test_a_commit_without_an_organisation_is_not_saved(self):
        saved = CodeChangeService.save_commits_from_webhook(
            provider='github', project_id='repo',
            commits=[{'sha': 'abc', 'message': 'x', 'timestamp': _T0.isoformat()}],
        )

        self.assertEqual(saved, [])
        self.assertFalse(CodeChange.objects.exists())
