"""Tests for ai_model.trace_context — trace enrichment for RCA prompts.

Covers:

* Native OTLP path — spans in Trace/Span tables produce top_slow /
  top_errors / services_touched.
* Empty batch → returns None cleanly.
* Cross-org isolation — no leakage of another org's traces.
* Service filter — only spans for the project's services are included.
* External-provider fallback — used only when native returns 0 spans;
  wrapped in try/except so a broken provider doesn't kill RCA.
* Prompt formatter — produces expected header sections; empty
  summary returns empty string.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from django.test import TestCase

from ai_model.trace_context import (
    build_trace_context, format_trace_context_for_prompt,
    snapshot_trace_context,
)
from Organisations.models import Organisations
from Projects.models import Project
from traces.models import Span, Trace


def _fake_batch(project, when):
    """Minimal batch stand-in — we only touch .timestamp, .project, .data."""
    class _B:
        pass
    b = _B()
    b.timestamp = when
    b.project = project
    b.data = {}
    return b


class TraceContextNativeTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='CtxOrg')
        cls.other_org = Organisations.objects.create(name='OtherCtxOrg')
        cls.project = Project.objects.create(
            organisation=cls.org, name='ctx-project',
        )
        # Project services — required so build_trace_context can filter.
        from Projects.models import ProjectService
        ProjectService.objects.create(project=cls.project, name='checkout', service_type='application')
        ProjectService.objects.create(project=cls.project, name='api', service_type='application')

        base = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        cls.window_end = base + timedelta(minutes=10)

        # In-window trace for org — checkout with one slow span + one error.
        cls.trace = Trace.objects.create(
            trace_id='a' * 32,
            organisation=cls.org,
            root_service_name='checkout',
            root_operation='POST /checkout',
            start_time=base + timedelta(minutes=1),
            end_time=base + timedelta(minutes=1, milliseconds=300),
            duration_ms=300,
            span_count=2,
            error_span_count=1,
            status_code='ERROR',
        )
        Span.objects.create(
            trace=cls.trace, span_id='1' * 16, parent_span_id='',
            service_name='checkout', operation_name='POST /checkout',
            start_time=base + timedelta(minutes=1),
            end_time=base + timedelta(minutes=1, milliseconds=300),
            duration_ms=300, status_code='OK',
        )
        Span.objects.create(
            trace=cls.trace, span_id='2' * 16, parent_span_id='1' * 16,
            service_name='checkout', operation_name='db.query',
            start_time=base + timedelta(minutes=1, milliseconds=10),
            end_time=base + timedelta(minutes=1, milliseconds=150),
            duration_ms=140, status_code='ERROR', status_message='timeout',
        )

        # Cross-org trace — must NEVER leak.
        Trace.objects.create(
            trace_id='b' * 32,
            organisation=cls.other_org,
            root_service_name='checkout',
            root_operation='op',
            start_time=base + timedelta(minutes=2),
            end_time=base + timedelta(minutes=2, milliseconds=999),
            duration_ms=999,
        )

    def test_native_path_returns_summary(self):
        batch = _fake_batch(self.project, self.window_end)
        summary = build_trace_context(batch)
        self.assertIsNotNone(summary)
        self.assertEqual(summary['source'], 'otlp')
        self.assertEqual(summary['span_count'], 2)
        self.assertEqual(summary['error_span_count'], 1)
        self.assertEqual(summary['trace_count'], 1)
        # Slowest span (300ms) leads.
        self.assertEqual(summary['top_slow'][0]['duration_ms'], 300)
        # Error span surfaced with message.
        self.assertEqual(summary['top_errors'][0]['status_message'], 'timeout')

    def test_batch_time_range_is_the_window(self):
        # An investigation over 12:00-12:10 analysed two hours later still
        # reads the traces of its own window, not the interval before it.
        batch = _fake_batch(self.project, self.window_end + timedelta(hours=2))
        batch.data = {'statistics': {'time_range': {
            'start': '2026-09-04T12:00:00Z', 'end': '2026-09-04T12:10:00Z'}}}
        summary = build_trace_context(batch)
        self.assertIsNotNone(summary)
        self.assertEqual(summary['trace_count'], 1)

    def test_a_service_that_never_roots_a_trace_gets_its_traces(self):
        """payments is called by a frontend outside the project: its traces
        are rooted elsewhere, and the analysis used to get none (journey suite)."""
        from Projects.models import Project, ProjectService
        backend = Project.objects.create(organisation=self.org, name='backend-only')
        ProjectService.objects.create(project=backend, name='db', service_type='application')
        Span.objects.create(
            trace=self.trace, span_id='3' * 16, parent_span_id='1' * 16,
            service_name='db', operation_name='SELECT',
            start_time=self.trace.start_time, end_time=self.trace.end_time,
            duration_ms=20, status_code='OK')
        summary = build_trace_context(_fake_batch(backend, self.window_end))
        self.assertIsNotNone(summary)
        self.assertIn('db', summary['services_touched'])

    def test_none_batch_returns_none(self):
        self.assertIsNone(build_trace_context(None))

    def test_batch_without_timestamp_returns_none(self):
        class _B: pass
        b = _B()
        b.timestamp = None
        b.project = self.project
        b.data = {}
        self.assertIsNone(build_trace_context(b))

    def test_cross_org_isolation(self):
        # Batch in the same window but for the other org's project —
        # never sees our trace.
        other_project = Project.objects.create(
            organisation=self.other_org, name='foreign',
        )
        batch = _fake_batch(other_project, self.window_end)
        summary = build_trace_context(batch)
        # Other org has 1 trace with no spans — native returns None.
        self.assertIsNone(summary)


    def test_another_org_holding_the_same_trace_id_adds_none_of_its_spans(self):
        # Security review 2026-11, finding 1: a trace id is unique per org
        # only, so the span lookup must go by trace row, not trace id.
        twin = Trace.objects.create(
            trace_id='a' * 32, organisation=self.other_org,
            root_service_name='checkout', root_operation='op',
            start_time=self.trace.start_time, end_time=self.trace.end_time,
            duration_ms=5000,
        )
        Span.objects.create(
            trace=twin, span_id='7' * 16, service_name='checkout',
            operation_name='foreign-op', start_time=self.trace.start_time,
            end_time=self.trace.end_time, duration_ms=5000, status_code='ERROR',
        )

        summary = build_trace_context(_fake_batch(self.project, self.window_end))

        self.assertEqual(summary['span_count'], 2)
        self.assertNotIn('foreign-op', {s['operation_name'] for s in summary['top_slow']})
        self.assertEqual(summary['top_slow'][0]['trace_id'], 'a' * 32)


class TraceContextExternalFallbackTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='ExtCtxOrg')
        cls.project = Project.objects.create(
            organisation=cls.org, name='ext-ctx-project',
        )
        from Projects.models import ProjectService
        ProjectService.objects.create(project=cls.project, name='checkout', service_type='application')

    def test_falls_back_to_provider_when_no_native(self):
        # No native Trace rows for this org → external adapter is tried.
        fake_provider = MagicMock()
        from traces.schemas import SpanEntry, TraceEntry
        fake_provider.fetch_traces.return_value = [
            TraceEntry(
                trace_id='c' * 32,
                root_service_name='checkout',
                root_operation='GET /health',
                start_time=datetime.utcnow(),
                end_time=datetime.utcnow(),
                duration_ms=500,
                span_count=1,
                error_span_count=0,
                spans=[SpanEntry(
                    trace_id='c' * 32,
                    span_id='0' * 16,
                    service_name='checkout',
                    operation_name='GET /health',
                    duration_ms=500,
                    status_code='OK',
                )],
            )
        ]

        with patch(
            'integrations.registry.IntegrationRegistry.get_trace_provider_for_org',
            return_value=fake_provider,
        ):
            batch = _fake_batch(self.project, datetime.utcnow())
            summary = build_trace_context(batch)

        self.assertIsNotNone(summary)
        self.assertEqual(summary['source'], 'external')
        self.assertGreaterEqual(summary['span_count'], 1)

    def test_provider_exception_returns_none_not_500(self):
        fake_provider = MagicMock()
        fake_provider.fetch_traces.side_effect = RuntimeError('adapter blew up')
        with patch(
            'integrations.registry.IntegrationRegistry.get_trace_provider_for_org',
            return_value=fake_provider,
        ):
            batch = _fake_batch(self.project, datetime.utcnow())
            # Should NOT raise, should not return partial data.
            summary = build_trace_context(batch)
        self.assertIsNone(summary)

    def test_no_provider_configured_returns_none(self):
        with patch(
            'integrations.registry.IntegrationRegistry.get_trace_provider_for_org',
            return_value=None,
        ):
            batch = _fake_batch(self.project, datetime.utcnow())
            self.assertIsNone(build_trace_context(batch))


class TraceContextSnapshotTest(TestCase):
    """Snapshot persistence — write once at batch creation, read back forever."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='SnapOrg')
        from Projects.models import Project, ProjectService
        cls.project = Project.objects.create(organisation=cls.org, name='snap-project')
        ProjectService.objects.create(
            project=cls.project, name='checkout', service_type='application',
        )

        base = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        cls.window_end = base + timedelta(minutes=10)
        cls.trace = Trace.objects.create(
            trace_id='e' * 32,
            organisation=cls.org,
            root_service_name='checkout',
            root_operation='POST /snap',
            start_time=base + timedelta(minutes=1),
            end_time=base + timedelta(minutes=1, milliseconds=500),
            duration_ms=500,
            span_count=1,
            error_span_count=0,
            status_code='OK',
        )
        Span.objects.create(
            trace=cls.trace, span_id='0' * 16, parent_span_id='',
            service_name='checkout', operation_name='POST /snap',
            start_time=base + timedelta(minutes=1),
            end_time=base + timedelta(minutes=1, milliseconds=500),
            duration_ms=500, status_code='OK',
        )

    def _batch_with_data(self):
        """Batch stub with the shape ``snapshot_trace_context`` needs."""
        class _B:
            pass
        b = _B()
        b.timestamp = self.window_end
        b.project = self.project
        b.data = {}
        # Track save() calls so we can assert persistence.
        b.saved_fields = []
        def save(update_fields=None):
            b.saved_fields.append(tuple(update_fields or []))
        b.save = save
        return b

    def test_snapshot_writes_to_batch_data(self):
        batch = self._batch_with_data()
        result = snapshot_trace_context(batch)
        self.assertIsNotNone(result)
        self.assertIn('traces', batch.data)
        self.assertEqual(batch.data['traces']['span_count'], 1)
        # Persisted via save(update_fields=['data']).
        self.assertIn(('data',), batch.saved_fields)

    def test_snapshot_is_json_serialisable(self):
        """batch.data lands in a JSONField — the snapshot must round-trip."""
        import json
        batch = self._batch_with_data()
        snapshot_trace_context(batch)
        # Should not raise.
        json.dumps(batch.data['traces'])

    def test_build_prefers_snapshot_over_live(self):
        """Once snapshotted, live queries are skipped — reproducible."""
        batch = self._batch_with_data()
        snapshot_trace_context(batch)
        # Mutate the DB so a live query would return something different.
        Trace.objects.filter(pk=self.trace.pk).delete()
        # build_trace_context must still return the snapshot (not None).
        summary = build_trace_context(batch)
        self.assertIsNotNone(summary)
        self.assertEqual(summary['span_count'], 1)

    def test_snapshot_failure_never_raises(self):
        """If save() blows up, snapshot returns None instead of propagating."""
        batch = self._batch_with_data()
        def bad_save(update_fields=None):
            raise RuntimeError('DB down')
        batch.save = bad_save
        self.assertIsNone(snapshot_trace_context(batch))

    def test_snapshot_none_batch(self):
        self.assertIsNone(snapshot_trace_context(None))


