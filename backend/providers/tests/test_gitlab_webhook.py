"""
Tests for GitLab CI/CD webhook handler.

Verifies that:
- Push events dispatch Celery tasks
- Pipeline events create Pipeline records with legacy fields
- Build events trigger log retrieval
- parse_pipeline_event produces correct normalized format
- Unhandled event types return appropriate message
- Failed pipelines create deployment records
"""

import json
from unittest.mock import MagicMock, Mock, patch

from django.test import SimpleTestCase


def _make_request(payload):
    """Create a mock request with the given payload as JSON body."""
    request = Mock()
    request.body = json.dumps(payload).encode('utf-8')
    request.data = payload
    return request


class TestParsePipelineEvent(SimpleTestCase):
    """Test that parse_pipeline_event correctly normalizes GitLab payloads."""

    @patch('providers.gitlab_webhook.detect_environment_with_source',
            return_value=('production', 'branch'))
    def test_normalizes_pipeline_payload(self, mock_detect_env):
        from providers.gitlab_webhook import GitLabCICDWebhookHandler

        handler = GitLabCICDWebhookHandler()

        payload = {
            'object_kind': 'pipeline',
            'object_attributes': {
                'id': 12345,
                'status': 'success',
                'ref': 'main',
                'sha': 'abc123def456',
                'source': 'push',
                'tag': False,
                'url': 'https://gitlab.com/org/repo/-/pipelines/12345',
            },
            'project': {'id': 999},
            'builds': [
                {
                    'id': 101,
                    'name': 'test-job',
                    'stage': 'test',
                    'status': 'success',
                    'duration': 45.2,
                },
                {
                    'id': 102,
                    'name': 'deploy-job',
                    'stage': 'deploy',
                    'status': 'success',
                    'duration': 120.0,
                },
            ],
        }

        result = handler.parse_pipeline_event(payload)

        self.assertEqual(result['pipeline_id'], '12345')
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['branch'], 'main')
        self.assertEqual(result['commit_shas'], ['abc123def456'])
        self.assertEqual(result['environment'], 'production')
        self.assertEqual(result['project_id'], '999')
        self.assertEqual(len(result['jobs']), 2)
        self.assertEqual(result['jobs'][0]['name'], 'test-job')
        self.assertEqual(result['jobs'][0]['stage'], 'test')
        self.assertEqual(result['jobs'][1]['name'], 'deploy-job')
        self.assertEqual(result['jobs'][1]['stage'], 'deploy')
        self.assertIn('metadata', result)
        mock_detect_env.assert_called_once_with(
            branch='main', job_name='deploy-job', project_id='999',
        )


class TestPushEvent(SimpleTestCase):
    """Test push event handling."""

    @patch('providers.tasks.process_push_event')
    def test_dispatches_celery_task(self, mock_task):
        from providers.gitlab_webhook import GitLabCICDWebhookHandler

        handler = GitLabCICDWebhookHandler()

        payload = {
            'object_kind': 'push',
            'project': {'id': 42},
            'ref': 'refs/heads/main',
            'commits': [
                {'id': 'sha1', 'message': 'first commit'},
                {'id': 'sha2', 'message': 'second commit'},
            ],
        }

        response = handler._handle_push_event(payload)

        mock_task.delay.assert_called_once_with(
            project_id='42',
            commits_data=payload['commits'],
            branch='main',
        )
        self.assertIn('Processing 2 commits', response.data['message'])
        self.assertEqual(response.data['project_id'], 42)
        self.assertEqual(response.data['branch'], 'main')

    @patch('providers.tasks.process_push_event')
    def test_push_no_commits_returns_message(self, mock_task):
        from providers.gitlab_webhook import GitLabCICDWebhookHandler

        handler = GitLabCICDWebhookHandler()

        payload = {
            'object_kind': 'push',
            'project': {'id': 42},
            'ref': 'refs/heads/main',
            'commits': [],
        }

        response = handler._handle_push_event(payload)

        mock_task.delay.assert_not_called()
        self.assertIn('no commits found', response.data['message'])


class TestBuildEvent(SimpleTestCase):
    """Test build/job event handling."""

    @patch('providers.tasks.retrieve_gitlab_job_logs')
    @patch('providers.models.GitlabProject.objects')
    def test_retrieves_logs(self, mock_gp_objects, mock_task):
        from providers.gitlab_webhook import GitLabCICDWebhookHandler

        mock_gp_objects.filter.return_value.first.return_value = None
        handler = GitLabCICDWebhookHandler()

        payload = {
            'object_kind': 'build',
            'build_status': 'failed',
            'project_id': '42',
            'build_id': 101,
            'build_name': 'test-job',
            'pipeline_id': '999',
            'ref': 'main',
            'build_duration': 30.5,
            'user': {'username': 'dev'},
        }

        response = handler._handle_build_event(payload)

        mock_task.delay.assert_called_once_with(
            '42', '999', 'main', 101, 'test-job', 'failed', 30.5, 'dev',
        )
        self.assertEqual(response.data['message'], 'Logs retrieval initiated for job.')

    def test_skips_pending_jobs(self):
        from providers.gitlab_webhook import GitLabCICDWebhookHandler

        handler = GitLabCICDWebhookHandler()

        for status in ('pending', 'running', 'created'):
            payload = {'object_kind': 'build', 'build_status': status}
            response = handler._handle_build_event(payload)
            self.assertIn('not for a handled event type', response.data['message'])


