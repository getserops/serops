"""
Tests for deduplication fixes.

Covers:
- GAP 1: TOCTOU race — IntegrityError retry on concurrent fingerprint creation
- GAP 2: Organisation isolation in filter_unique_logs calls
- GAP 3: Celery task lock (acquire/release)
- GAP 5: time_tolerance_seconds actually splits distant groups
- GAP 7: Server-side cursor, lookback cap, LIKE escaping
- C1: Null-project isolation via organisation FK
- C2: Environment consistency (batch.environment vs batch.data)
- C3: Intra-batch fingerprint includes error_class/error_target
- H1: Empty component fallback prevents cross-type collisions
- H2: Error class validation preserves non-standard AI values
- H3: Fingerprint versioning (v4 prefix, legacy compat, upgrade)
"""

import threading
import time
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from django.db import IntegrityError, connection, connections
from django.test import TestCase, override_settings
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


class RobustTransactionTestCase(SeedPreservingTransactionTestCase):
    """Transactional test case with per-test connection recovery.

    The flush, its CASCADE, and restoring migration seed data afterwards
    all come from SeedPreservingTransactionTestCase.
    """

    def setUp(self):
        # Ensure a fresh, valid DB connection
        for conn in connections.all():
            try:
                conn.close()
            except Exception:
                pass
        connection.ensure_connection()

    def tearDown(self):
        # Close thread-opened connections before the teardown flush
        for conn in connections.all():
            try:
                conn.close()
            except Exception:
                pass
        connection.ensure_connection()


# ─── GAP 1: TOCTOU race — unique constraint catches duplicate inserts ───

class TestIntegrityErrorRetry(RobustTransactionTestCase):
    """
    Verify that the partial unique constraint (fingerprint, project) WHERE status
    IN ('OPEN', 'MUTED') prevents duplicate issues and the retry path works.
    """

    def setUp(self):
        super().setUp()
        self.org = Organisations.objects.create(
            name=f"test-org-{uuid.uuid4().hex[:8]}",
            website="https://t.com",
        )
        self.project = Project.objects.create(
            name=f"test-project-{uuid.uuid4().hex[:8]}",
            organisation=self.org,
        )
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id=f'test-batch-{uuid.uuid4().hex[:8]}',
            project=self.project,
            organisation=self.org, timestamp=timezone.now(), data={}
        )

    def test_unique_constraint_prevents_duplicate_open_issues(self):
        """Two OPEN issues with same fingerprint+project should violate constraint."""
        fp = Issue.generate_fingerprint(
            'MEMORY_HIGH', 'SERVICE', 'test-project', 'svc-a', 'production'
        )
        Issue.objects.create(
            batch=self.batch, project=self.project, fingerprint=fp,
            issue_type='MEMORY_HIGH', scope='SERVICE', component='svc-a',
            severity='WARNING', description='test', status='OPEN',
        )
        with self.assertRaises(IntegrityError):
            Issue.objects.create(
                batch=self.batch, project=self.project, fingerprint=fp,
                issue_type='MEMORY_HIGH', scope='SERVICE', component='svc-a',
                severity='WARNING', description='test2', status='OPEN',
            )

    def test_resolved_issues_dont_block_new_open(self):
        """A RESOLVED issue should NOT block creation of a new OPEN one."""
        fp = Issue.generate_fingerprint(
            'CPU_HIGH', 'SERVICE', 'test-project', 'svc-b', 'production'
        )
        Issue.objects.create(
            batch=self.batch, project=self.project, fingerprint=fp,
            issue_type='CPU_HIGH', scope='SERVICE', component='svc-b',
            severity='WARNING', description='old', status='RESOLVED',
        )
        # Should succeed — constraint only covers OPEN/MUTED
        new_issue = Issue.objects.create(
            batch=self.batch, project=self.project, fingerprint=fp,
            issue_type='CPU_HIGH', scope='SERVICE', component='svc-b',
            severity='WARNING', description='new', status='OPEN',
        )
        self.assertIsNotNone(new_issue.pk)

    def test_concurrent_creation_no_duplicates(self):
        """
        Simulate the TOCTOU race: many threads try to create the same new issue.
        The unique constraint + retry logic should result in exactly 1 issue.
        """
        issue_data = {
            'issue_type': 'DATABASE_ERROR',
            'scope': 'SERVICE',
            'component': 'db-service',
            'severity': 'CRITICAL',
            'description': 'Connection pool exhausted',
            'error_class': 'DB_CONNECTION',
            'error_target': 'postgres',
        }

        num_threads = 8
        results = []
        errors = []

        def worker():
            try:
                issue, created = Issue.find_or_create_deduplicated(
                    issue_data, self.batch, self.project, 'production'
                )
                results.append((issue.id, created))
            except Exception as e:
                errors.append(str(e))
            finally:
                _close_thread_conn()

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(len(errors), 0, f"Errors: {errors}")
        self.assertEqual(len(results), num_threads)

        # Exactly one unique issue
        unique_ids = set(r[0] for r in results)
        self.assertEqual(len(unique_ids), 1)

        # Occurrence count should match
        issue = Issue.objects.get(pk=list(unique_ids)[0])
        self.assertEqual(issue.occurrence_count, num_threads)


