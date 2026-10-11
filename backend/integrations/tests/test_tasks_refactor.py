
from django.test import SimpleTestCase, TestCase
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
import dataclasses

from Data.tasks import deduplicate_logs, is_log_matching_environment
from integrations.schemas import LogEntry

class TestTasksRefactor(SimpleTestCase):

    def setUp(self):
        self.timestamp = datetime(2023, 1, 1, 12, 0, 0)
        self.iso_timestamp = self.timestamp.isoformat()
        
    def test_deduplicate_logs_with_log_entries(self):
        """Verify deduplication works with canonical LogEntry objects."""
        ts1 = self.timestamp
        ts2 = self.timestamp + timedelta(seconds=10)
        
        logs = [
            LogEntry(
                timestamp=ts1,
                message="Error connecting to DB",
                level="ERROR",
                raw_id="1",
                labels={'environment': 'prod'}
            ),
            LogEntry(
                timestamp=ts2, 
                message="Error connecting to DB",  # Identical message
                level="ERROR",
                raw_id="2",
                labels={'environment': 'prod'}
            )
        ]
        
        deduped = deduplicate_logs(logs)
        
        self.assertEqual(len(deduped), 1)
        self.assertTrue(deduped[0].deduplicated)
        self.assertEqual(deduped[0].occurrence_count, 2)
        self.assertIn("REPEATED 2x", deduped[0].message)
        
    def test_deduplicate_logs_with_legacy_dicts(self):
        """Verify deduplication works with legacy dictionaries."""
        ts1 = self.iso_timestamp
        ts2 = (self.timestamp + timedelta(seconds=10)).isoformat()
        
        logs = [
            {
                '_id': '1',
                '_source': {
                    '@timestamp': ts1,
                    'message': 'Error connecting to DB',
                    'level': 'ERROR'
                }
            },
            {
                '_id': '2',
                '_source': {
                    '@timestamp': ts2,
                    'message': 'Error connecting to DB',
                    'level': 'ERROR'
                }
            }
        ]
        
        deduped = deduplicate_logs(logs)
        
        self.assertEqual(len(deduped), 1)
        self.assertTrue(deduped[0]['_source']['deduplicated'])
        self.assertEqual(deduped[0]['_source']['occurrence_count'], 2)
        self.assertIn("REPEATED 2x", deduped[0]['_source']['message'])

    def test_is_log_matching_environment(self):
        """Verify environment matching works for both types."""
        # LogEntry
        entry = LogEntry(
            timestamp=self.timestamp, message="test", 
            labels={'environment': 'production'}
        )
        self.assertTrue(is_log_matching_environment(entry, 'production'))
        self.assertFalse(is_log_matching_environment(entry, 'staging'))
        
        # Legacy dict
        legacy = {
            '_source': {
                'environment': 'production'
            }
        }
        self.assertTrue(is_log_matching_environment(legacy, 'production'))
        self.assertFalse(is_log_matching_environment(legacy, 'staging'))

    def test_filter_unique_logs_placeholder(self):
        """filter_unique_logs now uses raw SQL — DB-backed tests live in test_dedup_fixes.py."""
        pass


class TestFilterUniqueLogs(TestCase):
    """DB-backed tests for filter_unique_logs (moved from SimpleTestCase)."""

    def test_filter_unique_logs_hybrid(self):
        """Verify filtering deduplicates against previous batch data."""
        from django.utils import timezone
        from Data.models import AIAnalyzedBatch
        from Data.tasks import filter_unique_logs
        from Organisations.models import Organisations
        from Projects.models import Project

        org = Organisations.objects.create(name="refactor-test-org")
        proj = Project.objects.create(name="refactor-test-proj", organisation=org)

        ts = timezone.now() - timedelta(minutes=10)

        # Create a previous batch containing "Old Error"
        AIAnalyzedBatch.objects.create(
            batch_id='old-batch',
            project=proj, organisation=org,
            timestamp=ts,
            data={'logs': [
                {'_id': 'old1', '_source': {'message': 'Old Error', '@timestamp': ts.isoformat()}}
            ]}
        )

        new_logs = [
            LogEntry(timestamp=ts, message="Old Error", raw_id="old1"),
            LogEntry(
                timestamp=ts + timedelta(seconds=1), message="New Error", raw_id="new1"
            ),
        ]

        time_window = timezone.now() - timedelta(hours=1)
        unique = filter_unique_logs(new_logs, time_window, organisation=org)

        self.assertEqual(len(unique), 1)
        self.assertEqual(unique[0].message, "New Error")
