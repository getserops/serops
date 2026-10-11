"""Per-service metric identity.

Kubernetes metric templates aggregate ``by (service_name)``, so every service
in a project reports at the same instants. Everything downstream keyed on
timestamp alone, which silently collapsed those series into one — the reason
memory anomalies stayed at zero on the validation cluster while a container was
climbing towards an OOMKill.
"""

from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import SimpleTestCase

from integrations.metrics_processing import (
    calculate_memory_usage,
    preprocess_metrics_for_ai,
)

BASE = datetime(2026, 9, 28, 10, 0, tzinfo=dt_timezone.utc)

MIB = 1024 * 1024


def _prompt_for(metrics_summary):
    """Render the batch prompt for a metrics summary and nothing else."""
    from ai_model.prompt_context import DataSourceContext
    from ai_model.prompts import _build_user_content
    return _build_user_content(DataSourceContext(
        batch_data={}, logs=[], metrics_summary=metrics_summary))


def _points(series_key, values, source_table, start=BASE, step=30):
    return [
        {
            'time': start + timedelta(seconds=step * i),
            'value': float(v),
            'series_key': series_key,
            'series_id': 0,
            'source_table': source_table,
        }
        for i, v in enumerate(values)
    ]


def _four_services(hot='cache', hot_used_pct=95, quiet_used_pct=20, samples=12):
    """One service saturating its 96Mi limit, three comfortable."""
    limit = 96 * MIB
    total, available = [], []
    for svc in ('api', 'cache', 'checkout', 'loadgen'):
        used_pct = hot_used_pct if svc == hot else quiet_used_pct
        total += _points(svc, [limit] * samples, 'node_memory_MemTotal_bytes')
        available += _points(
            svc, [limit * (100 - used_pct) / 100] * samples,
            'node_memory_MemAvailable_bytes')
    return {'memory_total': total, 'memory_available': available}


class MemoryUsageIsPerSeriesTest(SimpleTestCase):
    def test_every_service_survives_the_join(self):
        """The old dict keyed on time alone kept only the last service."""
        usage = calculate_memory_usage(_four_services())
        self.assertEqual({p['series_key'] for p in usage},
                         {'api', 'cache', 'checkout', 'loadgen'})
        self.assertEqual(len(usage), 48, '12 samples x 4 services')

    def test_the_saturating_service_keeps_its_own_percentage(self):
        usage = calculate_memory_usage(_four_services())
        cache = [p['value'] for p in usage if p['series_key'] == 'cache']
        api = [p['value'] for p in usage if p['series_key'] == 'api']
        self.assertTrue(all(v == 95.0 for v in cache), cache)
        self.assertTrue(all(v == 20.0 for v in api), api)

    def test_total_and_available_are_never_crossed_between_services(self):
        """A 96Mi container's total must not be divided by a 512Mi sibling's
        available — that produced percentages with no physical meaning."""
        metrics = {
            'memory_total': (_points('small', [96 * MIB] * 3, 't')
                             + _points('large', [512 * MIB] * 3, 't')),
            'memory_available': (_points('small', [10 * MIB] * 3, 'a')
                                 + _points('large', [500 * MIB] * 3, 'a')),
        }
        usage = calculate_memory_usage(metrics)
        small = {p['value'] for p in usage if p['series_key'] == 'small'}
        large = {p['value'] for p in usage if p['series_key'] == 'large'}
        self.assertEqual(small, {89.58})
        self.assertEqual(large, {2.34})

    def test_unlimited_containers_are_skipped_not_divided_by_zero(self):
        metrics = {
            'memory_total': _points('unlimited', [0, 0], 't'),
            'memory_available': _points('unlimited', [0, 0], 'a'),
        }
        self.assertEqual(calculate_memory_usage(metrics), [])

    def test_vm_mode_single_series_unchanged(self):
        """Points with no series_key group under one default series."""
        metrics = {
            'memory_total': [{'time': BASE, 'value': 100.0}],
            'memory_available': [{'time': BASE, 'value': 25.0}],
        }
        usage = calculate_memory_usage(metrics)
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0]['value'], 75.0)


