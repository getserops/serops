"""Memory that sits still near its limit is context, not an anomaly.

Client C2 (phase 3, 2026-11-16): pods held 80-90 % of their limits all day;
every batch flagged them as sustained high memory and the noise outranked the
real fault. Growth, a level close to the limit, and restarts stay anomalies.
"""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import SimpleTestCase

from integrations.metrics_processing import preprocess_metrics_for_ai

BASE = datetime(2026, 11, 16, 10, 0, tzinfo=dt_timezone.utc)


def _series(service, values, table='memory_usage_percent'):
    return [{'time': BASE + timedelta(seconds=30 * i), 'value': float(v), 'series_key': service,
             'series_id': 0, 'source_table': table} for i, v in enumerate(values)]


K8S_QUIET = {'restarts': {}, 'terminated': [], 'waiting': [], 'changes': [], 'unavailable': [],
             'stuck': [], 'throttled': []}


def _summary(memory, lifecycle=K8S_QUIET, peak=None):
    raw = {'memory_usage_percent': memory, 'container_lifecycle': lifecycle}
    if peak is not None:
        raw['peak_pod_memory_percent'] = peak
    return preprocess_metrics_for_ai(raw)


def _prompt(summary):
    from ai_model.prompt_context import DataSourceContext
    from ai_model.prompts import _build_user_content
    return _build_user_content(DataSourceContext(batch_data={}, logs=[], metrics_summary=summary))


class SteadyMemoryTest(SimpleTestCase):
    def test_flat_near_limit_is_context_not_anomaly(self):
        s = _summary(_series('kafka', [86, 87, 86, 88, 87, 86, 87, 88, 87, 86]))
        self.assertEqual(s['memory']['anomalies'], [])
        self.assertEqual(s['memory']['steady_near_limit'][0]['service'], 'kafka')
        prompt = _prompt(s)
        self.assertIn('Memory steady near the limit', prompt)
        self.assertIn('kafka 86.8%', prompt)
        self.assertNotIn('Memory Anomalies', prompt)

    def test_growth_stays_an_anomaly(self):
        s = _summary(_series('cart', [76, 78, 80, 82, 84, 86, 88, 90, 92, 94]))
        self.assertEqual([a.get('service') for a in s['memory']['anomalies']], ['cart'])
        self.assertEqual(s['memory']['steady_near_limit'], [])

    def test_flat_but_at_the_limit_stays_an_anomaly(self):
        s = _summary(_series('cart', [96, 97, 96, 97, 96, 97, 96, 97, 96, 97]))
        self.assertEqual(len(s['memory']['anomalies']), 1)

    def test_restarted_service_stays_an_anomaly(self):
        lifecycle = dict(K8S_QUIET, restarts={'kafka': 2},
                         terminated=[{'container': 'kafka', 'reason': 'OOMKilled'}])
        s = _summary(_series('kafka', [86, 87, 86, 88, 87, 86, 87, 88, 87, 86]), lifecycle)
        self.assertEqual(len(s['memory']['anomalies']), 1)
        self.assertEqual(s['memory']['steady_near_limit'], [])

    def test_without_kubernetes_lifecycle_nothing_changes(self):
        """No lifecycle data means "no restart" is not known."""
        s = _summary(_series('db', [86, 87, 86, 88, 87, 86, 87, 88, 87, 86]), lifecycle={})
        self.assertEqual(len(s['memory']['anomalies']), 1)

    def test_steady_peak_pod_is_context_too(self):
        flat = _series('kafka', [85, 86, 85, 86, 85, 86, 85, 86, 85, 86], 'peak_pod_memory_percent')
        s = _summary(_series('kafka', [40] * 10), peak=flat)
        self.assertEqual(s['peak_pod']['memory_anomalies'], [])
        self.assertEqual(s['memory']['steady_near_limit'][0]['service'], 'kafka')
        self.assertNotIn('OOMKill candidate', _prompt(s))

    def test_other_services_anomaly_unaffected(self):
        mem = (_series('kafka', [86, 87, 86, 88, 87, 86, 87, 88, 87, 86])
               + _series('cart', [76, 78, 80, 82, 84, 86, 88, 90, 92, 94]))
        s = _summary(mem)
        self.assertEqual([a.get('service') for a in s['memory']['anomalies']], ['cart'])
        self.assertEqual([e['service'] for e in s['memory']['steady_near_limit']], ['kafka'])
