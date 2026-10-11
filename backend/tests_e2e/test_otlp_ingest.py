"""E2E: OTLP HTTP ingest → Trace/Span persisted → read API returns waterfall.

Exercises the trace-ingest seam (Item #10 in the launch plan) end-to-end:
a real OTLP JSON payload POSTed to ``/api/traces/v1/traces`` with a
Bearer IngestKey → the receiver parses the ``resourceSpans`` tree,
persists Trace + Span rows scoped to the key's organisation → the
authenticated read API (``/api/traces/traces/<trace_id>/``) returns
the full trace with its child spans in a shape the frontend
``TraceDetail`` waterfall consumes.

Every layer runs for real: bearer auth, protobuf/JSON dispatch, span
parsing, DB writes, org-scoping on the read viewset, and the
serialiser the frontend depends on. Only the outbound self-metrics
Prometheus counter is fire-and-forget on the ingest path — no network
hop to stub.
"""

from __future__ import annotations

from traces.models import IngestKey, Span, Trace

from .base import E2ETestCase


class OTLPIngestE2ETest(E2ETestCase):

    _PLAINTEXT_KEY = 'serops_otlp_e2e_test_key_do_not_reuse_xxx'

    def setUp(self):
        super().setUp()
        # Wire an IngestKey to the primary org so a Bearer header the
        # test controls will authenticate the OTLP receiver. We build
        # the row directly because IngestKey CRUD is admin-scoped
        # (covered by its own unit tests) — creating one via ORM
        # exercises the same set_key/verify path the CRUD ultimately
        # calls.
        self.key = IngestKey(
            organisation=self.org,
            name='e2e-primary-key',
            is_active=True,
        )
        self.key.set_key(self._PLAINTEXT_KEY)
        self.key.save()

    # ------------------------------------------------------------------
    # OTLP payload builder — matches the OTLP HTTP JSON spec verbatim.
    # ------------------------------------------------------------------

    def _payload(
        self,
        *,
        trace_id: str = 'a' * 32,
        parent_span_id: str = 'b' * 16,
        child_span_id: str = 'c' * 16,
        service_name: str = 'checkout',
    ) -> dict:
        """One trace, two spans (parent server span + child client span).

        Shape lifted from the OTLP HTTP JSON spec. The receiver's parser
        reads exactly this — camelCase keys, ns-precision timestamps,
        stringValue attribute leaves. Any drift here means the parser
        broke, not the fixture.
        """
        start_ns = 1_700_000_000_000_000_000
        end_ns = start_ns + 500_000_000  # 500 ms trace duration
        child_end = start_ns + 200_000_000

        return {
            'resourceSpans': [
                {
                    'resource': {
                        'attributes': [
                            {'key': 'service.name', 'value': {'stringValue': service_name}},
                            {'key': 'service.version', 'value': {'stringValue': '1.4.2'}},
                            {'key': 'deployment.environment', 'value': {'stringValue': 'production'}},
                        ],
                    },
                    'scopeSpans': [
                        {
                            'scope': {'name': 'checkout-instrumentation', 'version': '0.1.0'},
                            'spans': [
                                {
                                    'traceId': trace_id,
                                    'spanId': parent_span_id,
                                    'name': 'POST /checkout',
                                    'kind': 2,   # SERVER
                                    'startTimeUnixNano': str(start_ns),
                                    'endTimeUnixNano': str(end_ns),
                                    'status': {'code': 1},   # OK
                                    'attributes': [
                                        {'key': 'http.method', 'value': {'stringValue': 'POST'}},
                                        {'key': 'http.status_code', 'value': {'intValue': 200}},
                                    ],
                                },
                                {
                                    'traceId': trace_id,
                                    'spanId': child_span_id,
                                    'parentSpanId': parent_span_id,
                                    'name': 'redis.SET session',
                                    'kind': 3,   # CLIENT
                                    'startTimeUnixNano': str(start_ns + 10_000_000),
                                    'endTimeUnixNano': str(child_end),
                                    'status': {'code': 2, 'message': 'timeout'},   # ERROR
                                    'attributes': [
                                        {'key': 'db.system', 'value': {'stringValue': 'redis'}},
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        }

    def _bearer(self, key: str = _PLAINTEXT_KEY) -> dict:
        return {'HTTP_AUTHORIZATION': f'Bearer {key}'}

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_full_ingest_creates_trace_and_spans_visible_on_read_api(self):
        self.client.force_authenticate(user=None)   # OTLP is bearer, not Django auth

        payload = self._payload()
        resp = self.client.post(
            '/api/traces/v1/traces',
            data=payload,
            format='json',
            **self._bearer(),
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['accepted_traces'], 1)
        self.assertEqual(resp.data['accepted_spans'], 2)

        # DB assertions — one trace, two spans, all scoped to primary org.
        traces = Trace.objects.filter(organisation=self.org)
        self.assertEqual(traces.count(), 1)
        trace = traces.get()
        self.assertEqual(trace.trace_id, 'a' * 32)
        self.assertEqual(trace.root_service_name, 'checkout')

        spans = Span.objects.filter(trace=trace).order_by('start_time')
        self.assertEqual(spans.count(), 2)
        span_names = [s.operation_name for s in spans]
        self.assertEqual(span_names, ['POST /checkout', 'redis.SET session'])

        # Read API — authenticate as the org's admin.
        self.client.force_authenticate(user=self.admin)
        detail = self.client.get(f'/api/traces/traces/{trace.trace_id}/')
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(detail.data['trace_id'], trace.trace_id)
        self.assertEqual(len(detail.data['spans']), 2)
        # Child span must carry its parent_span_id — the frontend
        # waterfall keys off this to reconstruct the tree.
        child = next(
            s for s in detail.data['spans']
            if s['span_id'] == 'c' * 16
        )
        self.assertEqual(child['parent_span_id'], 'b' * 16)

    def test_missing_bearer_key_is_401_and_no_rows_created(self):
        self.client.force_authenticate(user=None)

        resp = self.client.post(
            '/api/traces/v1/traces',
            data=self._payload(),
            format='json',
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(Trace.objects.count(), 0)
        self.assertEqual(Span.objects.count(), 0)

    def test_wrong_bearer_key_is_401_no_leak(self):
        self.client.force_authenticate(user=None)

        # A well-formed but unregistered key — verify() will lookup by
        # its SHA-256 hash and find nothing.
        resp = self.client.post(
            '/api/traces/v1/traces',
            data=self._payload(),
            format='json',
            **self._bearer(key='serops_otlp_never_issued_xxx'),
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(Trace.objects.count(), 0)

    def test_inactive_key_cannot_ingest(self):
        """Revoking a key by flipping is_active=False must reject
        immediately — key rotation is worth nothing if a revoked key
        still lets spans in."""
        self.client.force_authenticate(user=None)

        self.key.is_active = False
        self.key.save(update_fields=['is_active'])

        resp = self.client.post(
            '/api/traces/v1/traces',
            data=self._payload(),
            format='json',
            **self._bearer(),
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(Trace.objects.count(), 0)

    def test_other_org_cannot_read_ingested_trace(self):
        """Ingest → cross-org GET must 404. IngestKeys are scoped to
        one org; the OTLP receiver honours that; the read viewset
        must honour it too."""
        self.client.force_authenticate(user=None)

        payload = self._payload()
        ingest = self.client.post(
            '/api/traces/v1/traces',
            data=payload, format='json', **self._bearer(),
        )
        self.assertEqual(ingest.status_code, 200)

        # Switch to the second org's admin — they must not see the
        # trace even though they know its 32-hex id.
        self._auth(self.other_admin)
        resp = self.client.get(f"/api/traces/traces/{'a' * 32}/")
        self.assertEqual(resp.status_code, 404)

    def test_empty_resource_spans_is_200_zero_ingest(self):
        """OTLP HTTP spec: an empty resourceSpans payload is legitimate
        (health-check style). Receiver must 200 without persisting rows
        so a collector's zero-batch heartbeat doesn't error-loop."""
        self.client.force_authenticate(user=None)

        resp = self.client.post(
            '/api/traces/v1/traces',
            data={'resourceSpans': []},
            format='json',
            **self._bearer(),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['accepted_traces'], 0)
        self.assertEqual(resp.data['accepted_spans'], 0)
        self.assertEqual(Trace.objects.count(), 0)
