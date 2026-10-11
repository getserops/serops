"""Tests for the self-metrics endpoint + middleware (Item #24)."""

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from Data.self_metrics import (
    ALERT_RECEIVED, BATCH_CREATED, HTTP_REQUESTS, OTLP_SPANS_RECEIVED,
    bucket_endpoint, bucket_status,
)


class BucketFunctionsTest(TestCase):

    def test_endpoint_specific_before_generic(self):
        self.assertEqual(bucket_endpoint('/api/data/batches/abc/timeline/'), 'data_batch_timeline')
        self.assertEqual(bucket_endpoint('/api/data/batches/abc/'), 'data_batch_detail')
        self.assertEqual(bucket_endpoint('/api/data/batches'), 'data_batch_list')

    def test_endpoint_traces(self):
        self.assertEqual(bucket_endpoint('/api/traces/v1/traces'), 'otlp_traces')
        self.assertEqual(bucket_endpoint('/api/traces/keys/'), 'traces_keys')

    def test_endpoint_alert_webhook(self):
        self.assertEqual(bucket_endpoint('/api/webhooks/alerts/alertmanager/42/'), 'alert_webhook')

    def test_endpoint_unknown_falls_back(self):
        self.assertEqual(bucket_endpoint('/random/path/'), 'other')

    def test_status_class(self):
        self.assertEqual(bucket_status(200), '2xx')
        self.assertEqual(bucket_status(404), '4xx')
        self.assertEqual(bucket_status(500), '5xx')
        self.assertEqual(bucket_status(302), '3xx')
        self.assertEqual(bucket_status('bogus'), 'other')


class MetricsEndpointTest(TestCase):

    def setUp(self):
        self.client = APIClient()

    def test_returns_prometheus_content_type(self):
        response = self.client.get('/metrics/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/plain', response['Content-Type'])
        # Exposition should include our declared metric families.
        body = response.content.decode()
        self.assertIn('serops_up', body)
        self.assertIn('serops_batch_created_total', body)
        self.assertIn('serops_http_requests_total', body)

    def test_metric_increment_visible(self):
        BATCH_CREATED.labels(outcome='created').inc()
        body = self.client.get('/metrics/').content.decode()
        # After the inc(), the counter line must be present with a value.
        self.assertRegex(body, r'serops_batch_created_total\{outcome="created"\}\s+\S+')

    def test_up_gauge_is_one(self):
        body = self.client.get('/metrics/').content.decode()
        self.assertIn('serops_up 1.0', body)

    @override_settings()
    def test_basic_auth_when_configured(self):
        import os
        os.environ['SEROPS_METRICS_BASIC_AUTH'] = 'user:pass'
        try:
            # No credentials → 401.
            r = self.client.get('/metrics/')
            self.assertEqual(r.status_code, 401)
            self.assertIn('WWW-Authenticate', r)
            # Wrong credentials → 401.
            import base64
            wrong = base64.b64encode(b'user:wrong').decode()
            r = self.client.get('/metrics/', HTTP_AUTHORIZATION=f'Basic {wrong}')
            self.assertEqual(r.status_code, 401)
            # Right credentials → 200.
            right = base64.b64encode(b'user:pass').decode()
            r = self.client.get('/metrics/', HTTP_AUTHORIZATION=f'Basic {right}')
            self.assertEqual(r.status_code, 200)
        finally:
            del os.environ['SEROPS_METRICS_BASIC_AUTH']


class RequestMiddlewareTest(TestCase):
    """The middleware auto-increments HTTP_REQUESTS on every response."""

    def setUp(self):
        self.client = APIClient()

    def test_hitting_health_bumps_counter(self):
        # Capture before.
        before = self.client.get('/metrics/').content.decode()
        # Trigger any request.
        self.client.get('/api/health/')
        after = self.client.get('/metrics/').content.decode()
        # Same lookup pattern — health bucket should now appear or grow.
        self.assertIn('endpoint_group="health"', after)
        # Exact-count check is fragile across parallel tests, but the
        # label combination should exist post-request.
        self.assertNotEqual(before, after)