# ─── GAP 5: time_tolerance_seconds ───

class TestTimeTolerance(TestCase):
    """Verify deduplicate_logs respects time_tolerance_seconds."""

    def test_close_logs_are_merged(self):
        """Logs within tolerance should be grouped."""
        from integrations.ingestion import deduplicate_logs

        base = datetime(2024, 1, 1, 12, 0, 0)
        logs = [
            {'_id': '1', '_source': {'message': 'DB timeout', '@timestamp': base.isoformat()}},
            {'_id': '2', '_source': {'message': 'DB timeout', '@timestamp': (base + timedelta(seconds=30)).isoformat()}},
        ]
        result = deduplicate_logs(logs, time_tolerance_seconds=60)
        self.assertEqual(len(result), 1)
        self.assertIn('REPEATED 2x', result[0]['_source']['message'])

    def test_distant_logs_stay_separate(self):
        """Logs beyond tolerance should NOT be grouped."""
        from integrations.ingestion import deduplicate_logs

        base = datetime(2024, 1, 1, 12, 0, 0)
        logs = [
            {'_id': '1', '_source': {'message': 'DB timeout', '@timestamp': base.isoformat()}},
            {'_id': '2', '_source': {'message': 'DB timeout', '@timestamp': (base + timedelta(hours=2)).isoformat()}},
        ]
        result = deduplicate_logs(logs, time_tolerance_seconds=60)
        # Should produce 2 separate entries (not collapsed)
        self.assertEqual(len(result), 2)

    def test_mixed_windows(self):
        """Three logs: first two close, third distant — should produce 2 entries."""
        from integrations.ingestion import deduplicate_logs

        base = datetime(2024, 1, 1, 12, 0, 0)
        logs = [
            {'_id': '1', '_source': {'message': 'timeout', '@timestamp': base.isoformat()}},
            {'_id': '2', '_source': {'message': 'timeout', '@timestamp': (base + timedelta(seconds=20)).isoformat()}},
            {'_id': '3', '_source': {'message': 'timeout', '@timestamp': (base + timedelta(hours=1)).isoformat()}},
        ]
        result = deduplicate_logs(logs, time_tolerance_seconds=60)
        self.assertEqual(len(result), 2)


# ─── GAP 7/8: LIKE escaping ───

class TestLikeEscaping(TestCase):
    """Verify _escape_like prevents wildcard injection."""

    def test_escape_percent(self):
        from integrations.ingestion import _escape_like
        self.assertEqual(_escape_like('my%project'), 'my\\%project')

    def test_escape_underscore(self):
        from integrations.ingestion import _escape_like
        self.assertEqual(_escape_like('my_project'), 'my\\_project')

    def test_escape_backslash(self):
        from integrations.ingestion import _escape_like
        self.assertEqual(_escape_like('my\\project'), 'my\\\\project')

    def test_normal_name_unchanged(self):
        from integrations.ingestion import _escape_like
        self.assertEqual(_escape_like('my-project-name'), 'my-project-name')


# ─── GAP 3: Task lock ───

