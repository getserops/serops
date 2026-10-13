"""Regression tests for bugs found validating the documented Kubernetes
setup against a real cluster (k8s 1.31 / containerd, Loki 2.9, Promtail 3.5).

Every test here locks in behaviour that was observed to be wrong on live
data, not behaviour deduced from reading the code. The corresponding
real-cluster observation is named in each test so a future reader can tell
what would break if the assertion were relaxed.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from integrations.adapters.loki import LokiLogProvider
from integrations.schemas import (
    _logql_severity_alternatives,
    EMPTY_LOGQL_SELECTOR,
    LogQuery,
    _detect_level,
    _detect_level_from_line,
)


class MultiServiceSelectorTest(SimpleTestCase):
    """Observed: `service_name=~"api| checkout"` returned 1 of 2 streams.

    RE2 read " checkout" as a literal with a leading space, so every
    alternative after the first silently matched nothing. A batch scoped
    to N services fed the AI logs from only the first.
    """

    def test_services_joined_without_space(self):
        logql = LogQuery(services=['api', 'checkout']).to_logql()
        self.assertIn('service_name=~"api|checkout"', logql)
        self.assertNotIn('| ', logql)

    def test_three_services_all_present(self):
        logql = LogQuery(services=['api', 'checkout', 'redis']).to_logql()
        self.assertIn('service_name=~"api|checkout|redis"', logql)

    def test_single_service_unaffected(self):
        self.assertIn(
            'service_name=~"api"', LogQuery(services=['api']).to_logql(),
        )

    def test_severity_filter_has_no_stray_space(self):
        """Severity moved to a line filter (see SeverityLineFilterTest), but
        it must stay free of the same spaced-join defect."""
        logql = LogQuery(severity=['ERROR', 'WARN']).to_logql()
        self.assertNotIn('| ERROR', logql)
        self.assertNotIn('|WARN|  ', logql)


class EmptySelectorTest(SimpleTestCase):
    """Observed: an unfiltered query produced `{}`, and Loki answered
    HTTP 400 "queries require at least one regexp or equality matcher
    that does not have an empty-compatible value".
    """

    def test_unfiltered_query_yields_the_named_sentinel(self):
        self.assertEqual(LogQuery().to_logql(), EMPTY_LOGQL_SELECTOR)

    def test_any_filter_produces_a_real_selector(self):
        self.assertNotEqual(
            LogQuery(project='shop').to_logql(), EMPTY_LOGQL_SELECTOR,
        )


def _labels_response(labels):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {'status': 'success', 'data': labels}
    return resp


class AnyStreamSelectorTest(SimpleTestCase):
    """Loki cannot express "every stream", so an unfiltered sample has to
    name a label that exists. Which label is chosen decides whether the
    ingest-health report is honest.
    """

    def setUp(self):
        self.provider = LokiLogProvider(config={'host': 'http://loki:3100'})

    @patch('integrations.adapters.loki.requests.Session.get')
    def test_prefers_structural_label(self, mock_get):
        mock_get.return_value = _labels_response(
            ['environment', 'filename', 'service_name'],
        )
        self.assertEqual(
            self.provider._any_stream_selector(), '{filename=~".+"}',
        )

    @patch('integrations.adapters.loki.requests.Session.get')
    def test_never_picks_canonical_when_any_alternative_exists(self, mock_get):
        """Selecting on service_name would sample only streams that
        already have it, reporting 100% coverage on a mostly-untagged
        cluster. Any non-canonical label is preferable.
        """
        mock_get.return_value = _labels_response(['service_name', 'widget'])
        self.assertEqual(
            self.provider._any_stream_selector(), '{widget=~".+"}',
        )

    @patch('integrations.adapters.loki.requests.Session.get')
    def test_canonical_only_as_last_resort(self, mock_get):
        mock_get.return_value = _labels_response(['service_name'])
        self.assertEqual(
            self.provider._any_stream_selector(), '{service_name=~".+"}',
        )

    @patch('integrations.adapters.loki.requests.Session.get')
    def test_no_labels_returns_none(self, mock_get):
        mock_get.return_value = _labels_response([])
        self.assertIsNone(self.provider._any_stream_selector())

    @patch('integrations.adapters.loki.requests.Session.get')
    def test_uses_discovered_selector_for_unfiltered_search(self, mock_get):
        """The end-to-end shape of the fix: an unfiltered LogQuery must
        never put `{}` on the wire.
        """
        def responder(url, **kwargs):
            if url.endswith('/loki/api/v1/labels'):
                return _labels_response(['pod'])
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                'status': 'success', 'data': {'result': []},
            }
            return resp

        mock_get.side_effect = responder
        end = datetime.now(timezone.utc)
        self.provider.search(None, LogQuery(
            time_range=(end - timedelta(minutes=30), end), max_results=10,
        ))

        queries = [
            kwargs['params']['query']
            for _, kwargs in mock_get.call_args_list
            if 'params' in kwargs and 'query' in kwargs.get('params', {})
        ]
        self.assertTrue(queries, 'no query_range call was made')
        self.assertNotIn(EMPTY_LOGQL_SELECTOR, queries)
        self.assertIn('{pod=~".+"}', queries)


class LevelFromLineTest(SimpleTestCase):
    """Observed: 200/200 sampled records came back INFO, including lines
    reading `ERROR checkout PaymentGatewayTimeout`. Loki keeps severity in
    the line, not in a stream label, and `_detect_level` only ever saw the
    (absent) label.
    """

    def test_normalizer_cannot_parse_a_line(self):
        """Why a second helper exists at all."""
        self.assertEqual(
            _detect_level('2026-09-27 ERROR checkout failed'), 'INFO',
        )

    def test_plain_prefixed_levels(self):
        for line, expected in [
            ('2026-09-27T12:00:00+00:00 ERROR checkout timeout', 'ERROR'),
            ('2026-09-27T12:00:00+00:00 WARN  redis evicted keys=17', 'WARN'),
            ('2026-09-27T12:00:00+00:00 INFO  api GET /v1/orders 200', 'INFO'),
            ('2026-09-27T12:00:00+00:00 DEBUG cache warm', 'DEBUG'),
        ]:
            with self.subTest(line=line):
                self.assertEqual(_detect_level_from_line(line), expected)

    def test_bracketed_and_structured_forms(self):
        for line, expected in [
            ('[ERROR] payment gateway timeout', 'ERROR'),
            ('ts=2026-09-27 level=warn msg="disk almost full"', 'WARN'),
            ('{"ts":"2026-09-27","level":"error","msg":"boom"}', 'ERROR'),
            ('lvl=debug component=cache', 'DEBUG'),
        ]:
            with self.subTest(line=line):
                self.assertEqual(_detect_level_from_line(line), expected)

    def test_severity_synonyms_normalize(self):
        self.assertEqual(_detect_level_from_line('FATAL disk lost'), 'ERROR')
        self.assertEqual(_detect_level_from_line('[CRITICAL] psu'), 'ERROR')
        self.assertEqual(_detect_level_from_line('WARNING slow query'), 'WARN')

    def test_prose_mention_does_not_promote(self):
        """A standalone-token requirement keeps message bodies from
        misclassifying an otherwise INFO line.
        """
        self.assertEqual(
            _detect_level_from_line('INFO  retried after errorHandler ran'),
            'INFO',
        )
        self.assertEqual(
            _detect_level_from_line('INFO  errors=0 warnings=0'), 'INFO',
        )

    def test_first_token_wins(self):
        self.assertEqual(
            _detect_level_from_line('ERROR downstream returned INFO page'),
            'ERROR',
        )

    def test_empty_and_unmatched_fall_back(self):
        self.assertEqual(_detect_level_from_line(''), 'INFO')
        self.assertEqual(_detect_level_from_line('no level here'), 'INFO')
        self.assertEqual(
            _detect_level_from_line('no level here', default='DEBUG'), 'DEBUG',
        )

    def test_body_mention_beyond_scan_window_ignored(self):
        line = 'INFO ' + ('x' * 400) + ' ERROR'
        self.assertEqual(_detect_level_from_line(line), 'INFO')


def _stream_response(stream_labels, lines):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        'status': 'success',
        'data': {'result': [{
            'stream': stream_labels,
            'values': [[str(1700000000000000000 + i), ln]
                       for i, ln in enumerate(lines)],
        }]},
    }
    return resp


class LokiLevelIntegrationTest(SimpleTestCase):
    """The parser's level precedence: label first, line only as fallback."""

    def setUp(self):
        self.provider = LokiLogProvider(config={'host': 'http://loki:3100'})

    @patch('integrations.adapters.loki.requests.Session.get')
    def test_level_parsed_from_line_when_no_label(self, mock_get):
        mock_get.return_value = _stream_response(
            {'service_name': 'checkout', 'pod': 'checkout-1'},
            [
                '2026-09-27T12:00:00+00:00 ERROR checkout PaymentGatewayTimeout',
                '2026-09-27T12:00:02+00:00 WARN  checkout payment retry',
                '2026-09-27T12:00:04+00:00 INFO  checkout order placed',
            ],
        )
        entries = self.provider.search('x', {'logql': '{service_name="checkout"}'})
        self.assertEqual([e.level for e in entries], ['ERROR', 'WARN', 'INFO'])

    @patch('integrations.adapters.loki.requests.Session.get')
    def test_explicit_label_beats_line_text(self, mock_get):
        """An operator who did promote log_level stays authoritative."""
        mock_get.return_value = _stream_response(
            {'service_name': 'api', 'log_level': 'ERROR'},
            ['2026-09-27T12:00:00+00:00 INFO  api handled request'],
        )
        entries = self.provider.search('x', {'logql': '{service_name="api"}'})
        self.assertEqual([e.level for e in entries], ['ERROR'])

    @patch('integrations.adapters.loki.requests.Session.get')
    def test_legacy_level_label_still_honoured(self, mock_get):
        mock_get.return_value = _stream_response(
            {'service_name': 'api', 'level': 'warn'},
            ['2026-09-27T12:00:00+00:00 some message'],
        )
        entries = self.provider.search('x', {'logql': '{service_name="api"}'})
        self.assertEqual([e.level for e in entries], ['WARN'])


