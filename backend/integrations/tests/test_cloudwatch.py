"""Tests for CloudWatch Log and Metric providers."""
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from botocore.exceptions import ClientError
from django.test import SimpleTestCase

from integrations.adapters.cloudwatch_logs import CloudWatchLogProvider, _get_boto3_client
from integrations.adapters.cloudwatch_metrics import CloudWatchMetricProvider
from integrations.base import LogSearchError
from integrations.schemas import LogQuery


def _denied(operation):
    return ClientError({"Error": {"Code": "AccessDeniedException", "Message": "not authorized"}}, operation)


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

    def test_health_check_says_which_permission_is_missing(self):
        self.mock_client.describe_log_groups.return_value = {"logGroups": [{"logGroupName": "/ecs/shop"}]}
        self.mock_client.start_query.side_effect = _denied("StartQuery")
        self.assertFalse(self.provider.health_check())
        self.assertIn("logs:StartQuery", self.provider.last_error)

    def test_a_refused_query_is_an_error_not_no_logs(self):
        self.mock_client.start_query.side_effect = _denied("StartQuery")
        with self.assertRaisesRegex(LogSearchError, "logs:StartQuery"):
            self.provider.search("/ecs/shop", LogQuery())

    def test_no_group_or_star_searches_the_account_groups(self):
        # Insights has no wildcard: "*" was sent as a group name and refused.
        self.mock_client.describe_log_groups.return_value = {"logGroups": [{"logGroupName": "/ecs/a"}]}
        self.mock_client.start_query.return_value = {"queryId": "q"}
        self.mock_client.get_query_results.return_value = {"status": "Complete", "results": []}
        for index in (None, "*"):
            self.provider.search(index, LogQuery())
            self.assertEqual(self.mock_client.start_query.call_args.kwargs["logGroupNames"], ["/ecs/a"])

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

        with self.assertRaisesRegex(LogSearchError, "Failed"):
            self.provider.search(index="/aws/ecs/myapp", query={})

    def test_lambda_service_is_the_function_not_the_date(self):
        self.mock_client.start_query.return_value = {"queryId": "q"}
        self.mock_client.get_query_results.return_value = {"status": "Complete", "results": [
            [{"field": "@message", "value": "boom"}, {"field": "@log", "value": "1:/aws/lambda/shop-checkout"},
             {"field": "@logStream", "value": "2026/10/31/[$LATEST]9f8e"}],
            [{"field": "@message", "value": "boom"}, {"field": "@log", "value": "1:/ecs/shop"},
             {"field": "@logStream", "value": "ecs/orders/4f1c2d3e"}],
        ]}
        entries = self.provider.search("/aws/lambda/shop-checkout,/ecs/shop", LogQuery())
        self.assertEqual([e.service for e in entries], ["shop-checkout", "orders"])

    def test_get_indices_adds_eks_application_groups(self):
        def groups(limit, **kwargs):
            if kwargs.get("logGroupNamePrefix") == "/aws/containerinsights/":
                names = ["/aws/containerinsights/prod/application", "/aws/containerinsights/prod/performance"]
            elif kwargs.get("logGroupNamePattern"):
                names = ["/ecs/shop-payments"]
            else:
                names = []
            return {"logGroups": [{"logGroupName": n} for n in names]}
        self.mock_client.describe_log_groups.side_effect = groups
        project = MagicMock()
        project.name = "shop"
        self.assertEqual(self.provider.get_indices(project),
                         ["/ecs/shop-payments", "/aws/containerinsights/prod/application"])

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


def _metrics(*dimension_sets):
    return {"Metrics": [{"Dimensions": [{"Name": k, "Value": v} for k, v in d.items()]} for d in dimension_sets]}


