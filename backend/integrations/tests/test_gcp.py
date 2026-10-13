"""Tests for the GCP Cloud Logging + Cloud Monitoring adapters.

Every SDK call is mocked at the module boundary. No live GCP calls,
no service-account keys required for CI.
"""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from integrations.adapters import gcp_logging, gcp_monitoring
from integrations.adapters.gcp_logging import (
    GcpCloudLoggingProvider,
    _load_credentials,
)
from integrations.adapters.gcp_monitoring import GcpCloudMonitoringProvider
from integrations.schemas import (
    LogQuery,
    _gcp_bareword,
    _gcp_escape,
)


# ---------------------------------------------------------------------------
# Escape helpers
# ---------------------------------------------------------------------------


class TestGcpEscapingHelpers(SimpleTestCase):

    def test_escape_plain(self):
        self.assertEqual(_gcp_escape("acme-checkout"), "acme-checkout")

    def test_escape_double_quote(self):
        self.assertEqual(_gcp_escape('foo"bar'), 'foo\\"bar')

    def test_escape_backslash_then_quote(self):
        self.assertEqual(_gcp_escape('a\\"b'), 'a\\\\\\"b')

    def test_escape_rejects_non_string(self):
        for bad in (None, 12, {"a": 1}, [1]):
            with self.assertRaises(TypeError):
                _gcp_escape(bad)

    def test_bareword_accepts_severity(self):
        for name in ("INFO", "ERROR", "WARN", "DEBUG_1"):
            self.assertEqual(_gcp_bareword(name), name)

    def test_bareword_rejects_injection(self):
        for bad in ("ERROR OR *", "ERROR;", "", "sev-erity"):
            with self.assertRaises(ValueError):
                _gcp_bareword(bad)


# ---------------------------------------------------------------------------
# LogQuery → GCP filter
# ---------------------------------------------------------------------------


class TestLogQueryToGcpFilter(SimpleTestCase):

    def test_empty_query_returns_empty(self):
        self.assertEqual(LogQuery().to_gcp_filter(), "")

    def test_project_and_env(self):
        f = LogQuery(project="acme", environment="prod").to_gcp_filter()
        self.assertIn('labels.project_name="acme"', f)
        self.assertIn('labels.environment="prod"', f)
        self.assertIn(" AND ", f)

    def test_severity_uses_ordinal_threshold(self):
        # ERROR is 500; requesting ERROR should yield >=ERROR
        self.assertIn(">=ERROR", LogQuery(severity=["ERROR"]).to_gcp_filter())
        # Mixed lowered — WARNING (400) is lower than ERROR (500), so
        # the threshold should be the minimum.
        f = LogQuery(severity=["ERROR", "WARNING"]).to_gcp_filter()
        self.assertIn(">=WARNING", f)

    def test_services_or_group(self):
        f = LogQuery(services=["api", "worker"]).to_gcp_filter()
        self.assertIn(
            '(labels.service_name="api" OR labels.service_name="worker")', f
        )

    def test_text_search_substring(self):
        f = LogQuery(text_search="timeout").to_gcp_filter()
        self.assertIn('jsonPayload.message:"timeout"', f)

    def test_time_range_inline(self):
        start = datetime(2026, 8, 27, 9, 0, 0)
        end = datetime(2026, 8, 27, 10, 0, 0)
        f = LogQuery(time_range=(start, end)).to_gcp_filter()
        self.assertIn(f'timestamp>="{start.isoformat()}"', f)
        self.assertIn(f'timestamp<="{end.isoformat()}"', f)

    def test_injection_in_value_is_escaped(self):
        f = LogQuery(project='foo" OR labels.env="prod').to_gcp_filter()
        # Escaped so the payload stays inside the string literal.
        self.assertIn('labels.project_name="foo\\" OR labels.env=\\"prod"', f)


# ---------------------------------------------------------------------------
# Credential loading
# ---------------------------------------------------------------------------


_MINIMAL_SA_KEY = {
    "type": "service_account",
    "project_id": "test-project",
    "private_key_id": "kid",
    "private_key": "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n",
    "client_email": "sa@test-project.iam.gserviceaccount.com",
    "client_id": "123",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/sa@test-project.iam.gserviceaccount.com",
}


