"""Tests for PrometheusMetricProvider."""
from unittest.mock import patch, MagicMock
from datetime import datetime

from django.test import SimpleTestCase

from integrations.adapters.prometheus import PrometheusMetricProvider


class TestPrometheusMetricProvider(SimpleTestCase):

    def setUp(self):
        self.provider = PrometheusMetricProvider(config={
            "host": "http://prometheus:9090",
        })

    # ---- health_check ----

    @patch("integrations.adapters.prometheus.requests.Session.get")
    def test_health_check_success(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        self.assertTrue(self.provider.health_check())
        mock_get.assert_called_once()
        self.assertIn("/-/healthy", mock_get.call_args[0][0])

    @patch("integrations.adapters.prometheus.requests.Session.get")
    def test_health_check_failure(self, mock_get):
        mock_get.return_value = MagicMock(status_code=503)
        self.assertFalse(self.provider.health_check())

    @patch("integrations.adapters.prometheus.requests.Session.get")
    def test_health_check_exception(self, mock_get):
        from requests.exceptions import ConnectionError
        mock_get.side_effect = ConnectionError("refused")
        self.assertFalse(self.provider.health_check())

    # ---- query_range ----

    @patch("integrations.adapters.prometheus.requests.Session.get")
    def test_query_range_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "data": {
                "resultType": "matrix",
                "result": [
                    {
                        "metric": {"instance": "web-1:9100", "organisation_name": "acme"},
                        "values": [
                            [1672531200.0, "100.5"],
                            [1672531260.0, "105.0"],
                        ],
                    },
                    {
                        "metric": {"instance": "web-2:9100", "organisation_name": "acme"},
                        "values": [
                            [1672531200.0, "50.0"],
                        ],
                    },
                ],
            },
        }
        mock_get.return_value = mock_resp

        results = self.provider.query_range(
            metric="node_memory_MemTotal_bytes",
            labels={"organisation_name": "acme"},
            start=datetime(2023, 1, 1, 0, 0, 0),
            end=datetime(2023, 1, 1, 1, 0, 0),
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].metric_name, "node_memory_MemTotal_bytes")
        self.assertEqual(len(results[0].points), 2)
        self.assertAlmostEqual(results[0].points[0].value, 100.5)
        self.assertEqual(results[0].labels["instance"], "web-1:9100")

        # Verify PromQL selector was built correctly
        call_kwargs = mock_get.call_args[1]
        self.assertIn('organisation_name="acme"', call_kwargs["params"]["query"])

    @patch("integrations.adapters.prometheus.requests.Session.get")
    def test_query_range_empty(self, mock_get):
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

    # ---- discover_hosts ----

    @patch("integrations.adapters.prometheus.requests.Session.get")
    def test_discover_hosts(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "data": [
                {"instance": "web-1:9100", "hostname": "web-1", "environment": "prod"},
                {"instance": "db-1:9100", "hostname": "db-1", "environment": "staging"},
            ],
        }
        mock_get.return_value = mock_resp

        hosts = self.provider.discover_hosts(org="acme", project="backend")

        self.assertEqual(len(hosts), 2)
        self.assertEqual(hosts[0].hostname, "web-1")
        self.assertEqual(hosts[0].environment, "prod")
        self.assertEqual(hosts[0].labels["instance"], "web-1:9100")
        self.assertEqual(hosts[0].project, "backend")

    # ---- helpers ----

    def test_build_selector_no_labels(self):
        result = PrometheusMetricProvider._build_selector("up", {})
        self.assertEqual(result, "up")

    def test_build_selector_with_labels(self):
        result = PrometheusMetricProvider._build_selector(
            "node_memory_MemTotal_bytes", {"organisation_name": "acme", "env": "prod"}
        )
        self.assertIn('organisation_name="acme"', result)
        self.assertIn('env="prod"', result)
        self.assertTrue(result.startswith("node_memory_MemTotal_bytes{"))

    def test_auto_step_short_range(self):
        step = PrometheusMetricProvider._auto_step(
            datetime(2023, 1, 1, 12, 0), datetime(2023, 1, 1, 12, 30)
        )
        self.assertEqual(step, "15s")

    def test_auto_step_long_range(self):
        step = PrometheusMetricProvider._auto_step(
            datetime(2023, 1, 1), datetime(2023, 1, 3)
        )
        self.assertEqual(step, "15m")
