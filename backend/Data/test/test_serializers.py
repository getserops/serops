"""
Unit Tests for Data App Serializers

Tests cover:
- AIAnalyzedBatchSerializer
- IssueSerializer
- Serializer validation
- Nested serialization
"""

from django.test import TestCase
from django.utils import timezone
from Data.models import AIAnalyzedBatch, Issue
from Data.serializers import (
    AIAnalyzedBatchSerializer,
    AIAnalyzedBatchListSerializer,
    IssueSerializer
)


class TestIssueSerializer(TestCase):
    """Test cases for IssueSerializer."""

    def setUp(self):
        """Set up test data."""
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='test_batch_001',
            timestamp=timezone.now()
        )
        
        self.issue = Issue.objects.create(
            batch=self.batch,
            severity='CRITICAL',
            description='Test error',
            recommendation='Fix it',
            root_cause='Bad code'
        )

    def test_issue_serialization(self):
        """Test issue serializes correctly."""
        serializer = IssueSerializer(self.issue)
        data = serializer.data
        
        self.assertEqual(data['severity'], 'CRITICAL')
        self.assertEqual(data['description'], 'Test error')
        self.assertEqual(data['recommendation'], 'Fix it')
        self.assertEqual(data['root_cause'], 'Bad code')
        self.assertEqual(data['batch_id_str'], 'test_batch_001')
        self.assertIn('batch_timestamp', data)

    def test_issue_read_only_fields(self):
        """Test batch_id_str and batch_timestamp are read-only."""
        serializer = IssueSerializer(self.issue)
        data = serializer.data
        
        # These should be present
        self.assertIn('batch_id_str', data)
        self.assertIn('batch_timestamp', data)
        
        # But should be derived from batch, not settable

    # === CORRELATION FIELD TESTS ===
    
    def test_has_commit_correlation_with_commit(self):
        """Test has_commit_correlation returns True when commit SHA in root_cause."""
        self.issue.root_cause = 'A recent code change (commit 70f5655b) caused the issue'
        self.issue.save(compute_correlations=True)
        
        serializer = IssueSerializer(self.issue)
        data = serializer.data
        
        self.assertTrue(data['has_commit_correlation'])
        shas = [c.get('sha') if isinstance(c, dict) else c
                for c in data['linked_commits']]
        self.assertEqual(shas, ['70f5655b'])
    
    def test_has_commit_correlation_without_commit(self):
        """Test has_commit_correlation returns False when no commit SHA present."""
        self.issue.root_cause = 'Some issue with no code reference'
        self.issue.save(compute_correlations=True)
        
        serializer = IssueSerializer(self.issue)
        data = serializer.data
        
        self.assertFalse(data['has_commit_correlation'])
        self.assertEqual(data['linked_commits'], [])
    
    def test_commit_extraction_from_recommendation(self):
        """Test commit SHA extracted from recommendation field."""
        self.issue.recommendation = 'Review commit 96b76950 to fix this issue'
        self.issue.root_cause = 'Unknown cause'
        self.issue.save(compute_correlations=True)
        
        serializer = IssueSerializer(self.issue)
        data = serializer.data
        
        self.assertTrue(data['has_commit_correlation'])
        # linked_commits entries are dicts carrying provider context now,
        # not bare SHA strings.
        self.assertIn('96b76950', [c['sha'] for c in data['linked_commits']])
    
    def test_multiple_commits_extraction(self):
        """Test multiple commit SHAs are extracted and deduplicated."""
        self.issue.root_cause = 'commit 70f5655b and commit 96b76950 caused issues'
        self.issue.recommendation = 'Revert commit 70f5655b'  # Duplicate
        self.issue.save(compute_correlations=True)
        
        serializer = IssueSerializer(self.issue)
        data = serializer.data
        
        self.assertTrue(data['has_commit_correlation'])
        self.assertEqual(len(data['linked_commits']), 2)
        shas = [c['sha'] for c in data['linked_commits']]
        self.assertIn('70f5655b', shas)
        self.assertIn('96b76950', shas)
    
    def test_has_metric_correlation_memory(self):
        """Test has_metric_correlation returns True for memory keywords."""
        self.issue.description = 'Out of memory error in worker process'
        self.issue.save(compute_correlations=True)
        
        serializer = IssueSerializer(self.issue)
        data = serializer.data
        
        self.assertTrue(data['has_metric_correlation'])
    
    def test_has_metric_correlation_cpu(self):
        """Test has_metric_correlation returns True for CPU keywords."""
        self.issue.root_cause = 'High CPU usage caused by infinite loop'
        self.issue.save(compute_correlations=True)
        
        serializer = IssueSerializer(self.issue)
        data = serializer.data
        
        self.assertTrue(data['has_metric_correlation'])
    
    def test_has_metric_correlation_false(self):
        """Test has_metric_correlation returns False when no metric keywords."""
        self.issue.description = 'API authentication failed'
        self.issue.root_cause = 'Invalid API key'
        self.issue.save(compute_correlations=True)
        
        serializer = IssueSerializer(self.issue)
        data = serializer.data
        
        self.assertFalse(data['has_metric_correlation'])
    
    def test_correlation_summary_with_commit_and_metric(self):
        """Test correlation_summary includes both commit and metric info."""
        self.issue.root_cause = 'commit 70f5655b caused memory leak'
        self.issue.description = 'Memory usage at 95%'
        self.issue.save(compute_correlations=True)
        
        serializer = IssueSerializer(self.issue)
        data = serializer.data
        
        summary = data['correlation_summary']
        types = [s['type'] for s in summary]
        
        self.assertIn('commit', types)
        self.assertIn('metric', types)
    
    def test_correlation_summary_empty(self):
        """Test correlation_summary is empty when no correlations."""
        self.issue.root_cause = 'Unknown issue'
        self.issue.description = 'Something went wrong'
        self.issue.save(compute_correlations=True)
        
        serializer = IssueSerializer(self.issue)
        data = serializer.data
        
        self.assertEqual(data['correlation_summary'], [])
    
    def test_correlation_fields_present(self):
        """Test all correlation fields are present in serialized data."""
        serializer = IssueSerializer(self.issue)
        data = serializer.data
        
        self.assertIn('has_commit_correlation', data)
        self.assertIn('has_metric_correlation', data)
        self.assertIn('linked_commits', data)
        self.assertIn('correlation_summary', data)