class AnomalyDetectionIsPerSeriesTest(SimpleTestCase):
    """Run over a mixed list, the detector sees one service's high samples
    separated by its neighbours' low ones and finds nothing sustained.
    """

    def _summary(self, **kwargs):
        raw = _four_services(**kwargs)
        raw['memory_usage_percent'] = calculate_memory_usage(raw)
        raw['cpu_usage_percent'] = []
        return preprocess_metrics_for_ai(raw)

    def test_one_saturating_service_is_detected(self):
        anomalies = self._summary()['memory']['anomalies']
        self.assertTrue(anomalies, 'cache at 95% must produce an anomaly')

    def test_the_anomaly_names_the_service(self):
        anomalies = self._summary()['memory']['anomalies']
        self.assertEqual({a['service'] for a in anomalies}, {'cache'},
                         'only cache is above the 75% threshold')

    def test_quiet_project_produces_no_anomalies(self):
        summary = self._summary(hot_used_pct=30)
        self.assertEqual(summary['memory']['anomalies'], [])

    def test_all_services_hot_are_all_reported(self):
        summary = self._summary(hot_used_pct=90, quiet_used_pct=88)
        self.assertEqual(
            {a['service'] for a in summary['memory']['anomalies']},
            {'api', 'cache', 'checkout', 'loadgen'})

    def test_anomalies_are_ordered_worst_first(self):
        raw = _four_services()
        # Give each service a distinct peak above the threshold.
        limit = 96 * MIB
        total, available = [], []
        for svc, pct in (('api', 80), ('cache', 97), ('checkout', 88)):
            total += _points(svc, [limit] * 12, 't')
            available += _points(svc, [limit * (100 - pct) / 100] * 12, 'a')
        raw = {'memory_total': total, 'memory_available': available}
        raw['memory_usage_percent'] = calculate_memory_usage(raw)
        raw['cpu_usage_percent'] = []
        anomalies = preprocess_metrics_for_ai(raw)['memory']['anomalies']
        self.assertEqual([a['service'] for a in anomalies],
                         ['cache', 'checkout', 'api'])


class UnlabelledSeriesTest(SimpleTestCase):
    """``sum by (service_name)`` also returns a bucket for the containers that
    carry no service label — on the validation cluster that was a fifth series
    alongside the four real ones. It is real data and must be kept, but naming
    it invents a service that does not exist.
    """

    def _summary_with_unlabelled(self):
        limit = 96 * MIB
        total = _points('cache', [limit] * 12, 't') + _points('default', [limit] * 12, 't')
        available = (_points('cache', [limit * 0.03] * 12, 'a')
                     + _points('default', [limit * 0.05] * 12, 'a'))
        raw = {'memory_total': total, 'memory_available': available}
        raw['memory_usage_percent'] = calculate_memory_usage(raw)
        raw['cpu_usage_percent'] = []
        return preprocess_metrics_for_ai(raw)

    def test_unlabelled_anomaly_carries_no_service_name(self):
        anomalies = self._summary_with_unlabelled()['memory']['anomalies']
        unlabelled = [a for a in anomalies if 'service' not in a]
        named = [a for a in anomalies if a.get('service')]
        self.assertTrue(unlabelled, 'the default bucket must not be given a name')
        self.assertEqual({a['service'] for a in named}, {'cache'})

    def test_prompt_calls_it_unlabelled_not_default(self):
        prompt = _prompt_for(self._summary_with_unlabelled())
        self.assertIn('unlabelled containers', prompt)
        self.assertNotIn('  default:', prompt)

    def test_its_capacity_still_counts_towards_the_total(self):
        summary = self._summary_with_unlabelled()
        self.assertAlmostEqual(summary['memory']['total_gb'],
                               round(2 * 96 * MIB / 1_073_741_824, 2), places=2)


class ProjectTotalMemoryTest(SimpleTestCase):
    def test_total_sums_the_services_rather_than_reading_the_first(self):
        """``memory_total[0]`` was whichever service the provider listed first,
        reported as the project's whole capacity."""
        raw = _four_services()
        raw['memory_usage_percent'] = calculate_memory_usage(raw)
        raw['cpu_usage_percent'] = []
        summary = preprocess_metrics_for_ai(raw)
        self.assertAlmostEqual(summary['memory']['total_gb'],
                               round(4 * 96 * MIB / 1_073_741_824, 2), places=2)