class SearchErrorSurfacingTest(SimpleTestCase):
    """Observed: a 400 became `return []`, and the validator rendered five
    "missing canonical field" warnings. Empty-vs-failed must be separable.
    """

    def setUp(self):
        self.provider = LokiLogProvider(config={'host': 'http://loki:3100'})

    @patch('integrations.adapters.loki.requests.Session.get')
    def test_request_failure_records_last_error(self, mock_get):
        from requests.exceptions import RequestException
        mock_get.side_effect = RequestException('400 Client Error: Bad Request')

        self.assertEqual(
            self.provider.search('x', {'logql': '{a="b"}'}), [],
        )
        self.assertIsNotNone(self.provider.last_error)
        self.assertIn('{a="b"}', self.provider.last_error)

    @patch('integrations.adapters.loki.requests.Session.get')
    def test_genuine_empty_result_leaves_last_error_clear(self, mock_get):
        mock_get.return_value = _stream_response({'service_name': 'api'}, [])
        self.assertEqual(
            self.provider.search('x', {'logql': '{a="b"}'}), [],
        )
        self.assertIsNone(self.provider.last_error)

    @patch('integrations.adapters.loki.requests.Session.get')
    def test_last_error_cleared_between_searches(self, mock_get):
        from requests.exceptions import RequestException
        mock_get.side_effect = RequestException('boom')
        self.provider.search('x', {'logql': '{a="b"}'})
        self.assertIsNotNone(self.provider.last_error)

        mock_get.side_effect = None
        mock_get.return_value = _stream_response({'service_name': 'api'}, [])
        self.provider.search('x', {'logql': '{a="b"}'})
        self.assertIsNone(self.provider.last_error)


