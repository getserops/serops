"""
Tests for Data app views: batch CRUD, issue actions, analytics,
dashboard, settings, and metrics endpoints.

Covers all view-level gaps identified in the test coverage audit.
"""

import uuid
from unittest.mock import patch, MagicMock
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from Organisations.models import Organisations
from Users.models import User
from Projects.models import Project
from Data.models import AIAnalyzedBatch, Issue, AuditLog, RetentionPolicy


class DataViewTestBase(APITestCase):
    """Shared setUp for Data view tests."""

    def setUp(self):
        self.org = Organisations.objects.create(
            name='Data Org', website='https://data.com',
        )
        self.other_org = Organisations.objects.create(
            name='Other Org', website='https://other.com',
        )
        self.admin = User.objects.create_user(
            username='dataadmin', email='da@test.com',
            password='Test123!', organisation=self.org,
            role='admin', is_active=True,
        )
        self.user = User.objects.create_user(
            username='datauser', email='du@test.com',
            password='Test123!', organisation=self.org,
            role='user', is_active=True,
        )
        self.viewer = User.objects.create_user(
            username='dataviewer', email='dv@test.com',
            password='Test123!', organisation=self.org,
            role='viewer', is_active=True,
        )
        self.other_user = User.objects.create_user(
            username='otheruser', email='ou@test.com',
            password='Test123!', organisation=self.other_org,
            role='admin', is_active=True,
        )

        self.project = Project.objects.create(
            name='test-project', organisation=self.org,
        )
        self.other_project = Project.objects.create(
            name='other-project', organisation=self.other_org,
        )
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='batch-001', project=self.project,
            organisation=self.org, timestamp=timezone.now(),
            data={'logs': []},
        )

    def _auth(self, user):
        self.client.force_authenticate(user=user)


# ---------------------------------------------------------------------------
# Batch views
# ---------------------------------------------------------------------------

