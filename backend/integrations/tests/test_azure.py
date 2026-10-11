"""Tests for the Azure Log Analytics + Azure Monitor adapters.

Every SDK call is mocked at the module boundary. No live Azure calls,
no service principal required for CI.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from integrations.adapters.azure_logs import (
    AzureLogAnalyticsProvider,
    _build_credential,
)
from integrations.adapters.azure_metrics import AzureMonitorProvider
from integrations.schemas import (
    LogQuery,
    _kql_bareword,
    _kql_datetime,
    _kql_escape,
)


# ---------------------------------------------------------------------------
# Escape helpers
# ---------------------------------------------------------------------------


class TestKqlEscapingHelpers(SimpleTestCase):

    def test_escape_plain(self):
        self.assertEqual(_kql_escape("acme-checkout"), "acme-checkout")

    def test_escape_double_quote(self):
        self.assertEqual(_kql_escape('foo"bar'), 'foo\\"bar')

    def test_escape_backslash_then_quote(self):
        # Same ordering test as SPL / GCP — the backslash pass must
        # come first so the escape it inserts for the quote isn't
        # re-escaped.
        self.assertEqual(_kql_escape('a"\\b'), 'a\\"\\\\b')

    def test_escape_rejects_non_string(self):
        for bad in (None, 12, {"a": 1}, [1]):
            with self.assertRaises(TypeError):
                _kql_escape(bad)

    def test_bareword_accepts_valid_tables(self):
        for name in ("AppTraces", "Perf", "ContainerLog", "_MyTable"):
            self.assertEqual(_kql_bareword(name), name)

    def test_bareword_rejects_starting_digit(self):
        # KQL identifiers cannot start with a digit.
        for bad in ("1Table", "9AppTraces"):
            with self.assertRaises(ValueError):
                _kql_bareword(bad)

    def test_bareword_rejects_injection(self):
        for bad in ("Perf | drop", "AppTraces;", "", "Table Name",
                    'Perf" or true', "let x = ..."):
            with self.assertRaises(ValueError):
                _kql_bareword(bad)

    def test_datetime_accepts_valid_iso(self):
        for ts in ("2026-08-27T09:00:00Z", "2026-08-27T09:00:00.123Z",
                   "2026-08-27T09:00:00+00:00"):
            self.assertEqual(_kql_datetime(ts), ts)

    def test_datetime_rejects_injection(self):
        for bad in ("2026-08-27T09:00:00Z; drop",
                    "2026-08-27 or 1=1",
                    "2026-08-27T09:00:00Z or Level == 'Error'",
                    ""):
            with self.assertRaises(ValueError):
                _kql_datetime(bad)


# ---------------------------------------------------------------------------
# LogQuery → KQL
# ---------------------------------------------------------------------------


class TestLogQueryToAzureKql(SimpleTestCase):

    def test_empty_query_still_has_table_and_top(self):
        kql = LogQuery().to_azure_kql()
        self.assertTrue(kql.startswith("AppTraces"))
        self.assertIn("| top 5000 by TimeGenerated desc", kql)

    def test_custom_table(self):
        kql = LogQuery().to_azure_kql(table="Perf")
        self.assertTrue(kql.startswith("Perf"))

    def test_invalid_table_raises(self):
        with self.assertRaises(ValueError):
            LogQuery().to_azure_kql(table="Perf | drop")

    def test_project_and_env(self):
        kql = LogQuery(project="acme", environment="prod").to_azure_kql()
        self.assertIn('| where Properties.project_name == "acme"', kql)
        self.assertIn('| where Properties.environment == "prod"', kql)

    def test_services_in_clause(self):
        kql = LogQuery(services=["api", "worker"]).to_azure_kql()
        self.assertIn('| where Properties.service_name in ("api", "worker")', kql)

    def test_severity_ordinal_threshold(self):
        # ERROR = 3 → >= 3
        self.assertIn("SeverityLevel >= 3", LogQuery(severity=["ERROR"]).to_azure_kql())
        # WARN + ERROR → min is WARN (2) → >= 2
        self.assertIn("SeverityLevel >= 2",
                      LogQuery(severity=["WARN", "ERROR"]).to_azure_kql())

    def test_text_search_contains(self):
        kql = LogQuery(text_search="timeout").to_azure_kql()
        self.assertIn('| where Message contains "timeout"', kql)

    def test_time_range_uses_validated_datetime(self):
        start = datetime(2026, 8, 27, 9, 0, 0)
        end = datetime(2026, 8, 27, 10, 0, 0)
        kql = LogQuery(time_range=(start, end)).to_azure_kql()
        self.assertIn("datetime(2026-08-27T09:00:00)", kql)
        self.assertIn("datetime(2026-08-27T10:00:00)", kql)

    def test_injection_in_value_is_escaped(self):
        kql = LogQuery(project='foo" or true //').to_azure_kql()
        # The escaped payload stays inside the quoted string literal.
        self.assertIn('Properties.project_name == "foo\\" or true //"', kql)

    def test_max_results_bounded(self):
        kql = LogQuery(max_results=42).to_azure_kql()
        self.assertIn("| top 42 by TimeGenerated desc", kql)


# ---------------------------------------------------------------------------
# Credential builder
# ---------------------------------------------------------------------------


class TestBuildCredential(SimpleTestCase):

    def test_missing_fields_raise(self):
        with self.assertRaises(ValueError):
            _build_credential("t", "c", "")
        with self.assertRaises(ValueError):
            _build_credential("t", "", "s")
        with self.assertRaises(ValueError):
            _build_credential("", "c", "s")

    def test_all_fields_passed_to_sdk(self):
        fake_credential = object()
        fake_ClientSecretCredential = MagicMock(return_value=fake_credential)
        fake_module = SimpleNamespace(ClientSecretCredential=fake_ClientSecretCredential)
        with patch.dict("sys.modules", {"azure.identity": fake_module}):
            result = _build_credential("tid", "cid", "cs")
        self.assertIs(result, fake_credential)
        fake_ClientSecretCredential.assert_called_once_with(
            tenant_id="tid", client_id="cid", client_secret="cs"
        )


# ---------------------------------------------------------------------------
# AzureLogAnalyticsProvider
# ---------------------------------------------------------------------------


def _make_log_provider(client_mock: MagicMock) -> AzureLogAnalyticsProvider:
    with patch(
        "integrations.adapters.azure_logs._build_credential",
        return_value="FAKE-CRED",
    ):
        with patch(
            "integrations.adapters.azure_logs._build_logs_client",
            return_value=client_mock,
        ):
            return AzureLogAnalyticsProvider(config={
                "tenant_id": "tid", "client_id": "cid",
                "password": "cs", "workspace_id": "wsid",
            })


class TestAzureLogAnalyticsProvider(SimpleTestCase):

    def test_requires_workspace_id(self):
        with patch("integrations.adapters.azure_logs._build_credential"):
            with patch("integrations.adapters.azure_logs._build_logs_client"):
                with self.assertRaisesRegex(ValueError, "workspace_id"):
                    AzureLogAnalyticsProvider(config={
                        "tenant_id": "t", "client_id": "c", "password": "s",
                    })

    def test_health_check_ok(self):
        client = MagicMock()
        client.query_workspace.return_value = MagicMock()
        provider = _make_log_provider(client)
        self.assertTrue(provider.health_check())

    def test_health_check_swallows_errors(self):
        client = MagicMock()
        client.query_workspace.side_effect = Exception("Forbidden")
        provider = _make_log_provider(client)
        self.assertFalse(provider.health_check())

    def test_search_translates_logquery_to_kql(self):
        client = MagicMock()
        client.query_workspace.return_value = MagicMock(tables=[])
        provider = _make_log_provider(client)
        provider.search(
            index="Perf",
            query=LogQuery(severity=["ERROR"], project="acme"),
            time_range=(datetime(2026, 8, 27, 9), datetime(2026, 8, 27, 10)),
        )
        sent = client.query_workspace.call_args.kwargs
        self.assertEqual(sent["workspace_id"], "wsid")
        self.assertIn("Perf", sent["query"])
        self.assertIn('Properties.project_name == "acme"', sent["query"])

    def test_search_string_query_passes_through(self):
        client = MagicMock()
        client.query_workspace.return_value = MagicMock(tables=[])
        provider = _make_log_provider(client)
        provider.search(index="", query="AppTraces | count")
        sent = client.query_workspace.call_args.kwargs
        self.assertEqual(sent["query"], "AppTraces | count")

    def test_search_rejects_unsupported_query_type(self):
        client = MagicMock()
        provider = _make_log_provider(client)
        with self.assertRaises(TypeError):
            provider.search(index="", query=object())

    def test_parse_response_normalises_apptraces(self):
        # Build a fake response shaped like azure.monitor.query.LogsQueryResult
        fake_column = lambda name: SimpleNamespace(name=name)
        fake_table = SimpleNamespace(
            columns=[
                fake_column("TimeGenerated"),
                fake_column("Message"),
                fake_column("SeverityLevel"),
                fake_column("Properties"),
                fake_column("OperationId"),
                fake_column("ItemId"),
                fake_column("Computer"),
            ],
            rows=[
                [
                    datetime(2026, 8, 27, 9, 5),
                    "db timeout",
                    3,
                    '{"service_name":"backend-api"}',
                    "op-1",
                    "item-1",
                    "vm-1",
                ]
            ],
        )
        response = SimpleNamespace(tables=[fake_table])
        entries = AzureLogAnalyticsProvider._parse_response(response, "AppTraces", 100)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e.message, "db timeout")
        self.assertEqual(e.level, "ERROR")   # SeverityLevel 3 → ERROR
        self.assertEqual(e.service, "backend-api")
        self.assertEqual(e.host, "vm-1")
        self.assertEqual(e.trace_id, "op-1")
        self.assertEqual(e.raw_id, "item-1")
        # Parsed Properties flow into labels under a properties. prefix
        self.assertEqual(e.labels["properties.service_name"], "backend-api")
        self.assertEqual(e.labels["_index"], "AppTraces")

    def test_parse_response_respects_size_cap(self):
        fake_table = SimpleNamespace(
            columns=[SimpleNamespace(name="Message")],
            rows=[["a"], ["b"], ["c"]],
        )
        response = SimpleNamespace(tables=[fake_table])
        entries = AzureLogAnalyticsProvider._parse_response(response, "T", 2)
        self.assertEqual(len(entries), 2)


# ---------------------------------------------------------------------------
# AzureMonitorProvider (metrics)
# ---------------------------------------------------------------------------


def _make_metric_provider(client_mock: MagicMock) -> AzureMonitorProvider:
    with patch(
        "integrations.adapters.azure_metrics._build_credential",
        return_value="FAKE",
    ):
        with patch(
            "integrations.adapters.azure_metrics._build_metrics_client",
            return_value=client_mock,
        ):
            return AzureMonitorProvider(config={
                "tenant_id": "t", "client_id": "c", "password": "s",
                "default_resource_uri":
                    "/subscriptions/sub/resourceGroups/rg/"
                    "providers/Microsoft.Compute/virtualMachines/vm-1",
            })


class TestAzureMonitorProvider(SimpleTestCase):

    def test_requires_default_resource(self):
        with patch("integrations.adapters.azure_metrics._build_credential"):
            with patch("integrations.adapters.azure_metrics._build_metrics_client"):
                with self.assertRaisesRegex(ValueError, "default_resource_uri"):
                    AzureMonitorProvider(config={
                        "tenant_id": "t", "client_id": "c", "password": "s",
                    })

    def test_health_check_ok(self):
        client = MagicMock()
        client.list_metric_definitions.return_value = iter([SimpleNamespace(name="Percentage CPU")])
        provider = _make_metric_provider(client)
        self.assertTrue(provider.health_check())

    def test_health_check_swallows_errors(self):
        client = MagicMock()
        client.list_metric_definitions.side_effect = Exception("nope")
        provider = _make_metric_provider(client)
        self.assertFalse(provider.health_check())

    def test_pick_granularity_scales_with_range(self):
        start = datetime(2026, 8, 27, 0)
        end = datetime(2026, 8, 27, 1)   # 1 hour → 18s step but floored to 60s
        step = AzureMonitorProvider._pick_granularity(start, end)
        self.assertGreaterEqual(step.total_seconds(), 60)

        start = datetime(2026, 8, 26)
        end = datetime(2026, 8, 27)      # 24h → ~432s = 7min
        step = AzureMonitorProvider._pick_granularity(start, end)
        self.assertGreater(step.total_seconds(), 60)

    def test_metric_name_map(self):
        self.assertEqual(
            AzureMonitorProvider.METRIC_NAME_MAP.get("node_cpu_seconds_total"),
            "Percentage CPU",
        )

    def test_discover_hosts_returns_default_resource(self):
        client = MagicMock()
        provider = _make_metric_provider(client)
        hosts = provider.discover_hosts(org="acme", environment="prod")
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0].hostname, "vm-1")
        self.assertEqual(hosts[0].labels["resource_uri"],
                         "/subscriptions/sub/resourceGroups/rg/"
                         "providers/Microsoft.Compute/virtualMachines/vm-1")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestAzureRegistration(SimpleTestCase):

    def test_azure_in_adapter_map(self):
        from integrations.models import ADAPTER_MAP
        self.assertIn("azure", ADAPTER_MAP)
        self.assertEqual(
            ADAPTER_MAP["azure"]["logs"],
            "integrations.adapters.azure_logs.AzureLogAnalyticsProvider",
        )
        self.assertEqual(
            ADAPTER_MAP["azure"]["metrics"],
            "integrations.adapters.azure_metrics.AzureMonitorProvider",
        )

    def test_azure_in_provider_choices(self):
        from integrations.models import ObservabilityIntegration
        codes = [c for c, _ in ObservabilityIntegration.PROVIDER_CHOICES]
        self.assertIn("azure", codes)
