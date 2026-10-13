"""
Tests for race condition fix in issue deduplication.

Verifies that concurrent batch processing correctly increments occurrence_count
without lost updates using select_for_update() and F() expressions.
"""

import threading
import time
import uuid
from django.db import connection, connections
from django.utils import timezone

from Data.models import Issue, AIAnalyzedBatch
from Organisations.models import Organisations
from Projects.models import Project
from Utils.testing import SeedPreservingTransactionTestCase


def _close_thread_conn():
    """Close the DB connection for the current thread (avoids leaked sessions)."""
    try:
        connection.close()
    except Exception:
        pass


class TestIssueDeduplicationRaceCondition(SeedPreservingTransactionTestCase):
    """
    Test race conditions in issue deduplication under concurrent access.

    Uses a TransactionTestCase instead of TestCase to allow real database
    transactions (TestCase wraps everything in a transaction, preventing
    isolation testing).
    """

    def setUp(self):
        """Create test organization and project"""
        # Ensure fresh DB connection
        for conn in connections.all():
            conn.close()
        connection.ensure_connection()

        self.org = Organisations.objects.create(
            name=f"race-org-{uuid.uuid4().hex[:8]}",
        )
        self.project = Project.objects.create(
            name=f"race-proj-{uuid.uuid4().hex[:8]}",
            organisation=self.org
        )
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id=f'race-batch-{uuid.uuid4().hex[:8]}',
            project=self.project,
            organisation=self.org,
            timestamp=timezone.now(),
            data={}
        )

    def _run_threaded(self, worker_fn, num_threads, args_list=None):
        """Helper to run worker functions in threads and wait for completion."""
        threads = []
        for i in range(num_threads):
            args = args_list[i] if args_list else ()
            t = threading.Thread(target=worker_fn, args=args)
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=30)

        # Brief pause to let DB connections settle
        time.sleep(0.5)

    def tearDown(self):
        """Close all DB connections to prevent corrupting subsequent tests."""
        # Close all Django-managed connections (including thread-local ones)
        for conn in connections.all():
            try:
                conn.close()
            except Exception:
                pass
        # Brief pause to let the DB server release sessions
        time.sleep(0.5)
        # Re-establish the default connection for the teardown flush
        connection.ensure_connection()

    def test_concurrent_deduplication_no_lost_updates(self):
        """
        Verify that concurrent threads creating the same issue
        results in correct occurrence_count (no lost updates).
        """
        issue_data = {
            'issue_type': 'HIGH_MEMORY_USAGE',
            'scope': 'INFRASTRUCTURE',
            'component': 'backend-service',
            'severity': 'WARNING',
            'description': 'Memory usage above 80%',
            'recommended_action': 'Scale up or investigate memory leak',
            'root_cause': 'High traffic or memory leak',
            'error_class': 'RESOURCE',
            'error_target': 'memory'
        }

        num_threads = 8
        results = []
        errors = []

        def create_issue():
            try:
                issue, created = Issue.find_or_create_deduplicated(
                    issue_data, self.batch, self.project, 'production'
                )
                results.append((issue.id, created))
            except Exception as e:
                errors.append(str(e))
            finally:
                _close_thread_conn()

        self._run_threaded(create_issue, num_threads)

        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")
        self.assertEqual(len(results), num_threads, "Not all threads completed")

        unique_issue_ids = set(r[0] for r in results)
        self.assertEqual(len(unique_issue_ids), 1,
                         f"Expected 1 unique issue, got {len(unique_issue_ids)}")

        issue = Issue.objects.get(pk=list(unique_issue_ids)[0])
        self.assertEqual(issue.occurrence_count, num_threads,
                         f"Expected {num_threads}, got {issue.occurrence_count}. Lost updates!")

        created_count = sum(1 for _, created in results if created)
        self.assertEqual(created_count, 1,
                         f"Expected 1 creation, {created_count} reported")

    def test_concurrent_infrastructure_promotion(self):
        """
        Test race condition during INFRASTRUCTURE promotion.
        """
        infra_data = {
            'issue_type': 'HIGH_CPU_USAGE',
            'scope': 'INFRASTRUCTURE',
            'component': 'INFRASTRUCTURE',
            'severity': 'WARNING',
            'description': 'CPU usage above 90%',
            'error_class': 'RESOURCE',
            'error_target': 'cpu'
        }

        infra_issue, _ = Issue.find_or_create_deduplicated(
            infra_data, self.batch, self.project, 'production'
        )

        num_threads = 5
        results = []

        service_data = {
            'issue_type': 'HIGH_CPU_USAGE',
            'scope': 'SERVICE',
            'component': 'api-service',
            'severity': 'WARNING',
            'description': 'CPU usage above 90%',
            'error_class': 'RESOURCE',
            'error_target': 'cpu'
        }

        def promote_issue():
            try:
                issue, created = Issue.find_or_create_deduplicated(
                    service_data, self.batch, self.project, 'production'
                )
                results.append((issue.id, created, issue.occurrence_count))
            except Exception as e:
                results.append(('error', False, str(e)))
            finally:
                _close_thread_conn()

        self._run_threaded(promote_issue, num_threads)

        unique_ids = set(r[0] for r in results if r[0] != 'error')
        self.assertEqual(len(unique_ids), 1,
                         f"Expected 1 promoted issue, got {len(unique_ids)}")

        promoted_issue = Issue.objects.get(pk=list(unique_ids)[0])
        expected_count = 1 + num_threads
        self.assertEqual(promoted_issue.occurrence_count, expected_count,
                         f"Expected {expected_count}, got {promoted_issue.occurrence_count}")
        self.assertEqual(promoted_issue.component, 'api-service')
        self.assertEqual(promoted_issue.scope, 'SERVICE')

    def test_severity_escalation_race_condition(self):
        """
        Test that severity escalation works correctly under concurrent access.
        """
        initial_data = {
            'issue_type': 'SLOW_RESPONSE',
            'scope': 'SERVICE',
            'component': 'api',
            'severity': 'INFO',
            'error_class': 'PERFORMANCE',
            'error_target': 'latency'
        }

        initial_issue, _ = Issue.find_or_create_deduplicated(
            initial_data, self.batch, self.project, 'production'
        )

        severities = ['WARNING'] * 3 + ['CRITICAL'] * 3
        results = []

        def escalate_severity(severity):
            try:
                data = initial_data.copy()
                data['severity'] = severity
                issue, created = Issue.find_or_create_deduplicated(
                    data, self.batch, self.project, 'production'
                )
                results.append((issue.id, issue.severity))
            except Exception as e:
                results.append(('error', str(e)))
            finally:
                _close_thread_conn()

        self._run_threaded(
            escalate_severity, len(severities),
            args_list=[(sev,) for sev in severities]
        )

        final_issue = Issue.objects.get(pk=initial_issue.pk)
        self.assertEqual(final_issue.severity, 'CRITICAL',
                         "Severity should escalate to CRITICAL")

        expected_count = 1 + len(severities)
        self.assertEqual(final_issue.occurrence_count, expected_count,
                         f"Expected {expected_count}, got {final_issue.occurrence_count}")

    def test_status_reopen_race_condition(self):
        """
        Test that resolved issues are correctly reopened under concurrent access.
        """
        issue_data = {
            'issue_type': 'ERROR_RATE',
            'scope': 'SERVICE',
            'component': 'auth-service',
            'severity': 'WARNING',
            'error_class': 'ERROR',
            'error_target': 'authentication'
        }

        issue, _ = Issue.find_or_create_deduplicated(
            issue_data, self.batch, self.project, 'production'
        )
        issue.status = 'RESOLVED'
        issue.save()

        num_threads = 5
        results = []

        def reopen_issue():
            try:
                reopened, created = Issue.find_or_create_deduplicated(
                    issue_data, self.batch, self.project, 'production'
                )
                results.append((reopened.id, reopened.status))
            except Exception as e:
                results.append(('error', str(e)))
            finally:
                _close_thread_conn()

        self._run_threaded(reopen_issue, num_threads)

        reopened_issue = Issue.objects.get(pk=issue.pk)
        self.assertEqual(reopened_issue.status, 'OPEN')

        expected_count = 1 + num_threads
        self.assertEqual(reopened_issue.occurrence_count, expected_count,
                         f"Expected {expected_count}, got {reopened_issue.occurrence_count}")

    def test_no_deadlock_under_high_contention(self):
        """
        Verify that high contention doesn't cause deadlocks.
        """
        num_issues = 3
        threads_per_issue = 3
        total_threads = num_issues * threads_per_issue

        results = []
        errors = []

        def create_varied_issue(issue_number):
            try:
                issue_data = {
                    'issue_type': f'ISSUE_TYPE_{issue_number}',
                    'scope': 'SERVICE',
                    'component': f'service-{issue_number}',
                    'severity': 'WARNING',
                    'error_class': 'OTHER',
                    'error_target': f'target-{issue_number}'
                }
                issue, created = Issue.find_or_create_deduplicated(
                    issue_data, self.batch, self.project, 'production'
                )
                results.append((issue.id, created))
            except Exception as e:
                errors.append(f"Issue {issue_number}: {str(e)}")
            finally:
                _close_thread_conn()

        args_list = [(issue_num,) for issue_num in range(num_issues)
                     for _ in range(threads_per_issue)]
        self._run_threaded(create_varied_issue, total_threads, args_list=args_list)

        self.assertEqual(len(errors), 0,
                         f"Errors occurred (possible deadlock): {errors}")
        self.assertEqual(len(results), total_threads,
                         f"Only {len(results)}/{total_threads} threads completed")

        unique_issue_ids = set(r[0] for r in results)
        self.assertEqual(len(unique_issue_ids), num_issues,
                         f"Expected {num_issues} unique issues, got {len(unique_issue_ids)}")

        for issue_id in unique_issue_ids:
            issue = Issue.objects.get(pk=issue_id)
            self.assertEqual(issue.occurrence_count, threads_per_issue,
                             f"Issue {issue_id}: count {issue.occurrence_count}, expected {threads_per_issue}")
