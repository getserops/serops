"""Unit tests for the Grafana Tempo trace adapter.

Uses ``unittest.mock`` to stub HTTP calls — no live Tempo needed.
Covers:

* ``fetch_traces`` — hits /api/search, then hydrates each hit via
  ``fetch_trace`` (search returns trace-summary only).
* ``fetch_trace`` — parses OTLP JSON via the shared parser so IDs
  match native OTLP-ingested traces.
* Multi-tenant ``X-Scope-OrgID`` header set from config.
* 404 → None (not-found trace should not blow up).
* ConnectionError → [] / None (never raise into RCA path).
* Legacy ``{"batches": [...]}`` shape from older Tempo versions works
  the same as the modern ``{"resourceSpans": [...]}``.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from django.test import TestCase
from requests.exceptions import ConnectionError

from integrations.adapters.tempo_traces import TempoTraceAdapter


def _mock_response(status_code=200, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body if json_body is not None else {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        from requests.exceptions import HTTPError
        resp.raise_for_status.side_effect = HTTPError(f'{status_code}')
    return resp


def _otlp_payload(trace_id_hex, error=False):
    """A minimal OTLP resourceSpans body — same shape Tempo returns."""
    return {
        'resourceSpans': [{
            'resource': {
                'attributes': [
                    {'key': 'service.name', 'value': {'stringValue': 'checkout'}},
                ],
            },
            'scopeSpans': [{
                'spans': [
                    {
                        'traceId': trace_id_hex,
                        'spanId': '1' * 16,
                        'parentSpanId': '',
                        'name': 'POST /checkout',
                        'kind': 'SPAN_KIND_SERVER',
                        'startTimeUnixNano': '1730000000000000000',
                        'endTimeUnixNano': '1730000000250000000',
                        'status': {'code': 'STATUS_CODE_ERROR' if error else 'STATUS_CODE_OK'},
                    },
                    {
                        'traceId': trace_id_hex,
                        'spanId': '2' * 16,
                        'parentSpanId': '1' * 16,
                        'name': 'db.query',
                        'kind': 'SPAN_KIND_CLIENT',
                        'startTimeUnixNano': '1730000000010000000',
                        'endTimeUnixNano': '1730000000150000000',
                        'status': {'code': 'STATUS_CODE_OK'},
                    },
                ],
            }],
        }],
    }


class TempoTenancyTest(TestCase):

    def test_tenant_id_becomes_x_scope_org_id(self):
        adapter = TempoTraceAdapter(config={
            'host': 'http://tempo-test:3200',
            'extra_config': {'tenant_id': 'team-a'},
        })
        self.assertEqual(adapter._session.headers.get('X-Scope-OrgID'), 'team-a')

    def test_no_tenant_id_ok(self):
        adapter = TempoTraceAdapter(config={'host': 'http://tempo-test:3200'})
        self.assertNotIn('X-Scope-OrgID', adapter._session.headers)


class TempoFetchTraceTest(TestCase):

    def setUp(self):
        self.adapter = TempoTraceAdapter(config={'host': 'http://tempo-test:3200'})
        self.trace_id = 'a' * 32

    def test_fetch_trace_ok(self):
        with patch.object(
            self.adapter._session, 'get',
            return_value=_mock_response(200, _otlp_payload(self.trace_id)),
        ):
            trace = self.adapter.fetch_trace(self.trace_id)
        self.assertIsNotNone(trace)
        self.assertEqual(trace.trace_id, self.trace_id)
        self.assertEqual(trace.root_service_name, 'checkout')
        self.assertEqual(trace.root_operation, 'POST /checkout')
        self.assertEqual(trace.span_count, 2)
        self.assertEqual(trace.error_span_count, 0)
        # Child span linkage survives the parse.
        child = next(s for s in trace.spans if s.parent_span_id)
        self.assertEqual(child.parent_span_id, '1' * 16)

    def test_fetch_trace_error_flag(self):
        with patch.object(
            self.adapter._session, 'get',
            return_value=_mock_response(200, _otlp_payload(self.trace_id, error=True)),
        ):
            trace = self.adapter.fetch_trace(self.trace_id)
        self.assertEqual(trace.status_code, 'ERROR')
        self.assertEqual(trace.error_span_count, 1)

    def test_fetch_trace_legacy_batches_shape(self):
        """Older Tempo returned {"batches": [...]} instead of "resourceSpans"."""
        legacy_body = {'batches': _otlp_payload(self.trace_id)['resourceSpans']}
        with patch.object(
            self.adapter._session, 'get',
            return_value=_mock_response(200, legacy_body),
        ):
            trace = self.adapter.fetch_trace(self.trace_id)
        self.assertIsNotNone(trace)
        self.assertEqual(trace.span_count, 2)

    def test_fetch_trace_404_returns_none(self):
        with patch.object(
            self.adapter._session, 'get',
            return_value=_mock_response(404),
        ):
            self.assertIsNone(self.adapter.fetch_trace(self.trace_id))

    def test_fetch_trace_network_error(self):
        with patch.object(self.adapter._session, 'get', side_effect=ConnectionError('down')):
            self.assertIsNone(self.adapter.fetch_trace(self.trace_id))

    def test_fetch_trace_empty_payload_returns_none(self):
        with patch.object(
            self.adapter._session, 'get',
            return_value=_mock_response(200, {'resourceSpans': []}),
        ):
            self.assertIsNone(self.adapter.fetch_trace(self.trace_id))


class TempoFetchTracesTest(TestCase):

    def setUp(self):
        self.adapter = TempoTraceAdapter(config={'host': 'http://tempo-test:3200'})
        self.since = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        self.until = self.since + timedelta(hours=1)

    def test_fetch_traces_search_then_hydrate(self):
        """/api/search returns trace IDs; adapter hydrates each via fetch_trace."""
        trace_id = 'b' * 32

        def side_effect(url, **kwargs):
            if '/api/search' in url:
                return _mock_response(200, {'traces': [{'traceID': trace_id}]})
            if '/api/traces/' in url:
                return _mock_response(200, _otlp_payload(trace_id))
            return _mock_response(404)

        with patch.object(self.adapter._session, 'get', side_effect=side_effect):
            traces = self.adapter.fetch_traces('checkout', self.since, self.until, limit=5)

        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0].trace_id, trace_id)
        self.assertEqual(traces[0].span_count, 2)

    def test_fetch_traces_network_error_returns_empty(self):
        with patch.object(self.adapter._session, 'get', side_effect=ConnectionError('boom')):
            self.assertEqual(
                self.adapter.fetch_traces('svc', self.since, self.until), [],
            )

    def test_fetch_traces_skips_hits_that_fail_hydrate(self):
        """If /api/traces/<id> 404s, we drop that trace but keep others."""
        good_id = 'c' * 32
        bad_id = 'd' * 32

        def side_effect(url, **kwargs):
            if '/api/search' in url:
                return _mock_response(200, {'traces': [
                    {'traceID': bad_id},
                    {'traceID': good_id},
                ]})
            if f'/api/traces/{good_id}' in url:
                return _mock_response(200, _otlp_payload(good_id))
            return _mock_response(404)

        with patch.object(self.adapter._session, 'get', side_effect=side_effect):
            traces = self.adapter.fetch_traces('svc', self.since, self.until)

        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0].trace_id, good_id)


class TempoHealthCheckTest(TestCase):

    def setUp(self):
        self.adapter = TempoTraceAdapter(config={'host': 'http://tempo-test:3200'})

    def test_health_ok(self):
        with patch.object(self.adapter._session, 'get',
                          return_value=_mock_response(200, {})):
            self.assertTrue(self.adapter.health_check())

    def test_health_down(self):
        with patch.object(self.adapter._session, 'get', side_effect=ConnectionError('nope')):
            self.assertFalse(self.adapter.health_check())
