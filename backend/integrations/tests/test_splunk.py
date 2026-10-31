"""Tests for the Splunk log adapter and SPL query translation.

Covers:
  - Adapter lifecycle: config validation, session setup, header wiring
  - SPL query translation: correct field mapping, escaping, injection defence
  - Search flow: start_job → wait → fetch_results with proper polling
  - Failure modes: bad status, dispatch failure, timeout, unauthorised
  - Health check + get_indices
  - Result parsing into canonical LogEntry

Every network call is mocked. No live Splunk instance required.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from integrations.adapters.splunk import SplunkLogProvider
from integrations.schemas import LogQuery, _spl_escape, _spl_token


# ---------------------------------------------------------------------------
# SPL translation + helpers
# ---------------------------------------------------------------------------


class TestSPLEscapingHelpers(SimpleTestCase):
    """The escape helpers are the security boundary — test them hard."""

    def test_escape_plain_string_untouched(self):
        self.assertEqual(_spl_escape("acme-checkout"), "acme-checkout")

    def test_escape_double_quote(self):
        self.assertEqual(_spl_escape('foo"bar'), 'foo\\"bar')

    def test_escape_backslash(self):
        self.assertEqual(_spl_escape("foo\\bar"), "foo\\\\bar")

    def test_escape_backslash_then_quote(self):
        # Order matters — the backslash pass must come first so the
        # escape it inserts for the quote doesn't get re-escaped.
        self.assertEqual(_spl_escape('foo"\\bar'), 'foo\\"\\\\bar')

    def test_escape_rejects_non_string(self):
        with self.assertRaises(TypeError):
            _spl_escape(123)
        with self.assertRaises(TypeError):
            _spl_escape(None)
        with self.assertRaises(TypeError):
            _spl_escape({"a": 1})

    def test_token_accepts_valid_index(self):
        for name in ("main", "acme-logs", "app_logs", "prod-2026"):
            self.assertEqual(_spl_token(name), name)

    def test_token_rejects_injection(self):
        for bad in ('main"', "main OR *", "main; DROP", "main/../etc", ""):
            with self.assertRaises(ValueError):
                _spl_token(bad)

    def test_token_rejects_non_string(self):
        with self.assertRaises(ValueError):
            _spl_token(None)


class TestLogQueryToSPL(SimpleTestCase):
    """LogQuery.to_splunk_spl builds correctly-quoted SPL."""

    def test_default_index_only(self):
        spl = LogQuery().to_splunk_spl()
        self.assertTrue(spl.startswith("search index=main"))
        self.assertIn("| head 5000", spl)

    def test_project_and_env_filters(self):
        q = LogQuery(project="acme-checkout", environment="production")
        spl = q.to_splunk_spl()
        self.assertIn('(project_name IN ("acme-checkout") OR project IN ("acme-checkout"))', spl)
        self.assertIn('environment IN ("production", "prod", "prd")', spl)
        self.assertIn('env IN ("production", "prod", "prd")', spl)

    def test_severity_list_becomes_or_join(self):
        spl = LogQuery(severity=["error", "warning"]).to_splunk_spl()
        # Every spelling (values match case-insensitively in SPL), on every
        # level field, or a message word for raw events without one.
        self.assertIn('log_level IN ("ERROR", "ERR", "WARNING", "WARN", "50", "40")', spl)
        self.assertIn('log.level IN (', spl)
        self.assertIn(' OR exception OR ', spl)

    def test_services_becomes_in_clause(self):
        spl = LogQuery(services=["api", "worker"]).to_splunk_spl()
        self.assertIn('service_name IN ("api", "worker")', spl)
        self.assertIn('kubernetes.labels.app IN ("api", "worker")', spl)
        self.assertNotIn('app.kubernetes.io/name', spl)  # search cannot quote a field name

    def test_text_search_quoted_phrase(self):
        spl = LogQuery(text_search="timeout on payment").to_splunk_spl()
        self.assertIn('"timeout on payment"', spl)

    def test_max_results_reflected_in_head(self):
        spl = LogQuery(max_results=42).to_splunk_spl()
        self.assertIn("| head 42", spl)

    def test_custom_index(self):
        spl = LogQuery().to_splunk_spl(index="acme-logs")
        self.assertTrue(spl.startswith("search index=acme-logs"))

    def test_injection_attempt_in_value_is_escaped(self):
        # The classic injection: try to escape the quoted value and
        # inject a new SPL clause. Both the quote and the backslash
        # must survive escaping so it stays inside the string literal.
        spl = LogQuery(project='foo" OR index=* OR "').to_splunk_spl()
        # The escaped form should appear once, and no unescaped OR
        # from the payload should exist outside the quotes.
        self.assertIn('project_name IN ("foo\\" OR index=* OR \\"")', spl)

    def test_injection_attempt_in_index_raises(self):
        # Values that go into a bareword position (like index=) must
        # raise, not silently rewrite. Silent rewrites route queries
        # to the wrong index which is worse than failing loudly.
        with self.assertRaises(ValueError):
            LogQuery().to_splunk_spl(index="main OR index=*")


# ---------------------------------------------------------------------------
# Adapter construction
# ---------------------------------------------------------------------------


class TestSplunkAdapterInit(SimpleTestCase):

    def test_requires_host(self):
        with self.assertRaisesRegex(ValueError, "host"):
            SplunkLogProvider(config={"password": "tok"})

    def test_requires_token(self):
        with self.assertRaisesRegex(ValueError, "token"):
            SplunkLogProvider(config={"host": "https://s.example"})

    def test_strips_trailing_slash_from_host(self):
        provider = SplunkLogProvider(config={
            "host": "https://s.example:8089/",
            "password": "tok",
        })
        # Endpoint builder uses base + "/" already; we just want the
        # stored base to not double-slash.
        self.assertEqual(provider._base_url, "https://s.example:8089")

    def test_bearer_token_header(self):
        provider = SplunkLogProvider(config={
            "host": "https://s.example",
            "password": "sekrit-token",
        })
        self.assertEqual(
            provider._session.headers["Authorization"], "Bearer sekrit-token"
        )
        self.assertEqual(provider._session.headers["Accept"], "application/json")

    def test_verify_ssl_configurable(self):
        p1 = SplunkLogProvider(config={"host": "https://x", "password": "t"})
        self.assertTrue(p1._session.verify)
        p2 = SplunkLogProvider(config={
            "host": "https://x", "password": "t", "verify_ssl": False,
        })
        self.assertFalse(p2._session.verify)


# ---------------------------------------------------------------------------
# Search flow
# ---------------------------------------------------------------------------


def _make_provider() -> SplunkLogProvider:
    return SplunkLogProvider(config={
        "host": "https://splunk.example:8089",
        "password": "tok",
    })


class TestSplunkSearchFlow(SimpleTestCase):
    """Mocks the whole HTTP surface via patching the requests.Session."""

    def setUp(self):
        self.provider = _make_provider()
        self.session = MagicMock()
        self.provider._session = self.session
        # Preserve the header dict shape so any callers reading it work
        self.session.headers = {"Authorization": "Bearer tok", "Accept": "application/json"}

    def _mock_start_ok(self, sid: str = "sid-1"):
        r = MagicMock(status_code=201)
        r.json.return_value = {"sid": sid}
        self.session.post.return_value = r

    def _mock_poll_done(self):
        r = MagicMock(status_code=200)
        r.json.return_value = {
            "entry": [{"content": {"dispatchState": "DONE"}}]
        }
        return r

    def _mock_results(self, rows):
        r = MagicMock(status_code=200)
        r.json.return_value = {"results": rows}
        r.raise_for_status = MagicMock()
        return r

    def test_json_events_from_hec_shippers(self):
        """Fluent Bit / OTel / Vector send JSON events; unless the sourcetype
        extracts them the canonical fields are only inside _raw."""
        self._mock_start_ok()
        raw = ('{"service_name":"payments","log_level":"ERROR","environment":"production",'
               '"message":"pool exhausted","kubernetes":{"pod_name":"payments-1"}}')
        self.session.get.side_effect = [self._mock_poll_done(), self._mock_results([
            {"_time": "2026-08-26T12:00:00Z", "_raw": raw},
        ])]
        (e,) = self.provider.search(index="main", query=LogQuery(severity=["error"]),
                                    time_range=(datetime(2026, 8, 26, 11), datetime(2026, 8, 26, 12)))
        self.assertEqual(e.service, "payments")
        self.assertEqual(e.level, "ERROR")
        self.assertEqual(e.message, "pool exhausted")
        # ...and every field is requested from /results (only defaults otherwise).
        self.assertEqual(self.session.get.call_args.kwargs["params"]["f"], "*")

    def test_extracted_fields_win_over_raw(self):
        self._mock_start_ok()
        self.session.get.side_effect = [self._mock_poll_done(), self._mock_results([
            {"_time": "2026-08-26T12:00:00Z", "_raw": '{"service_name":"old"}', "service_name": "checkout"},
        ])]
        (e,) = self.provider.search(index="main", query=LogQuery(),
                                    time_range=(datetime(2026, 8, 26, 11), datetime(2026, 8, 26, 12)))
        self.assertEqual(e.service, "checkout")

    def test_comma_list_falls_back_to_configured_index(self):
        """The batch code passes ','.join(get_indices()); never send that to Splunk."""
        self._mock_start_ok()
        self.session.get.side_effect = [self._mock_poll_done(), self._mock_results([])]
        self.provider.search(index="_internal,main,summary", query=LogQuery(severity=["error"]),
                             time_range=(datetime(2026, 8, 26, 11), datetime(2026, 8, 26, 12)))
        spl = self.session.post.call_args.kwargs["data"]["search"]
        self.assertIn("index=main", spl)
        self.assertNotIn(",", spl.split("index=", 1)[1].split()[0])

    def test_happy_path_returns_normalised_entries(self):
        self._mock_start_ok()
        results_resp = self._mock_results([
            {
                "_time": "2026-08-26T12:00:00Z",
                "_raw": "connection refused",
                "log_level": "ERROR",
                "service_name": "payment-worker",
                "host": "worker-1",
                "trace_id": "t-abc",
                "_cd": "0:1234",
                "extra": "kept-in-labels",
            },
        ])
        # GET is called twice — once for poll, once for results.
        self.session.get.side_effect = [self._mock_poll_done(), results_resp]

        entries = self.provider.search(
            index="main",
            query=LogQuery(severity=["error"]),
            time_range=(datetime(2026, 8, 26, 11), datetime(2026, 8, 26, 12)),
        )

        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e.message, "connection refused")
        self.assertEqual(e.level, "ERROR")
        self.assertEqual(e.service, "payment-worker")
        self.assertEqual(e.host, "worker-1")
        self.assertEqual(e.raw_id, "0:1234")
        # Underscore-prefixed Splunk internals + canonical fields must
        # be filtered out of labels; the "extra" custom field survives.
        self.assertEqual(e.labels["extra"], "kept-in-labels")
        self.assertNotIn("_cd", e.labels)
        self.assertNotIn("log_level", e.labels)
        self.assertNotIn("service_name", e.labels)
        # _index gets stamped so downstream can route
        self.assertEqual(e.labels["_index"], "main")

    def test_start_job_failure_returns_empty(self):
        r = MagicMock(status_code=401, text="Unauthorized")
        self.session.post.return_value = r
        result = self.provider.search(index="main", query=LogQuery())
        self.assertEqual(result, [])
        # We must NOT call poll or results if start failed
        self.session.get.assert_not_called()

    def test_poll_failed_dispatch_returns_empty(self):
        self._mock_start_ok()
        failed_poll = MagicMock(status_code=200)
        failed_poll.json.return_value = {
            "entry": [{"content": {"dispatchState": "FAILED", "messages": []}}]
        }
        self.session.get.return_value = failed_poll
        result = self.provider.search(index="main", query=LogQuery())
        self.assertEqual(result, [])

    def test_dict_query_uses_raw_spl(self):
        self._mock_start_ok()
        self.session.get.side_effect = [self._mock_poll_done(), self._mock_results([])]
        self.provider.search(
            index="main",
            query={"spl": "search index=main custom_field=xyz"},
        )
        # Confirm the raw SPL was sent as the search body
        sent = self.session.post.call_args.kwargs.get("data", {})
        self.assertEqual(sent["search"], "search index=main custom_field=xyz")

    def test_search_rejects_unsupported_query_type(self):
        with self.assertRaises(TypeError):
            self.provider.search(index="main", query=object())


class TestSplunkHealthCheck(SimpleTestCase):

    def setUp(self):
        self.provider = _make_provider()
        self.session = MagicMock()
        self.session.headers = self.provider._session.headers
        self.provider._session = self.session

    def test_health_check_ok(self):
        self.session.get.return_value = MagicMock(status_code=200)
        self.assertTrue(self.provider.health_check())

    def test_health_check_unauthorised(self):
        self.session.get.return_value = MagicMock(status_code=401)
        self.assertFalse(self.provider.health_check())

    def test_health_check_network_error(self):
        from requests.exceptions import ConnectionError as ReqConnErr
        self.session.get.side_effect = ReqConnErr("dns failure")
        self.assertFalse(self.provider.health_check())


class TestSplunkGetIndices(SimpleTestCase):

    def setUp(self):
        self.provider = _make_provider()
        self.session = MagicMock()
        self.session.headers = self.provider._session.headers
        self.provider._session = self.session

    def _visible(self, *names):
        r = MagicMock(status_code=200)
        r.json.return_value = {"entry": [{"name": n} for n in names]}
        r.raise_for_status = MagicMock()
        self.session.get.return_value = r

    def test_returns_only_the_configured_index(self):
        """Every visible index used to be returned; the batch code joined
        them into a comma list that the SPL bareword check rejects."""
        self._visible("_audit", "_internal", "main", "acme-logs", "")
        self.assertEqual(self.provider.get_indices(project=MagicMock(name="Any")), ["main"])

    def test_configured_index_from_extra_config(self):
        self.provider._index = "acme-logs"
        self._visible("main", "acme-logs")
        self.assertEqual(self.provider.get_indices(project=None), ["acme-logs"])

    def test_configured_index_not_visible(self):
        self._visible("_internal", "other")
        self.assertEqual(self.provider.get_indices(project=None), [])

    def test_get_indices_swallows_failure(self):
        from requests.exceptions import ConnectionError as ReqConnErr
        self.session.get.side_effect = ReqConnErr("boom")
        self.assertEqual(self.provider.get_indices(project=None), [])


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestSplunkRegistration(SimpleTestCase):
    """Splunk must be reachable through the same registry path as the others."""

    def test_provider_in_adapter_map(self):
        from integrations.models import ADAPTER_MAP
        self.assertIn("splunk", ADAPTER_MAP)
        self.assertEqual(
            ADAPTER_MAP["splunk"]["logs"],
            "integrations.adapters.splunk.SplunkLogProvider",
        )

    def test_provider_in_choices(self):
        from integrations.models import ObservabilityIntegration
        codes = [c for c, _ in ObservabilityIntegration.PROVIDER_CHOICES]
        self.assertIn("splunk", codes)
