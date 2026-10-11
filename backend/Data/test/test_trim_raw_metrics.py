"""Raw metric points must not accumulate forever.

They are 93% of a batch's stored payload (measured: 69 KB of 74 KB) and serve
one purpose — the batch metrics chart. The analysis, the issues and
`metrics_summary` are the other 7%.

Before this task there was no way to shed them: `run_auto_retention_cleanup`
deletes whole batches, which takes the analysis too, and it only runs for
organisations that opted into `auto_cleanup_enabled` — default False. So the
heaviest part of the payload grew without bound, roughly 10 MB per day per
project at a ten-minute batch interval.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from Data.models import AIAnalyzedBatch, RetentionPolicy
from Data.tasks import trim_raw_metric_payloads
from Organisations.models import Organisations
from Projects.models import Project


def _raw_metrics():
    pt = {'time': '2026-10-04T12:00:00+00:00', 'value': 42.0, 'series_key': 'cache'}
    return {'memory_usage_percent': [pt] * 40, 'cpu_usage_percent': [pt] * 40}


class TrimRawMetricsTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Trim Org')
        self.project = Project.objects.create(name='trim-project', organisation=self.org)
        self.policy = RetentionPolicy.objects.create(
            organisation=self.org, raw_metrics_retention_days=30,
        )

    def _batch(self, age_days, with_metrics=True):
        data = {
            'logs': [{'message': 'something'}],
            'metrics_summary': {'memory': {'anomalies': []}, 'data_points': {'memory': 40}},
            'analysis_result': {'correlated_issues': [{'component': 'cache'}]},
        }
        data['metrics'] = _raw_metrics() if with_metrics else {}
        b = AIAnalyzedBatch.objects.create(
            batch_id=f'trim-{age_days}-{with_metrics}', project=self.project,
            organisation=self.org, timestamp=timezone.now() - timedelta(days=age_days),
            data=data, analysis_text='a narrative worth keeping',
        )
        return b

    def test_old_batch_loses_its_raw_points(self):
        b = self._batch(age_days=60)
        trim_raw_metric_payloads()
        b.refresh_from_db()
        self.assertEqual(b.data['metrics'], {})

    def test_recent_batch_is_untouched(self):
        b = self._batch(age_days=2)
        trim_raw_metric_payloads()
        b.refresh_from_db()
        self.assertEqual(len(b.data['metrics']['memory_usage_percent']), 40)

    def test_everything_worth_keeping_survives(self):
        """The point of trimming rather than deleting the batch."""
        b = self._batch(age_days=60)
        trim_raw_metric_payloads()
        b.refresh_from_db()
        self.assertEqual(b.analysis_text, 'a narrative worth keeping')
        self.assertEqual(b.data['metrics_summary']['data_points']['memory'], 40)
        self.assertEqual(
            b.data['analysis_result']['correlated_issues'][0]['component'], 'cache')
        self.assertEqual(len(b.data['logs']), 1)

    def test_it_records_when_it_trimmed(self):
        b = self._batch(age_days=60)
        trim_raw_metric_payloads()
        b.refresh_from_db()
        self.assertIn('metrics_trimmed_at', b.data)

    def test_zero_means_keep_forever(self):
        self.policy.raw_metrics_retention_days = 0
        self.policy.save()
        b = self._batch(age_days=900)
        trim_raw_metric_payloads()
        b.refresh_from_db()
        self.assertEqual(len(b.data['metrics']['memory_usage_percent']), 40)

    def test_it_runs_without_auto_cleanup_enabled(self):
        """Unlike whole-batch deletion. auto_cleanup_enabled defaults to False,
        which is why the payload grew unbounded on a default install."""
        self.assertFalse(self.policy.auto_cleanup_enabled)
        b = self._batch(age_days=60)
        result = trim_raw_metric_payloads()
        b.refresh_from_db()
        self.assertEqual(b.data['metrics'], {})
        self.assertEqual(result['batches_trimmed'], 1)

    def test_it_is_idempotent(self):
        self._batch(age_days=60)
        first = trim_raw_metric_payloads()
        second = trim_raw_metric_payloads()
        self.assertEqual(first['batches_trimmed'], 1)
        self.assertEqual(second['batches_trimmed'], 0,
                         'an already-trimmed batch must not be rewritten')

    def test_it_reports_what_it_freed(self):
        self._batch(age_days=60)
        result = trim_raw_metric_payloads()
        self.assertGreater(result['approx_bytes_freed'], 1000)

    def test_an_org_with_no_policy_is_left_alone(self):
        other_org = Organisations.objects.create(name='No Policy Org')
        other_project = Project.objects.create(name='np', organisation=other_org)
        b = AIAnalyzedBatch.objects.create(
            batch_id='np-1', project=other_project, organisation=other_org,
            timestamp=timezone.now() - timedelta(days=900),
            data={'metrics': _raw_metrics()},
        )
        trim_raw_metric_payloads()
        b.refresh_from_db()
        self.assertEqual(len(b.data['metrics']['memory_usage_percent']), 40)
