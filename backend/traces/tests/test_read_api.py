"""Tests for the traces read API (list + detail + services)."""

from datetime import datetime, timedelta, timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from Organisations.models import Organisations
from traces.models import Span, Trace

User = get_user_model()


class TraceReadApiTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='ReadOrg')
        cls.other_org = Organisations.objects.create(name='OtherReadOrg')
        cls.user = User.objects.create_user(
            username='reader', email='r@t.com', password='p',
            organisation=cls.org, role='user', is_active=True,
        )
        cls.other_user = User.objects.create_user(
            username='outsider', email='o@t.com', password='p',
            organisation=cls.other_org, role='user', is_active=True,
        )

        base = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)

        cls.trace_a = Trace.objects.create(
            trace_id='a' * 32,
            organisation=cls.org,
            root_service_name='checkout',
            root_operation='POST /checkout',
            start_time=base,
            end_time=base + timedelta(milliseconds=250),
            duration_ms=250,
            span_count=3,
            error_span_count=0,
            status_code='OK',
        )
        cls.trace_b = Trace.objects.create(
            trace_id='b' * 32,
            organisation=cls.org,
            root_service_name='api',
            root_operation='GET /users',
            start_time=base + timedelta(hours=1),
            end_time=base + timedelta(hours=1, milliseconds=50),
            duration_ms=50,
            span_count=1,
            error_span_count=1,
            status_code='ERROR',
        )
        # Cross-org trace — must never leak.
        Trace.objects.create(
            trace_id='c' * 32,
            organisation=cls.other_org,
            root_service_name='other-service',
            root_operation='op',
            start_time=base,
            end_time=base + timedelta(milliseconds=10),
            duration_ms=10,
        )

        # Spans for trace_a — used to test detail waterfall.
        Span.objects.create(
            trace=cls.trace_a, span_id='1' * 16, parent_span_id='',
            service_name='checkout', operation_name='POST /checkout',
            start_time=base, end_time=base + timedelta(milliseconds=250),
            duration_ms=250, status_code='OK',
        )
        Span.objects.create(
            trace=cls.trace_a, span_id='2' * 16, parent_span_id='1' * 16,
            service_name='checkout', operation_name='db.query',
            start_time=base + timedelta(milliseconds=10),
            end_time=base + timedelta(milliseconds=150),
            duration_ms=140, status_code='OK',
            attributes={'db.system': 'postgresql'},
        )

    def setUp(self):
        self.client = APIClient()

    # ─── auth ────────────────────────────────────────────────────────

    def test_list_requires_auth(self):
        response = self.client.get('/api/traces/traces/')
        self.assertIn(response.status_code, (401, 403))

    def test_detail_requires_auth(self):
        response = self.client.get(f'/api/traces/traces/{self.trace_a.trace_id}/')
        self.assertIn(response.status_code, (401, 403))

    # ─── list ────────────────────────────────────────────────────────

    def test_list_scoped_to_org(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/traces/traces/')
        self.assertEqual(response.status_code, 200)
        trace_ids = {t['trace_id'] for t in response.json()['results']}
        self.assertEqual(trace_ids, {'a' * 32, 'b' * 32})

    def test_outsider_sees_zero(self):
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get('/api/traces/traces/')
        self.assertEqual(response.status_code, 200)
        # Only the other-org trace is visible to that user.
        trace_ids = {t['trace_id'] for t in response.json()['results']}
        self.assertEqual(trace_ids, {'c' * 32})

    def test_list_orders_newest_first(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/traces/traces/')
        ids = [t['trace_id'] for t in response.json()['results']]
        # trace_b starts 1 hour after trace_a, so it comes first.
        self.assertEqual(ids, ['b' * 32, 'a' * 32])

    # ─── filters ─────────────────────────────────────────────────────

    def test_filter_by_service(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/traces/traces/?service=checkout')
        results = response.json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['trace_id'], 'a' * 32)

    def test_filter_by_status(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/traces/traces/?status=ERROR')
        results = response.json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['trace_id'], 'b' * 32)

    def test_filter_by_status_lowercase(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/traces/traces/?status=error')
        results = response.json()['results']
        self.assertEqual(len(results), 1)

    def test_filter_by_min_duration(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/traces/traces/?min_duration_ms=100')
        results = response.json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['trace_id'], 'a' * 32)  # 250ms

    def test_bad_min_duration_ignored_not_500(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/traces/traces/?min_duration_ms=foo')
        self.assertEqual(response.status_code, 200)
        # Both traces still returned — filter is silently dropped.
        self.assertEqual(len(response.json()['results']), 2)

    def test_filter_by_time_window(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            '/api/traces/traces/'
            '?since=2026-09-04T12:30:00Z'
            '&until=2026-09-04T14:00:00Z'
        )
        results = response.json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['trace_id'], 'b' * 32)

    def test_bad_since_ignored(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/traces/traces/?since=not-a-date')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['results']), 2)

    # ─── detail ──────────────────────────────────────────────────────

    def test_detail_returns_trace_with_spans(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/traces/traces/{self.trace_a.trace_id}/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['trace_id'], 'a' * 32)
        self.assertEqual(len(data['spans']), 2)
        # Ordered by start_time (root first, then child).
        self.assertEqual(data['spans'][0]['span_id'], '1' * 16)
        self.assertEqual(data['spans'][1]['span_id'], '2' * 16)
        # JSONB attributes round-trip cleanly.
        self.assertEqual(data['spans'][1]['attributes'], {'db.system': 'postgresql'})

    def test_detail_cross_org_returns_404(self):
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(f'/api/traces/traces/{self.trace_a.trace_id}/')
        self.assertEqual(response.status_code, 404)

    def test_detail_bad_trace_id_shape_404(self):
        self.client.force_authenticate(user=self.user)
        # Not 32 hex — router regex rejects → 404.
        response = self.client.get('/api/traces/traces/not-a-trace-id/')
        self.assertEqual(response.status_code, 404)

    # ─── services helper ─────────────────────────────────────────────

    def test_services_list(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/traces/traces/services/')
        self.assertEqual(response.status_code, 200)
        # Only the caller's org's service names, sorted.
        self.assertEqual(response.json(), ['api', 'checkout'])

    def test_a_service_that_never_starts_a_trace_can_be_filtered_on(self):
        """payments only appears as a child span (journey suite, B12)."""
        Span.objects.create(
            trace=self.trace_a, span_id='3' * 16, parent_span_id='1' * 16,
            service_name='payments', operation_name='POST /charge',
            start_time=self.trace_a.start_time, end_time=self.trace_a.end_time,
            duration_ms=100, status_code='ERROR')
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.get('/api/traces/traces/services/').json(), ['api', 'checkout', 'payments'])
        results = self.client.get('/api/traces/traces/?service=payments').json()['results']
        self.assertEqual([r['trace_id'] for r in results], ['a' * 32])
