"""Anomaly detection in preprocess_metrics_for_ai.

Three interacting bugs meant `anomalies` was ALWAYS an empty list, so the AI
was never told about a sustained spike:

1. Timestamps were assumed to be ISO strings. In the pipeline they are real
   datetimes (fetch_metrics_with_provider copies TimeSeriesPoint.timestamp
   through, and calculate_cpu_usage subtracts them), so
   `value.replace('Z', '+00:00')` hit datetime.replace() -> TypeError,
   swallowed by a bare except. Observed live: "No valid timestamps found in 18
   metric values".

2. `timezone.utc` referred to django.utils.timezone, whose `utc` alias Django
   removed in 5.0. So even with parseable input the sustained branch raised
   AttributeError inside a broad except and produced nothing.

3. Emitted start_time/end_time were copied verbatim from the input. Had (1)
   ever been fixed alone, datetimes would have reached
   AIAnalyzedBatch.data — a JSONField — and failed to serialise on save. Bug
   (1) was masking a crash, which is why all three are fixed together.
"""
import json
from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from integrations.metrics_processing import (
    _coerce_datetime,
    _iso_timestamp,
    preprocess_metrics_for_ai,
)


class CoerceDatetimeTest(SimpleTestCase):

    def test_accepts_aware_datetime(self):
        dt = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(_coerce_datetime(dt), dt)

    def test_naive_datetime_assumed_utc(self):
        got = _coerce_datetime(datetime(2026, 9, 27, 12, 0))
        self.assertEqual(got.tzinfo, timezone.utc)

    def test_accepts_iso_string(self):
        got = _coerce_datetime('2026-09-27T12:00:00+00:00')
        self.assertEqual(got, datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc))

    def test_accepts_z_suffix(self):
        got = _coerce_datetime('2026-09-27T12:00:00Z')
        self.assertEqual(got, datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc))

    def test_naive_iso_string_assumed_utc(self):
        self.assertEqual(_coerce_datetime('2026-09-27T12:00:00').tzinfo, timezone.utc)

    def test_rejects_unusable(self):
        for bad in (None, '', 'not-a-date', 123, [], {}):
            with self.subTest(value=bad):
                self.assertIsNone(_coerce_datetime(bad))


class IsoTimestampTest(SimpleTestCase):

    def test_datetime_becomes_string(self):
        out = _iso_timestamp(datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc))
        self.assertIsInstance(out, str)
        self.assertTrue(out.startswith('2026-09-27T12:00:00'))

    def test_string_passes_through_normalised(self):
        self.assertTrue(_iso_timestamp('2026-09-27T12:00:00Z').startswith('2026-09-27'))

    def test_unusable_becomes_empty_string(self):
        self.assertEqual(_iso_timestamp(None), '')


def _series(start, count, value, step_seconds=30):
    """Metric points with REAL datetimes — what the pipeline actually passes."""
    return [
        {
            'time': start + timedelta(seconds=i * step_seconds),
            'value': value,
            'series_id': 0,
            'source_table': 'memory_usage_percent',
        }
        for i in range(count)
    ]