class TestCredentialLoading(SimpleTestCase):

    def test_missing_credentials_raises(self):
        with self.assertRaisesRegex(ValueError, "service-account JSON key"):
            _load_credentials({})

    def test_non_json_string_raises(self):
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            _load_credentials({"password": "not-json"})

    def test_wrong_type_raises(self):
        bad = dict(_MINIMAL_SA_KEY)
        bad["type"] = "user"
        with self.assertRaisesRegex(ValueError, "service-account"):
            _load_credentials({"password": json.dumps(bad)})

    def test_dict_input_bypasses_json_parse(self):
        # Dict input should NOT go through json.loads. We mock the SDK
        # boundary and assert the parsed dict is what the SDK receives.
        fake_creds_obj = object()
        fake_sa_module = SimpleNamespace(
            Credentials=SimpleNamespace(
                from_service_account_info=MagicMock(return_value=fake_creds_obj)
            )
        )
        with patch.dict(
            "sys.modules",
            {
                "google.oauth2": SimpleNamespace(service_account=fake_sa_module),
                "google.oauth2.service_account": fake_sa_module,
            },
        ):
            creds = _load_credentials({"password": _MINIMAL_SA_KEY})
        self.assertIs(creds, fake_creds_obj)
        fake_sa_module.Credentials.from_service_account_info.assert_called_once_with(
            _MINIMAL_SA_KEY
        )

    def test_string_json_input_is_parsed_then_passed(self):
        fake_creds_obj = object()
        fake_sa_module = SimpleNamespace(
            Credentials=SimpleNamespace(
                from_service_account_info=MagicMock(return_value=fake_creds_obj)
            )
        )
        with patch.dict(
            "sys.modules",
            {
                "google.oauth2": SimpleNamespace(service_account=fake_sa_module),
                "google.oauth2.service_account": fake_sa_module,
            },
        ):
            creds = _load_credentials({"password": json.dumps(_MINIMAL_SA_KEY)})
        self.assertIs(creds, fake_creds_obj)
        # The SDK receives the parsed dict, not the raw string
        fake_sa_module.Credentials.from_service_account_info.assert_called_once_with(
            _MINIMAL_SA_KEY
        )


# ---------------------------------------------------------------------------
# GcpCloudLoggingProvider
# ---------------------------------------------------------------------------


class _FakeLogEntry:
    def __init__(self, message, log_name="projects/x/logs/app", severity="INFO",
                 labels=None, resource_labels=None, insert_id="i-1"):
        self.payload = message
        self.log_name = log_name
        self.severity = severity
        self.labels = labels or {}
        self.resource = SimpleNamespace(labels=resource_labels or {})
        self.timestamp = datetime(2026, 8, 27, 9, 0, 0)
        self.trace = ""
        self.insert_id = insert_id


def _make_log_provider(client_mock: MagicMock) -> GcpCloudLoggingProvider:
    """Build a provider with all SDK boundaries stubbed."""
    with patch(
        "integrations.adapters.gcp_logging._load_credentials",
        return_value="FAKE-CREDS",
    ):
        with patch(
            "integrations.adapters.gcp_logging._build_client",
            return_value=client_mock,
        ):
            return GcpCloudLoggingProvider(
                config={
                    "password": json.dumps(_MINIMAL_SA_KEY),
                    "project_id": "test-project",
                }
            )


class TestGcpCloudLoggingProvider(SimpleTestCase):

    def test_requires_project_id(self):
        with patch("integrations.adapters.gcp_logging._load_credentials"):
            with patch("integrations.adapters.gcp_logging._build_client"):
                with self.assertRaisesRegex(ValueError, "project_id"):
                    GcpCloudLoggingProvider(config={"password": "x"})

    def test_health_check_ok(self):
        client = MagicMock()
        client.list_entries.return_value = iter([_FakeLogEntry("hi")])
        provider = _make_log_provider(client)
        self.assertTrue(provider.health_check())

    def test_health_check_swallows_errors(self):
        client = MagicMock()
        client.list_entries.side_effect = Exception("401 Unauthorized")
        provider = _make_log_provider(client)
        self.assertFalse(provider.health_check())

    def test_search_returns_normalised_entries(self):
        client = MagicMock()
        client.list_entries.return_value = iter([
            _FakeLogEntry(
                message="db timeout",
                severity="ERROR",
                labels={"service_name": "backend-api"},
                resource_labels={"instance_id": "vm-1", "zone": "us-east1-b"},
                insert_id="i-42",
            ),
        ])
        provider = _make_log_provider(client)
        results = provider.search(
            index="",
            query=LogQuery(severity=["ERROR"]),
            time_range=(datetime(2026, 8, 27, 9), datetime(2026, 8, 27, 10)),
        )
        self.assertEqual(len(results), 1)
        e = results[0]
        self.assertEqual(e.message, "db timeout")
        self.assertEqual(e.level, "ERROR")
        self.assertEqual(e.service, "backend-api")
        self.assertEqual(e.host, "vm-1")
        self.assertEqual(e.raw_id, "i-42")
        # Resource labels are prefixed to avoid clashing with SDK labels
        self.assertEqual(e.labels["resource.zone"], "us-east1-b")

    def test_search_index_prefixes_log_name_filter(self):
        client = MagicMock()
        client.list_entries.return_value = iter([])
        provider = _make_log_provider(client)
        provider.search(index="app", query=LogQuery())
        called_filter = client.list_entries.call_args.kwargs.get("filter_", "")
        # log_name is quoted and points at the project-scoped path
        self.assertIn('logName="projects/test-project/logs/app"', called_filter)

    def test_search_dict_query_passes_filter_through(self):
        client = MagicMock()
        client.list_entries.return_value = iter([])
        provider = _make_log_provider(client)
        provider.search(index="", query={"filter": "severity>=ERROR"})
        called_filter = client.list_entries.call_args.kwargs.get("filter_", "")
        self.assertEqual(called_filter, "severity>=ERROR")

    def test_search_rejects_unsupported_query_type(self):
        client = MagicMock()
        provider = _make_log_provider(client)
        with self.assertRaises(TypeError):
            provider.search(index="", query=object())

    def test_search_returns_partial_results_on_iteration_error(self):
        # Simulate: first two entries succeed, then the iterator raises
        def bad_iter():
            yield _FakeLogEntry("first")
            yield _FakeLogEntry("second")
            raise Exception("token expired mid-stream")
        client = MagicMock()
        client.list_entries.return_value = bad_iter()
        provider = _make_log_provider(client)
        results = provider.search(index="", query=LogQuery())
        # Partial results are more useful than nothing
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].message, "first")
        self.assertEqual(results[1].message, "second")

    def test_get_indices_returns_distinct_log_names(self):
        client = MagicMock()
        client.list_entries.return_value = iter([
            _FakeLogEntry("x", log_name="projects/test-project/logs/app"),
            _FakeLogEntry("y", log_name="projects/test-project/logs/api"),
            _FakeLogEntry("z", log_name="projects/test-project/logs/app"),  # dup
        ])
        provider = _make_log_provider(client)
        result = provider.get_indices(project=None)
        self.assertEqual(sorted(result), [
            "projects/test-project/logs/api",
            "projects/test-project/logs/app",
        ])


