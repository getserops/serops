"""
Tests for async GitLab job log retrieval.

Verifies that:
- Build events dispatch Celery task (not synchronous call)
- Celery task delegates to gitlab_retrieve_job_logs utility
"""

from unittest.mock import patch, Mock
from django.test import SimpleTestCase


class TestBuildEventDispatchesCeleryTask(SimpleTestCase):
    """Test that _handle_build_event dispatches async task."""

    @patch('providers.tasks.retrieve_gitlab_job_logs')
    @patch('providers.models.GitlabProject.objects')
    def test_build_event_dispatches_celery_task(self, mock_gp_objects, mock_task):
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

        # Should call .delay() (async), not the function directly
        mock_task.delay.assert_called_once_with(
            '42', '999', 'main', 101, 'test-job', 'failed', 30.5, 'dev',
        )
        self.assertEqual(response.data['message'], 'Logs retrieval initiated for job.')

    @patch('providers.tasks.retrieve_gitlab_job_logs')
    @patch('providers.models.GitlabProject.objects')
    def test_build_event_dispatches_for_success_too(self, mock_gp_objects, mock_task):
        from providers.gitlab_webhook import GitLabCICDWebhookHandler

        mock_gp_objects.filter.return_value.first.return_value = None
        handler = GitLabCICDWebhookHandler()

        payload = {
            'object_kind': 'build',
            'build_status': 'success',
            'project_id': '42',
            'build_id': 102,
            'build_name': 'deploy-job',
            'pipeline_id': '999',
            'ref': 'main',
            'build_duration': 60.0,
            'user': {'username': 'dev'},
        }

        handler._handle_build_event(payload)

        mock_task.delay.assert_called_once()


class TestRetrieveGitlabJobLogsTask(SimpleTestCase):
    """Test the Celery task delegates to the utility function."""

    @patch('providers.tasks.gitlab_retrieve_job_logs')
    def test_task_delegates_to_util(self, mock_util_fn):
        from providers.tasks import retrieve_gitlab_job_logs

        mock_util_fn.return_value = "Logs processed"

        # Call the underlying function directly (bypass Celery's bind=True)
        result = retrieve_gitlab_job_logs.run(
            '42', '999', 'main', 101, 'test-job', 'failed', 30.5, 'dev',
        )

        mock_util_fn.assert_called_once_with(
            '42', '999', 'main', 101, 'test-job', 'failed', 30.5, 'dev',
        )
        self.assertEqual(result, "Logs processed")