class AnomalyDetectionTest(SimpleTestCase):

    START = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)

    def _summary(self, mem_points):
        return preprocess_metrics_for_ai({
            'memory_usage_percent': mem_points,
            'memory_total': [],
            'memory_available': [],
            'cpu_usage_percent': [],
        })

    def test_sustained_high_memory_is_detected(self):
        """95% for ten straight samples is the case this function exists for.
        It previously returned []."""
        summary = self._summary(_series(self.START, 10, 95.0))
        self.assertTrue(
            summary['memory']['anomalies'],
            'sustained high memory produced no anomaly',
        )

    def test_sustained_anomaly_shape(self):
        anomaly = self._summary(_series(self.START, 10, 95.0))['memory']['anomalies'][0]
        self.assertTrue(anomaly['sustained'])
        self.assertEqual(anomaly['type'], 'memory_high_usage_sustained')
        self.assertEqual(anomaly['peak_value'], 95.0)
        self.assertEqual(anomaly['duration_seconds'], 270)  # 9 gaps x 30s
        self.assertEqual(anomaly['coverage_percent'], 100.0)

    def test_quiet_series_produces_no_anomaly(self):
        self.assertEqual(self._summary(_series(self.START, 10, 5.0))['memory']['anomalies'], [])

    def test_threshold_boundary_not_flagged(self):
        """75.0 is the memory threshold and the comparison is strictly >."""
        self.assertEqual(self._summary(_series(self.START, 10, 75.0))['memory']['anomalies'], [])

    def test_timestamps_are_strings_not_datetimes(self):
        """They land in AIAnalyzedBatch.data, a JSONField."""
        anomaly = self._summary(_series(self.START, 10, 95.0))['memory']['anomalies'][0]
        self.assertIsInstance(anomaly['start_time'], str)
        self.assertIsInstance(anomaly['end_time'], str)

    def test_summary_is_json_serialisable(self):
        """The regression that mattered: a datetime here fails on batch save."""
        summary = self._summary(_series(self.START, 10, 95.0))
        json.dumps(summary)  # would raise TypeError on a datetime

    def test_iso_string_input_also_works(self):
        """Reanalysis reads a serialised batch back, so the same code sees
        strings. Both shapes must behave identically."""
        as_strings = [
            {**p, 'time': p['time'].isoformat()}
            for p in _series(self.START, 10, 95.0)
        ]
        self.assertTrue(self._summary(as_strings)['memory']['anomalies'])

    def test_mixed_datetime_and_string_input(self):
        points = _series(self.START, 10, 95.0)
        for i in range(0, len(points), 2):
            points[i]['time'] = points[i]['time'].isoformat()
        self.assertTrue(self._summary(points)['memory']['anomalies'])

    def test_unparseable_points_are_skipped_not_fatal(self):
        points = _series(self.START, 10, 95.0)
        points.append({'time': 'garbage', 'value': 99.0, 'series_id': 0})
        points.append({'time': None, 'value': 99.0, 'series_id': 0})
        self.assertTrue(self._summary(points)['memory']['anomalies'])

    def test_all_unparseable_returns_empty_without_raising(self):
        points = [{'time': 'garbage', 'value': 99.0, 'series_id': 0}] * 3
        self.assertEqual(self._summary(points)['memory']['anomalies'], [])

    def test_stats_still_reported_alongside_anomalies(self):
        """Guard against a fix that breaks the averages that already worked."""
        summary = self._summary(_series(self.START, 10, 95.0))
        self.assertEqual(summary['memory']['usage_percent']['avg'], 95.0)
        self.assertEqual(summary['memory']['usage_percent']['max'], 95.0)

    def test_correlation_window_brackets_the_anomaly(self):
        anomaly = self._summary(_series(self.START, 10, 95.0))['memory']['anomalies'][0]
        window_start = datetime.fromisoformat(anomaly['correlation_window']['start'])
        window_end = datetime.fromisoformat(anomaly['correlation_window']['end'])
        self.assertLess(window_start, _coerce_datetime(anomaly['start_time']))
        self.assertGreater(window_end, _coerce_datetime(anomaly['end_time']))

    def test_cpu_threshold_is_independent(self):
        """CPU trips at 80, memory at 75 — 78% is a memory anomaly only."""
        summary = preprocess_metrics_for_ai({
            'memory_usage_percent': _series(self.START, 10, 78.0),
            'cpu_usage_percent': _series(self.START, 10, 78.0),
            'memory_total': [], 'memory_available': [],
        })
        self.assertTrue(summary['memory']['anomalies'])
        self.assertEqual(summary['cpu']['anomalies'], [])


class TimeRangeTest(SimpleTestCase):
    """`all_times.sort()` compared raw values, so a list holding both a
    datetime and a string raised TypeError and aborted the entire summary —
    not just the time range. The list is built from two independent metric
    sources, so mixed types are reachable.
    """

    START = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)

    def _summary(self, mem, cpu):
        return preprocess_metrics_for_ai({
            'memory_usage_percent': mem, 'cpu_usage_percent': cpu,
            'memory_total': [], 'memory_available': [],
        })

    def test_mixed_sources_do_not_raise(self):
        mem = _series(self.START, 3, 10.0)
        cpu = [{**p, 'time': p['time'].isoformat()}
               for p in _series(self.START, 3, 10.0)]
        tr = self._summary(mem, cpu)['time_range']
        self.assertIsNotNone(tr['start'])
        self.assertIsNotNone(tr['end'])

    def test_range_spans_both_sources(self):
        mem = _series(self.START, 2, 10.0)
        cpu = _series(self.START + timedelta(hours=1), 2, 10.0)
        tr = self._summary(mem, cpu)['time_range']
        self.assertTrue(tr['start'].startswith('2026-09-27T12:00:00'))
        self.assertTrue(tr['end'].startswith('2026-09-27T13:00:30'))

    def test_always_strings_for_json(self):
        tr = self._summary(_series(self.START, 2, 10.0), [])['time_range']
        self.assertIsInstance(tr['start'], str)
        json.dumps(tr)

    def test_unparseable_entries_dropped(self):
        mem = _series(self.START, 2, 10.0) + [{'time': 'garbage', 'value': 1.0}]
        tr = self._summary(mem, [])['time_range']
        self.assertTrue(tr['start'].startswith('2026-09-27T12:00:00'))

    def test_no_points_leaves_range_empty(self):
        tr = self._summary([], [])['time_range']
        self.assertEqual(tr, {'start': None, 'end': None})
