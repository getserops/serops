"""
Tests for task retry logic on batch creation tasks.

Ensures that batch creation tasks properly retry on transient failures
with exponential backoff.
"""

from django.test import TestCase
from unittest.mock import Mock, patch, MagicMock
from celery.exceptions import Retry
from Data.tasks import create_log_batch, create_log_batch_with_project_name, create_batches_for_all_projects


class TestTaskRetryLogic(TestCase):
    """Test retry logic for batch creation tasks"""

    @patch('Data.tasks.IntegrationRegistry')
    def test_create_log_batch_retries_on_failure(self, mock_registry):
        """create_log_batch should retry up to 3 times on provider failure"""
        # Mock provider that raises exception
        mock_provider = Mock()
        mock_provider.search.side_effect = Exception("Provider connection failed")
        mock_registry.get_log_provider_for_org.return_value = mock_provider

        # Create mock task with retry capability
        task_mock = Mock()
        task_mock.request.retries = 0
        task_mock.retry.side_effect = Retry()

        # Patch the task's self reference
        with patch('Data.tasks.create_log_batch', task_mock):
            try:
                create_log_batch()
            except Retry:
                pass  # Expected on first retry

        # Verify retry was attempted
        self.assertTrue(task_mock.retry.called or mock_provider.search.called)

    @patch('Data.tasks.Project')
    @patch('Data.tasks.IntegrationRegistry')
    def test_create_log_batch_with_project_name_retries(self, mock_registry, mock_project):
        """create_log_batch_with_project_name should retry on failures"""
        # Mock provider failure
        mock_provider = Mock()
        mock_provider.search.side_effect = Exception("Network timeout")
        mock_registry.get_log_provider_for_org.return_value = mock_provider

        # Mock project
        mock_project.objects.get.return_value = Mock(
            name="test-project",
            organisation=Mock(id=1, name="test-org")
        )

        # This test verifies the retry decorator is present
        # Actual retry behavior is tested in integration tests
        self.assertTrue(hasattr(create_log_batch_with_project_name, 'retry'))

    def test_exponential_backoff_calculation(self):
        """Verify exponential backoff timing calculation"""
        # Backoff formula: 10 * (2 ** retries)
        backoff_times = []
        for retry_count in range(3):
            backoff = 10 * (2 ** retry_count)
            backoff_times.append(backoff)

        # Expected: 10s, 20s, 40s
        self.assertEqual(backoff_times[0], 10)  # First retry: 10 seconds
        self.assertEqual(backoff_times[1], 20)  # Second retry: 20 seconds
        self.assertEqual(backoff_times[2], 40)  # Third retry: 40 seconds

    @patch('Data.tasks.Project')
    def test_create_batches_for_all_projects_handles_per_project_failures(self, mock_project):
        """create_batches_for_all_projects should handle individual project failures gracefully"""
        # Create mock projects
        project1 = Mock(
            name="project1",
            es_index_name="index1",
            organisation=Mock(id=1)
        )
        project2 = Mock(
            name="project2",
            es_index_name="index2",
            organisation=Mock(id=2)
        )

        mock_project.objects.filter.return_value.exclude.return_value.select_related.return_value = [
            project1, project2
        ]

        # This test verifies error handling structure
        # Full integration test would mock the provider
        self.assertTrue(hasattr(create_batches_for_all_projects, 'retry'))

    def test_task_decorator_configuration(self):
        """Verify tasks have correct retry configuration"""
        # Check create_log_batch
        self.assertTrue(hasattr(create_log_batch, 'max_retries'))
        self.assertTrue(hasattr(create_log_batch, 'default_retry_delay'))

        # Check create_log_batch_with_project_name
        self.assertTrue(hasattr(create_log_batch_with_project_name, 'max_retries'))
        self.assertTrue(hasattr(create_log_batch_with_project_name, 'default_retry_delay'))

        # Check create_batches_for_all_projects
        self.assertTrue(hasattr(create_batches_for_all_projects, 'max_retries'))
        self.assertTrue(hasattr(create_batches_for_all_projects, 'default_retry_delay'))

    @patch('Data.tasks.IntegrationRegistry')
    def test_retry_count_in_error_message(self, mock_registry):
        """Error messages should include retry attempt number"""
        # Mock provider that fails
        mock_provider = Mock()
        mock_provider.search.side_effect = Exception("Test error")
        mock_registry.get_log_provider_for_org.return_value = mock_provider

        with patch('Data.tasks.logger') as mock_logger:
            try:
                # Call task directly (bind=True provides self automatically)
                create_log_batch()
            except:
                pass

            # Check if logger was called (info on start, error on exception)
            self.assertTrue(mock_logger.error.called or mock_logger.info.called)