class TestAIAnalyzedBatchSerializer(TestCase):
    """Test cases for AIAnalyzedBatchSerializer."""

    def setUp(self):
        """Set up test batch with issues."""
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='test_batch_002',
            timestamp=timezone.now(),
            issue_count=2,
            logs_analyzed=50,
            token_count=1000
        )
        
        Issue.objects.create(
            batch=self.batch,
            severity='CRITICAL',
            description='Critical issue'
        )
        Issue.objects.create(
            batch=self.batch,
            severity='WARNING',
            description='Warning issue'
        )

    def test_batch_serialization(self):
        """Test batch serializes with all fields."""
        serializer = AIAnalyzedBatchSerializer(self.batch)
        data = serializer.data
        
        self.assertEqual(data['batch_id'], 'test_batch_002')
        self.assertEqual(data['issue_count'], 2)
        self.assertEqual(data['logs_analyzed'], 50)
        self.assertEqual(data['token_count'], 1000)
        self.assertIn('timestamp', data)
        self.assertIn('created_at', data)

    def test_batch_includes_nested_issues(self):
        """Test batch serialization includes nested issues."""
        serializer = AIAnalyzedBatchSerializer(self.batch)
        data = serializer.data
        
        self.assertIn('issues', data)
        self.assertEqual(len(data['issues']), 2)
        self.assertEqual(data['issues'][0]['severity'], 'WARNING')  # Ordered by created_at desc

    def test_batch_read_only_fields(self):
        """Test read-only fields cannot be updated."""
        update_data = {
            'batch_id': 'test_batch_002',
            'token_count': 9999  # Should not be updateable
        }
        
        serializer = AIAnalyzedBatchSerializer(self.batch, data=update_data, partial=True)
        
        if serializer.is_valid():
            serializer.save()
            self.batch.refresh_from_db()
            
            # token_count should not have changed (it's read-only)
            self.assertEqual(self.batch.token_count, 1000)


class TestAIAnalyzedBatchListSerializer(TestCase):
    """Test cases for AIAnalyzedBatchListSerializer."""

    def setUp(self):
        """Set up test batch."""
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='test_batch_list',
            timestamp=timezone.now(),
            analysis_text='{"summary": "Test analysis"}',
            model_name='gemini-1.5-pro'
        )

    def test_list_serializer_excludes_data(self):
        """Test list serializer doesn't include heavy 'data' field."""
        serializer = AIAnalyzedBatchListSerializer(self.batch)
        data = serializer.data
        
        self.assertNotIn('data', data)  # Heavy field excluded for performance

    def test_list_serializer_includes_analysis(self):
        """Test list serializer includes computed analysis field."""
        serializer = AIAnalyzedBatchListSerializer(self.batch)
        data = serializer.data
        
        self.assertIn('analysis', data)

    def test_get_analysis_parses_json(self):
        """Test analysis field parses JSON from analysis_text."""
        self.batch.analysis_text = '{"summary": "Critical errors", "count": 5}'
        self.batch.save()
        
        serializer = AIAnalyzedBatchListSerializer(self.batch)
        data = serializer.data
        
        self.assertIsInstance(data['analysis'], dict)
        self.assertEqual(data['analysis']['summary'], "Critical errors")
        self.assertEqual(data['analysis']['count'], 5)

    def test_get_analysis_handles_invalid_json(self):
        """Test analysis field handles invalid JSON gracefully."""
        self.batch.analysis_text = "Not valid JSON"
        self.batch.save()
        
        serializer = AIAnalyzedBatchListSerializer(self.batch)
        data = serializer.data
        
        # Should return empty dict on parse error
        self.assertEqual(data['analysis'], {})

    def test_get_analysis_with_no_text(self):
        """Test analysis field with no analysis_text."""
        self.batch.analysis_text = None
        self.batch.data = {}
        self.batch.save()
        
        serializer = AIAnalyzedBatchListSerializer(self.batch)
        data = serializer.data
        
        self.assertEqual(data['analysis'], {})
