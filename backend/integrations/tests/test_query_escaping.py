"""Names from organisations, projects, environments and services stay values
in every query language SerOps writes (phase 3 review, MT-6 and LG17).

An unescaped ``"`` used to end the PromQL string literal: a project named
``x"} or up{organisation_name=~".+`` read every organisation's series from a
Prometheus they share, and a quote in an ordinary name gave a parse error
that read as "no metrics".
"""
import re
from datetime import datetime, timezone
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from integrations.adapters.prometheus import PrometheusMetricProvider
from integrations.promql import promql_escape, promql_matchers
from integrations.schemas import LogQuery

INJECTION = 'x"} or up{organisation_name=~".+'
T0 = datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 11, 16, 10, 5, tzinfo=timezone.utc)


def _string_literals(expr):
    """The double-quoted literals of a PromQL/LogQL expression, honouring
    backslash escapes, and what is left outside them."""
    literals, outside, i = [], [], 0
    while i < len(expr):
        if expr[i] == '"':
            j, buf = i + 1, []
            while expr[j] != '"':
                if expr[j] == '\\':
                    buf.append(expr[j + 1])
                    j += 2
                else:
                    buf.append(expr[j])
                    j += 1
            literals.append(''.join(buf))
            i = j + 1
        else:
            outside.append(expr[i])
            i += 1
    return literals, ''.join(outside)


class PromQLTest(SimpleTestCase):

    def test_values_are_escaped(self):
        self.assertEqual(promql_escape('a"b\\c'), 'a\\"b\\\\c')
        self.assertEqual(promql_matchers({'project_name': 'a"b', 'environment': ''}), 'project_name="a\\"b"')

    def test_an_injected_project_name_stays_one_value(self):
        selector = PrometheusMetricProvider._build_selector(
            'node_memory_MemTotal_bytes', {'organisation_name': 'acme', 'project_name': INJECTION})

        literals, outside = _string_literals(selector)
        self.assertEqual(literals, ['acme', INJECTION])
        # Nothing of the name is left outside the quotes: no "or", no second selector.
        self.assertEqual(outside, 'node_memory_MemTotal_bytes{organisation_name=,project_name=}')

    def test_an_invalid_label_name_is_refused_not_dropped(self):
        with self.assertRaises(ValueError):
            promql_matchers({'organisation_name="x"} or up{a': 'b'})

    def test_the_kubernetes_query_escapes_values(self):
        provider = PrometheusMetricProvider.__new__(PrometheusMetricProvider)
        provider._topology_mode = 'kubernetes'
        provider.query_range_expr = MagicMock(return_value=[])
        provider.query_range(
            'node_cpu_seconds_total', {'organisation_name': 'acme', 'project_name': INJECTION}, T0, T1)

        expr = provider.query_range_expr.call_args[0][0]
        literals, outside = _string_literals(expr)
        self.assertIn(INJECTION, literals)
        self.assertNotIn(' or up', outside)

    def test_the_peak_pod_queries_escape_values(self):
        from integrations.metrics_processing import _fetch_peak_pod_metrics
        provider = MagicMock(spec=['query_range_expr'])
        provider.query_range_expr.return_value = []
        _fetch_peak_pod_metrics(provider, {'organisation_name': 'acme', 'project_name': INJECTION}, T0, T1)

        exprs = [c.args[0] for c in provider.query_range_expr.call_args_list]
        self.assertTrue(exprs)
        for expr in exprs:
            literals, outside = _string_literals(expr)
            self.assertIn(INJECTION, literals)
            self.assertNotIn(' or up', outside)


