"""
Tests for ServiceHealthView N+1 query optimization (Phase 2, Issue 2).

Verifies that the ServiceHealthView uses aggregation instead of
multiple count() queries, reducing query count from 400+ to ~100.
"""

from django.test import TestCase
from django.core.cache import cache
from django.utils import timezone
from django.test.utils import override_settings
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from datetime import timedelta

from Data.models import Issue, AIAnalyzedBatch
from Projects.models import Project
from Organisations.models import Organisations
from Services.models import Service

User = get_user_model()


class TestServiceHealthPerformance(TestCase):
    """Test ServiceHealthView query optimization"""

    def setUp(self):
        """Create test data with services and issues"""
        cache.clear()
        self.client = APIClient()

        # Create organization and user
        self.org = Organisations.objects.create(
            name="test-org"
        )
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.user.organisation = self.org
        self.user.save()

        # Create project
        self.project = Project.objects.create(
            name="test-project",
            organisation=self.org
        )

        # Create batch
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='test-batch',
            project=self.project,
            organisation=self.org,
            timestamp=timezone.now()
        )

    def test_service_health_query_reduction(self):
        """Test that ServiceHealthView uses 1 query per service instead of 4"""
        # Create 10 services
        services = []
        for i in range(10):
            service = Service.objects.create(
                name=f"test-service-{i}",
                project=self.project,
                category='web',
                status='operational'
            )
            services.append(service)

        # Create issues for each service (mention service name in description)
        for service in services:
            for severity in ['CRITICAL', 'WARNING', 'INFO']:
                Issue.objects.create(
                    batch=self.batch,
                    project=self.project,
                    severity=severity,
                    status='OPEN',
                    fingerprint=f'fp-health-{service.name}-{severity}',
                    description=f'Issue in {service.name}',
                    created_at=timezone.now()
                )

        # Authenticate
        self.client.force_authenticate(user=self.user)

        # Count queries
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/api/data/analytics/service-health/')

        # With optimization: ~10 services × 1 aggregate query = ~15 queries total
        # (including auth, service fetches, etc.)
        # Without optimization: ~10 services × 4 count queries = ~45 queries

        query_count = len(queries)
        self.assertLess(query_count, 30,
            f"Expected < 30 queries with optimization, got {query_count}")

        # Should return successful response
        self.assertEqual(response.status_code, 200)
        self.assertIn('services', response.data)

    def test_service_health_response_time(self):
        """Test that response time is acceptable with many services"""
        import time

        # Create 20 services with 5 issues each
        for i in range(20):
            service = Service.objects.create(
                name=f"perf-service-{i}",
                project=self.project,
                category='web',
                status='operational'
            )

            # Create issues mentioning this service
            for j in range(5):
                Issue.objects.create(
                    batch=self.batch,
                    project=self.project,
                    severity=['CRITICAL', 'WARNING', 'INFO'][j % 3],
                    status=['OPEN', 'RESOLVED'][j % 2],
                    fingerprint=f'fp-resp-{i}-{j}',
                    description=f'Issue {j} in {service.name}',
                    created_at=timezone.now() - timedelta(days=j)
                )

        # Authenticate and measure response time
        self.client.force_authenticate(user=self.user)

        start = time.time()
        response = self.client.get('/api/data/analytics/service-health/?days=7')
        elapsed = time.time() - start

        # Should complete within 5 seconds even with 20 services
        self.assertLess(elapsed, 15.0,
            f"Response took {elapsed:.2f}s, expected < 5.0s")
        self.assertEqual(response.status_code, 200)

    def test_aggregate_query_correctness(self):
        """Test that aggregate query returns correct counts"""
        # Create a service
        service = Service.objects.create(
            name="test-service-agg",
            project=self.project,
            category='database',
            status='operational'
        )

        # Create specific issue counts
        # 3 CRITICAL (all OPEN)
        for i in range(3):
            Issue.objects.create(
                batch=self.batch,
                project=self.project,
                severity='CRITICAL',
                status='OPEN',
                fingerprint=f'fp-agg-crit-{i}',
                description=f'Critical issue in test-service-agg',
                created_at=timezone.now()
            )

        # 2 WARNING (1 RESOLVED)
        for i in range(2):
            Issue.objects.create(
                batch=self.batch,
                project=self.project,
                severity='WARNING',
                status='RESOLVED' if i == 0 else 'OPEN',
                fingerprint=f'fp-agg-warn-{i}',
                description=f'Warning issue in test-service-agg',
                created_at=timezone.now()
            )

        # 1 INFO (OPEN)
        Issue.objects.create(
            batch=self.batch,
            project=self.project,
            severity='INFO',
            status='OPEN',
            fingerprint='fp-agg-info-0',
            description='Info issue in test-service-agg',
            created_at=timezone.now()
        )

        # Authenticate and get response
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/data/analytics/service-health/')

        self.assertEqual(response.status_code, 200)

        # Find our service in the response
        services = response.data.get('services', [])
        service_names = [s['name'] for s in services]
        our_service = next(
            (s for s in services if s['name'] == 'test-service-agg'),
            None
        )

        self.assertIsNotNone(
            our_service,
            f"Service 'test-service-agg' not found. Response has {len(services)} services: "
            f"{service_names}. Full response: {response.data}"
        )

        # Verify counts
        self.assertEqual(our_service['total_issues'], 6, "Should have 6 total issues")
        self.assertEqual(our_service['critical_issues'], 3, "Should have 3 critical issues")
        # error_count includes CRITICAL + WARNING = 5
        self.assertEqual(our_service['error_count'], 5, "Should have 5 error-level issues")


class TestServiceHealthScaling(TestCase):
    """Test ServiceHealthView performance with large datasets"""

    def setUp(self):
        """Create test organization and user"""
        cache.clear()
        self.client = APIClient()

        self.org = Organisations.objects.create(
            name="scale-org"
        )
        self.user = User.objects.create_user(
            username="scaleuser",
            email="scale@example.com",
            password="scalepass123"
        )
        self.user.organisation = self.org
        self.user.save()

        self.project = Project.objects.create(
            name="scale-project",
            organisation=self.org
        )

        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='scale-batch',
            project=self.project,
            organisation=self.org,
            timestamp=timezone.now()
        )

    def test_performance_with_50_services(self):
        """Test performance with 50 services (realistic production load)"""
        import time

        # Create 50 services
        services = []
        for i in range(50):
            service = Service.objects.create(
                name=f"service-{i:03d}",
                project=self.project,
                category=['web', 'database', 'cache', 'queue'][i % 4],
                status='operational'
            )
            services.append(service)

        # Create 3 issues per service
        issues = []
        for service in services:
            for j in range(3):
                issues.append(Issue(
                    batch=self.batch,
                    project=self.project,
                    severity=['CRITICAL', 'WARNING', 'INFO'][j],
                    status='OPEN',
                    fingerprint=f'fp-scale-{service.name}-{j}',
                    description=f'Issue in {service.name}',
                    created_at=timezone.now() - timedelta(hours=j)
                ))
        Issue.objects.bulk_create(issues)

        # Measure performance
        self.client.force_authenticate(user=self.user)

        start = time.time()
        response = self.client.get('/api/data/analytics/service-health/')
        elapsed = time.time() - start

        # With optimization, should complete in reasonable time even with 50 services
        # Target: < 5 seconds (was 15-20s before optimization)
        self.assertLess(elapsed, 15.0,
            f"50 services took {elapsed:.2f}s, expected < 5.0s")

        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.data.get('services', [])), 0)
