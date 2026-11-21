"""JVM garbage collection: the query, the narrow fallback, the summary and
the prompt line (client C2, J2: a Java service in repeated full GCs was
named but GC never was)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase

from ai_model.prompt_context import DataSourceContext
from ai_model.prompts import _build_user_content
from integrations import metrics_processing as mp
from integrations.schemas import TimeSeries, TimeSeriesPoint

T0 = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
LABELS = {'organisation_name': 'Ledger', 'project_name': 'ledger', 'environment': 'production'}


def series(labels, *values):
    return TimeSeries(metric_name='x', labels=labels,
                      points=[TimeSeriesPoint(timestamp=T0 + timedelta(seconds=15 * i), value=v)
                              for i, v in enumerate(values)])


class FakeProvider:
    def __init__(self, answers):
        self.answers = list(answers)
        self.exprs = []

    def query_range_expr(self, expr, start, end):
        self.exprs.append(expr)
        answer = self.answers.pop(0) if self.answers else []
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeQuerySet(list):
    def exclude(self, **kw):
        return FakeQuerySet(d for d in self if d['namespace'])

    def values_list(self, field, flat=True):
        return [d[field] for d in self]


def project(namespaces=(), services=('ad', 'checkout')):
    return SimpleNamespace(
        log_rules_clean=lambda: [('namespace', n) for n in namespaces],
        deployments=FakeQuerySet([]),
        services=FakeQuerySet([{'name': s} for s in services]))


class FetchTest(SimpleTestCase):

    def test_the_project_labels_are_tried_first_and_one_query_covers_every_agent(self):
        provider = FakeProvider([[series({'service_name': 'ad'}, 2.0, 35.0)],
                                 [series({'service_name': 'ad'}, 1.0, 40.0)]])
        out = mp._fetch_jvm_gc(provider, LABELS, T0, T0, project(['ledger']))
        self.assertEqual(out['jvm_gc_matched_by'], 'project labels')
        self.assertEqual([p['value'] for p in out['jvm_gc_time_percent']], [2.0, 35.0])
        self.assertEqual(out['jvm_gc_time_percent'][0]['series_key'], 'ad')
        share, count = provider.exprs
        for name in ('jvm_gc_duration_seconds_sum', 'process_runtime_jvm_gc_duration_seconds_sum',
                     'process_runtime_jvm_gc_duration_milliseconds_sum', 'jvm_gc_collection_seconds_sum',
                     'jvm_gc_pause_seconds_sum'):
            self.assertIn(name, share)
        self.assertIn('project_name="ledger"', share)
        self.assertIn('jvm_gc_action!~"(?i).*concurrent.*"', share)
        self.assertIn('* 0.1)', share)          # milliseconds -> % of time
        self.assertIn('jvm_gc_pause_seconds_count', count)
        self.assertIn('* 60', count)
        self.assertNotIn('namespace=~', share)

    def test_the_fallback_needs_a_namespace_and_stays_on_the_projects_services(self):
        provider = FakeProvider([[], [series({'job': 'ledger/ad'}, 30.0)], []])
        out = mp._fetch_jvm_gc(provider, LABELS, T0, T0, project(['ledger'], ['ad', 'fraud-detection']))
        self.assertEqual(out['jvm_gc_matched_by'], 'namespace and service')
        self.assertEqual(out['jvm_gc_time_percent'][0]['series_key'], 'ad')
        fallback = provider.exprs[1]
        self.assertNotIn('project_name=', fallback)
        self.assertIn('namespace=~"ledger"', fallback)
        self.assertIn('service_name=~"ad|fraud\\\\-detection"', fallback)
        self.assertIn('job=~"(.+/)?(ad|fraud\\\\-detection)"', fallback)

    def test_no_namespace_means_no_fallback(self):
        provider = FakeProvider([[]])
        self.assertEqual(mp._fetch_jvm_gc(provider, LABELS, T0, T0, project([])), {})
        self.assertEqual(len(provider.exprs), 1)

    def test_values_are_escaped_in_the_regex(self):
        provider = FakeProvider([[], []])
        mp._fetch_jvm_gc(provider, LABELS, T0, T0, project(['led"ger'], ['a.b']))
        self.assertIn('namespace=~"led\\"ger"', provider.exprs[1])
        self.assertIn('service_name=~"a\\\\.b"', provider.exprs[1])

    def test_failures_never_raise(self):
        provider = FakeProvider([RuntimeError('boom'), RuntimeError('boom')])
        self.assertEqual(mp._fetch_jvm_gc(provider, LABELS, T0, T0, project(['ledger'])), {})
        broken = SimpleNamespace(log_rules_clean=lambda: 1 / 0, deployments=None, services=None)
        self.assertEqual(mp._fetch_jvm_gc(FakeProvider([[]]), LABELS, T0, T0, broken), {})

    def test_a_store_without_promql_is_skipped(self):
        self.assertEqual(mp._fetch_jvm_gc(object(), LABELS, T0, T0, project(['ledger'])), {})

    def test_no_labels_and_no_namespace_never_queries_unscoped(self):
        provider = FakeProvider([])
        self.assertEqual(mp._fetch_jvm_gc(provider, {}, T0, T0, project([])), {})
        self.assertEqual(provider.exprs, [])


def raw(share, counts=()):
    return {'memory_total': [], 'memory_free': [], 'memory_available': [], 'cpu': [],
            'jvm_gc_time_percent': [{'time': T0, 'value': v, 'series_key': k} for k, v in share],
            'jvm_gc_collections_per_minute': [{'time': T0, 'value': v, 'series_key': k} for k, v in counts],
            'jvm_gc_matched_by': 'project labels'}


class SummaryTest(SimpleTestCase):

    def test_the_threshold_flags_only_the_service_over_it(self):
        summary = mp.preprocess_metrics_for_ai(raw([('ad', 3.0), ('ad', 34.5), ('cart', 1.2)], [('ad', 41.0)]))
        jvm = summary['jvm_gc']
        self.assertEqual(jvm['threshold_percent'], 10.0)
        ad, cart = jvm['services']
        self.assertEqual((ad['service'], ad['peak_percent'], ad['avg_percent']), ('ad', 34.5, 18.8))
        self.assertTrue(ad['over_threshold'])
        self.assertEqual(ad['peak_collections_per_minute'], 41.0)
        self.assertFalse(cart['over_threshold'])
        self.assertIsNone(cart['peak_collections_per_minute'])

    def test_no_jvm_data_gives_an_empty_block(self):
        self.assertEqual(mp.preprocess_metrics_for_ai(raw([]))['jvm_gc'], {})


def prompt(summary):
    return _build_user_content(DataSourceContext(batch_data={}, logs=[], metrics_summary=summary))


class PromptTest(SimpleTestCase):

    def test_a_jvm_over_the_threshold_is_named_with_what_the_figure_measures(self):
        text = prompt(mp.preprocess_metrics_for_ai(raw([('ad', 34.5)], [('ad', 41.0)])))
        self.assertIn('JVM garbage collection above 10% of time', text)
        self.assertIn('share of wall time each JVM spent in garbage collection (pauses, plus concurrent '
                      'phases where the agent does not separate them)', text)
        self.assertIn('ad peak 34.5%', text)
        self.assertIn('41 collections/min at peak', text)

    def test_healthy_jvms_get_one_short_line(self):
        text = prompt(mp.preprocess_metrics_for_ai(raw([('ad', 0.8), ('cart', 2.0)])))
        self.assertIn('JVM garbage collection: all 2 JVMs under 10% of time in GC.', text)
        self.assertNotIn('above 10%', text)

    def test_no_jvm_data_no_line(self):
        self.assertNotIn('garbage collection', prompt(mp.preprocess_metrics_for_ai(raw([]))).lower())


class BenchmarkInputsUnchangedTest(SimpleTestCase):
    """The JVM line appears only with JVM data. No benchmark scenario carries
    any, so every scored prompt is exactly what it was before this change."""

    def test_no_scenario_carries_jvm_gc_data(self):
        from rca_benchmark import runner

        def keys(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    yield k
                    yield from keys(v)
            elif isinstance(node, (list, tuple)):
                for v in node:
                    yield from keys(v)

        checked = 0
        for name, builds in runner.SETS.items():
            for build in builds:
                scenario = build()
                found = {k for k in keys(scenario) if str(k).startswith('jvm_gc')}
                self.assertEqual(found, set(), f'{name} {scenario.get("id")}')
                checked += 1
        self.assertEqual(checked, sum(len(b) for b in runner.SETS.values()))
        self.assertGreater(checked, 0)