class PerServiceSummaryBlockTest(SimpleTestCase):
    def _summary(self):
        raw = _four_services()
        raw['memory_usage_percent'] = calculate_memory_usage(raw)
        raw['cpu_usage_percent'] = []
        return preprocess_metrics_for_ai(raw)

    def test_each_service_gets_its_own_stats(self):
        block = self._summary()['per_service']['memory_usage_percent']
        self.assertEqual(set(block), {'api', 'cache', 'checkout', 'loadgen'})
        self.assertEqual(block['cache']['max'], 95.0)
        self.assertEqual(block['api']['max'], 20.0)

    def test_prompt_names_the_saturating_service(self):
        """Aggregates read as "48% avg, peak 95%" with no service attached;
        the prompt has to say which one."""
        prompt = _prompt_for(self._summary())
        self.assertIn('Memory by service:', prompt)
        self.assertIn('cache', prompt)

    def test_single_service_project_skips_the_breakdown(self):
        """With one series the breakdown just repeats the aggregate."""
        limit = 96 * MIB
        raw = {
            'memory_total': _points('only', [limit] * 6, 't'),
            'memory_available': _points('only', [limit * 0.1] * 6, 'a'),
        }
        raw['memory_usage_percent'] = calculate_memory_usage(raw)
        raw['cpu_usage_percent'] = []
        prompt = _prompt_for(preprocess_metrics_for_ai(raw))
        self.assertNotIn('Memory by service:', prompt)


class PeakPodHidesNoHotReplicaTest(SimpleTestCase):
    """A saturating replica must be visible even when its siblings are idle.

    Every K8s metric template aggregates `sum by (service_name)`, which is the
    right view of capacity and the wrong view of risk. Three replicas at 95%,
    20% and 20% sum to about 45% — under the 75% threshold, so no anomaly fires
    and the prompt reports a healthy service until the kubelet OOMKills the hot
    one.

    Same fault as project-wide aggregation hiding a saturating service, one
    level further down. Measured on the validation cluster: the unlabelled
    container bucket read 40.2% aggregate against 52.8% for its worst member.
    """

    @staticmethod
    def _summary(peak_values, agg_values, samples=12):
        """Build a summary where `cache` aggregates low but peaks high."""
        raw = {
            'peak_pod_memory_percent': _points('cache', peak_values * samples, 'p'),
            'peak_pod_cpu_cores': [],
            'memory_usage_percent': _points('cache', agg_values * samples, 'a'),
            'cpu_usage_percent': [],
        }
        return preprocess_metrics_for_ai(raw)

    def test_the_aggregate_alone_would_miss_it(self):
        """Establishes the premise: 45% raises nothing."""
        summary = self._summary(peak_values=[95.0], agg_values=[45.0])
        self.assertEqual(summary['memory']['anomalies'], [],
                         'the aggregate is genuinely below threshold')

    def test_the_peak_view_catches_it(self):
        summary = self._summary(peak_values=[95.0], agg_values=[45.0])
        anomalies = summary['peak_pod']['memory_anomalies']
        self.assertTrue(anomalies, 'a pod at 95% of its limit must be reported')
        self.assertEqual(anomalies[0]['service'], 'cache')

    def test_peak_stats_are_per_service(self):
        summary = self._summary(peak_values=[95.0], agg_values=[45.0])
        self.assertEqual(summary['peak_pod']['memory_percent']['cache']['max'], 95.0)

    def test_a_healthy_service_raises_nothing(self):
        summary = self._summary(peak_values=[30.0], agg_values=[28.0])
        self.assertEqual(summary['peak_pod']['memory_anomalies'], [])

    def test_prompt_names_the_divergence(self):
        prompt = _prompt_for(self._summary(peak_values=[95.0], agg_values=[45.0]))
        self.assertIn('Peak single-pod memory', prompt)
        self.assertIn('cache', prompt)
        self.assertIn('OOMKill candidate', prompt)

    def test_prompt_stays_quiet_when_peak_matches_aggregate(self):
        """On a single-replica service the two are identical, and repeating the
        number teaches the model nothing."""
        prompt = _prompt_for(self._summary(peak_values=[36.0], agg_values=[36.0]))
        self.assertNotIn('Peak single-pod memory', prompt)

    def test_missing_peak_data_is_not_an_error(self):
        """VM-mode providers never produce it."""
        raw = {'memory_usage_percent': _points('only', [40.0] * 6, 'a'),
               'cpu_usage_percent': []}
        summary = preprocess_metrics_for_ai(raw)
        self.assertEqual(summary['peak_pod']['memory_anomalies'], [])
        self.assertEqual(summary['peak_pod']['memory_percent'], {})
