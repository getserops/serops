"""Tests for VictoriaMetrics and Mimir metric providers."""
from unittest.mock import patch, MagicMock
from datetime import datetime

from django.test import SimpleTestCase

from integrations.adapters.victoriametrics import VictoriaMetricsMetricProvider
from integrations.adapters.mimir import MimirMetricProvider


class TestVictoriaMetricsProvider(SimpleTestCase):

    def setUp(self):
        self.provider = VictoriaMetricsMetricProvider(config={
            "host": "http://vm:8428",
        })

    @patch("integrations.adapters.prometheus.requests.Session.get")
    def test_health_check_uses_health_endpoint(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        self.assertTrue(self.provider.health_check())
        self.assertIn("/health", mock_get.call_args[0][0])
        # Should NOT use /-/healthy
        self.assertNotIn("/-/healthy", mock_get.call_args[0][0])

    @patch("integrations.adapters.prometheus.requests.Session.get")
    def test_health_check_failure(self, mock_get):
        mock_get.return_value = MagicMock(status_code=503)
        self.assertFalse(self.provider.health_check())

    @patch("integrations.adapters.prometheus.requests.Session.get")
    def test_query_range_inherited(self, mock_get):
        """Verify query_range is inherited from PrometheusMetricProvider."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "data": {"resultType": "matrix", "result": []},
        }
        mock_get.return_value = mock_resp

        results = self.provider.query_range(
            metric="node_cpu_seconds_total",
            labels={},
            start=datetime(2023, 1, 1),
            end=datetime(2023, 1, 2),
        )
        self.assertEqual(results, [])
        # Should use /api/v1/query_range (Prometheus-compatible path)
        self.assertIn("/api/v1/query_range", mock_get.call_args[0][0])

    def test_capabilities(self):
        self.assertFalse(self.provider.capabilities.exemplars)
        self.assertEqual(self.provider.capabilities.max_query_window_days, 90)


class TestMimirProvider(SimpleTestCase):

    def setUp(self):
        self.provider = MimirMetricProvider(config={
            "host": "http://mimir:9009",
            "tenant_id": "acme",
        })

    @patch("integrations.adapters.prometheus.requests.Session.get")
    def test_health_check_uses_ready_endpoint(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        self.assertTrue(self.provider.health_check())
        self.assertIn("/ready", mock_get.call_args[0][0])

    @patch("integrations.adapters.prometheus.requests.Session.get")
    def test_not_ready_but_queries_work_passes(self, mock_get):
        """Client C2: /ready 503 while the ring forms, queries already fine."""
        mock_get.side_effect = [MagicMock(status_code=503, text="Some services are not Running"),
                                MagicMock(status_code=200)]
        self.assertTrue(self.provider.health_check())
        self.assertEqual(mock_get.call_args[0][0], "http://mimir:9009/prometheus/api/v1/query")

    @patch("integrations.adapters.prometheus.requests.Session.get")
    def test_not_ready_says_what_mimir_said(self, mock_get):
        mock_get.side_effect = [MagicMock(status_code=503, text="Some services are not Running:\nStarting: 1"),
                                MagicMock(status_code=503, text="")]
        self.assertFalse(self.provider.health_check())
        self.assertIn('HTTP 503 on /ready ("Some services are not Running:")', self.provider.last_error)
        self.assertIn("/prometheus/api/v1/query", self.provider.last_error)
        self.assertIn("retry", self.provider.last_error)

    @patch("integrations.adapters.prometheus.requests.Session.get")
    def test_wrong_tenant_says_so(self, mock_get):
        mock_get.side_effect = [MagicMock(status_code=404, text=""), MagicMock(status_code=401, text="no org id")]
        self.assertFalse(self.provider.health_check())
        self.assertIn("X-Scope-OrgID", self.provider.last_error)

    def test_tenant_header_set(self):
        self.assertEqual(
            self.provider._session.headers.get("X-Scope-OrgID"), "acme"
        )

    @patch("integrations.adapters.prometheus.requests.Session.get")
    def test_query_range_uses_prometheus_prefix(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "data": {"resultType": "matrix", "result": []},
        }
        mock_get.return_value = mock_resp

        self.provider.query_range(
            metric="up", labels={},
            start=datetime(2023, 1, 1), end=datetime(2023, 1, 2),
        )
        # Should use /prometheus/api/v1/query_range
        call_url = mock_get.call_args[0][0]
        self.assertIn("/prometheus/api/v1/query_range", call_url)

    def test_capabilities(self):
        self.assertTrue(self.provider.capabilities.exemplars)
        self.assertEqual(self.provider.capabilities.max_query_window_days, 365)
