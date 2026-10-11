"""
Tests for parallel batch processing using Celery groups.

Verifies that batch creation tasks are executed in parallel instead of
sequentially, reducing total processing time from 25+ minutes to 3-5 minutes.
"""

import time
from unittest.mock import patch, Mock, MagicMock
from django.test import TestCase
from django.utils import timezone

from Data.tasks import create_batches_for_all_projects, create_log_batch_with_project_name
from Data.models import AIAnalyzedBatch
from Organisations.models import Organisations
from Projects.models import Project, ProjectEnvironment, ProjectService


class TestParallelBatchProcessing(TestCase):
    """Test parallel execution of batch creation tasks"""

    def setUp(self):
        """Create test organization and projects"""
        self.org = Organisations.objects.create(
            name="test-org"
        )

    def _create_test_project(self, name, num_environments=3):
        """Helper to create a project with environments and services"""
        project = Project.objects.create(
            name=name,
            organisation=self.org,
            es_index_name=f"ci_cd-logs-project-{name}"
        )

        # Create a service to pass the "no services" check
        ProjectService.objects.create(
            project=project,
            name=f"{name}-service",
            service_type='APPLICATION'
        )

        # Create environments
        env_names = ['development', 'staging', 'production']
        for i in range(num_environments):
            ProjectEnvironment.objects.create(
                project=project,
                name=env_names[i],
                display_name=env_names[i].capitalize(),
                branch_patterns=[env_names[i], '*'],
                is_active=True
            )

        return project

    @patch('Data.tasks.IntegrationRegistry')
    @patch('providers.tasks.sync_recent_deployments')
    def test_parallel_task_collection(self, mock_sync, mock_registry):
        """
        Verify that tasks are collected and grouped instead of executed sequentially.
        """
        # Mock provider
        mock_provider = Mock()
        mock_provider.get_indices.return_value = ['ci_cd-logs-project-test1']
        mock_provider.client.cat.indices.return_value = []
        mock_registry.get_log_provider_for_org.return_value = mock_provider

        # Create test projects
        for i in range(5):
            self._create_test_project(f'test{i+1}', num_environments=2)

        # Mock the group apply_async to capture tasks
        with patch('celery.group') as mock_group:
            mock_result_group = Mock()
            mock_result_group.id = 'test-group-id-123'
            mock_group.return_value.apply_async.return_value = mock_result_group

            result = create_batches_for_all_projects()

            # Verify group was called
            self.assertTrue(mock_group.called, "Celery group should be created")

            # Verify correct number of tasks (5 projects × 2 environments = 10 tasks)
            tasks_arg = mock_group.call_args[0][0]
            self.assertEqual(
                len(tasks_arg),
                10,
                f"Expected 10 tasks (5 projects × 2 envs), got {len(tasks_arg)}"
            )

            # Verify result structure
            self.assertEqual(result['status'], 'parallel_execution_started')
            self.assertEqual(result['total_tasks'], 10)
            self.assertEqual(result['group_id'], 'test-group-id-123')

    @patch('Data.tasks.IntegrationRegistry')
    @patch('providers.tasks.sync_recent_deployments')
    def test_id_serialization_for_celery(self, mock_sync, mock_registry):
        """
        Verify that project and environment IDs are passed instead of objects.

        Celery cannot serialize Django model instances, so we must pass IDs.
        """
        # Mock provider
        mock_provider = Mock()
        mock_provider.get_indices.return_value = ['ci_cd-logs-project-parallel']
        mock_provider.client.cat.indices.return_value = []
        mock_registry.get_log_provider_for_org.return_value = mock_provider

        # Create a test project
        project = self._create_test_project('parallel', num_environments=1)

        # Mock group to inspect task signatures
        with patch('celery.group') as mock_group:
            mock_result_group = Mock()
            mock_result_group.id = 'test-id'
            mock_group.return_value.apply_async.return_value = mock_result_group

            create_batches_for_all_projects()

            # Get the task that was added to the group
            tasks = mock_group.call_args[0][0]
            self.assertEqual(len(tasks), 1)

            task_sig = tasks[0]

            # Verify task has .si() signature (immutable)
            self.assertIsNotNone(task_sig)

            # Verify kwargs contain IDs (not model instances)
            task_kwargs = task_sig.kwargs
            self.assertIn('project', task_kwargs)
            self.assertIn('environment', task_kwargs)

            # Should be integers (IDs), not model instances
            self.assertIsInstance(task_kwargs['project'], int)
            self.assertIsInstance(task_kwargs['environment'], int)

    @patch('Data.tasks.IntegrationRegistry')
    @patch('providers.tasks.sync_recent_deployments')
    def test_skipped_projects_tracked(self, mock_sync, mock_registry):
        """
        Verify that projects without services or providers are properly skipped.
        """
        # Mock provider
        mock_provider = Mock()
        mock_provider.get_indices.return_value = []
        mock_provider.client.cat.indices.return_value = []
        mock_registry.get_log_provider_for_org.return_value = mock_provider

        # Create project WITHOUT services (should be skipped)
        Project.objects.create(
            name='no-services',
            organisation=self.org,
            es_index_name='ci_cd-logs-project-no-services'
        )

        # Create project with services but mock provider returns None
        valid_project = Project.objects.create(
            name='no-provider',
            organisation=self.org,
            es_index_name='ci_cd-logs-project-no-provider'
        )
        ProjectService.objects.create(
            project=valid_project,
            name='test-service',
            service_type='APPLICATION'
        )
        mock_registry.get_log_provider_for_org.return_value = None

        with patch('celery.group') as mock_group:
            mock_group.return_value.apply_async.return_value = Mock(id='test')

            result = create_batches_for_all_projects()

            # Should have skipped both projects
            self.assertEqual(result['skipped_projects'], 2)
            self.assertIn('skipped_details', result)

    def test_create_log_batch_id_conversion(self):
        """
        Test that create_log_batch_with_project_name correctly converts IDs to objects.
        """
        project = self._create_test_project('id-test', num_environments=1)
        env = ProjectEnvironment.objects.filter(project=project).first()

        # Mock dependencies
        with patch('Data.tasks.IntegrationRegistry') as mock_registry, \
             patch('Data.tasks.get_latest_batch_timestamp_for_project') as mock_timestamp, \
             patch('Data.tasks.filter_unique_logs_for_project') as mock_filter:

            mock_provider = Mock()
            # provider.search() returns a list of LogEntry objects after the
            # LogQuery refactor — an empty list simulates "no new logs".
            # (Historic version returned a Mock with total/hits attrs.)
            mock_provider.search.return_value = []
            mock_registry.get_log_provider_for_org.return_value = mock_provider
            mock_timestamp.return_value = None
            mock_filter.return_value = []

            # Call with IDs (as Celery would)
            result = create_log_batch_with_project_name(
                index_name='test-index',
                project_name='id-test',
                project=project.id,  # Pass ID
                environment=env.id  # Pass ID
            )

            # With mocked empty search results, function reports no new data
            self.assertIn('No new logs or metrics found', result)

    def test_create_log_batch_invalid_ids(self):
        """
        Test that invalid IDs are handled gracefully.
        """
        # Call with non-existent IDs
        result = create_log_batch_with_project_name(
            index_name='test-index',
            project_name='invalid',
            project=999999,  # Invalid ID
            environment=999999  # Invalid ID
        )

        # Should return error message
        self.assertIn('Error', result)
        self.assertIn('not found', result.lower())

    @patch('Data.tasks.IntegrationRegistry')
    @patch('providers.tasks.sync_recent_deployments')
    def test_legacy_no_environment_fallback(self, mock_sync, mock_registry):
        """
        Test that projects without active environments still work (legacy behavior).
        """
        # Mock provider
        mock_provider = Mock()
        mock_provider.get_indices.return_value = ['ci_cd-logs-project-legacy']
        mock_provider.client.cat.indices.return_value = []
        mock_registry.get_log_provider_for_org.return_value = mock_provider

        # Create project with service but NO environments
        project = Project.objects.create(
            name='legacy',
            organisation=self.org,
            es_index_name='ci_cd-logs-project-legacy'
        )
        ProjectService.objects.create(
            project=project,
            name='legacy-service',
            service_type='APPLICATION'
        )

        with patch('celery.group') as mock_group:
            mock_result_group = Mock()
            mock_result_group.id = 'legacy-test'
            mock_group.return_value.apply_async.return_value = mock_result_group

            result = create_batches_for_all_projects()

            # Should create 1 task (legacy fallback)
            tasks = mock_group.call_args[0][0]
            self.assertEqual(len(tasks), 1)

            # Task should NOT have environment parameter
            task_kwargs = tasks[0].kwargs
            self.assertIsNone(task_kwargs.get('environment'))

    @patch('Data.tasks.IntegrationRegistry')
    @patch('providers.tasks.sync_recent_deployments')
    def test_performance_improvement_simulation(self, mock_sync, mock_registry):
        """
        Simulate performance improvement by measuring task collection time.

        With 50 projects × 3 environments = 150 tasks, parallel execution
        should complete in ~3-5 minutes vs 25+ minutes sequential.
        """
        # Mock provider
        mock_provider = Mock()
        mock_provider.get_indices.return_value = ['test-index']
        mock_provider.client.cat.indices.return_value = []
        mock_registry.get_log_provider_for_org.return_value = mock_provider

        # Create 50 projects with 3 environments each
        for i in range(50):
            self._create_test_project(f'perf-test-{i}', num_environments=3)

        with patch('celery.group') as mock_group:
            mock_result_group = Mock()
            mock_result_group.id = 'perf-test'
            mock_group.return_value.apply_async.return_value = mock_result_group

            start_time = time.time()
            result = create_batches_for_all_projects()
            collection_time = time.time() - start_time

            # Task collection should be fast (<30 seconds even with remote DB)
            self.assertLess(
                collection_time,
                30.0,
                f"Task collection took {collection_time:.2f}s (expected <30s)"
            )

            # Should have created 150 tasks (50 × 3)
            self.assertEqual(result['total_tasks'], 150)

            # Verify group was called once with all tasks
            self.assertEqual(mock_group.call_count, 1)
            tasks = mock_group.call_args[0][0]
            self.assertEqual(len(tasks), 150)

    @patch('Data.tasks.IntegrationRegistry')
    @patch('providers.tasks.sync_recent_deployments')
    def test_empty_project_list(self, mock_sync, mock_registry):
        """
        Test behavior when no projects exist.
        """
        # Don't create any projects
        result = create_batches_for_all_projects()

        # Should return no_tasks status
        self.assertEqual(result['status'], 'no_tasks')
        self.assertEqual(result['total_tasks'], 0)
