"""Raw metrics must survive the trip to storage.

`serialize_metrics` assumed every value in the payload was a list of point
dicts and did `{**item}` over it. `fetch_metrics_with_provider` also returns
`container_lifecycle`, which is a dict — so iterating it yielded its KEYS and
unpacking a string raised `TypeError: 'str' object is not a mapping`.

The caller's broad except turned that into `serialized_metrics = {}` under a log
line reading "Error fetching metrics", blaming a fetch that had worked. Measured
before the fix: 20 of the last 20 batches had `data['metrics'] == {}` while
`metrics_summary` held 45 CPU and 45 memory points.

Two things broke downstream, which is why this matters more than a lost chart:
the batch metrics endpoint reads `data['metrics']['memory_usage_percent']` and
got nothing, and `metrics_count` — computed from the serialized payload — was
permanently 0, feeding the batch-creation gates. A metrics-only incident (CPU
spike, no error logs, no traces) produced no batch at all.
"""
from datetime import datetime, timezone as dt_timezone

from django.test import SimpleTestCase

from Data.serializers import serialize_metrics

T = datetime(2026, 10, 4, 12, 0, tzinfo=dt_timezone.utc)


def _k8s_payload():
    """The exact shape fetch_metrics_with_provider returns on Kubernetes."""
    point = {'time': T, 'value': 42.0, 'series_key': 'cache',
             'series_id': 0, 'source_table': 'memory_usage_percent'}
    return {
        'memory_total': [point],
        'memory_free': [point],
        'memory_available': [point],
        'cpu': [point],
        'memory_usage_percent': [point],
        'cpu_usage_percent': [point],
        # The key that broke it: a dict, not a list of points.
        'container_lifecycle': {
            'terminated': [{'container': 'cache', 'reason': 'OOMKilled'}],
            'restarts': {'cache': 2, 'api': 1},
        },
    }


class KubernetesPayloadSurvivesTest(SimpleTestCase):
    def test_it_does_not_raise(self):
        serialize_metrics(_k8s_payload())  # used to TypeError

    def test_the_time_series_are_kept(self):
        out = serialize_metrics(_k8s_payload())
        for key in ('memory_total', 'cpu', 'memory_usage_percent'):
            with self.subTest(key=key):
                self.assertEqual(len(out[key]), 1)

    def test_metrics_count_is_not_zero(self):
        """This is the number the batch-creation gates read. Zero here meant a
        metrics-only incident could not produce a batch."""
        out = serialize_metrics(_k8s_payload())
        count = sum(len(v) for v in out.values() if isinstance(v, list))
        self.assertEqual(count, 6)

    def test_container_lifecycle_passes_through_intact(self):
        out = serialize_metrics(_k8s_payload())
        self.assertEqual(out['container_lifecycle']['restarts'], {'cache': 2, 'api': 1})
        self.assertEqual(
            out['container_lifecycle']['terminated'][0]['reason'], 'OOMKilled')

    def test_datetime_becomes_an_iso_string(self):
        """It has to be JSON-serialisable to reach a JSONField."""
        out = serialize_metrics(_k8s_payload())
        self.assertEqual(out['memory_total'][0]['time'], T.isoformat())

    def test_series_key_survives(self):
        """Per-series identity is what makes the chart and the anomaly
        detection per-service rather than project-wide."""
        out = serialize_metrics(_k8s_payload())
        self.assertEqual(out['memory_usage_percent'][0]['series_key'], 'cache')

    def test_result_is_json_serialisable(self):
        import json
        json.dumps(serialize_metrics(_k8s_payload()))


class ToleratesOddInputTest(SimpleTestCase):
    """Losing the entire payload because one entry was unexpected is the exact
    failure mode this function already caused once."""

    def test_none_time_is_preserved(self):
        out = serialize_metrics({'cpu': [{'time': None, 'value': 1.0}]})
        self.assertIsNone(out['cpu'][0]['time'])

    def test_iso_string_time_passes_through(self):
        out = serialize_metrics({'cpu': [{'time': T.isoformat(), 'value': 1.0}]})
        self.assertEqual(out['cpu'][0]['time'], T.isoformat())

    def test_non_dict_entry_does_not_lose_the_payload(self):
        out = serialize_metrics({'cpu': ['unexpected', {'time': T, 'value': 1.0}]})
        self.assertEqual(len(out['cpu']), 2)

    def test_scalar_value_passes_through(self):
        out = serialize_metrics({'cpu': [], 'some_scalar': 3.5})
        self.assertEqual(out['some_scalar'], 3.5)

    def test_empty_and_none_payloads(self):
        self.assertEqual(serialize_metrics({}), {})
        self.assertEqual(serialize_metrics(None), {})
