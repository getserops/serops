"""Tests for trace-based correlations + unified timeline (Item #12)."""

from datetime import datetime, timedelta, timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from Data.correlation_engine import (
    build_comprehensive_correlations,
    correlate_spans_with_code_changes,
    correlate_spans_with_logs,
    correlate_spans_with_metrics,
)
from Data.models import AIAnalyzedBatch
from Data.unified_timeline import build_unified_timeline
from Organisations.models import Organisations

User = get_user_model()


# ============================================================================
# correlate_spans_with_logs
# ============================================================================


class SpanErrorToLogErrorTest(TestCase):

    def _traces(self, service='checkout', message='timeout'):
        return {
            'top_errors': [{
                'trace_id': 'a' * 32,
                'service_name': service,
                'operation_name': 'POST /checkout',
                'status_message': message,
            }],
        }

    def _err_log(self, service='checkout', message='connection timeout on POST /checkout',
                 when='2026-09-04T12:00:05Z'):
        return {'level': 'ERROR', 'component': service, 'message': message, 'timestamp': when}

    def test_empty_inputs_return_empty(self):
        self.assertEqual(correlate_spans_with_logs({}, []), [])
        self.assertEqual(correlate_spans_with_logs(self._traces(), []), [])
        self.assertEqual(correlate_spans_with_logs({}, [self._err_log()]), [])

    def test_matching_service_yields_medium(self):
        corrs = correlate_spans_with_logs(self._traces(), [self._err_log(message='different')])
        self.assertEqual(len(corrs), 1)
        self.assertEqual(corrs[0]['confidence'], 'MEDIUM')
        self.assertEqual(corrs[0]['service'], 'checkout')

    def test_message_overlap_yields_high(self):
        # Span msg starts with 'timeout' and log msg contains 'timeout' → HIGH.
        corrs = correlate_spans_with_logs(self._traces(message='timeout'),
                                          [self._err_log(message='connection timeout on POST /checkout')])
        self.assertEqual(corrs[0]['confidence'], 'HIGH')

    def test_different_service_no_correlation(self):
        corrs = correlate_spans_with_logs(self._traces(service='checkout'),
                                          [self._err_log(service='api', message='x')])
        self.assertEqual(corrs, [])

    def test_non_error_log_ignored(self):
        info_log = {'level': 'INFO', 'component': 'checkout', 'message': 'x',
                    'timestamp': '2026-09-04T12:00:05Z'}
        self.assertEqual(correlate_spans_with_logs(self._traces(), [info_log]), [])


# ============================================================================
# correlate_spans_with_code_changes
# ============================================================================


class SlowSpanAfterDeployTest(TestCase):

    def _traces(self):
        return {
            'services_touched': ['checkout'],
            'top_slow': [{
                'trace_id': 'b' * 32,
                'service_name': 'checkout',
                'operation_name': 'POST /checkout',
                'duration_ms': 1500,
            }],
        }

    def test_file_path_matches_service(self):
        change = {
            'sha': 'abcdef123456', 'message': 'refactor', 'author': 'me',
            'files': ['services/checkout/handler.py', 'shared/util.py'],
        }
        corrs = correlate_spans_with_code_changes(self._traces(), [change])
        self.assertEqual(len(corrs), 1)
        self.assertEqual(corrs[0]['services_affected'], ['checkout'])
        self.assertEqual(corrs[0]['commit_sha'], 'abcdef12')

    def test_no_matching_files_no_correlation(self):
        change = {'files': ['docs/README.md'], 'sha': 'x', 'message': 'docs', 'author': 'me'}
        self.assertEqual(correlate_spans_with_code_changes(self._traces(), [change]), [])

    def test_empty_traces_returns_empty(self):
        change = {'files': ['services/checkout/x.py'], 'sha': 'x', 'message': 'm', 'author': 'me'}
        self.assertEqual(correlate_spans_with_code_changes({}, [change]), [])

    def test_dict_files_supported(self):
        change = {
            'sha': 'aa', 'message': 'x', 'author': 'me',
            'files': [{'path': 'apps/checkout/main.py', 'diff': ''}],
        }
        corrs = correlate_spans_with_code_changes(self._traces(), [change])
        self.assertEqual(len(corrs), 1)