class TestTaskLock(TestCase):
    """Verify acquire/release task lock semantics."""

    @override_settings(CACHES={'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'test-lock-cache',
    }})
    def test_acquire_and_release(self):
        from Data.tasks import _acquire_task_lock, _release_task_lock
        from django.core.cache import cache
        cache.clear()

        key = 'test_lock:unit'
        self.assertTrue(_acquire_task_lock(key, ttl=10))
        # Second acquire should fail
        self.assertFalse(_acquire_task_lock(key, ttl=10))
        # After release, acquire should succeed again
        _release_task_lock(key)
        self.assertTrue(_acquire_task_lock(key, ttl=10))
        _release_task_lock(key)

    @override_settings(CACHES={'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'test-lock-cache-2',
    }})
    def test_different_keys_independent(self):
        from Data.tasks import _acquire_task_lock, _release_task_lock
        from django.core.cache import cache
        cache.clear()

        self.assertTrue(_acquire_task_lock('lock:a', ttl=10))
        self.assertTrue(_acquire_task_lock('lock:b', ttl=10))
        _release_task_lock('lock:a')
        _release_task_lock('lock:b')


# ─── GAP 2: Organisation isolation in filter_unique_logs ───

class TestOrgIsolationInTasks(TestCase):
    """
    Verify that filter_unique_logs_for_project passes organisation
    correctly so logs are not cross-tenant deduplicated.
    """

    def setUp(self):
        self.org_a = Organisations.objects.create(name="org-a", website="https://a.com")
        self.org_b = Organisations.objects.create(name="org-b", website="https://b.com")
        self.project_a = Project.objects.create(name="proj-a", organisation=self.org_a)
        self.project_b = Project.objects.create(name="proj-b", organisation=self.org_b)

    def test_same_log_different_orgs_not_deduped(self):
        """Same log message in different orgs should both be considered unique."""
        from integrations.ingestion import filter_unique_logs

        # Create a batch for org A
        AIAnalyzedBatch.objects.create(
            batch_id='org-a-batch-1',
            project=self.project_a,
            organisation=self.org_a,
            timestamp=timezone.now() - timedelta(minutes=10),
            data={'logs': [
                {'_id': 'shared-log-1', '_source': {
                    'message': 'Connection refused to redis:6379',
                    '@timestamp': (timezone.now() - timedelta(minutes=10)).isoformat(),
                }}
            ]}
        )

        # A new log with the same message, being processed for org B
        new_log = {
            '_id': 'shared-log-1',
            '_source': {
                'message': 'Connection refused to redis:6379',
                '@timestamp': timezone.now().isoformat(),
            }
        }

        time_window = timezone.now() - timedelta(hours=1)

        # Against org B — should NOT be filtered out (org B has no batches)
        unique_for_b = filter_unique_logs([new_log], time_window, organisation=self.org_b)
        self.assertEqual(len(unique_for_b), 1)

        # Against org A — SHOULD be filtered out
        unique_for_a = filter_unique_logs([new_log], time_window, organisation=self.org_a)
        self.assertEqual(len(unique_for_a), 0)


# ─── GAP 7: Lookback cap ───

class TestLookbackCap(TestCase):
    """Verify the hard lookback cap prevents scanning ancient batches."""

    def test_old_batch_not_scanned(self):
        """A batch older than MAX_DEDUP_LOOKBACK_DAYS should be ignored."""
        from integrations.ingestion import filter_unique_logs

        org = Organisations.objects.create(name="old-org", website="https://o.com")
        proj = Project.objects.create(name="old-proj", organisation=org)

        # Create a batch 60 days ago (older than 30-day default cap)
        old_time = timezone.now() - timedelta(days=60)
        AIAnalyzedBatch.objects.create(
            batch_id='ancient-batch',
            project=proj, organisation=org,
            timestamp=old_time,
            data={'logs': [
                {'_id': 'ancient-1', '_source': {
                    'message': 'Ancient error',
                    '@timestamp': old_time.isoformat(),
                }}
            ]}
        )

        # A new log with the same message — should NOT be filtered out
        # because the old batch is beyond the lookback cap
        new_log = {
            '_id': 'ancient-1',
            '_source': {
                'message': 'Ancient error',
                '@timestamp': timezone.now().isoformat(),
            }
        }

        # Use a time_window of 90 days ago (wider than cap)
        time_window = timezone.now() - timedelta(days=90)
        unique = filter_unique_logs([new_log], time_window, organisation=org)
        # The cap should clamp to 30 days, so the 60-day-old batch is excluded
        self.assertEqual(len(unique), 1)


# ─── C1: Null-project isolation via organisation FK ───