class LogQLTest(SimpleTestCase):

    def test_services_category_event_type_and_text_are_escaped(self):
        query = LogQuery(project='shop', services=['pay.ments', 'a"b'], category='c"x',
                         event_type='e"} | x', text_search='err"} |~ "')
        logql = query.to_logql()

        self.assertIn('service_name=~"pay\\\\.ments|a\\"b"', logql)
        self.assertIn('category="c\\"x"', logql)
        self.assertIn('event_type="e\\"} | x"', logql)
        literals, outside = _string_literals(logql)
        # Every value is inside its own literal; nothing of it leaks out.
        self.assertIn('shop', literals)
        # The text is an RE2 literal: "|" is escaped for the regex as well.
        self.assertIn('err"\\} \\|~ "', literals)
        self.assertNotIn('err', outside)

    def test_the_legacy_loki_builder_escapes_values(self):
        from integrations.adapters.loki import LokiLogProvider
        logql = LokiLogProvider._build_logql('a"b', {'match_phrase': {'message': 'x\\"y'}})

        literals, outside = _string_literals(logql)
        self.assertEqual(literals, ['a"b', 'x\\"y'])

    def test_the_legacy_loki_builder_refuses_a_bad_label_name(self):
        from integrations.adapters.loki import LokiLogProvider
        with self.assertRaises(ValueError):
            LokiLogProvider._build_logql('app', {'stream_labels': {'a="x"} or {b': 'c'}})


class OtherLanguagesTest(SimpleTestCase):
    """The builders that already escaped, pinned so they keep doing it."""

    def _q(self, **kw):
        return LogQuery(project=INJECTION, environment='prod"x', time_range=(T0, T1), **kw)

    def test_kql(self):
        kql = self._q().to_azure_kql()
        self.assertIn('"x\\"} or up{organisation_name=~\\".+"', kql)

    def test_spl(self):
        spl = self._q().to_splunk_spl()
        self.assertIn('x\\"} or up{organisation_name=~\\".+', spl)

    def test_gcp_filter(self):
        gcp = self._q().to_gcp_filter()
        self.assertIn('labels.project_name="x\\"} or up{organisation_name=~\\".+"', gcp)

    def test_gcp_rule_fields_cannot_inject_a_path(self):
        gcp = LogQuery(project='shop', project_rules=[('resource.x OR labels.a', 'v')]).to_gcp_filter()
        self.assertIn('labels."resource.x OR labels.a"="v"', gcp)

    def test_cloudwatch_insights(self):
        cw = self._q().to_cloudwatch_insights()
        self.assertIn("'x\"} or up{organisation_name=~\".+'", cw)
        # The log-group regex is delimited by "/": a "/" in a name is escaped.
        cw = LogQuery(project='a/b').to_cloudwatch_insights()
        self.assertTrue(re.search(r'a\\/b', cw))

    def test_datadog(self):
        dd = LogQuery(project='shop', text_search='x OR service:other').to_datadog_query()
        self.assertIn('"x OR service:other"', dd)


class TraceQueryTest(SimpleTestCase):

    def test_datadog_traces_quote_the_service(self):
        from integrations.adapters.datadog_traces import DatadogTraceAdapter
        provider = DatadogTraceAdapter.__new__(DatadogTraceAdapter)
        provider._session = MagicMock()
        provider._session.post.return_value.json.return_value = {'data': []}
        provider.base_url = 'https://api.datadoghq.eu'
        provider.timeout_seconds = 5
        try:
            provider.fetch_traces('my svc OR service:other', T0, T1)
        except Exception:
            pass
        body = provider._session.post.call_args.kwargs['json']
        self.assertIn('service:"my svc OR service:other"', body['data']['attributes']['filter']['query'])

    def test_tempo_quotes_the_service(self):
        from integrations.adapters.tempo_traces import TempoTraceAdapter
        provider = TempoTraceAdapter.__new__(TempoTraceAdapter)
        provider._session = MagicMock()
        provider._session.get.return_value.json.return_value = {'traces': []}
        provider._session.get.return_value.status_code = 200
        provider.base_url = 'http://tempo'
        provider.timeout_seconds = 5
        try:
            provider.fetch_traces('my svc', T0, T1)
        except Exception:
            pass
        params = provider._session.get.call_args.kwargs.get('params') or provider._session.get.call_args[1]['params']
        self.assertEqual(params['tags'], 'service.name="my svc"')
