"""Tests for LokiLogProvider."""
from unittest.mock import patch, MagicMock
from datetime import datetime

from django.test import SimpleTestCase

from integrations.adapters.loki import LokiLogProvider


class TestLokiLogProvider(SimpleTestCase):

    def setUp(self):
        self.provider = LokiLogProvider(config={
            "host": "http://loki:3100",
        })

    # ---- health_check ----

    @patch("integrations.adapters.loki.requests.Session.get")
    def test_health_check_success(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        self.assertTrue(self.provider.health_check())
        self.assertIn("/ready", mock_get.call_args[0][0])

    @patch("integrations.adapters.loki.requests.Session.get")
    def test_health_check_failure(self, mock_get):
        mock_get.return_value = MagicMock(status_code=503)
        self.assertFalse(self.provider.health_check())

    # ---- search ----

    @patch("integrations.adapters.loki.requests.Session.get")
    def test_search_basic(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "data": {
                "resultType": "streams",
                "result": [
                    {
                        "stream": {
                            "app": "myapp",
                            "level": "error",
                            "host": "web-1",
                        },
                        "values": [
                            ["1672531200000000000", "Connection refused to database"],
                            ["1672531260000000000", "Retry attempt 1 failed"],
                        ],
                    }
                ],
            },
        }
        mock_get.return_value = mock_resp

        results = self.provider.search(
            index="myapp",
            query={},
            time_range=(datetime(2023, 1, 1), datetime(2023, 1, 2)),
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].message, "Connection refused to database")
        self.assertEqual(results[0].level, "ERROR")
        self.assertEqual(results[0].service, "myapp")
        self.assertEqual(results[0].host, "web-1")
        self.assertIn("_index", results[0].labels)

    @patch("integrations.adapters.loki.requests.Session.get")
    def test_search_with_filter(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "data": {"resultType": "streams", "result": []},
        }
        mock_get.return_value = mock_resp

        self.provider.search(
            index="myapp",
            query={"match_phrase": {"message": "error"}},
        )

        # Verify LogQL contains line filter
        call_kwargs = mock_get.call_args[1]
        self.assertIn('|= "error"', call_kwargs["params"]["query"])

    # ---- get_indices ----

    @patch("integrations.adapters.loki.requests.Session.get")
    def test_get_indices(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "data": ["app1", "app2", "nginx"],
        }
        mock_get.return_value = mock_resp

        project = MagicMock()
        project.name = "test"
        result = self.provider.get_indices(project)

        self.assertEqual(result, ["app1", "app2", "nginx"])

    # ---- LogQL building ----

    def test_build_logql_basic(self):
        logql = LokiLogProvider._build_logql("myapp", {})
        self.assertEqual(logql, '{app="myapp"}')

    def test_build_logql_with_filter(self):
        logql = LokiLogProvider._build_logql(
            "myapp", {"match_phrase": {"message": "timeout"}}
        )
        self.assertEqual(logql, '{app="myapp"} |= "timeout"')

    def test_build_logql_raw_override(self):
        logql = LokiLogProvider._build_logql(
            "ignored", {"logql": '{job="custom"} |~ "err.*"'}
        )
        self.assertEqual(logql, '{job="custom"} |~ "err.*"')

    def test_build_logql_extra_labels(self):
        logql = LokiLogProvider._build_logql(
            "myapp", {"stream_labels": {"env": "prod"}}
        )
        self.assertIn('app="myapp"', logql)
        self.assertIn('env="prod"', logql)