# ============================================================================
# correlate_spans_with_metrics
# ============================================================================


class SlowSpanDuringMetricSpikeTest(TestCase):

    def _traces(self):
        return {
            'top_slow': [{
                'trace_id': 'c' * 32, 'service_name': 'api',
                'operation_name': 'GET /users', 'duration_ms': 900,
            }],
        }

    def test_cpu_anomaly_correlated(self):
        summary = {'cpu': {'anomalies': [{
            'start_time': '2026-09-04T12:00:00Z', 'peak_value': 92, 'duration_seconds': 60,
        }]}}
        corrs = correlate_spans_with_metrics(self._traces(), summary)
        self.assertEqual(len(corrs), 1)
        self.assertEqual(corrs[0]['metric_type'], 'cpu')
        self.assertEqual(corrs[0]['top_slow_duration_ms'], 900)

    def test_no_anomalies_no_correlation(self):
        summary = {'cpu': {'anomalies': []}, 'memory': {'anomalies': []}}
        self.assertEqual(correlate_spans_with_metrics(self._traces(), summary), [])

    def test_no_slow_spans_no_correlation(self):
        summary = {'cpu': {'anomalies': [{'start_time': 'T', 'peak_value': 92}]}}
        self.assertEqual(correlate_spans_with_metrics({}, summary), [])


# ============================================================================
# Comprehensive builder passes traces_summary through
# ============================================================================


class BuildComprehensiveWithTracesTest(TestCase):

    def test_traces_summary_optional_kwarg(self):
        # No traces_summary — the three new keys still exist as empty lists.
        result = build_comprehensive_correlations(
            logs=[], metrics_summary={}, code_changes=[],
        )
        for k in ('span_error_to_log_error', 'slow_span_after_deploy',
                  'slow_span_during_metric_spike'):
            self.assertIn(k, result['correlations'])
            self.assertEqual(result['correlations'][k], [])

    def test_traces_summary_populates_all_three(self):
        traces = {
            'top_errors': [{'trace_id': 'a' * 32, 'service_name': 'checkout',
                             'operation_name': 'POST /', 'status_message': 'boom'}],
            'top_slow': [{'trace_id': 'a' * 32, 'service_name': 'checkout',
                           'operation_name': 'POST /', 'duration_ms': 800}],
            'services_touched': ['checkout'],
        }
        result = build_comprehensive_correlations(
            logs=[{'level': 'ERROR', 'component': 'checkout', 'message': 'boom',
                    'timestamp': '2026-09-04T12:00:05Z'}],
            metrics_summary={'cpu': {'anomalies': [{'start_time': 'T', 'peak_value': 95}]}},
            code_changes=[{'sha': 'aa', 'message': 'x', 'author': 'me',
                            'files': ['services/checkout/x.py']}],
            traces_summary=traces,
        )
        self.assertEqual(len(result['correlations']['span_error_to_log_error']), 1)
        self.assertEqual(len(result['correlations']['slow_span_after_deploy']), 1)
        self.assertEqual(len(result['correlations']['slow_span_during_metric_spike']), 1)


# ============================================================================
# Unified timeline
# ============================================================================