class TestCloudWatchMetricProvider(SimpleTestCase):

    @patch("integrations.adapters.cloudwatch_metrics._get_boto3_client")
    def setUp(self, mock_client_factory):
        self.mock_client = MagicMock()
        mock_client_factory.return_value = self.mock_client
        self.listed = {}
        self.mock_client.get_paginator.return_value.paginate.side_effect = (
            lambda Namespace, MetricName: [self.listed.get(MetricName, {"Metrics": []})])
        self.provider = CloudWatchMetricProvider(config={
            "aws_region": "us-east-1",
            "username": "key-id",
            "password": "secret",
        })

    def test_health_check_success(self):
        self.mock_client.list_metrics.return_value = {"Metrics": []}
        self.mock_client.get_metric_data.return_value = {"MetricDataResults": []}
        self.assertTrue(self.provider.health_check())
        # ListMetrics takes no MaxRecords: sending it failed every health check.
        self.assertNotIn("MaxRecords", self.mock_client.list_metrics.call_args.kwargs)

    def test_health_check_failure(self):
        self.mock_client.list_metrics.side_effect = _denied("ListMetrics")
        self.assertFalse(self.provider.health_check())
        self.assertIn("cloudwatch:ListMetrics", self.provider.last_error)

    def test_one_series_per_host_from_the_agent(self):
        # GetMetricData matches dimensions exactly, so the series are listed
        # first; SerOps labels the agent never sends must not filter them out.
        self.listed["mem_total"] = _metrics(
            {"host": "web-1", "InstanceId": "i-1"}, {"host": "web-2", "InstanceId": "i-2"}, {"InstanceId": "i-1"})
        self.mock_client.get_metric_data.return_value = {"MetricDataResults": [
            {"Id": "m0", "Timestamps": [datetime(2026, 10, 31, 12, tzinfo=timezone.utc)], "Values": [8.0]},
            {"Id": "m1", "Timestamps": [datetime(2026, 10, 31, 12, tzinfo=timezone.utc)], "Values": [4.0]},
        ]}
        series = self.provider.query_range("node_memory_MemTotal_bytes",
                                           {"organisation_name": "Acme Cloud", "project_name": "shop"},
                                           datetime(2026, 10, 31, 11), datetime(2026, 10, 31, 12))
        self.assertEqual([(s.labels["host"], s.points[0].value) for s in series], [("web-1", 8.0), ("web-2", 4.0)])
        queries = self.mock_client.get_metric_data.call_args.kwargs["MetricDataQueries"]
        self.assertEqual(queries[0]["MetricStat"]["Metric"]["Dimensions"],
                         [{"Name": "host", "Value": "web-1"}, {"Name": "InstanceId", "Value": "i-1"}])

    def test_cpu_reads_cpu_total_then_falls_back_to_ec2(self):
        self.listed["cpu_usage_active"] = _metrics({"host": "web-1", "cpu": "cpu0"}, {"host": "web-1", "cpu": "cpu-total"})
        self.mock_client.get_metric_data.return_value = {"MetricDataResults": []}
        self.provider.query_range("node_cpu_seconds_total", {}, datetime(2026, 1, 1), datetime(2026, 1, 1, 1))
        dims = self.mock_client.get_metric_data.call_args.kwargs["MetricDataQueries"][0]["MetricStat"]["Metric"]["Dimensions"]
        self.assertIn({"Name": "cpu", "Value": "cpu-total"}, dims)

        self.listed = {"CPUUtilization": _metrics({"InstanceId": "i-9"})}
        self.provider.query_range("node_cpu_seconds_total", {}, datetime(2026, 1, 1), datetime(2026, 1, 1, 1))
        metric = self.mock_client.get_metric_data.call_args.kwargs["MetricDataQueries"][0]["MetricStat"]["Metric"]
        self.assertEqual((metric["Namespace"], metric["Dimensions"]), ("AWS/EC2", [{"Name": "InstanceId", "Value": "i-9"}]))
        self.assertTrue(self.provider.cpu_is_percent)

    def test_series_carrying_a_project_dimension_are_scoped(self):
        self.listed["mem_total"] = _metrics({"host": "a", "project_name": "shop"}, {"host": "b", "project_name": "blog"})
        self.mock_client.get_metric_data.return_value = {"MetricDataResults": []}
        self.provider.query_range("node_memory_MemTotal_bytes", {"project_name": "shop"},
                                  datetime(2026, 1, 1), datetime(2026, 1, 1, 1))
        queries = self.mock_client.get_metric_data.call_args.kwargs["MetricDataQueries"]
        self.assertEqual(len(queries), 1)
        self.assertIn({"Name": "host", "Value": "a"}, queries[0]["MetricStat"]["Metric"]["Dimensions"])

    def test_query_range_unknown_metric(self):
        results = self.provider.query_range(
            metric="unknown_metric", labels={},
            start=datetime(2023, 1, 1), end=datetime(2023, 1, 2),
        )
        self.assertEqual(results, [])

    def test_discover_hosts(self):
        self.listed["cpu_usage_active"] = _metrics(
            {"host": "web-1", "cpu": "cpu-total"}, {"host": "web-2", "cpu": "cpu-total"}, {"host": "web-1", "cpu": "cpu0"})
        hosts = self.provider.discover_hosts(org="acme")
        self.assertEqual(sorted(h.hostname for h in hosts), ["web-1", "web-2"])


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