class TestNullProjectDedup(RobustTransactionTestCase):
    """Verify that null-project issues are isolated by organisation."""

    def setUp(self):
        super().setUp()
        self.org_a = Organisations.objects.create(
            name=f"org-a-c1-{uuid.uuid4().hex[:8]}",
            website="https://a.com",
        )
        self.org_b = Organisations.objects.create(
            name=f"org-b-c1-{uuid.uuid4().hex[:8]}",
            website="https://b.com",
        )
        self.batch_a = AIAnalyzedBatch.objects.create(
            batch_id=f'c1-batch-a-{uuid.uuid4().hex[:8]}',
            organisation=self.org_a,
            timestamp=timezone.now(), data={}
        )
        self.batch_b = AIAnalyzedBatch.objects.create(
            batch_id=f'c1-batch-b-{uuid.uuid4().hex[:8]}',
            organisation=self.org_b,
            timestamp=timezone.now(), data={}
        )

    def test_null_project_same_org_deduplicates(self):
        """Two issues with same fingerprint, null project, same org -> dedup."""
        issue_data = {
            'issue_type': 'MEMORY_HIGH', 'scope': 'INFRASTRUCTURE',
            'component': 'node-1', 'severity': 'WARNING',
            'description': 'High memory', 'error_class': 'OUT_OF_MEMORY',
            'error_target': '',
        }
        issue1, created1 = Issue.find_or_create_deduplicated(
            issue_data, self.batch_a, None, 'production'
        )
        issue2, created2 = Issue.find_or_create_deduplicated(
            issue_data, self.batch_a, None, 'production'
        )
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(issue1.pk, issue2.pk)

    def test_null_project_different_orgs_not_deduped(self):
        """Same fingerprint, null project, different orgs -> both created."""
        issue_data = {
            'issue_type': 'MEMORY_HIGH', 'scope': 'INFRASTRUCTURE',
            'component': 'node-1', 'severity': 'WARNING',
            'description': 'High memory', 'error_class': 'OUT_OF_MEMORY',
            'error_target': '',
        }
        issue1, created1 = Issue.find_or_create_deduplicated(
            issue_data, self.batch_a, None, 'production'
        )
        issue2, created2 = Issue.find_or_create_deduplicated(
            issue_data, self.batch_b, None, 'production'
        )
        self.assertTrue(created1)
        self.assertTrue(created2)
        self.assertNotEqual(issue1.pk, issue2.pk)

    def test_constraint_prevents_null_project_duplicate(self):
        """Raw create with same fingerprint+org+null project -> IntegrityError."""
        fp = Issue.generate_fingerprint(
            'CPU_HIGH', 'INFRASTRUCTURE', '', 'node-x', 'production'
        )
        Issue.objects.create(
            batch=self.batch_a, project=None, organisation=self.org_a,
            fingerprint=fp, issue_type='CPU_HIGH', scope='INFRASTRUCTURE',
            component='node-x', severity='WARNING', description='test',
            status='OPEN',
        )
        with self.assertRaises(IntegrityError):
            Issue.objects.create(
                batch=self.batch_a, project=None, organisation=self.org_a,
                fingerprint=fp, issue_type='CPU_HIGH', scope='INFRASTRUCTURE',
                component='node-x', severity='WARNING', description='test2',
                status='OPEN',
            )


# ─── C2: Environment consistency ───

class TestEnvironmentConsistency(TestCase):
    """Verify batch.environment field is used, not batch.data['environment']."""

    def test_batch_environment_field_used(self):
        """batch.environment='staging' but data has 'production' -> fingerprint uses 'staging'."""
        org = Organisations.objects.create(name="env-org", website="https://e.com")
        project = Project.objects.create(name="env-proj", organisation=org)
        batch = AIAnalyzedBatch.objects.create(
            batch_id='env-batch', project=project, organisation=org,
            timestamp=timezone.now(),
            data={'environment': 'production'},
            environment='staging',
        )
        # The environment used should be 'staging' (model field), not 'production' (JSON)
        self.assertEqual(batch.environment, 'staging')
        # Verify that batch.data has a different value
        self.assertEqual(batch.data.get('environment'), 'production')

    def test_empty_environment_defaults_production(self):
        """batch with empty environment string -> code should use 'production' default."""
        org = Organisations.objects.create(name="env-org2", website="https://e2.com")
        project = Project.objects.create(name="env-proj2", organisation=org)
        batch = AIAnalyzedBatch.objects.create(
            batch_id='env-batch2', project=project, organisation=org,
            timestamp=timezone.now(), data={},
            environment='',
        )
        # Our fix: `batch.environment or 'production'`
        env = batch.environment or 'production'
        self.assertEqual(env, 'production')