class TestPipelineEvent(SimpleTestCase):
    """Test pipeline event handling."""

    @patch('providers.gitlab_webhook.GitLabCICDWebhookHandler._store_cicd_logs')
    @patch('providers.gitlab_webhook.GitLabCICDWebhookHandler._create_deployments')
    @patch('providers.gitlab_webhook.GitLabCICDWebhookHandler._create_pipeline_record')
    @patch('providers.gitlab_webhook.detect_environment_with_source',
            return_value=('staging', 'branch'))
    def test_creates_records(self, mock_detect, mock_create_pipeline, mock_create_deploy, mock_store_logs):
        from providers.gitlab_webhook import GitLabCICDWebhookHandler

        mock_pipeline = Mock()
        mock_create_pipeline.return_value = mock_pipeline

        handler = GitLabCICDWebhookHandler()

        payload = {
            'object_kind': 'pipeline',
            'object_attributes': {
                'id': 555,
                'status': 'success',
                'ref': 'staging',
                'sha': 'abc123',
            },
            'project': {'id': 42},
            'builds': [],
        }

        response = handler._handle_pipeline_event(payload)

        mock_create_pipeline.assert_called_once()
        mock_create_deploy.assert_called_once()
        mock_store_logs.assert_called_once()
        self.assertEqual(response.data['message'], 'pipeline processed')

    @patch('providers.gitlab_webhook.GitLabCICDWebhookHandler._store_cicd_logs')
    @patch('providers.gitlab_webhook.GitLabCICDWebhookHandler._create_deployments')
    @patch('providers.gitlab_webhook.GitLabCICDWebhookHandler._create_pipeline_record')
    @patch('providers.gitlab_webhook.detect_environment_with_source',
            return_value=('production', 'branch'))
    def test_failed_pipeline_creates_deployments(self, mock_detect, mock_create_pipeline, mock_create_deploy, mock_store_logs):
        from providers.gitlab_webhook import GitLabCICDWebhookHandler

        mock_pipeline = Mock()
        mock_create_pipeline.return_value = mock_pipeline

        handler = GitLabCICDWebhookHandler()

        payload = {
            'object_kind': 'pipeline',
            'object_attributes': {
                'id': 556,
                'status': 'failed',
                'ref': 'main',
                'sha': 'def456',
            },
            'project': {'id': 42},
            'builds': [{'id': 1, 'name': 'deploy', 'stage': 'deploy', 'status': 'failed', 'duration': 10}],
        }

        handler._handle_pipeline_event(payload)

        # Failed is a terminal status → deployments should be created
        mock_create_deploy.assert_called_once()
        # Verify the normalized data passed to _create_deployments has 'failed' status
        normalized_arg = mock_create_deploy.call_args[0][0]
        self.assertEqual(normalized_arg['status'], 'failed')

    @patch('providers.gitlab_webhook.GitLabCICDWebhookHandler._store_cicd_logs')
    @patch('providers.gitlab_webhook.GitLabCICDWebhookHandler._create_deployments')
    @patch('providers.gitlab_webhook.GitLabCICDWebhookHandler._create_pipeline_record')
    @patch('providers.gitlab_webhook.detect_environment_with_source',
            return_value=('development', 'branch'))
    def test_running_pipeline_skips_deployments(self, mock_detect, mock_create_pipeline, mock_create_deploy, mock_store_logs):
        from providers.gitlab_webhook import GitLabCICDWebhookHandler

        mock_create_pipeline.return_value = Mock()
        handler = GitLabCICDWebhookHandler()

        payload = {
            'object_kind': 'pipeline',
            'object_attributes': {
                'id': 557,
                'status': 'running',
                'ref': 'feature-x',
                'sha': 'ghi789',
            },
            'project': {'id': 42},
            'builds': [],
        }

        handler._handle_pipeline_event(payload)

        # Running is not terminal → no deployments
        mock_create_deploy.assert_not_called()


class TestUnhandledEvent(SimpleTestCase):
    """Test unhandled event type routing."""

    def test_returns_unhandled_message(self):
        from providers.gitlab_webhook import GitLabCICDWebhookHandler

        handler = GitLabCICDWebhookHandler()
        handler.validate_request = Mock(return_value=True)
        request = _make_request({'object_kind': 'note'})

        response = handler.post(request)

        self.assertIn('not for a handled event type', response.data['message'])

    def test_routes_push_event(self):
        """Verify post() routes push events correctly."""
        from providers.gitlab_webhook import GitLabCICDWebhookHandler

        handler = GitLabCICDWebhookHandler()
        handler.validate_request = Mock(return_value=True)
        handler._handle_push_event = Mock(return_value=Mock(data={'message': 'ok'}))

        request = _make_request({
            'object_kind': 'push',
            'project': {'id': 1},
            'commits': [],
            'ref': 'refs/heads/main',
        })

        handler.post(request)

        handler._handle_push_event.assert_called_once()
