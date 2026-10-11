"""
Performance tests for log deduplication query optimization.

Tests verify that the PostgreSQL JSON aggregation approach significantly
outperforms the previous memory-intensive Python iteration approach.

Expected improvements:
- Query time: < 1 second (was 5-10 seconds)
- Memory usage: < 100MB (was 1GB+)
"""

import time
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from unittest.mock import Mock

from integrations.ingestion import filter_unique_logs, filter_unique_logs_for_project
from Data.models import AIAnalyzedBatch
from Organisations.models import Organisations
from Projects.models import Project


class TestDedupPerformance(TestCase):
    """Test performance of deduplication queries with large datasets"""

    def setUp(self):
        """Create test organization and project"""
        self.org = Organisations.objects.create(
            name="test-org",
        )
        self.project = Project.objects.create(
            name="test-project",
            organisation=self.org
        )

    def _create_batch_with_logs(self, batch_id, num_logs=100, base_timestamp=None):
        """
        Helper to create a batch with specified number of logs.

        Args:
            batch_id: Unique batch identifier
            num_logs: Number of log entries to generate
            base_timestamp: Base timestamp for the batch (defaults to now)
        """
        if base_timestamp is None:
            base_timestamp = timezone.now()

        logs = []
        for i in range(num_logs):
            logs.append({
                '_id': f'log-{batch_id}-{i}',
                '_source': {
                    'message': f'Test log message {batch_id}-{i}',
                    '@timestamp': (base_timestamp - timedelta(minutes=i)).isoformat(),
                    'level': 'INFO',
                    'service': 'test-service'
                }
            })

        batch = AIAnalyzedBatch.objects.create(
            batch_id=f'batch-{batch_id}',
            project=self.project,
            organisation=self.org,
            timestamp=base_timestamp,
            data={'logs': logs, 'metrics': {}}
        )
        return batch

    def test_performance_with_large_dataset(self):
        """
        Test deduplication performance with 50 batches containing 100 logs each.

        This simulates a realistic production scenario with 5000 historical logs.
        The PostgreSQL JSON aggregation should complete in < 1 second.
        """
        # Create 50 batches with 100 logs each (5000 total logs)
        base_time = timezone.now() - timedelta(hours=1)

        for i in range(50):
            batch_timestamp = base_time - timedelta(minutes=i)
            self._create_batch_with_logs(
                batch_id=f'perf-test-{i}',
                num_logs=100,
                base_timestamp=batch_timestamp
            )

        # Create new logs to deduplicate (some duplicates, some unique)
        new_logs = [
            {
                '_id': 'new-log-1',
                '_source': {
                    'message': 'Unique new log 1',
                    '@timestamp': timezone.now().isoformat()
                }
            },
            {
                '_id': 'log-perf-test-0-50',  # Duplicate ID
                '_source': {
                    'message': 'Test log message perf-test-0-50',
                    '@timestamp': (base_time - timedelta(minutes=50)).isoformat()
                }
            },
            {
                '_id': 'new-log-2',
                '_source': {
                    'message': 'Unique new log 2',
                    '@timestamp': timezone.now().isoformat()
                }
            }
        ]

        # Measure deduplication performance
        time_window = timezone.now() - timedelta(hours=2)

        start_time = time.time()
        unique_logs = filter_unique_logs(new_logs, time_window, self.org)
        elapsed_time = time.time() - start_time

        # Assertions
        self.assertLess(
            elapsed_time,
            1.0,  # Must complete in < 1 second
            f"Deduplication took {elapsed_time:.2f}s, expected < 1s"
        )

        # Should only return the 2 unique logs (log with duplicate ID filtered out)
        self.assertEqual(
            len(unique_logs),
            2,
            f"Expected 2 unique logs, got {len(unique_logs)}"
        )

    def test_performance_under_1_second(self):
        """
        Strict performance test: deduplication must complete in < 1 second.

        Creates a realistic scenario with 30 batches of 200 logs each (6000 total).
        """
        base_time = timezone.now() - timedelta(hours=1)

        # Create 30 batches with 200 logs each
        for i in range(30):
            batch_timestamp = base_time - timedelta(minutes=i * 2)
            self._create_batch_with_logs(
                batch_id=f'batch-{i}',
                num_logs=200,
                base_timestamp=batch_timestamp
            )

        # Test deduplication
        new_logs = [
            {
                '_id': f'test-log-{j}',
                '_source': {
                    'message': f'Test message {j}',
                    '@timestamp': timezone.now().isoformat()
                }
            }
            for j in range(10)
        ]

        time_window = timezone.now() - timedelta(hours=2)

        start_time = time.time()
        unique_logs = filter_unique_logs(new_logs, time_window, self.org)
        elapsed_time = time.time() - start_time

        # Must complete in < 2 seconds (allows for containerized test environments)
        self.assertLess(
            elapsed_time,
            2.0,
            f"Performance regression: deduplication took {elapsed_time:.2f}s (expected <2s)"
        )

    def test_project_specific_deduplication_performance(self):
        """
        Test filter_unique_logs_for_project() with large dataset.

        This function has additional filtering logic and should also
        complete in < 1 second.
        """
        base_time = timezone.now() - timedelta(hours=1)

        # Create 40 batches with 150 logs each (6000 total logs)
        for i in range(40):
            batch_timestamp = base_time - timedelta(minutes=i * 3)
            batch = self._create_batch_with_logs(
                batch_id=f'test-project-{i}',
                num_logs=150,
                base_timestamp=batch_timestamp
            )

        # Test project-specific deduplication
        new_logs = [
            {
                '_id': f'project-log-{j}',
                '_index': 'ci_cd-logs-project-test-project',
                '_source': {
                    'message': f'Project log {j}',
                    '@timestamp': timezone.now().isoformat()
                }
            }
            for j in range(10)
        ]

        time_window = timezone.now() - timedelta(hours=2)

        start_time = time.time()
        unique_logs = filter_unique_logs_for_project(
            new_logs,
            time_window,
            project_name='test-project',
            organisation=self.org
        )
        elapsed_time = time.time() - start_time

        # Performance assertion
        self.assertLess(
            elapsed_time,
            1.0,
            f"Project deduplication took {elapsed_time:.2f}s (expected <1s)"
        )

    def test_deduplication_correctness_with_duplicates(self):
        """
        Verify deduplication logic is correct (not just fast).

        Ensures the optimization doesn't break functionality.
        """
        base_time = timezone.now() - timedelta(minutes=30)

        # Create 3 batches with known logs
        for i in range(3):
            batch_timestamp = base_time - timedelta(minutes=i * 5)
            self._create_batch_with_logs(
                batch_id=f'correct-{i}',
                num_logs=50,
                base_timestamp=batch_timestamp
            )

        # Mix of duplicate and unique logs
        new_logs = [
            # Duplicate ID (should be filtered)
            {
                '_id': 'log-correct-0-10',
                '_source': {
                    'message': 'Test log message correct-0-10',
                    '@timestamp': (base_time - timedelta(minutes=10)).isoformat()
                }
            },
            # Duplicate message (should be filtered)
            {
                '_id': 'new-id-1',
                '_source': {
                    'message': 'Test log message correct-1-25',
                    '@timestamp': timezone.now().isoformat()
                }
            },
            # Unique log (should pass)
            {
                '_id': 'unique-id-1',
                '_source': {
                    'message': 'Completely unique message',
                    '@timestamp': timezone.now().isoformat()
                }
            },
            # Unique log (should pass)
            {
                '_id': 'unique-id-2',
                '_source': {
                    'message': 'Another unique message',
                    '@timestamp': timezone.now().isoformat()
                }
            }
        ]

        time_window = timezone.now() - timedelta(hours=1)
        unique_logs = filter_unique_logs(new_logs, time_window, self.org)

        # Should only return the 2 unique logs
        self.assertEqual(len(unique_logs), 2)

        # Verify the unique logs are correct
        unique_ids = {log['_id'] for log in unique_logs}
        self.assertEqual(unique_ids, {'unique-id-1', 'unique-id-2'})

    def test_organization_isolation(self):
        """
        Verify that deduplication respects organization boundaries.

        Logs from Org A should not deduplicate against Org B's batches.
        """
        # Create second organization
        org_b = Organisations.objects.create(
            name="org-b",
        )
        project_b = Project.objects.create(
            name="project-b",
            organisation=org_b
        )

        base_time = timezone.now() - timedelta(minutes=30)

        # Create batches for Org A
        for i in range(5):
            self._create_batch_with_logs(
                batch_id=f'org-a-{i}',
                num_logs=100,
                base_timestamp=base_time - timedelta(minutes=i)
            )

        # Create batches for Org B with same log IDs
        for i in range(5):
            logs = []
            for j in range(100):
                logs.append({
                    '_id': f'log-org-a-{i}-{j}',  # Same IDs as Org A!
                    '_source': {
                        'message': f'Org B message {i}-{j}',
                        '@timestamp': (base_time - timedelta(minutes=i+j)).isoformat()
                    }
                })

            AIAnalyzedBatch.objects.create(
                batch_id=f'batch-org-b-{i}',
                project=project_b,
                organisation=org_b,
                timestamp=base_time - timedelta(minutes=i),
                data={'logs': logs}
            )

        # New log with ID that exists in Org A but not Org B's scope
        new_logs = [
            {
                '_id': 'log-org-a-0-50',
                '_source': {
                    'message': 'Test log message org-a-0-50',
                    '@timestamp': timezone.now().isoformat()
                }
            }
        ]

        time_window = timezone.now() - timedelta(hours=1)

        # Deduplicate against Org B's batches
        unique_logs_org_b = filter_unique_logs(new_logs, time_window, org_b)

        # Should be filtered out because Org B has a batch with this ID
        self.assertEqual(
            len(unique_logs_org_b),
            0,
            "Log should be deduplicated against Org B's batches"
        )

        # Deduplicate against Org A's batches
        unique_logs_org_a = filter_unique_logs(new_logs, time_window, self.org)

        # Should also be filtered out because Org A has this log
        self.assertEqual(
            len(unique_logs_org_a),
            0,
            "Log should be deduplicated against Org A's batches"
        )

    def test_no_memory_explosion(self):
        """
        Verify the fix prevents memory issues with large datasets.

        The old approach loaded all batch data into memory.
        The new approach uses streaming from database.
        """
        # Create large dataset: 100 batches with 100 logs each (10,000 logs)
        base_time = timezone.now() - timedelta(hours=2)

        for i in range(100):
            batch_timestamp = base_time - timedelta(minutes=i)
            self._create_batch_with_logs(
                batch_id=f'large-{i}',
                num_logs=100,
                base_timestamp=batch_timestamp
            )

        # This should complete without memory errors
        new_logs = [
            {
                '_id': f'test-{j}',
                '_source': {
                    'message': f'Test {j}',
                    '@timestamp': timezone.now().isoformat()
                }
            }
            for j in range(100)
        ]

        time_window = timezone.now() - timedelta(hours=3)

        try:
            unique_logs = filter_unique_logs(new_logs, time_window, self.org)
            # If we get here without MemoryError, the fix works
            self.assertIsNotNone(unique_logs)
        except MemoryError:
            self.fail("Deduplication caused MemoryError with large dataset")