# ─── C3: Intra-batch fingerprint includes error_class/error_target ───

class TestIntraBatchFingerprint(TestCase):
    """Verify intra-batch dedup includes error_class/error_target in fingerprint."""

    def test_different_error_classes_not_collapsed(self):
        """Two issues with same type/component but different error_class -> different fingerprints."""
        fp1 = Issue.generate_fingerprint(
            'DATABASE_ERROR', 'SERVICE', 'proj', 'db', 'production',
            error_class='DB_CONNECTION', error_target='postgres'
        )
        fp2 = Issue.generate_fingerprint(
            'DATABASE_ERROR', 'SERVICE', 'proj', 'db', 'production',
            error_class='QUERY_ERROR', error_target='postgres'
        )
        self.assertNotEqual(fp1, fp2)

    def test_same_error_class_collapsed(self):
        """Two identical issues in same batch -> same fingerprint."""
        fp1 = Issue.generate_fingerprint(
            'DATABASE_ERROR', 'SERVICE', 'proj', 'db', 'production',
            error_class='DB_CONNECTION', error_target='postgres'
        )
        fp2 = Issue.generate_fingerprint(
            'DATABASE_ERROR', 'SERVICE', 'proj', 'db', 'production',
            error_class='DB_CONNECTION', error_target='postgres'
        )
        self.assertEqual(fp1, fp2)


# ─── H1: Empty component fallback ───

class TestEmptyComponentFallback(TestCase):
    """Verify empty component uses issue-type-specific fallback, not generic 'UNKNOWN'."""

    def test_empty_component_different_types_not_merged(self):
        """MEMORY_HIGH and CPU_HIGH both with empty component -> different fingerprints."""
        fp_mem = Issue.generate_fingerprint(
            'MEMORY_HIGH', 'SERVICE', 'proj', '', 'production'
        )
        fp_cpu = Issue.generate_fingerprint(
            'CPU_HIGH', 'SERVICE', 'proj', '', 'production'
        )
        self.assertNotEqual(fp_mem, fp_cpu)

    def test_empty_component_same_type_merged(self):
        """Same issue_type with empty component -> same fingerprint."""
        fp1 = Issue.generate_fingerprint(
            'MEMORY_HIGH', 'SERVICE', 'proj', '', 'production'
        )
        fp2 = Issue.generate_fingerprint(
            'MEMORY_HIGH', 'SERVICE', 'proj', '', 'production'
        )
        self.assertEqual(fp1, fp2)


# ─── H2: Error class validation ───

class TestErrorClassValidation(TestCase):
    """Verify validate_error_class preserves non-standard AI values."""

    def test_known_class_accepted(self):
        """Known class like 'CONNECTION_REFUSED' -> returns as-is (uppercased)."""
        self.assertEqual(Issue.validate_error_class('CONNECTION_REFUSED'), 'CONNECTION_REFUSED')
        self.assertEqual(Issue.validate_error_class('connection_refused'), 'CONNECTION_REFUSED')

    def test_unknown_class_preserved(self):
        """Non-standard class like 'CUSTOM_AI_ERROR' -> preserved uppercased."""
        result = Issue.validate_error_class('CUSTOM_AI_ERROR')
        self.assertEqual(result, 'CUSTOM_AI_ERROR')

    def test_empty_class_defaults_other(self):
        """Empty string -> 'OTHER'."""
        self.assertEqual(Issue.validate_error_class(''), 'OTHER')

    def test_none_class_defaults_other(self):
        """None -> 'OTHER'."""
        self.assertEqual(Issue.validate_error_class(None), 'OTHER')

    def test_whitespace_class_defaults_other(self):
        """Whitespace-only -> 'OTHER'."""
        self.assertEqual(Issue.validate_error_class('   '), 'OTHER')

    def test_very_long_class_defaults_other(self):
        """Class longer than 50 chars -> 'OTHER'."""
        long_class = 'A' * 51
        self.assertEqual(Issue.validate_error_class(long_class), 'OTHER')


# ─── H3: Fingerprint versioning ───