# ---------------------------------------------------------------------------
# GcpCloudMonitoringProvider
# ---------------------------------------------------------------------------


def _make_metric_provider(client_mock: MagicMock) -> GcpCloudMonitoringProvider:
    with patch(
        "integrations.adapters.gcp_monitoring._load_credentials",
        return_value="FAKE",
    ):
        with patch(
            "integrations.adapters.gcp_monitoring._build_metric_client",
            return_value=client_mock,
        ):
            return GcpCloudMonitoringProvider(
                config={
                    "password": json.dumps(_MINIMAL_SA_KEY),
                    "project_id": "test-project",
                }
            )


class TestGcpCloudMonitoringProvider(SimpleTestCase):

    def test_requires_project_id(self):
        with patch("integrations.adapters.gcp_monitoring._load_credentials"):
            with patch("integrations.adapters.gcp_monitoring._build_metric_client"):
                with self.assertRaisesRegex(ValueError, "project_id"):
                    GcpCloudMonitoringProvider(config={"password": "x"})

    def test_health_check_ok(self):
        client = MagicMock()
        client.list_metric_descriptors.return_value = iter([SimpleNamespace(type="x")])
        provider = _make_metric_provider(client)
        self.assertTrue(provider.health_check())

    def test_health_check_swallows_errors(self):
        client = MagicMock()
        client.list_metric_descriptors.side_effect = Exception("no")
        provider = _make_metric_provider(client)
        self.assertFalse(provider.health_check())

    def test_build_filter_escapes_labels(self):
        result = GcpCloudMonitoringProvider._build_filter(
            'compute.googleapis.com/instance/cpu/utilization',
            {'env': 'prod" OR *'},
        )
        # Metric type stays as-is (no injection possible in fixed value)
        self.assertIn('metric.type="compute.googleapis.com/instance/cpu/utilization"', result)
        # Label value is escaped
        self.assertIn(r'metric.labels.env="prod\" OR *"', result)

    def test_build_filter_skips_empty_labels(self):
        result = GcpCloudMonitoringProvider._build_filter("m/t", {"a": "", "b": None, "c": "keep"})
        self.assertIn('metric.labels.c="keep"', result)
        self.assertNotIn("metric.labels.a=", result)
        self.assertNotIn("metric.labels.b=", result)

    def test_metric_name_map(self):
        # Ensure the canonical → GCP mapping table is intact.
        gcp_type = GcpCloudMonitoringProvider.METRIC_NAME_MAP.get(
            "node_cpu_seconds_total"
        )
        self.assertEqual(
            gcp_type, "compute.googleapis.com/instance/cpu/utilization"
        )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestGcpRegistration(SimpleTestCase):

    def test_gcp_in_adapter_map(self):
        from integrations.models import ADAPTER_MAP
        self.assertIn("gcp", ADAPTER_MAP)
        self.assertEqual(
            ADAPTER_MAP["gcp"]["logs"],
            "integrations.adapters.gcp_logging.GcpCloudLoggingProvider",
        )
        self.assertEqual(
            ADAPTER_MAP["gcp"]["metrics"],
            "integrations.adapters.gcp_monitoring.GcpCloudMonitoringProvider",
        )

    def test_gcp_in_provider_choices(self):
        from integrations.models import ObservabilityIntegration
        codes = [c for c, _ in ObservabilityIntegration.PROVIDER_CHOICES]
        self.assertIn("gcp", codes)
