"""Tests for OpenSearchLogProvider."""
from unittest.mock import patch, MagicMock
from datetime import datetime

from django.test import SimpleTestCase

from integrations.adapters.opensearch import OpenSearchLogProvider


class TestOpenSearchLogProvider(SimpleTestCase):

    @patch("integrations.adapters.opensearch._get_opensearch_client")
    def setUp(self, mock_client_factory):
        self.mock_client = MagicMock()
        mock_client_factory.return_value = self.mock_client
        self.provider = OpenSearchLogProvider(config={
            "host": "https://opensearch:9200",
        })

    def test_health_check_green(self):
        self.mock_client.cluster.health.return_value = {"status": "green"}
        self.assertTrue(self.provider.health_check())

    def test_health_check_yellow(self):
        self.mock_client.cluster.health.return_value = {"status": "yellow"}
        self.assertTrue(self.provider.health_check())

    def test_health_check_red(self):
        self.mock_client.cluster.health.return_value = {"status": "red"}
        self.assertFalse(self.provider.health_check())

    def test_health_check_exception(self):
        self.mock_client.cluster.health.side_effect = Exception("down")
        self.assertFalse(self.provider.health_check())

    def test_search_returns_log_entries(self):
        self.mock_client.search.return_value = {
            "hits": {
                "total": {"value": 2},
                "hits": [
                    {
                        "_id": "os-1",
                        "_index": "application-logs-myapp",
                        "_source": {
                            "@timestamp": "2023-01-01T12:00:00Z",
                            "message": "Error in service",
                            "level": "error",
                            "hostname": "web-1",
                        },
                    },
                    {
                        "_id": "os-2",
                        "_index": "application-logs-myapp",
                        "_source": {
                            "@timestamp": "2023-01-01T12:01:00Z",
                            "message": "Recovered",
                            "level": "info",
                        },
                    },
                ],
            }
        }

        results = self.provider.search(index="application-logs-myapp", query={})

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].message, "Error in service")
        self.assertEqual(results[0].level, "ERROR")
        self.assertEqual(results[0].raw_id, "os-1")
        self.assertEqual(results[1].message, "Recovered")

    def test_search_with_time_range(self):
        self.mock_client.search.return_value = {"hits": {"hits": []}}

        self.provider.search(
            index="myapp",
            query={"query": {"match_all": {}}},
            time_range=(datetime(2023, 1, 1), datetime(2023, 1, 2)),
        )

        call_kwargs = self.mock_client.search.call_args[1]
        body = call_kwargs["body"]
        must = body["query"]["bool"]["must"]
        range_filter = next(f for f in must if "range" in f)
        self.assertIn("@timestamp", range_filter["range"])

    def test_search_error_returns_empty(self):
        self.mock_client.search.side_effect = Exception("timeout")
        results = self.provider.search(index="myapp", query={})
        self.assertEqual(results, [])

    def test_get_indices(self):
        self.mock_client.cat.indices.return_value = [
            {"index": "application-logs-myapp-2023.01"},
            {"index": "application-logs-myapp-2023.02"},
        ]

        project = MagicMock()
        project.name = "MyApp"
        results = self.provider.get_indices(project)

        self.assertEqual(len(results), 2)
        self.assertIn("application-logs-myapp-2023.01", results)