class UnifiedTimelineBuilderTest(TestCase):

    def _mkbatch(self, data):
        class _B:
            pass
        b = _B()
        b.data = data
        return b

    def test_none_batch_returns_empty(self):
        self.assertEqual(build_unified_timeline(None), [])

    def test_no_data_attribute_returns_empty(self):
        class _B: pass
        self.assertEqual(build_unified_timeline(_B()), [])

    def test_all_five_sources_merged_and_sorted(self):
        batch = self._mkbatch({
            'logs': [{'_source': {
                'log_level': 'ERROR', 'message': 'boom',
                '@timestamp': '2026-09-04T12:00:05Z',
                'service': {'name': 'checkout'},
            }}],
            'metrics_summary': {'cpu': {'anomalies': [{
                'start_time': '2026-09-04T12:00:02Z', 'peak_value': 95, 'duration_seconds': 30,
            }]}},
            'code_changes': [{
                'sha': 'aabbcc123456', 'message': 'refactor', 'author': 'me',
                'branch': 'main', 'timestamp': '2026-09-04T11:58:00Z',
                'stats': {'files': 3},
            }],
            'cicd_logs': [{
                'job_name': 'test', 'status': 'failed', 'branch': 'main',
                'pipeline_id': 42, 'finished_at': '2026-09-04T12:00:00Z',
            }],
            'traces': {'top_errors': [{
                'trace_id': 'a' * 32, 'service_name': 'checkout',
                'operation_name': 'POST /', 'status_message': 'timeout',
                'duration_ms': 300, 'start_time': '2026-09-04T12:00:04Z',
            }]},
        })
        events = build_unified_timeline(batch)
        kinds = [e['kind'] for e in events]
        # All 5 kinds represented.
        self.assertEqual(
            set(kinds),
            {'log', 'metric_anomaly', 'deploy', 'cicd', 'span_error'},
        )
        # Sorted ascending — deploy at 11:58 comes first.
        self.assertEqual(events[0]['kind'], 'deploy')
        # Log at 12:00:05 is last of the timed events.
        timed_kinds = [e['kind'] for e in events if e.get('time')]
        self.assertEqual(timed_kinds[-1], 'log')

    def test_info_logs_filtered_out(self):
        batch = self._mkbatch({'logs': [
            {'_source': {'log_level': 'INFO', 'message': 'startup',
                          '@timestamp': '2026-09-04T12:00:00Z'}},
            {'_source': {'log_level': 'ERROR', 'message': 'boom',
                          '@timestamp': '2026-09-04T12:00:00Z'}},
        ]})
        events = build_unified_timeline(batch)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['severity'], 'ERROR')

    def test_max_events_cap_honoured(self):
        # Manufacture 100 error logs — cap them at 5.
        batch = self._mkbatch({'logs': [
            {'_source': {'log_level': 'ERROR', 'message': f'x{i}',
                          '@timestamp': f'2026-09-04T12:00:{i:02d}Z'}}
            for i in range(60)
        ]})
        events = build_unified_timeline(batch, max_events=5)
        self.assertEqual(len(events), 5)


# ============================================================================
# Timeline endpoint
# ============================================================================


class BatchTimelineEndpointTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='TimelineOrg')
        self.other_org = Organisations.objects.create(name='OtherTimelineOrg')
        self.user = User.objects.create_user(
            username='tuser', email='tu@t.com', password='p',
            organisation=self.org, role='user', is_active=True,
        )
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='batch_timeline_1',
            organisation=self.org,
            data={'logs': [{'_source': {
                'log_level': 'ERROR', 'message': 'boom',
                '@timestamp': '2026-09-04T12:00:00Z',
            }}]},
        )
        self.other_batch = AIAnalyzedBatch.objects.create(
            batch_id='batch_other_org',
            organisation=self.other_org,
            data={},
        )
        self.client = APIClient()

    def _url(self, bid):
        return f'/api/data/batches/{bid}/timeline/'

    def test_requires_auth(self):
        self.assertIn(self.client.get(self._url('batch_timeline_1')).status_code, (401, 403))

    def test_own_batch_returns_events(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self._url('batch_timeline_1'))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['batch_id'], 'batch_timeline_1')
        self.assertEqual(len(body['events']), 1)
        self.assertEqual(body['events'][0]['kind'], 'log')

    def test_cross_org_404(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self._url('batch_other_org'))
        self.assertEqual(response.status_code, 404)

    def test_max_events_capped_at_500(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self._url('batch_timeline_1') + '?max_events=9999')
        self.assertEqual(response.status_code, 200)
        # Server clamps to 500 — with only 1 event we can only check no error.

    def test_bad_max_events_defaults(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self._url('batch_timeline_1') + '?max_events=foo')
        self.assertEqual(response.status_code, 200)