class TraceContextFormatterTest(TestCase):

    def test_empty_summary_yields_empty_string(self):
        self.assertEqual(format_trace_context_for_prompt(None), '')
        self.assertEqual(format_trace_context_for_prompt({}), '')
        self.assertEqual(format_trace_context_for_prompt({'span_count': 0}), '')

    def test_formatter_produces_expected_sections(self):
        summary = {
            'source': 'otlp',
            'span_count': 5,
            'error_span_count': 1,
            'trace_count': 2,
            'services_touched': ['api', 'checkout'],
            'top_slow': [
                {'trace_id': 'aa' * 16, 'service_name': 'checkout',
                 'operation_name': 'POST /x', 'duration_ms': 900},
            ],
            'top_errors': [
                {'trace_id': 'bb' * 16, 'service_name': 'api',
                 'operation_name': 'db.query', 'status_message': 'timeout'},
            ],
        }
        text = format_trace_context_for_prompt(summary)
        self.assertIn('Distributed Traces:', text)
        self.assertIn('Source: otlp', text)
        self.assertIn('Services in window: api, checkout', text)
        self.assertIn('900ms', text)
        self.assertIn('timeout', text)


class ServiceTimingsTest(TestCase):
    """Self time puts latency on the service it happens in, not on its callers
    (production scenario B4 on Online Boutique: the top-5 slowest spans were
    all the frontend waiting on a slow catalogue, and the frontend was blamed)."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='TimingOrg')
        cls.project = Project.objects.create(organisation=cls.org, name='shop')
        from Projects.models import ProjectService
        for name in ('frontend', 'catalog', 'cart'):
            ProjectService.objects.create(project=cls.project, name=name, service_type='application')
        cls.base = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
        cls.window_end = cls.base + timedelta(minutes=15)

        def trace(n, at, catalog_ms):
            t = Trace.objects.create(
                trace_id=f'{n:032x}', organisation=cls.org, root_service_name='frontend',
                root_operation='GET /product', start_time=at,
                end_time=at + timedelta(milliseconds=catalog_ms + 10),
                duration_ms=catalog_ms + 10)
            # frontend server span -> frontend client span -> catalog server span
            spans = [('a', '', 'frontend', 'GET /product', catalog_ms + 10),
                     ('b', 'a', 'frontend', 'grpc.client/GetProduct', catalog_ms + 2),
                     ('c', 'b', 'catalog', 'GetProduct', catalog_ms),
                     ('d', 'a', 'cart', 'GetCart', 3)]
            for sid, parent, svc, op, ms in spans:
                Span.objects.create(
                    trace=t, span_id=sid * 16, parent_span_id=parent * 16 if parent else '',
                    service_name=svc, operation_name=op, start_time=at,
                    end_time=at + timedelta(milliseconds=ms), duration_ms=ms, status_code='OK')

        for i in range(10):    # the window before: healthy
            trace(i, cls.base - timedelta(minutes=10, seconds=i), 5)
        for i in range(10):    # this window: the catalog takes 3s
            trace(100 + i, cls.base + timedelta(minutes=5, seconds=i), 3000)

    def batch(self):
        b = _fake_batch(self.project, self.window_end)
        b.data = {'statistics': {'time_range': {
            'start': '2026-11-02T12:00:00Z', 'end': '2026-11-02T12:15:00Z'}}}
        return b

    def test_latency_is_on_the_catalog_not_the_frontend(self):
        summary = build_trace_context(self.batch())
        rows = {r['service_name']: r for r in summary['per_service']}
        self.assertEqual(summary['per_service'][0]['service_name'], 'catalog')
        self.assertEqual(rows['catalog']['self_p95_ms'], 3000)
        self.assertEqual(rows['catalog']['slowest_operation'], 'GetProduct')
        # The frontend's total is slow, its own time is not.
        self.assertEqual(rows['frontend']['p95_ms'], 3010)
        self.assertLessEqual(rows['frontend']['self_p95_ms'], 10)

    def test_each_service_is_compared_with_the_window_before(self):
        summary = build_trace_context(self.batch())
        catalog = next(r for r in summary['per_service'] if r['service_name'] == 'catalog')
        self.assertEqual(catalog['baseline']['self_p95_ms'], 5)
        self.assertEqual(catalog['baseline']['spans'], 10)

    def test_the_prompt_lists_self_time_and_the_window_before(self):
        text = format_trace_context_for_prompt(build_trace_context(self.batch()))
        self.assertIn('Per-service timings', text)
        self.assertIn('catalog: 10 spans (window before: 10), p50 3000ms, p95 3000ms, self p95 3000ms, 0 errors '
                      '(window before: p95 5ms, self p95 5ms); slowest own time: GetProduct 3000ms', text)

    def test_same_traffic_is_not_called_a_change(self):
        text = format_trace_context_for_prompt(build_trace_context(self.batch()))
        self.assertIn('Traffic: 40 spans in this window, 40 in the window before\n', text)

    def test_parallel_children_never_give_negative_self_time(self):
        from ai_model.trace_context import _service_timings
        rows = [('t', 'p', '', 'api', 'GET /', 100, 'OK'),
                ('t', 'c1', 'p', 'db', 'q1', 90, 'OK'),
                ('t', 'c2', 'p', 'db', 'q2', 90, 'ERROR')]
        timings = _service_timings(rows)
        self.assertEqual(timings['api']['self_p95_ms'], 0)
        self.assertEqual(timings['db']['errors'], 1)


class TrafficChangeTest(TestCase):
    """A traffic surge shows as a change in volume, counted past the 500-trace
    cap the timings use (production scenario R9 on Online Boutique: a 5x
    load-generator surge slowed every service and the analysis blamed one
    service's client code)."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='SurgeOrg')
        cls.project = Project.objects.create(organisation=cls.org, name='shop')
        from Projects.models import ProjectService
        for name in ('frontend', 'catalog'):
            ProjectService.objects.create(project=cls.project, name=name, service_type='application')
        other = Organisations.objects.create(name='OtherOrg')
        cls.base = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
        n = 0

        def trace(org, at, ms):
            nonlocal n
            n += 1
            t = Trace.objects.create(
                trace_id=f'{n:032x}', organisation=org, root_service_name='frontend',
                root_operation='GET /', start_time=at, end_time=at + timedelta(milliseconds=ms),
                duration_ms=ms)
            for sid, parent, svc in (('a', '', 'frontend'), ('b', 'a', 'catalog')):
                Span.objects.create(
                    trace=t, span_id=sid * 16, parent_span_id=parent * 16 if parent else '',
                    service_name=svc, operation_name='op', start_time=at,
                    end_time=at + timedelta(milliseconds=ms), duration_ms=ms, status_code='OK')

        for i in range(4):     # the window before
            trace(cls.org, cls.base - timedelta(minutes=10, seconds=i), 20)
        for i in range(20):    # this window: five times the traffic, slower
            trace(cls.org, cls.base + timedelta(minutes=5, seconds=i), 900)
        for i in range(30):    # another organisation's traffic never counts
            trace(other, cls.base + timedelta(minutes=5, seconds=i), 5)

    def batch(self):
        b = _fake_batch(self.project, self.base + timedelta(minutes=15))
        b.data = {'statistics': {'time_range': {
            'start': '2026-11-02T12:00:00Z', 'end': '2026-11-02T12:15:00Z'}}}
        return b

    def test_volume_per_service_and_in_total(self):
        summary = build_trace_context(self.batch())
        self.assertEqual(summary['traffic'], {'spans': 40, 'before': 8})
        rows = {r['service_name']: r for r in summary['per_service']}
        self.assertEqual(rows['catalog']['traffic'], {'spans': 20, 'before': 4})

    def test_the_prompt_shows_the_surge(self):
        text = format_trace_context_for_prompt(build_trace_context(self.batch()))
        self.assertIn('Traffic: 40 spans in this window, 8 in the window before (x5.0)', text)
        self.assertIn('catalog: 20 spans (window before: 4) (x5.0), p50 900ms', text)

    def test_counts_are_not_capped_by_the_timing_sample(self):
        # The timings read a capped sample of traces (500 in production);
        # simulate a cap of 2 and the traffic still counts every span.
        from ai_model import trace_context
        real = trace_context._project_trace_pks
        with patch.object(trace_context, '_project_trace_pks',
                          side_effect=lambda *a: real(*a)[:2]):
            summary = build_trace_context(self.batch())
        rows = {r['service_name']: r for r in summary['per_service']}
        self.assertEqual(rows['catalog']['spans'], 2)
        self.assertEqual(summary['traffic'], {'spans': 40, 'before': 8})

    def test_the_analysis_prompt_tells_the_model_to_check_traffic_first(self):
        from ai_model.prompts import get_batch_analysis_system_prompt
        self.assertIn('look at traffic before code', get_batch_analysis_system_prompt())