class TestLogGroupNames(SimpleTestCase):
    """Found on a real AWS account: CloudWatch logs seldom carry a project
    or environment field; the log group name says it."""

    def test_a_group_named_after_the_project_counts_unless_the_record_names_another(self):
        q = LogQuery(project="shop").to_cloudwatch_insights()
        self.assertIn("@log like /(?i)^[0-9]*:.*shop/", q)
        self.assertIn("not ispresent(project_name) and not ispresent(project)", q)

    def test_plain_text_events_are_decided_by_the_group_alone(self):
        # Insights finds no field on a plain line, and "not ispresent(x)"
        # is then false: the orders logs of /ecs/shop-orders-prod were lost.
        q = LogQuery(project="shop").to_cloudwatch_insights()
        self.assertIn(r"@message not like /^\s*\{/ or (not ispresent(project_name)", q)

    def test_environment_is_a_word_of_the_group_name(self):
        import re
        q = LogQuery(environment="production").to_cloudwatch_insights()
        pattern = re.search(r"@log like /\(\?i\)(.*?)/ and", q.replace(r"\/", "/")).group(1)
        for group, matches in (("/ecs/shop-orders-prod", True), ("/ecs/shop-orders-staging", False),
                               ("/aws/containerinsights/acme-prod/application", True),
                               ("/aws/lambda/product-api", False), ("/ecs/production/api", True)):
            with self.subTest(group=group):
                self.assertEqual(bool(re.search(pattern, "123456789012:" + group, re.I)), matches)

    def test_with_a_single_environment_a_group_naming_no_environment_counts(self):
        # The shop-checkout Lambda logs: no env field, no env word in the group.
        import re
        q = LogQuery(environment="production", environment_untagged=True).to_cloudwatch_insights()
        pattern = re.search(r"@log not like /\(\?i\)(.*?)/ and", q.replace(r"\/", "/")).group(1)
        for group, excluded in (("/aws/lambda/shop-checkout", False), ("/ecs/shop-orders-staging", True),
                                ("/ecs/shop-orders-prod", False), ("/ecs/api-dev", True)):
            with self.subTest(group=group):
                self.assertEqual(bool(re.search(pattern, "123456789012:" + group, re.I)), excluded)
        self.assertNotIn("@log not like", LogQuery(environment="production").to_cloudwatch_insights())


class TestPercentCpu(SimpleTestCase):
    def test_a_percentage_is_not_differentiated(self):
        from integrations.metrics_processing import fetch_metrics_with_provider
        from integrations.schemas import TimeSeries, TimeSeriesPoint
        provider = MagicMock(spec=["query_range", "cpu_is_percent"])
        provider.cpu_is_percent = True
        point = TimeSeriesPoint(timestamp=datetime(2026, 10, 31, 12, tzinfo=timezone.utc), value=73.8)
        provider.query_range.return_value = [TimeSeries(metric_name="m", labels={"host": "web-1"}, points=[point])]
        project = MagicMock()
        with patch("integrations.registry.IntegrationRegistry.get_metric_provider_for_org", return_value=provider):
            metrics = fetch_metrics_with_provider(datetime(2026, 10, 31, 11), datetime(2026, 10, 31, 12),
                                                  project_obj=project, project_name_str="shop")
        self.assertEqual([p["value"] for p in metrics["cpu_usage_percent"]], [73.8])


class CloudWatchTimestampTest(SimpleTestCase):
    """Logs Insights returns @timestamp without an offset; it is UTC. Left
    naive, it crashed the batch window (compared with aware datetimes)."""

    def test_insights_timestamp_is_utc(self):
        from datetime import datetime, timezone
        from integrations.schemas import _parse_timestamp
        self.assertEqual(_parse_timestamp("2026-10-31 19:36:28.308"),
                         datetime(2026, 10, 31, 19, 36, 28, 308000, tzinfo=timezone.utc))

    def test_an_offset_is_kept(self):
        from integrations.schemas import _parse_timestamp
        self.assertEqual(_parse_timestamp("2026-10-31T21:36:28+02:00").utcoffset().total_seconds(), 7200)


class CloudWatchStreamLocationTest(SimpleTestCase):
    """CI/CD events are read back from the group they are written to; the
    scheduler used the Elasticsearch index name (serops-cicd-acme), a group
    that never exists, so CloudWatch never correlated a pipeline failure."""

    def test_cicd_events_are_read_where_they_are_written(self):
        from unittest.mock import patch
        from integrations.schemas import LogStream
        with patch('integrations.adapters.cloudwatch_logs._get_boto3_client'):
            from integrations.adapters.cloudwatch_logs import CloudWatchLogProvider
            provider = CloudWatchLogProvider({'aws_region': 'eu-central-1', 'username': 'k', 'password': 's'})
        stream = LogStream(category='cicd', org_slug='acme', project='shop')
        self.assertEqual(provider.stream_location(stream), '/serops/cicd/acme')
        self.assertEqual(provider.stream_location(stream), stream.to_cloudwatch_log_group())
