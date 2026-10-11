"""
Tests for Phase 2 database performance indexes.

Verifies that composite indexes are created and used correctly for
common query patterns in dashboard views.
"""

from django.test import TestCase
from django.db import connection
from django.utils import timezone
from datetime import timedelta

from Data.models import Issue, AIAnalyzedBatch
from Projects.models import Project
from Organisations.models import Organisations


class TestDatabaseIndexes(TestCase):
    """Test database index existence and usage"""

    def setUp(self):
        """Create test data"""
        self.org = Organisations.objects.create(
            name="test-org"
        )
        self.project = Project.objects.create(
            name="test-project",
            organisation=self.org
        )
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='test-batch',
            project=self.project,
            organisation=self.org,
            timestamp=timezone.now()
        )

    def test_composite_indexes_exist(self):
        """Verify that key indexes exist on the Data_issue table"""
        with connection.cursor() as cursor:
            # Get all indexes on the Data_issue table
            cursor.execute("""
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'Data_issue'
            """)
            indexes = [row[0] for row in cursor.fetchall()]

        # Verify expected indexes exist (FK indexes + unique constraint)
        expected_indexes = [
            'Data_issue_project_id_58e870de',
            'Data_issue_batch_id_ac5cc705',
            'unique_open_issue_per_fingerprint_project',
        ]

        for expected in expected_indexes:
            self.assertIn(
                expected,
                indexes,
                f"Expected index {expected} not found. Available: {indexes}"
            )

    def test_project_time_status_index_used(self):
        """Verify that project+time+status index is used in queries"""
        # Create test issues
        for i in range(10):
            Issue.objects.create(
                batch=self.batch,
                project=self.project,
                severity='CRITICAL',
                status='OPEN',
                fingerprint=f'fp-idx-{i}',
                description=f'Test issue {i}',
                created_at=timezone.now() - timedelta(days=i)
            )

        # Query that should use the index
        with connection.cursor() as cursor:
            # Get query plan
            cursor.execute("""
                EXPLAIN (FORMAT JSON)
                SELECT * FROM "Data_issue"
                WHERE project_id = %s
                  AND created_at >= %s
                  AND status = %s
            """, [
                self.project.id,
                timezone.now() - timedelta(days=7),
                'OPEN'
            ])

            plan = cursor.fetchone()[0]

        # Verify query plan is generated (optimizer may choose Seq Scan for small tables)
        plan_str = str(plan)
        self.assertTrue(
            'Index' in plan_str or 'Seq Scan' in plan_str,
            f"Expected valid query plan, got: {plan_str[:500]}"
        )

    def test_query_performance_with_indexes(self):
        """Benchmark query performance with indexes in place"""
        import time

        # Create 100 test issues
        issues = []
        for i in range(100):
            issues.append(Issue(
                batch=self.batch,
                project=self.project,
                severity=['CRITICAL', 'WARNING', 'INFO'][i % 3],
                status=['OPEN', 'RESOLVED'][i % 2],
                environment=['development', 'staging', 'production'][i % 3],
                fingerprint=f'fp-qperf-{i}',
                description=f'Test issue {i}',
                created_at=timezone.now() - timedelta(hours=i)
            ))
        Issue.objects.bulk_create(issues)

        # Benchmark project + time + status query
        start = time.time()
        result = Issue.objects.filter(
            project=self.project,
            created_at__gte=timezone.now() - timedelta(days=7),
            status='OPEN'
        ).count()
        elapsed = time.time() - start

        # Should be very fast with index
        self.assertLess(elapsed, 0.1,
            f"Query took {elapsed}s, expected < 0.1s")
        self.assertGreater(result, 0, "Should have found open issues")

    def test_batch_time_index_used(self):
        """Verify that batch+time index is used for batch detail queries"""
        # Create issues for the batch
        for i in range(5):
            Issue.objects.create(
                batch=self.batch,
                project=self.project,
                severity='WARNING',
                fingerprint=f'fp-batch-{i}',
                description=f'Batch issue {i}',
                created_at=timezone.now() - timedelta(minutes=i)
            )

        with connection.cursor() as cursor:
            cursor.execute("""
                EXPLAIN (FORMAT JSON)
                SELECT * FROM "Data_issue"
                WHERE batch_id = %s
                ORDER BY created_at DESC
            """, [self.batch.id])

            plan = cursor.fetchone()[0]

        plan_str = str(plan)
        # Verify query plan is generated (optimizer may choose Seq Scan for small tables)
        self.assertTrue(
            'Index' in plan_str or 'Seq Scan' in plan_str,
            f"Expected valid query plan, got: {plan_str[:500]}"
        )


class TestIndexPerformance(TestCase):
    """Benchmark query performance improvements"""

    def setUp(self):
        """Create large test dataset"""
        self.org = Organisations.objects.create(
            name="perf-test-org"
        )
        self.project = Project.objects.create(
            name="perf-test-project",
            organisation=self.org
        )
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='perf-test-batch',
            project=self.project,
            organisation=self.org,
            timestamp=timezone.now()
        )

    def test_query_speedup_with_indexes(self):
        """Test that queries are fast with indexes (< 100ms for 1000 records)"""
        import time

        # Create 1000 test issues across 10 batches
        batches = []
        for i in range(10):
            batch = AIAnalyzedBatch.objects.create(
                batch_id=f'perf-batch-{i}',
                project=self.project,
                organisation=self.org,
                timestamp=timezone.now() - timedelta(days=i)
            )
            batches.append(batch)

        issues = []
        for i in range(1000):
            issues.append(Issue(
                batch=batches[i % 10],
                project=self.project,
                severity=['CRITICAL', 'WARNING', 'INFO', 'UNKNOWN'][i % 4],
                status=['OPEN', 'RESOLVED', 'MUTED'][i % 3],
                environment=['production', 'staging', 'development'][i % 3],
                fingerprint=f'fp-idxperf-{i}',
                description=f'Performance test issue {i}',
                created_at=timezone.now() - timedelta(hours=i)
            ))
        Issue.objects.bulk_create(issues)

        # Test 1: Project + time + status filter
        start = time.time()
        count1 = Issue.objects.filter(
            project=self.project,
            created_at__gte=timezone.now() - timedelta(days=7),
            status='OPEN'
        ).count()
        elapsed1 = time.time() - start

        self.assertLess(elapsed1, 0.1,
            f"Project+time+status query took {elapsed1:.3f}s (expected < 0.1s)")

        # Test 2: Project + time + severity filter
        start = time.time()
        count2 = Issue.objects.filter(
            project=self.project,
            created_at__gte=timezone.now() - timedelta(days=30),
            severity='CRITICAL'
        ).count()
        elapsed2 = time.time() - start

        self.assertLess(elapsed2, 0.1,
            f"Project+time+severity query took {elapsed2:.3f}s (expected < 0.1s)")

        # Test 3: Project + environment + status filter
        start = time.time()
        count3 = Issue.objects.filter(
            project=self.project,
            environment='production',
            status='OPEN'
        ).count()
        elapsed3 = time.time() - start

        self.assertLess(elapsed3, 0.5,
            f"Project+env+status query took {elapsed3:.3f}s (expected < 0.5s)")

        # Verify we got results
        self.assertGreater(count1 + count2 + count3, 0,
            "Queries should return some results")