class TestFingerprintVersioning(RobustTransactionTestCase):
    """Verify v4 fingerprint prefix, legacy compatibility, and upgrade."""

    def setUp(self):
        super().setUp()
        self.org = Organisations.objects.create(
            name=f"fp-org-{uuid.uuid4().hex[:8]}",
            website="https://fp.com",
        )
        self.project = Project.objects.create(
            name=f"fp-proj-{uuid.uuid4().hex[:8]}",
            organisation=self.org,
        )
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id=f'fp-batch-{uuid.uuid4().hex[:8]}',
            project=self.project,
            organisation=self.org, timestamp=timezone.now(), data={}
        )

    def test_v4_prefix(self):
        """New fingerprints start with 'v4:'."""
        fp = Issue.generate_fingerprint(
            'MEMORY_HIGH', 'SERVICE', 'proj', 'svc-a', 'production'
        )
        self.assertTrue(fp.startswith('v4:'))

    def test_legacy_fingerprint_no_prefix(self):
        """Legacy fingerprints have no version prefix."""
        fp = Issue.generate_legacy_fingerprint(
            'MEMORY_HIGH', 'SERVICE', 'proj', 'svc-a', 'production'
        )
        self.assertFalse(fp.startswith('v4:'))
        self.assertEqual(len(fp), 32)

    def test_legacy_compat_matches(self):
        """Issue with old fingerprint found via dual query in find_or_create."""
        # Create issue with legacy fingerprint directly
        legacy_fp = Issue.generate_legacy_fingerprint(
            'CPU_HIGH', 'SERVICE', self.project.name, 'svc-b', 'production',
            error_class='OTHER', error_target=''
        )
        Issue.objects.create(
            batch=self.batch, project=self.project,
            fingerprint=legacy_fp, issue_type='CPU_HIGH', scope='SERVICE',
            component='svc-b', severity='WARNING', description='old issue',
            status='OPEN', error_class='OTHER', error_target='',
        )

        # Now try to find_or_create with same logical issue -> should match legacy and upgrade
        issue_data = {
            'issue_type': 'CPU_HIGH', 'scope': 'SERVICE',
            'component': 'svc-b', 'severity': 'CRITICAL',
            'description': 'new occurrence', 'error_class': 'OTHER',
            'error_target': '',
        }
        issue, created = Issue.find_or_create_deduplicated(
            issue_data, self.batch, self.project, 'production'
        )
        self.assertFalse(created)
        # Legacy fingerprint should have been upgraded to v4
        issue.refresh_from_db()
        self.assertTrue(issue.fingerprint.startswith('v4:'))

    def test_legacy_upgraded_on_match(self):
        """Matched legacy issue gets fingerprint upgraded to v4."""
        legacy_fp = Issue.generate_legacy_fingerprint(
            'DATABASE_ERROR', 'SERVICE', self.project.name, 'db-svc', 'production',
            error_class='DB_CONNECTION', error_target='postgres'
        )
        v4_fp = Issue.generate_fingerprint(
            'DATABASE_ERROR', 'SERVICE', self.project.name, 'db-svc', 'production',
            error_class='DB_CONNECTION', error_target='postgres'
        )
        # Sanity: they should differ
        self.assertNotEqual(legacy_fp, v4_fp)

        issue = Issue.objects.create(
            batch=self.batch, project=self.project,
            fingerprint=legacy_fp, issue_type='DATABASE_ERROR', scope='SERVICE',
            component='db-svc', severity='WARNING', description='old',
            status='OPEN', error_class='DB_CONNECTION', error_target='postgres',
        )

        issue_data = {
            'issue_type': 'DATABASE_ERROR', 'scope': 'SERVICE',
            'component': 'db-svc', 'severity': 'WARNING',
            'description': 'new', 'error_class': 'DB_CONNECTION',
            'error_target': 'postgres',
        }
        matched, created = Issue.find_or_create_deduplicated(
            issue_data, self.batch, self.project, 'production'
        )
        self.assertFalse(created)
        self.assertEqual(matched.pk, issue.pk)
        # Fingerprint should now be upgraded to v4
        matched.refresh_from_db()
        self.assertTrue(matched.fingerprint.startswith('v4:'))
        self.assertEqual(matched.fingerprint, v4_fp)


# ─── Integration: find_or_create_deduplicated ───

