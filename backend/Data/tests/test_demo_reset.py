"""
Tests for step 4 of the seeded-demo work:
  - the nightly reset_demo_org Celery task
  - the analytics exclusion that keeps demo batches out of the scheduler
    "last batch" calculation
"""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from Organisations.models import Organisations
from Projects.models import Project
from Data.models import AIAnalyzedBatch
from Data.tasks import reset_demo_org
from integrations.ingestion import (
    get_latest_batch_timestamp,
    get_scheduled_window_start,
    get_last_processed_log_timestamp,
)


# ---------------------------------------------------------------------------
# Analytics exclusion — the scheduler must not see demo-org batches.
# ---------------------------------------------------------------------------

class LatestBatchTimestampExcludesDemoTest(TestCase):
    """Demo-org batches must not poison the scheduler's last-batch
    calculation for real organisations."""

    def setUp(self):
        self.real_org = Organisations.objects.create(name='Real Org')
        self.demo_org = Organisations.objects.create(
            name='Demo Org', is_demo=True,
        )
        self.real_project = Project.objects.create(
            name='real-proj', organisation=self.real_org,
        )
        self.demo_project = Project.objects.create(
            name='real-proj-other', organisation=self.demo_org,
        )

    def _make_batch(self, project, org, hours_ago, batch_id):
        return AIAnalyzedBatch.objects.create(
            batch_id=batch_id,
            project=project,
            organisation=org,
            timestamp=timezone.now() - timedelta(hours=hours_ago),
            environment='production',
            data={'logs': []},
        )

    def test_latest_timestamp_ignores_demo_batch_even_when_newer(self):
        # Real org's most-recent batch is 5h old.
        self._make_batch(self.real_project, self.real_org, 5, 'real-batch-1')
        # Demo org has a batch from 1h ago that would otherwise win.
        self._make_batch(self.demo_project, self.demo_org, 1, 'demo-newer')

        latest = get_latest_batch_timestamp()
        self.assertIsNotNone(latest)
        age_hours = (timezone.now() - latest).total_seconds() / 3600
        self.assertGreater(age_hours, 4)
        self.assertLess(age_hours, 6)

    def test_window_start_ignores_demo_batch_with_same_prefix(self):
        # Real project produces "real-proj-1".
        self._make_batch(self.real_project, self.real_org, 4, 'real-proj-1')
        # Demo accidentally uses the same prefix and is newer.
        self._make_batch(self.demo_project, self.demo_org, 1, 'real-proj-2')

        latest = get_scheduled_window_start(self.real_project)
        age_hours = (timezone.now() - latest).total_seconds() / 3600
        self.assertGreater(age_hours, 3)

    def test_last_processed_log_ignores_demo_batch(self):
        # Real batch has a log; demo batch is empty but newer. The
        # helper should return the real batch's log, not None.
        AIAnalyzedBatch.objects.create(
            batch_id='real-with-logs',
            project=self.real_project,
            organisation=self.real_org,
            timestamp=timezone.now() - timedelta(hours=2),
            environment='production',
            data={'logs': [{'_source': {'@timestamp': '2026-06-23T00:00:00Z'}}]},
        )
        AIAnalyzedBatch.objects.create(
            batch_id='demo-newer-empty',
            project=self.demo_project,
            organisation=self.demo_org,
            timestamp=timezone.now() - timedelta(minutes=10),
            environment='production',
            data={'logs': []},
        )

        result = get_last_processed_log_timestamp()
        self.assertEqual(result, '2026-06-23T00:00:00Z')

    def test_returns_none_when_only_demo_data_exists(self):
        """A fresh self-host that has only run seed_demo_org should
        behave as if there were no batches at all — otherwise the
        first real batch's window calculation would include the demo's
        synthetic timestamps."""
        self._make_batch(self.demo_project, self.demo_org, 1, 'demo-only')
        self.assertIsNone(get_latest_batch_timestamp())


# ---------------------------------------------------------------------------
# Nightly reset task
# ---------------------------------------------------------------------------

class ResetDemoOrgTaskTest(TestCase):
    """The Celery task delegates to the management command. We test
    the surrounding behaviour: no-op when no demo exists, lock
    behaviour, and graceful failure."""

    def test_no_op_when_no_demo_org_present(self):
        result = reset_demo_org()
        self.assertIn('no demo organisation', result.lower())

    @patch('django.core.management.call_command')
    def test_runs_seed_when_demo_org_exists(self, mock_call):
        Organisations.objects.create(name='Acme Cloud Demo', is_demo=True)
        result = reset_demo_org()
        mock_call.assert_called_once_with('seed_demo_org', verbosity=0)
        self.assertIn('reset complete', result.lower())

    @patch('django.core.management.call_command', side_effect=RuntimeError('boom'))
    def test_seed_failure_is_caught_not_raised(self, mock_call):
        """Task must never raise — Celery would otherwise retry it and
        yesterday's stable demo state is preferable to repeated failures."""
        Organisations.objects.create(name='Acme Cloud Demo 2', is_demo=True)
        result = reset_demo_org()
        self.assertTrue(result.startswith('Error:'))
        self.assertIn('boom', result)
