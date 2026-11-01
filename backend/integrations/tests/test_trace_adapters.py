"""Unit tests for Jaeger / Zipkin / Datadog trace adapters.

Uses ``unittest.mock`` to stub the requests.Session.get / .post calls
— no live network hits. Each test verifies:

* Vendor JSON round-trips into canonical TraceEntry / SpanEntry.
* IDs are left-padded to OTEL widths (32/16 hex).
* Statuses map correctly (error tags → ERROR).
* fetch_trace(404) returns None cleanly.
* Network errors return [] (fetch_traces) or None (fetch_trace)
  without raising, so RCA enrichment never dies on a flaky provider.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from django.test import TestCase
from requests.exceptions import ConnectionError

from integrations.adapters.datadog_traces import DatadogTraceAdapter
from integrations.adapters.jaeger_traces import JaegerTraceAdapter
from integrations.adapters.zipkin_traces import ZipkinTraceAdapter


def _mock_response(status_code=200, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body if json_body is not None else {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        from requests.exceptions import HTTPError
        resp.raise_for_status.side_effect = HTTPError(f'{status_code}')
    return resp


# ============================================================================
# Jaeger
# ============================================================================


class JaegerAdapterTest(TestCase):

    def setUp(self):
        self.adapter = JaegerTraceAdapter(config={'host': 'http://jaeger-test:16686'})

    def _sample(self, error=False):
        return {
            'data': [{
                'traceID': 'abc123',
                'spans': [
                    {
                        'spanID': 'span0',
                        'operationName': 'GET /api',
                        'processID': 'p1',
                        'startTime': 1_700_000_000_000_000,   # micros
                        'duration': 250_000,                  # 250ms
                        'tags': [
                            {'key': 'span.kind', 'value': 'server'},
                            {'key': 'error', 'value': True} if error else
                            {'key': 'http.status_code', 'value': 200},
                        ],
                    },
                    {
                        'spanID': 'span1',
                        'operationName': 'db.query',
                        'processID': 'p1',
                        'startTime': 1_700_000_000_010_000,
                        'duration': 140_000,
                        'references': [{'refType': 'CHILD_OF', 'spanID': 'span0'}],
                        'tags': [{'key': 'db.system', 'value': 'postgresql'}],
                    },
                ],
                'processes': {'p1': {'serviceName': 'checkout'}},
            }]
        }

    def test_fetch_traces_ok(self):
        with patch.object(self.adapter._session, 'get',
                          return_value=_mock_response(200, self._sample())):
            traces = self.adapter.fetch_traces(
                'checkout',
                datetime(2026, 9, 4), datetime(2026, 9, 4, 1), limit=10,
            )
        self.assertEqual(len(traces), 1)
        trace = traces[0]
        # ID left-padded to OTEL width.
        self.assertEqual(len(trace.trace_id), 32)
        self.assertTrue(trace.trace_id.endswith('abc123'))
        self.assertEqual(trace.root_service_name, 'checkout')
        self.assertEqual(trace.root_operation, 'GET /api')
        self.assertEqual(trace.span_count, 2)
        self.assertEqual(trace.error_span_count, 0)
        self.assertEqual(trace.status_code, 'OK')
        # Parent linkage preserved.
        child = next(s for s in trace.spans if s.operation_name == 'db.query')
        self.assertTrue(child.parent_span_id.endswith('span0'))

    def test_fetch_traces_error_span_marks_trace_error(self):
        with patch.object(self.adapter._session, 'get',
                          return_value=_mock_response(200, self._sample(error=True))):
            traces = self.adapter.fetch_traces(
                'checkout', datetime.utcnow(), datetime.utcnow(), limit=10,
            )
        self.assertEqual(traces[0].error_span_count, 1)
        self.assertEqual(traces[0].status_code, 'ERROR')

    def test_fetch_trace_404_returns_none(self):
        with patch.object(self.adapter._session, 'get',
                          return_value=_mock_response(404)):
            self.assertIsNone(self.adapter.fetch_trace('abc'))

    def test_network_error_returns_empty(self):
        with patch.object(self.adapter._session, 'get', side_effect=ConnectionError('boom')):
            self.assertEqual(self.adapter.fetch_traces('svc', datetime.utcnow(), datetime.utcnow()), [])
            self.assertIsNone(self.adapter.fetch_trace('abc'))

    def test_health_check(self):
        with patch.object(self.adapter._session, 'get',
                          return_value=_mock_response(200, {})):
            self.assertTrue(self.adapter.health_check())
        with patch.object(self.adapter._session, 'get', side_effect=ConnectionError('nope')):
            self.assertFalse(self.adapter.health_check())


# ============================================================================
# Zipkin
# ============================================================================


class ZipkinAdapterTest(TestCase):

    def setUp(self):
        self.adapter = ZipkinTraceAdapter(config={'host': 'http://zipkin-test:9411'})

    def _sample(self, error=False):
        return [[
            {
                'traceId': 'abcd',
                'id': 'span0',
                'name': 'POST /checkout',
                'kind': 'SERVER',
                'timestamp': 1_700_000_000_000_000,
                'duration': 250_000,
                'localEndpoint': {'serviceName': 'checkout'},
                'tags': {'error': 'timeout'} if error else {'http.status': '200'},
                'annotations': [
                    {'timestamp': 1_700_000_000_050_000, 'value': 'ws'},
                ],
            },
            {
                'traceId': 'abcd',
                'id': 'span1',
                'parentId': 'span0',
                'name': 'db.query',
                'timestamp': 1_700_000_000_010_000,
                'duration': 140_000,
                'localEndpoint': {'serviceName': 'checkout'},
                'tags': {},
            },
        ]]

    def test_fetch_traces_ok(self):
        with patch.object(self.adapter._session, 'get',
                          return_value=_mock_response(200, self._sample())):
            traces = self.adapter.fetch_traces(
                'checkout', datetime.utcnow(), datetime.utcnow(), limit=10,
            )
        self.assertEqual(len(traces), 1)
        trace = traces[0]
        self.assertEqual(len(trace.trace_id), 32)
        self.assertEqual(trace.root_service_name, 'checkout')
        self.assertEqual(trace.status_code, 'OK')
        # Annotations become events.
        root = next(s for s in trace.spans if not s.parent_span_id)
        self.assertEqual(len(root.events), 1)
        self.assertEqual(root.events[0].name, 'ws')

    def test_fetch_traces_error_tag(self):
        with patch.object(self.adapter._session, 'get',
                          return_value=_mock_response(200, self._sample(error=True))):
            traces = self.adapter.fetch_traces(
                'checkout', datetime.utcnow(), datetime.utcnow(),
            )
        self.assertEqual(traces[0].status_code, 'ERROR')

    def test_fetch_trace_404_returns_none(self):
        with patch.object(self.adapter._session, 'get',
                          return_value=_mock_response(404)):
            self.assertIsNone(self.adapter.fetch_trace('abcd'))

    def test_network_error_returns_empty(self):
        with patch.object(self.adapter._session, 'get', side_effect=ConnectionError('boom')):
            self.assertEqual(self.adapter.fetch_traces('svc', datetime.utcnow(), datetime.utcnow()), [])
            self.assertIsNone(self.adapter.fetch_trace('abc'))


# ============================================================================
# Datadog APM
# ============================================================================


class DatadogAdapterTest(TestCase):

    def setUp(self):
        self.adapter = DatadogTraceAdapter(config={
            'extra_config': {'api_key': 'k', 'app_key': 'a', 'site': 'datadoghq.com'},
        })

    def _sample(self, error=False):
        return {
            'data': [
                {
                    'id': 'span0',
                    'type': 'spans',
                    'attributes': {
                        'trace_id': 'ff01',
                        'span_id': 'span0',
                        'parent_id': '0',
                        'service': 'checkout',
                        'resource_name': 'POST /checkout',
                        'type': 'web',
                        'start_timestamp': '2026-09-04T12:00:00Z',
                        'end_timestamp': '2026-09-04T12:00:00.250Z',
                        'duration': 250_000_000,   # nanos
                        'status': 'error' if error else 'ok',
                        'custom': {'http.status_code': 500 if error else 200},
                    },
                },
                {
                    'id': 'span1',
                    'type': 'spans',
                    'attributes': {
                        'trace_id': 'ff01',
                        'span_id': 'span1',
                        'parent_id': 'span0',
                        'service': 'checkout',
                        'resource_name': 'db.query',
                        'start_timestamp': '2026-09-04T12:00:00.010Z',
                        'end_timestamp': '2026-09-04T12:00:00.150Z',
                        'duration': 140_000_000,
                        'status': 'ok',
                        'custom': {},
                    },
                },
            ]
        }

    def test_fetch_traces_ok(self):
        with patch.object(self.adapter._session, 'post',
                          return_value=_mock_response(200, self._sample())):
            traces = self.adapter.fetch_traces(
                'checkout', datetime(2026, 9, 4, tzinfo=timezone.utc),
                datetime(2026, 9, 4, 1, tzinfo=timezone.utc),
            )
        self.assertEqual(len(traces), 1)
        trace = traces[0]
        self.assertEqual(len(trace.trace_id), 32)
        self.assertEqual(trace.root_service_name, 'checkout')
        self.assertEqual(trace.root_operation, 'POST /checkout')
        self.assertEqual(trace.span_count, 2)

    def test_fetch_traces_error_status(self):
        with patch.object(self.adapter._session, 'post',
                          return_value=_mock_response(200, self._sample(error=True))):
            traces = self.adapter.fetch_traces(
                'checkout',
                datetime(2026, 9, 4, tzinfo=timezone.utc),
                datetime(2026, 9, 4, 1, tzinfo=timezone.utc),
            )
        self.assertEqual(traces[0].status_code, 'ERROR')
        self.assertEqual(traces[0].error_span_count, 1)

    def test_network_error_returns_empty(self):
        with patch.object(self.adapter._session, 'post', side_effect=ConnectionError('boom')):
            self.assertEqual(self.adapter.fetch_traces(
                'svc',
                datetime(2026, 9, 4, tzinfo=timezone.utc),
                datetime(2026, 9, 4, 1, tzinfo=timezone.utc),
            ), [])
            self.assertIsNone(self.adapter.fetch_trace('abc'))

    def test_parent_zero_becomes_root(self):
        with patch.object(self.adapter._session, 'post',
                          return_value=_mock_response(200, self._sample())):
            traces = self.adapter.fetch_traces(
                'checkout',
                datetime(2026, 9, 4, tzinfo=timezone.utc),
                datetime(2026, 9, 4, 1, tzinfo=timezone.utc),
            )
        # span0 has parent_id "0" → treated as root (empty parent).
        root = next(s for s in traces[0].spans if not s.parent_span_id)
        self.assertTrue(root.span_id.endswith('span0'))


class DatadogHealthCheckTest(TestCase):
    """Test connection must try a span search: an application key scoped for
    logs and metrics only passed /api/v1/validate, then every fetch got 403."""

    def setUp(self):
        self.adapter = DatadogTraceAdapter(config={
            'extra_config': {'api_key': 'k', 'app_key': 'a', 'site': 'datadoghq.eu'},
        })

    def test_an_application_key_without_apm_read_fails_and_says_so(self):
        with patch.object(self.adapter._session, 'get', return_value=_mock_response(200, {'valid': True})), \
                patch.object(self.adapter._session, 'post', return_value=_mock_response(403, {'errors': ['Forbidden']})):
            self.assertFalse(self.adapter.health_check())
        self.assertIn('apm_read', self.adapter.last_error)

    def test_a_key_that_can_search_spans_is_healthy(self):
        with patch.object(self.adapter._session, 'get', return_value=_mock_response(200, {'valid': True})), \
                patch.object(self.adapter._session, 'post', return_value=_mock_response(200, {'data': []})) as post:
            self.assertTrue(self.adapter.health_check())
        self.assertIn('/api/v2/spans/events/search', post.call_args.args[0])
        self.assertIsNone(self.adapter.last_error)

    def test_an_invalid_api_key_fails_and_names_the_site(self):
        with patch.object(self.adapter._session, 'get', return_value=_mock_response(403, {})):
            self.assertFalse(self.adapter.health_check())
        self.assertIn('datadoghq.eu', self.adapter.last_error)


class DatadogLiveShapeTest(TestCase):
    """The request and span shape of the real Datadog EU API (2026-10-31)."""

    # A span as /api/v2/spans/events/search returns it for an OTLP-fed
    # service: decimal span ids, start and end, no duration.
    LIVE = {'data': [{'id': 'x', 'type': 'spans', 'attributes': {
        'service': 'payments', 'resource_name': 'GET /charge', 'operation_name': 'server',
        'trace_id': 'ad2afdbd7a3e7584e57dbb9f764f613f', 'span_id': '8779938157922599378',
        'parent_id': '14205786948509074645', 'start_timestamp': '2026-10-31T22:22:38.78Z',
        'end_timestamp': '2026-10-31T22:22:39.074Z', 'status': 'ok', 'error': 0, 'env': 'production',
        'custom': {}, 'tags': [], 'type': 'web'}}]}

    def setUp(self):
        self.adapter = DatadogTraceAdapter(config={
            'extra_config': {'api_key': 'k', 'app_key': 'a', 'site': 'datadoghq.eu'},
        })

    def test_every_search_says_it_is_a_search_request(self):
        """Without it Datadog answers 400: every fetch had failed."""
        with patch.object(self.adapter._session, 'post', return_value=_mock_response(200, self.LIVE)) as post:
            self.adapter.fetch_traces('payments', datetime(2026, 10, 31, 22, tzinfo=timezone.utc),
                                      datetime(2026, 10, 31, 23, tzinfo=timezone.utc))
            self.adapter.fetch_trace('ad2afdbd7a3e7584e57dbb9f764f613f')
        for call in post.call_args_list:
            self.assertEqual(call.kwargs['json']['data']['type'], 'search_request')
        # A trace looked up by id is searched beyond Datadog's 15-minute default.
        self.assertEqual(post.call_args_list[1].kwargs['json']['data']['attributes']['filter']['from'], 'now-15d')

    def test_a_live_span_gets_its_duration_and_hex_ids(self):
        with patch.object(self.adapter._session, 'post', return_value=_mock_response(200, self.LIVE)):
            [trace] = self.adapter.fetch_traces('payments', datetime(2026, 10, 31, 22, tzinfo=timezone.utc),
                                                datetime(2026, 10, 31, 23, tzinfo=timezone.utc))
        [span] = trace.spans
        self.assertEqual(span.duration_ms, 294)
        self.assertEqual(span.span_id, format(8779938157922599378, 'x').rjust(16, '0'))
        self.assertEqual(span.status_code, 'OK')

    def test_the_error_flag_marks_an_error_span(self):
        live = {'data': [{**self.LIVE['data'][0], 'attributes': {
            **self.LIVE['data'][0]['attributes'], 'status': 'ok', 'error': 1}}]}
        with patch.object(self.adapter._session, 'post', return_value=_mock_response(200, live)):
            [trace] = self.adapter.fetch_traces('payments', datetime(2026, 10, 31, 22, tzinfo=timezone.utc),
                                                datetime(2026, 10, 31, 23, tzinfo=timezone.utc))
        self.assertEqual(trace.error_span_count, 1)

    def test_a_refused_search_fails_the_health_check(self):
        with patch.object(self.adapter._session, 'get', return_value=_mock_response(200, {'valid': True})), \
                patch.object(self.adapter._session, 'post', return_value=_mock_response(400, {})):
            self.assertFalse(self.adapter.health_check())
        self.assertIn('400', self.adapter.last_error)