class TestLogBatchView(DataViewTestBase):
    """Tests for GET /data/batches"""

    def setUp(self):
        super().setUp()
        self.url = reverse('Batches')
        self._auth(self.user)

    def test_list_batches(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)

    def test_list_batches_pagination(self):
        # Create extra batches
        for i in range(3):
            AIAnalyzedBatch.objects.create(
                batch_id=f'batch-pg-{i}', project=self.project,
                organisation=self.org, timestamp=timezone.now(),
                data={'logs': []},
            )
        response = self.client.get(self.url, {'limit': 2, 'offset': 0})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertLessEqual(len(response.data['results']), 2)
        self.assertIn('pagination', response.data)

    def test_list_batches_filter_environment(self):
        AIAnalyzedBatch.objects.create(
            batch_id='batch-prod', project=self.project,
            organisation=self.org, timestamp=timezone.now(),
            data={'logs': []}, environment='production',
        )
        response = self.client.get(self.url, {'environment': 'production'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for b in response.data['results']:
            if b.get('environment'):
                self.assertEqual(b['environment'].lower(), 'production')

    def test_list_batches_sorting(self):
        response = self.client.get(self.url, {'order_by': '-timestamp'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_batches_org_isolation(self):
        """Cannot see other org's batches."""
        AIAnalyzedBatch.objects.create(
            batch_id='batch-other', project=self.other_project,
            organisation=self.other_org, timestamp=timezone.now(),
            data={'logs': []},
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        batch_ids = [b['batch_id'] for b in response.data['results']]
        self.assertNotIn('batch-other', batch_ids)

    def test_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TestBatchDetailView(DataViewTestBase):
    """Tests for GET /data/batches/<batch_id>/"""

    def setUp(self):
        super().setUp()
        self._auth(self.user)

    def test_get_batch_detail(self):
        url = reverse('batch-detail', kwargs={'batch_id': self.batch.batch_id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_batch_not_found(self):
        url = reverse('batch-detail', kwargs={'batch_id': 'nonexistent-999'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cross_org_denied(self):
        """Other org's batch not accessible."""
        other_batch = AIAnalyzedBatch.objects.create(
            batch_id='batch-xorg', project=self.other_project,
            organisation=self.other_org, timestamp=timezone.now(),
            data={'logs': []},
        )
        url = reverse('batch-detail', kwargs={'batch_id': 'batch-xorg'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated(self):
        self.client.force_authenticate(user=None)
        url = reverse('batch-detail', kwargs={'batch_id': self.batch.batch_id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TestBatchReanalyzeView(DataViewTestBase):
    """Tests for POST /data/batches/reanalyze/"""

    def setUp(self):
        super().setUp()
        self.url = reverse('batch-reanalyze')

    @patch('ai_model.tasks.reanalyze_batch_with_model')
    def test_reanalyze_success(self, mock_task):
        """Celery task queued, returns batch_ids."""
        from org_settings.models import AIModelProvider
        AIModelProvider.objects.get_or_create(
            name='gemini', defaults={'display_name': 'Gemini', 'is_active': True}
        )
        mock_task.delay = MagicMock()
        self._auth(self.user)
        response = self.client.post(self.url, {
            'batch_ids': [self.batch.batch_id],
            'model': 'gemini',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'queued')
        mock_task.delay.assert_called_once()

    def test_reanalyze_invalid_model(self):
        """Non-existent model name rejected."""
        self._auth(self.user)
        response = self.client.post(self.url, {
            'batch_ids': [self.batch.batch_id],
            'model': 'nonexistent_model',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reanalyze_denied_viewer(self):
        """@require_role('user') blocks viewer."""
        self._auth(self.viewer)
        response = self.client.post(self.url, {
            'batch_ids': [self.batch.batch_id],
            'model': 'gemini',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_reanalyze_batch_not_found(self):
        """Nonexistent batch_id returns 404."""
        from org_settings.models import AIModelProvider
        AIModelProvider.objects.get_or_create(
            name='gemini', defaults={'display_name': 'Gemini', 'is_active': True}
        )
        self._auth(self.user)
        response = self.client.post(self.url, {
            'batch_ids': ['nonexistent-batch'],
            'model': 'gemini',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(self.url, {
            'batch_ids': ['x'], 'model': 'gemini',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TestDeleteOldBatchesView(DataViewTestBase):
    """Tests for DELETE /data/delete-old-batches/"""

    def setUp(self):
        super().setUp()
        self.url = reverse('delete-old-batches')

    def test_delete_old_batches_admin(self):
        """Old batches removed, count in response."""
        # Create an old batch
        old = AIAnalyzedBatch.objects.create(
            batch_id='batch-old', project=self.project,
            organisation=self.org, timestamp=timezone.now(),
            data={'logs': []},
        )
        AIAnalyzedBatch.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=60)
        )
        self._auth(self.admin)
        response = self.client.delete(self.url, {'days': 30})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('deleted_batches', response.data)

    def test_delete_denied_user(self):
        """@require_role('admin') blocks user."""
        self._auth(self.user)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_custom_days(self):
        """?days=7 param respected."""
        self._auth(self.admin)
        response = self.client.delete(self.url + '?days=7')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Issue actions
# ---------------------------------------------------------------------------

class TestIssueActionsView(DataViewTestBase):
    """Tests for POST /data/issues/<issue_id>/<action>/"""

    def setUp(self):
        super().setUp()
        self._auth(self.user)
        self.issue = Issue.objects.create(
            batch=self.batch, severity='CRITICAL',
            description='Test issue', status='OPEN',
            organisation=self.org,
            fingerprint=f'v4:action-test-{uuid.uuid4().hex[:8]}',
        )

    def test_resolve_issue(self):
        url = reverse('issue-action', kwargs={
            'issue_id': self.issue.id, 'action': 'resolve',
        })
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.status, 'RESOLVED')
        self.assertIsNotNone(self.issue.resolved_at)

    def test_mute_issue_with_days(self):
        url = reverse('issue-action', kwargs={
            'issue_id': self.issue.id, 'action': 'mute',
        })
        response = self.client.post(url, {'days': 14}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.status, 'MUTED')
        self.assertIsNotNone(self.issue.muted_until)

    def test_reopen_issue(self):
        self.issue.status = 'RESOLVED'
        self.issue.resolved_at = timezone.now()
        self.issue.save()
        url = reverse('issue-action', kwargs={
            'issue_id': self.issue.id, 'action': 'reopen',
        })
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.status, 'OPEN')
        self.assertIsNone(self.issue.muted_until)

    def test_invalid_action(self):
        url = reverse('issue-action', kwargs={
            'issue_id': self.issue.id, 'action': 'delete',
        })
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cross_org_denied(self):
        """Other org's issue not accessible."""
        other_batch = AIAnalyzedBatch.objects.create(
            batch_id='batch-oi', project=self.other_project,
            organisation=self.other_org, timestamp=timezone.now(),
            data={'logs': []},
        )
        other_issue = Issue.objects.create(
            batch=other_batch, severity='CRITICAL',
            description='Other issue', status='OPEN',
            organisation=self.other_org,
            fingerprint=f'v4:other-issue-{uuid.uuid4().hex[:8]}',
        )
        url = reverse('issue-action', kwargs={
            'issue_id': other_issue.id, 'action': 'resolve',
        })
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# Analytics views
# ---------------------------------------------------------------------------

class TestAnalyticsViews(DataViewTestBase):
    """Tests for analytics endpoints: issue-stats, recommendation-stats,
    system-health, service-reliability, issue-trends."""

    def setUp(self):
        super().setUp()
        self._auth(self.user)
        # Create some issues for analytics (unique fingerprints required)
        Issue.objects.create(
            batch=self.batch, severity='CRITICAL',
            description='Crit issue', status='OPEN',
            organisation=self.org,
            fingerprint=f'v4:analytics-crit-{uuid.uuid4().hex[:8]}',
        )
        Issue.objects.create(
            batch=self.batch, severity='WARNING',
            description='Warn issue', status='OPEN',
            organisation=self.org,
            fingerprint=f'v4:analytics-warn-{uuid.uuid4().hex[:8]}',
        )

    def test_issue_stats(self):
        url = reverse('issue-stats')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('statistics', response.data)

    def test_recommendation_stats(self):
        url = reverse('recommendation-stats')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('statistics', response.data)

    def test_system_health(self):
        url = reverse('system-health')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('health_score', response.data)
        self.assertIn('status', response.data)

    def test_system_health_no_issues(self):
        """Empty org returns healthy score."""
        # Auth as other org user with no issues
        self._auth(self.other_user)
        url = reverse('system-health')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['health_score'], 100)

    def test_service_reliability(self):
        url = reverse('service-reliability')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_trend_analysis(self):
        url = reverse('issue-trends')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should return list of daily entries
        self.assertIsInstance(response.data, list)

    def test_analytics_org_isolation(self):
        """Only counts own org's issues."""
        self._auth(self.other_user)
        url = reverse('issue-stats')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Other org has no issues
        summary = response.data.get('statistics', {}).get('summary', {})
        self.assertEqual(summary.get('total', 0), 0)

    def test_analytics_unauthenticated(self):
        self.client.force_authenticate(user=None)
        url = reverse('issue-stats')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Dashboard views
# ---------------------------------------------------------------------------

class TestDashboardViews(DataViewTestBase):
    """Tests for dashboard endpoints: MTTR, service-health, root-causes,
    sentinel-stats, analysis-feed, correlation-insights."""

    def setUp(self):
        super().setUp()
        self._auth(self.user)

    def test_mttr_stats(self):
        url = reverse('mttr-stats')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('overall_mttr_hours', response.data)

    def test_mttr_custom_days(self):
        url = reverse('mttr-stats')
        response = self.client.get(url, {'days': 7})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('overall_mttr_hours', response.data)

    def test_service_health_map(self):
        url = reverse('service-health-map')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_root_cause_stats(self):
        url = reverse('root-cause-stats')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('breakdown', response.data)

    def test_sentinel_stats(self):
        url = reverse('sentinel-stats')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('decisions', response.data)

    def test_analysis_feed(self):
        url = reverse('analysis-feed')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('feed', response.data)

    def test_correlation_insights(self):
        url = reverse('correlation-insights')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Settings views
# ---------------------------------------------------------------------------

class TestSettingsViews(DataViewTestBase):
    """Tests for SecuritySettings, AuditLog, RetentionPolicy, DataUsage."""

    def test_get_security_settings(self):
        self._auth(self.admin)
        url = reverse('security-settings')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('password_policy', response.data)
        self.assertIn('session', response.data)

    def test_update_security_settings(self):
        self._auth(self.admin)
        url = reverse('security-settings')
        response = self.client.put(url, {
            'password_policy': {'min_length': 12},
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get('success'))

    def test_security_settings_denied_user(self):
        """Admin only for PUT."""
        self._auth(self.user)
        url = reverse('security-settings')
        response = self.client.put(url, {
            'password_policy': {'min_length': 12},
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_audit_log(self):
        self._auth(self.admin)
        AuditLog.objects.create(
            organisation=self.org, user=self.admin,
            action='LOGIN', details={'ip': '127.0.0.1'},
        )
        url = reverse('audit-log')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('logs', response.data)
        self.assertIn('pagination', response.data)

    def test_audit_log_denied_user(self):
        """Admin only."""
        self._auth(self.user)
        url = reverse('audit-log')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_retention_policy(self):
        self._auth(self.user)
        url = reverse('retention-policy')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('retention_days', response.data)

    def test_update_retention_policy(self):
        self._auth(self.admin)
        url = reverse('retention-policy')
        response = self.client.put(url, {
            'auto_cleanup_enabled': True,
            'retention_days': 30,
            'cleanup_frequency': 'weekly',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get('success'))

    def test_data_usage(self):
        self._auth(self.user)
        url = reverse('data-usage')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('totals', response.data)
        self.assertIn('batches', response.data['totals'])
        # Verify total_records is present and correct (1 batch from setUp)
        self.assertEqual(response.data['total_records'], 1)
        self.assertEqual(response.data['totals']['batches'], 1)

    def test_data_usage_counts_with_issues_and_pipelines(self):
        """Verify all record types are counted and summed correctly."""
        self._auth(self.user)
        # Create issues attached to the existing batch
        Issue.objects.create(batch=self.batch, severity='WARNING', description='desc 1')
        Issue.objects.create(batch=self.batch, severity='CRITICAL', description='desc 2')
        # Create a pipeline with direct organisation FK (non-GitLab path)
        from providers.models import Pipeline
        Pipeline.objects.create(
            organisation=self.org, pipeline_id='pipe-1',
            status='success', branch='main', cicd_provider='github_actions',
        )
        url = reverse('data-usage')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['totals']['batches'], 1)
        self.assertEqual(response.data['totals']['issues'], 2)
        self.assertEqual(response.data['totals']['pipelines'], 1)
        self.assertEqual(response.data['total_records'], 4)  # 1 + 2 + 1

    def test_data_usage_org_isolation(self):
        """Data from another org must not appear in counts."""
        self._auth(self.user)
        # Create data in the other org
        AIAnalyzedBatch.objects.create(
            batch_id='other-batch', project=self.other_project,
            organisation=self.other_org, timestamp=timezone.now(),
            data={'logs': []},
        )
        from providers.models import Pipeline
        Pipeline.objects.create(
            organisation=self.other_org, pipeline_id='other-pipe',
            status='success', branch='main',
        )
        url = reverse('data-usage')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Only the 1 batch from setUp should appear
        self.assertEqual(response.data['totals']['batches'], 1)
        self.assertEqual(response.data['totals']['pipelines'], 0)
        self.assertEqual(response.data['total_records'], 1)

    def test_data_usage_empty_org(self):
        """An org with no data should return all zeros."""
        self._auth(self.other_user)
        url = reverse('data-usage')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_records'], 0)
        self.assertEqual(response.data['totals']['batches'], 0)
        self.assertEqual(response.data['totals']['issues'], 0)
        self.assertEqual(response.data['totals']['pipelines'], 0)


# ---------------------------------------------------------------------------
# Metrics views (require mocking external providers)
# ---------------------------------------------------------------------------

class TestMetricsViews(DataViewTestBase):
    """Tests for metric/log endpoints with mocked providers."""

    def setUp(self):
        super().setUp()
        self._auth(self.user)

    @patch('Data.views.IntegrationRegistry')
    def test_memory_metrics(self, mock_registry):
        mock_provider = MagicMock()
        mock_provider.query_range.return_value = []
        mock_registry.get_metric_provider_for_org.return_value = mock_provider
        url = reverse('node-memory-swap')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('Data.views.IntegrationRegistry')
    def test_cpu_metrics(self, mock_registry):
        mock_provider = MagicMock()
        mock_provider.query_range.return_value = []
        mock_registry.get_metric_provider_for_org.return_value = mock_provider
        url = reverse('node-cpu-raw')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('Data.views.IntegrationRegistry')
    def test_metrics_no_provider(self, mock_registry):
        """No provider configured → graceful fallback."""
        mock_registry.get_metric_provider_for_org.side_effect = Exception('No provider')
        url = reverse('node-memory-swap')
        response = self.client.get(url)
        # Should return error or empty result, not crash
        self.assertIn(response.status_code, [200, 500])

    @patch('Data.views.IntegrationRegistry')
    def test_host_discovery(self, mock_registry):
        mock_provider = MagicMock()
        mock_provider.discover_hosts.return_value = []
        mock_registry.get_metric_provider_for_org.return_value = mock_provider
        url = reverse('host-discovery')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('hosts', response.data)

    @patch('Data.views.IntegrationRegistry')
    def test_fluentd_logs(self, mock_registry):
        mock_provider = MagicMock()
        mock_provider.search.return_value = []
        mock_registry.get_log_provider_for_org.return_value = mock_provider
        url = reverse('fluentd-logs')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_metric_correlation_from_stored_data(self):
        """MetricCorrelationView reads from batch.data['correlation_results']."""
        # Store engine output on batch
        self.batch.data['correlation_results'] = {
            'correlations': {
                'file_to_error': [],
                'deployment_to_metric_spike': [
                    {'metric_type': 'memory', 'anomaly_peak': '92%', 'commit_sha': 'abc123', 'confidence': 'HIGH'},
                ],
                'metric_spike_to_errors': [],
            },
            'summary': {'total_correlations': 1, 'high_confidence_count': 1},
        }
        self.batch.save(update_fields=['data'])
        url = reverse('metric-correlation', kwargs={'batch_id': self.batch.batch_id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('correlations', response.data)
        self.assertIn('summary', response.data)

    def test_metric_correlation_empty_batch(self):
        """MetricCorrelationView returns empty when no engine data stored."""
        url = reverse('metric-correlation', kwargs={'batch_id': self.batch.batch_id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['correlations'], {})

    def test_metric_correlation_filter_by_type(self):
        """MetricCorrelationView filters by metric_type query param."""
        self.batch.data['correlation_results'] = {
            'correlations': {
                'file_to_error': [],
                'deployment_to_metric_spike': [
                    {'metric_type': 'memory', 'confidence': 'HIGH'},
                    {'metric_type': 'cpu', 'confidence': 'MEDIUM'},
                ],
                'metric_spike_to_errors': [],
            },
            'summary': {'total_correlations': 2},
        }
        self.batch.save(update_fields=['data'])
        url = reverse('metric-correlation', kwargs={'batch_id': self.batch.batch_id})
        response = self.client.get(url, {'metric_type': 'memory'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        deploy_corrs = response.data['correlations']['deployment_to_metric_spike']
        self.assertEqual(len(deploy_corrs), 1)
        self.assertEqual(deploy_corrs[0]['metric_type'], 'memory')