class SeverityLineFilterTest(SimpleTestCase):
    """Observed: the stream selector alone returned 500 lines, and appending
    `| log_level=~"ERROR|WARNING|CRITICAL"` returned ZERO.

    `| x=~` is a LABEL filter, and log_level is not a Loki label (promoting
    severity to a label would multiply label cardinality, so collectors keep
    it in the line). Every batch for every Loki user was analysing an empty
    log set — and still reported success.
    """

    def test_severity_is_a_line_filter_not_a_label_filter(self):
        logql = LogQuery(severity=['ERROR']).to_logql()
        self.assertIn('|~', logql)
        self.assertNotIn('| log_level=~', logql)

    def test_case_insensitive(self):
        self.assertIn('(?i)', LogQuery(severity=['ERROR']).to_logql())

    def test_warning_also_matches_the_warn_spelling(self):
        """SerOps asks for WARNING; emitters overwhelmingly write WARN."""
        logql = LogQuery(severity=['WARNING']).to_logql()
        self.assertIn('WARNING', logql)
        self.assertIn('WARN', logql)

    def test_error_also_matches_err(self):
        logql = LogQuery(severity=['ERROR']).to_logql()
        self.assertIn('ERROR', logql)
        self.assertIn('ERR', logql)

    def test_critical_covers_crit_and_fatal(self):
        logql = LogQuery(severity=['CRITICAL']).to_logql()
        for spelling in ('CRITICAL', 'CRIT', 'FATAL'):
            self.assertIn(spelling, logql)

    def test_longer_spellings_precede_their_prefixes(self):
        """RE2 alternation is leftmost-first: ERR before ERROR would match
        only the prefix and truncate the token."""
        parts = _logql_severity_alternatives(['ERROR']).split('|')
        self.assertLess(parts.index('ERROR'), parts.index('ERR'))

    def test_no_duplicate_alternatives(self):
        alts = _logql_severity_alternatives(['ERROR', 'ERR', 'CRITICAL', 'FATAL'])
        parts = alts.split('|')
        self.assertEqual(len(parts), len(set(parts)))

    def test_selector_still_precedes_the_filter(self):
        logql = LogQuery(project='shop', severity=['ERROR']).to_logql()
        self.assertLess(logql.index('project_name="shop"'), logql.index('|~'))

    def test_unknown_severity_passes_through(self):
        self.assertIn('NOTICE', _logql_severity_alternatives(['notice']))
