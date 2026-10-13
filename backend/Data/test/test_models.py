"""
Unit Tests for Data App Models

Tests cover:
- AIAnalyzedBatch model functionality
- Batch ID generation
- Token calculation
- Analysis saving and retrieval
- Issue model functionality
"""

import unittest
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from Data.models import AIAnalyzedBatch, Issue


class TestAIAnalyzedBatch(TestCase):
    """Test cases for AIAnalyzedBatch model."""

    def setUp(self):
        """Set up test batches."""
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='test_batch_001',
            timestamp=timezone.now(),
            issue_count=5,
            logs_analyzed=100,
            data={'logs': ['test log 1', 'test log 2']}
        )

    def test_batch_creation(self):
        """Test batch is created correctly."""
        self.assertEqual(self.batch.batch_id, 'test_batch_001')
        self.assertEqual(self.batch.issue_count, 5)
        self.assertEqual(self.batch.logs_analyzed, 100)
        self.assertIsNotNone(self.batch.created_at)

    def test_generate_batch_id_format(self):
        """Test batch ID generation follows correct format."""
        batch_id = AIAnalyzedBatch.generate_batch_id()
        
        # Should start with "batch_"
        self.assertTrue(batch_id.startswith('batch_'))
        # Should contain date component (YYYYMMDD_HHMMSS)
        self.assertRegex(batch_id, r'batch_\d{8}_\d{6}_[a-f0-9]{4}')

    def test_generate_batch_id_uniqueness(self):
        """Test generated batch IDs are unique."""
        id1 = AIAnalyzedBatch.generate_batch_id()
        id2 = AIAnalyzedBatch.generate_batch_id()
        
        self.assertNotEqual(id1, id2)

    def test_calculate_tokens_from_logs(self):
        """Test token calculation from log messages."""
        self.batch.data = {
            'logs': [
                {'_source': {'message': 'Error message here'}},
                {'_source': {'message': 'Another error occurred'}}
            ]
        }
        self.batch.save()
        
        self.batch.calculate_tokens_from_logs()
        
        # Token count should be roughly message_length / 4
        self.assertGreater(self.batch.token_count, 0)

    def test_calculate_tokens_with_no_logs(self):
        """Test token calculation with empty logs."""
        self.batch.data = {'logs': []}
        self.batch.save()
        
        self.batch.calculate_tokens_from_logs()
        
        self.assertEqual(self.batch.token_count, 0)

    def test_has_analysis_property(self):
        """Test has_analysis property.

        Keyed on ``analyzed_at``, which every persistence path sets. This test
        used to write ``data['ai_analysis']`` and assert the property saw it —
        which passed only because the test wrote the one key nothing in the
        product ever wrote, so it asserted the bug rather than the behaviour.
        """
        self.assertFalse(self.batch.has_analysis)

        self.batch.save_analysis({'correlated_issues': []}, model_name='claude')
        self.batch.refresh_from_db()

        self.assertTrue(self.batch.has_analysis)

    def test_get_analysis_results(self):
        """Test retrieving analysis results.

        Reads back what ``save_analysis`` actually persists. Previously this
        seeded ``data['ai_analysis']`` by hand; no production code path wrote
        that key, so the getter returned ``{}`` for every real batch while the
        test stayed green.
        """
        analysis_data = {
            'summary': 'Critical issues found',
            'correlated_issues': [{'component': 'api', 'title': 'Issue 1'}],
        }
        self.batch.save_analysis(analysis_data, model_name='claude')
        self.batch.refresh_from_db()

        self.assertEqual(self.batch.get_analysis_results(), analysis_data)

    def test_get_analysis_results_empty_before_analysis(self):
        self.assertEqual(self.batch.get_analysis_results(), {})

    def test_save_analysis(self):
        """Test saving analysis to dedicated fields."""
        analysis_text = "Detailed analysis of the batch"
        model_name = "gemini-1.5-pro"
        
        self.batch.save_analysis(analysis_text, model_name)
        
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.analysis_text, analysis_text)
        self.assertEqual(self.batch.model_name, model_name)
        self.assertIsNotNone(self.batch.analyzed_at)

    def test_batch_ordering(self):
        """Test batches are ordered by timestamp descending."""
        batch1 = AIAnalyzedBatch.objects.create(
            batch_id='batch_old',
            timestamp=timezone.now() - timedelta(days=1)
        )
        batch2 = AIAnalyzedBatch.objects.create(
            batch_id='batch_new',
            timestamp=timezone.now()
        )
        
        batches = list(AIAnalyzedBatch.objects.all())
        
        # Newest batch should be first
        self.assertEqual(batches[0].batch_id, 'batch_new')


class TestIssue(TestCase):
    """Test cases for Issue model."""

    def setUp(self):
        """Set up test batch and issues."""
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='test_batch_issues',
            timestamp=timezone.now()
        )

    def test_issue_creation(self):
        """Test issue is created correctly."""
        issue = Issue.objects.create(
            batch=self.batch,
            severity='CRITICAL',
            description='Database connection failed',
            recommendation='Check database credentials',
            root_cause='Invalid password'
        )
        
        self.assertEqual(issue.severity, 'CRITICAL')
        self.assertEqual(issue.description, 'Database connection failed')
        self.assertEqual(issue.batch, self.batch)
        self.assertIsNotNone(issue.created_at)

    def test_issue_severity_choices(self):
        """Test all severity choices work."""
        severities = ['CRITICAL', 'WARNING', 'INFO', 'UNKNOWN']
        
        for severity in severities:
            issue = Issue.objects.create(
                batch=self.batch,
                severity=severity,
                description=f'Test {severity} issue'
            )
            self.assertEqual(issue.severity, severity)

    def test_issue_ordering(self):
        """Test issues are ordered by created_at descending."""
        issue1 = Issue.objects.create(
            batch=self.batch,
            severity='CRITICAL',
            description='Old issue'
        )
        
        # Wait a tiny bit to ensure different timestamps
        import time
        time.sleep(0.01)
        
        issue2 = Issue.objects.create(
            batch=self.batch,
            severity='WARNING',
            description='New issue'
        )
        
        issues = list(Issue.objects.all())
        
        # Newest issue should be first
        self.assertEqual(issues[0].description, 'New issue')

    def test_issue_batch_relationship(self):
        """Test reverse relationship from batch to issues."""
        issue1 = Issue.objects.create(
            batch=self.batch,
            severity='CRITICAL',
            description='Issue 1'
        )
        issue2 = Issue.objects.create(
            batch=self.batch,
            severity='WARNING',
            description='Issue 2'
        )
        
        batch_issues = self.batch.issues.all()
        
        self.assertEqual(batch_issues.count(), 2)

    def test_issue_cascade_delete(self):
        """Test issues are deleted when batch is deleted."""
        Issue.objects.create(
            batch=self.batch,
            severity='CRITICAL',
            description='Test issue'
        )
        
        batch_id = self.batch.pk
        self.batch.delete()
        
        # Issues should be deleted
        self.assertEqual(Issue.objects.filter(batch_id=batch_id).count(), 0)


if __name__ == '__main__':
    unittest.main()