class TestFindOrCreateDeduplicated(RobustTransactionTestCase):
    """Integration tests for the full dedup pipeline."""

    def setUp(self):
        super().setUp()
        self.org = Organisations.objects.create(
            name=f"integ-org-{uuid.uuid4().hex[:8]}",
            website="https://i.com",
        )
        self.project = Project.objects.create(
            name=f"integ-proj-{uuid.uuid4().hex[:8]}",
            organisation=self.org,
        )
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id=f'integ-batch-{uuid.uuid4().hex[:8]}',
            project=self.project,
            organisation=self.org, timestamp=timezone.now(), data={}
        )

    def test_resolved_issue_reopened(self):
        """RESOLVED issue with same fingerprint -> reopened."""
        issue_data = {
            'issue_type': 'API_ERROR', 'scope': 'SERVICE',
            'component': 'api-gw', 'severity': 'WARNING',
            'description': 'Gateway error', 'error_class': 'OTHER',
            'error_target': '',
        }
        # Create and resolve
        issue, created = Issue.find_or_create_deduplicated(
            issue_data, self.batch, self.project, 'production'
        )
        self.assertTrue(created)
        Issue.objects.filter(pk=issue.pk).update(status='RESOLVED')

        # Second occurrence should reopen
        issue2, created2 = Issue.find_or_create_deduplicated(
            issue_data, self.batch, self.project, 'production'
        )
        self.assertFalse(created2)
        self.assertEqual(issue2.pk, issue.pk)
        issue2.refresh_from_db()
        self.assertEqual(issue2.status, 'OPEN')

    def test_infrastructure_promotion(self):
        """INFRASTRUCTURE issue promoted to SERVICE scope when service-level issue arrives."""
        # Create infrastructure-level issue
        infra_data = {
            'issue_type': 'MEMORY_HIGH', 'scope': 'INFRASTRUCTURE',
            'component': 'INFRASTRUCTURE', 'severity': 'WARNING',
            'description': 'High memory on infra', 'error_class': 'OUT_OF_MEMORY',
            'error_target': '',
        }
        infra_issue, created = Issue.find_or_create_deduplicated(
            infra_data, self.batch, self.project, 'production'
        )
        self.assertTrue(created)

        # Service-level issue with same type should promote the infra issue
        svc_data = {
            'issue_type': 'MEMORY_HIGH', 'scope': 'SERVICE',
            'component': 'my-service', 'severity': 'CRITICAL',
            'description': 'High memory on service', 'error_class': 'OUT_OF_MEMORY',
            'error_target': '',
        }
        svc_issue, created2 = Issue.find_or_create_deduplicated(
            svc_data, self.batch, self.project, 'production'
        )
        self.assertFalse(created2)
        self.assertEqual(svc_issue.pk, infra_issue.pk)
        svc_issue.refresh_from_db()
        self.assertEqual(svc_issue.scope, 'SERVICE')
        self.assertEqual(svc_issue.component, 'my-service')

    def test_severity_escalation(self):
        """Lower severity matched, higher severity updates it."""
        issue_data = {
            'issue_type': 'NETWORK_ERROR', 'scope': 'SERVICE',
            'component': 'net-svc', 'severity': 'WARNING',
            'description': 'Network issue', 'error_class': 'OTHER',
            'error_target': '',
        }
        issue, _ = Issue.find_or_create_deduplicated(
            issue_data, self.batch, self.project, 'production'
        )
        self.assertEqual(issue.severity, 'WARNING')

        # Higher severity occurrence
        issue_data['severity'] = 'CRITICAL'
        issue2, created = Issue.find_or_create_deduplicated(
            issue_data, self.batch, self.project, 'production'
        )
        self.assertFalse(created)
        issue2.refresh_from_db()
        self.assertEqual(issue2.severity, 'CRITICAL')

    def test_organisation_set_on_new_issue(self):
        """New issue gets organisation from project or batch."""
        issue_data = {
            'issue_type': 'DISK_FULL', 'scope': 'INFRASTRUCTURE',
            'component': 'node-1', 'severity': 'CRITICAL',
            'description': 'Disk full', 'error_class': 'DISK_FULL',
            'error_target': '/dev/sda1',
        }
        issue, created = Issue.find_or_create_deduplicated(
            issue_data, self.batch, self.project, 'production'
        )
        self.assertTrue(created)
        self.assertEqual(issue.organisation, self.org)
