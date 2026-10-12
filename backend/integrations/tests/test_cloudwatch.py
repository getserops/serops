"""Tests for CloudWatch Log and Metric providers."""
from unittest.mock import patch, MagicMock
from datetime import datetime

from django.test import SimpleTestCase

from integrations.adapters.cloudwatch_logs import CloudWatchLogProvider, _get_boto3_client
from integrations.adapters.cloudwatch_metrics import CloudWatchMetricProvider


class TestCloudWatchLogProvider(SimpleTestCase):

    @patch("integrations.adapters.cloudwatch_logs._get_boto3_client")
    def setUp(self, mock_client_factory):
        self.mock_client = MagicMock()
        mock_client_factory.return_value = self.mock_client
        self.provider = CloudWatchLogProvider(config={
            "aws_region": "us-east-1",
            "username": "key-id",
            "password": "secret",
        })

    def test_health_check_success(self):
        self.mock_client.describe_log_groups.return_value = {"logGroups": []}
        self.assertTrue(self.provider.health_check())

    def test_health_check_failure(self):
        self.mock_client.describe_log_groups.side_effect = Exception("InvalidToken")
        self.assertFalse(self.provider.health_check())

    def test_search_starts_query_and_polls(self):
        self.mock_client.start_query.return_value = {"queryId": "q-123"}
        self.mock_client.get_query_results.return_value = {
            "status": "Complete",
            "results": [
                [
                    {"field": "@timestamp", "value": "2023-01-01T12:00:00Z"},
                    {"field": "@message", "value": "Connection error"},
                    {"field": "@logStream", "value": "app/web-1/task-id"},
                    {"field": "@ptr", "value": "ptr-abc"},
                ],
                [
                    {"field": "@timestamp", "value": "2023-01-01T12:01:00Z"},
                    {"field": "@message", "value": "Retry attempt"},
                    {"field": "@logStream", "value": "app/web-1/task-id"},
                    {"field": "@ptr", "value": "ptr-def"},
                ],
            ],
        }

        results = self.provider.search(
            index="/aws/ecs/myapp",
            query={},
            time_range=(datetime(2023, 1, 1), datetime(2023, 1, 2)),
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].message, "Connection error")
        self.assertEqual(results[0].raw_id, "ptr-abc")
        self.assertEqual(results[0].labels["log_group"], "/aws/ecs/myapp")

    def test_search_handles_failed_query(self):
        self.mock_client.start_query.return_value = {"queryId": "q-999"}
        self.mock_client.get_query_results.return_value = {
            "status": "Failed",
            "results": [],
        }

        results = self.provider.search(index="/aws/ecs/myapp", query={})
        self.assertEqual(results, [])

    def test_get_indices(self):
        self.mock_client.describe_log_groups.return_value = {
            "logGroups": [
                {"logGroupName": "/aws/myapp/api"},
                {"logGroupName": "/aws/myapp/worker"},
            ]
        }

        project = MagicMock()
        project.name = "MyApp"
        result = self.provider.get_indices(project)
        self.assertEqual(len(result), 2)

    def test_build_query_with_filter(self):
        query = CloudWatchLogProvider._build_query({
            "match_phrase": {"message": "timeout"}
        })
        self.assertIn("filter @message like 'timeout'", query)

    def test_build_query_raw_override(self):
        query = CloudWatchLogProvider._build_query({
            "insights_query": "fields @timestamp | limit 5"
        })
        self.assertEqual(query, "fields @timestamp | limit 5")


class TestCloudWatchMetricProvider(SimpleTestCase):

    @patch("integrations.adapters.cloudwatch_metrics._get_boto3_client")
    def setUp(self, mock_client_factory):
        self.mock_client = MagicMock()
        mock_client_factory.return_value = self.mock_client
        self.provider = CloudWatchMetricProvider(config={
            "aws_region": "us-east-1",
            "username": "key-id",
            "password": "secret",
        })

    def test_health_check_success(self):
        self.mock_client.list_metrics.return_value = {"Metrics": []}
        self.assertTrue(self.provider.health_check())

    def test_health_check_failure(self):
        self.mock_client.list_metrics.side_effect = Exception("expired")
        self.assertFalse(self.provider.health_check())

    def test_query_range_success(self):
        self.mock_client.get_metric_data.return_value = {
            "MetricDataResults": [
                {
                    "Id": "m1",
                    "Timestamps": [
                        datetime(2023, 1, 1, 12, 0),
                        datetime(2023, 1, 1, 12, 5),
                    ],
                    "Values": [80.0, 85.0],
                    "StatusCode": "Complete",
                }
            ]
        }

        results = self.provider.query_range(
            metric="node_cpu_seconds_total",
            labels={"InstanceId": "i-123"},
            start=datetime(2023, 1, 1),
            end=datetime(2023, 1, 2),
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(len(results[0].points), 2)
        self.assertAlmostEqual(results[0].points[0].value, 80.0)
        self.assertEqual(results[0].metric_name, "node_cpu_seconds_total")

    def test_query_range_unknown_metric(self):
        results = self.provider.query_range(
            metric="unknown_metric", labels={},
            start=datetime(2023, 1, 1), end=datetime(2023, 1, 2),
        )
        self.assertEqual(results, [])

    def test_discover_hosts(self):
        self.mock_client.list_metrics.return_value = {
            "Metrics": [
                {"Dimensions": [{"Name": "InstanceId", "Value": "i-abc"}]},
                {"Dimensions": [{"Name": "InstanceId", "Value": "i-def"}]},
                {"Dimensions": [{"Name": "InstanceId", "Value": "i-abc"}]},  # duplicate
            ]
        }

        hosts = self.provider.discover_hosts(org="acme")
        self.assertEqual(len(hosts), 2)
        self.assertEqual(hosts[0].hostname, "i-abc")


class TestCloudWatchCredentials(SimpleTestCase):
    """The adapter only ever uses the integration's own access key."""

    @patch("boto3.client")
    def test_explicit_key_is_passed_to_boto3(self, mock_client):
        _get_boto3_client("logs", {
            "username": "key-id", "password": "secret", "aws_region": "eu-west-1",
        })
        mock_client.assert_called_once_with(
            service_name="logs",
            region_name="eu-west-1",
            aws_access_key_id="key-id",
            aws_secret_access_key="secret",
        )

    @patch("boto3.client")
    def test_region_defaults_to_us_east_1(self, mock_client):
        _get_boto3_client("logs", {"username": "key-id", "password": "secret"})
        self.assertEqual(mock_client.call_args.kwargs["region_name"], "us-east-1")

    @patch("boto3.client")
    def test_missing_keys_never_fall_back_to_host_credentials(self, mock_client):
        for config in (
            {},
            {"username": "key-id"},
            {"password": "secret"},
            {"username": "", "password": ""},
        ):
            with self.subTest(config=config):
                with self.assertRaisesRegex(ValueError, "never uses the server"):
                    _get_boto3_client("logs", config)
        mock_client.assert_not_called()

    @patch("boto3.client")
    def test_both_providers_refuse_to_start_without_keys(self, mock_client):
        for provider_class in (CloudWatchLogProvider, CloudWatchMetricProvider):
            with self.subTest(provider=provider_class.__name__):
                with self.assertRaises(ValueError):
                    provider_class(config={"aws_region": "us-east-1"})
        mock_client.assert_not_called()
