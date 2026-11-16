"""A data source that cannot answer must say so (phase 3 review, LG1 / MT-1 /
CL-1 / CL-11).

Every adapter here used to turn a refused or failed query into ``[]``. The
batch then read that as "no errors, no anomalies", so an expired token or a
store that was down looked exactly like a quiet window. An empty list now
means "the query worked and matched nothing"; a failure raises.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError

from integrations.base import LogSearchError, MetricQueryError, describe_request_error
from integrations.metrics_processing import fetch_metrics_with_provider, metric_source_status

START = datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc)
END = START + timedelta(minutes=15)


def _response(status, payload=None):
    resp = MagicMock(status_code=status)
    resp.json.return_value = payload or {}
    if status >= 400:
        resp.raise_for_status.side_effect = HTTPError(response=resp)
    else:
        resp.raise_for_status.return_value = None
    return resp


class DescribeRequestErrorTest(SimpleTestCase):
    def test_status_code_and_meaning_never_the_text(self):
        exc = HTTPError('401 Client Error for url http://user:secret@loki/x', response=SimpleNamespace(status_code=401))
        self.assertEqual(describe_request_error(exc), 'HTTP 401 (authentication refused)')
        self.assertEqual(describe_request_error(HTTPError(response=SimpleNamespace(status_code=503))),
                         'HTTP 503 (server error)')
        self.assertEqual(describe_request_error(RequestsConnectionError('secret host')), 'ConnectionError')


class PrometheusFailClosedTest(SimpleTestCase):
    def setUp(self):
        from integrations.adapters.prometheus import PrometheusMetricProvider
        self.provider = PrometheusMetricProvider({'host': 'http://prometheus:9090'})

    def test_unreachable_store_raises(self):
        with patch.object(self.provider._session, 'get', side_effect=RequestsConnectionError('down')):
            with self.assertRaises(MetricQueryError):
                self.provider.query_range('node_memory_MemTotal_bytes', {}, START, END)

    def test_unauthorised_raises_with_the_status(self):
        with patch.object(self.provider._session, 'get', return_value=_response(401)):
            with self.assertRaises(MetricQueryError) as raised:
                self.provider.query_range_expr('up', START, END)
        self.assertIn('HTTP 401', str(raised.exception))

    def test_status_error_raises(self):
        body = {'status': 'error', 'errorType': 'bad_data', 'error': 'parse error'}
        with patch.object(self.provider._session, 'get', return_value=_response(200, body)):
            with self.assertRaises(MetricQueryError):
                self.provider.query_range_expr('up{', START, END)

    def test_no_series_is_still_an_empty_list(self):
        body = {'status': 'success', 'data': {'resultType': 'matrix', 'result': []}}
        with patch.object(self.provider._session, 'get', return_value=_response(200, body)):
            self.assertEqual(self.provider.query_range_expr('up', START, END), [])

    def test_partial_response_warnings_are_noted(self):
        body = {'status': 'success', 'warnings': ['store gateway timed out'],
                'data': {'resultType': 'matrix', 'result': []}}
        self.provider.last_search_notes = []
        with patch.object(self.provider._session, 'get', return_value=_response(200, body)):
            self.provider.query_range_expr('up', START, END)
        self.assertTrue(self.provider.last_search_notes)


class MetricPipelineStatusTest(SimpleTestCase):
    """fetch_metrics_with_provider reports what the store did."""

    def fetch(self, provider):
        project = SimpleNamespace(organisation=SimpleNamespace(name='acme'), cluster=None)
        with patch('integrations.registry.IntegrationRegistry.get_metric_provider_for_org', return_value=provider):
            return fetch_metrics_with_provider(START, END, project_obj=project, project_name_str='shop',
                                               environment_str='production')

    def test_every_query_refused_is_unavailable(self):
        provider = MagicMock(spec=['query_range', 'topology_mode'])
        provider.topology_mode = 'vm'
        provider.query_range.side_effect = MetricQueryError('Prometheus refused the query: HTTP 401')
        metrics = self.fetch(provider)
        self.assertEqual(metrics['_source_status']['status'], 'unavailable')
        self.assertIn('HTTP 401', metrics['_source_status']['detail'])
        self.assertEqual(metrics['cpu'], [])

    def test_one_refused_query_keeps_the_others(self):
        """Azure VM mode refuses the memory names (CL-10): CPU must survive."""
        from integrations.schemas import TimeSeries, TimeSeriesPoint
        cpu = [TimeSeries(metric_name='cpu', labels={'instance': 'vm-1'},
                          points=[TimeSeriesPoint(timestamp=START, value=12.0)])]

        def query_range(metric, labels, start, end):
            if metric.startswith('node_memory'):
                raise MetricQueryError('Azure Monitor refused the metrics query (HttpResponseError)')
            return cpu
        provider = MagicMock(spec=['query_range', 'topology_mode'])
        provider.topology_mode = 'vm'
        provider.query_range.side_effect = query_range
        metrics = self.fetch(provider)
        self.assertEqual(metrics['_source_status']['status'], 'partial')
        self.assertIn('3 of 4', metrics['_source_status']['detail'])
        self.assertEqual(len(metrics['cpu']), 1)

    def test_all_answered_is_ok(self):
        self.assertEqual(metric_source_status([], 4, []), {'status': 'ok', 'detail': ''})
        self.assertEqual(metric_source_status([], 4, ['partial answer'])['status'], 'partial')


class CloudMetricsFailClosedTest(SimpleTestCase):
    """CL-11: the four cloud metric adapters raise on auth and transport errors."""

    def test_cloudwatch(self):
        from integrations.adapters.cloudwatch_metrics import CloudWatchMetricProvider
        provider = CloudWatchMetricProvider.__new__(CloudWatchMetricProvider)
        provider._topology_mode = 'vm'
        provider._series = MagicMock(return_value=[{'InstanceId': 'i-1'}])
        provider._queries = MagicMock(return_value=[])
        provider.client = MagicMock()
        provider.client.get_metric_data.side_effect = RuntimeError('AccessDenied')
        with self.assertRaises(MetricQueryError):
            provider.query_range('node_cpu_seconds_total', {}, START, END)

    def test_datadog(self):
        from integrations.adapters.datadog_metrics import DatadogMetricProvider
        provider = DatadogMetricProvider({'api_key': 'k', 'app_key': 'a', 'host': 'https://api.datadoghq.eu'})
        with patch.object(provider._session, 'get', return_value=_response(403)):
            with self.assertRaises(MetricQueryError) as raised:
                provider.query_range('node_cpu_seconds_total', {'organisation_name': 'acme'}, START, END)
        self.assertIn('HTTP 403', str(raised.exception))


class GcpLoggingFailClosedTest(SimpleTestCase):
    """CL-1: list_entries is lazy, so a refused read arrives while iterating."""

    def provider(self, iterator):
        from integrations.adapters.gcp_logging import GcpCloudLoggingProvider
        provider = GcpCloudLoggingProvider.__new__(GcpCloudLoggingProvider)
        provider._project_id = 'serops-test'
        provider._max_page_size = 1000
        provider._client = MagicMock()
        provider._client.list_entries.return_value = iterator
        provider._log_name_clause = lambda index: ''
        provider._to_log_entry = lambda entry, index: entry
        return provider

    def test_refused_before_any_entry_raises(self):
        class PermissionDenied(Exception):
            pass

        def refused():
            raise PermissionDenied('403 caller does not have permission')
            yield  # pragma: no cover

        with self.assertRaises(LogSearchError) as raised:
            self.provider(refused()).search('', {'filter': 'severity>=ERROR'})
        self.assertIn('Logs Viewer', str(raised.exception))

    def test_refused_after_some_entries_keeps_them_and_says_partial(self):
        def two_then_quota():
            yield 'a'
            yield 'b'
            raise RuntimeError('429 RESOURCE_EXHAUSTED')

        provider = self.provider(two_then_quota())
        provider.last_search_notes = []
        self.assertEqual(provider.search('', {'filter': 'x'}), ['a', 'b'])
        self.assertTrue(any('after 2 entries' in n for n in provider.last_search_notes))


class GcpMonitoringVmFailClosedTest(SimpleTestCase):
    """CL-11 on the VM path added by !112 (_vm_series)."""

    def test_refused_vm_query_raises(self):
        from integrations.adapters.gcp_monitoring import GcpCloudMonitoringProvider
        provider = GcpCloudMonitoringProvider.__new__(GcpCloudMonitoringProvider)
        provider._client = MagicMock()
        provider._client.list_time_series.side_effect = RuntimeError('403 permission denied')
        provider._vm_request = lambda gcp_type, start, end, extra='': {}
        with self.assertRaises(MetricQueryError):
            provider._vm_series(GcpCloudMonitoringProvider._VM_CPU, {}, START, END)
