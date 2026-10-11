"""Tests for Datadog Log and Metric providers."""
from unittest.mock import patch, MagicMock
from datetime import datetime

from django.test import SimpleTestCase

from integrations.adapters.datadog_logs import DatadogLogProvider
from integrations.adapters.datadog_metrics import DatadogMetricProvider


class TestDatadogLogProvider(SimpleTestCase):

    def setUp(self):
        self.provider = DatadogLogProvider(config={
            "site": "datadoghq.com",
            "api_key": "test-api-key",
            "app_key": "test-app-key",
        })

    @patch("integrations.adapters.datadog_logs.requests.Session.get")
    def test_health_check_success(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        self.assertTrue(self.provider.health_check())
        self.assertIn("/api/v1/validate", mock_get.call_args[0][0])

    @patch("integrations.adapters.datadog_logs.requests.Session.get")
    def test_health_check_invalid_key(self, mock_get):
        mock_get.return_value = MagicMock(status_code=403)
        self.assertFalse(self.provider.health_check())

    def test_auth_headers_set(self):
        self.assertEqual(
            self.provider._session.headers.get("DD-API-KEY"), "test-api-key"
        )
        self.assertEqual(
            self.provider._session.headers.get("DD-APPLICATION-KEY"), "test-app-key"
        )

    @patch("integrations.adapters.datadog_logs.requests.Session.post")
    def test_search_basic(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {
                    "id": "dd-log-1",
                    "attributes": {
                        "timestamp": "2023-01-01T12:00:00Z",
                        "message": "Error connecting to DB",
                        "status": "error",
                        "service": "api-gateway",
                        "host": "web-1",
                        "tags": ["env:prod", "service:api-gateway"],
                    },
                }
            ]
        }
        mock_post.return_value = mock_resp

        results = self.provider.search(
            index="main",
            query={},
            time_range=(datetime(2023, 1, 1), datetime(2023, 1, 2)),
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].message, "Error connecting to DB")
        self.assertEqual(results[0].level, "ERROR")
        self.assertEqual(results[0].raw_id, "dd-log-1")
        self.assertEqual(results[0].labels.get("env"), "prod")

    @patch("integrations.adapters.datadog_logs.requests.Session.get")
    def test_get_indices(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "indexes": [
                {"name": "main"},
                {"name": "security"},
            ]
        }
        mock_get.return_value = mock_resp

        project = MagicMock()
        result = self.provider.get_indices(project)
        self.assertEqual(result, ["main", "security"])

    def test_build_query_basic(self):
        q = DatadogLogProvider._build_query("", {})
        self.assertEqual(q, "*")

    def test_build_query_with_index_and_text(self):
        q = DatadogLogProvider._build_query("main", {
            "match_phrase": {"message": "timeout"}
        })
        self.assertIn("index:main", q)
        self.assertIn("timeout", q)


class TestDatadogMetricProvider(SimpleTestCase):

    def setUp(self):
        self.provider = DatadogMetricProvider(config={
            "site": "datadoghq.com",
            "api_key": "test-api-key",
            "app_key": "test-app-key",
        })

    @patch("integrations.adapters.datadog_metrics.requests.Session.get")
    def test_health_check(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        self.assertTrue(self.provider.health_check())

    @patch("integrations.adapters.datadog_metrics.requests.Session.get")
    def test_query_range(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "series": [
                {
                    "scope": "host:web-1",
                    "pointlist": [
                        [1672531200000, 8589934592.0],
                        [1672531260000, 8589934000.0],
                    ],
                }
            ]
        }
        mock_get.return_value = mock_resp

        results = self.provider.query_range(
            metric="node_memory_MemTotal_bytes",
            labels={"host": "web-1"},
            start=datetime(2023, 1, 1),
            end=datetime(2023, 1, 2),
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(len(results[0].points), 2)
        self.assertEqual(results[0].labels.get("host"), "web-1")

        # Verify DD query format
        call_kwargs = mock_get.call_args[1]
        query = call_kwargs["params"]["query"]
        self.assertIn("system.mem.total", query)
        self.assertIn("host:web-1", query)

    @patch("integrations.adapters.datadog_metrics.requests.Session.get")
    def test_discover_hosts(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "host_list": [
                {
                    "name": "web-1",
                    "tags_by_source": {
                        "Datadog": ["env:prod", "role:web"],
                    },
                },
            ]
        }
        mock_get.return_value = mock_resp

        hosts = self.provider.discover_hosts(org="acme")
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0].hostname, "web-1")
        self.assertEqual(hosts[0].environment, "prod")

    def test_build_metric_query_with_labels(self):
        q = DatadogMetricProvider._build_metric_query(
            "node_memory_MemTotal_bytes", {"organisation_name": "acme"}
        )
        self.assertEqual(q, "avg:system.mem.total{organisation_name:acme}")

    def test_build_metric_query_no_labels(self):
        q = DatadogMetricProvider._build_metric_query(
            "node_cpu_seconds_total", {}
        )
        self.assertEqual(q, "avg:system.cpu.user{*}")
