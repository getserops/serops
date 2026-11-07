"""
Commits are timed against when they reached the batch's environment.

Review v1.2.13: "'Matched to when code reached each environment' is only
half true." Deployments selected the commits, but the correlator and
prompt rule 14 still used the commit time, so a stack-trace match scored
HIGH 30 min after the commit and produced nothing at 5 h, even when the
5 h-old commit had been deployed 10 min before the error.
"""
from django.test import SimpleTestCase

from ai_model.diff_selection import build_code_changes_section
from ai_model.prompt_context import DataSourceContext
from ai_model.prompts import get_batch_analysis_prompt
from Data.correlation_confidence import HIGH
from Data.correlation_engine import (
    build_comprehensive_correlations,
    correlate_logs_with_code_changes,
    correlate_metrics_with_code_changes,
)

ERROR_AT = '2026-11-03T15:00:00+00:00'
LOGS = [{
    'message': 'Traceback: File "/app/checkout/payment.py", line 42, in charge',
    'timestamp': ERROR_AT,
}]


def _change(committed, deployed=None, env='production'):
    change = {
        'sha': 'abc12345ff', 'message': 'retry charges', 'author': 'dev',
        'timestamp': committed, 'branch': 'main',
        'files': [{'path': 'checkout/payment.py', 'diff': ''}],
    }
    if deployed:
        change['deployed_at'] = deployed
        change['deployed_to'] = env
    return change


class FileToErrorDeployTimeTests(SimpleTestCase):
    def test_a_five_hour_old_commit_deployed_ten_minutes_before_the_error_scores_like_a_fresh_one(self):
        out = correlate_logs_with_code_changes(
            LOGS, [_change('2026-11-03T10:00:00+00:00', deployed='2026-11-03T14:50:00+00:00')])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['confidence'], HIGH)
        self.assertEqual(out[0]['time_basis'], 'deploy')
        self.assertEqual(out[0]['time_since_deploy_minutes'], 10.0)
        self.assertEqual(out[0]['time_since_commit_minutes'], 300.0)
        self.assertEqual(out[0]['deployed_to'], 'production')

    def test_the_same_commit_without_deployment_info_still_falls_back_to_commit_time(self):
        # Fallback unchanged: 5 h after the commit is outside the 4 h window.
        self.assertEqual(correlate_logs_with_code_changes(LOGS, [_change('2026-11-03T10:00:00+00:00')]), [])
        out = correlate_logs_with_code_changes(LOGS, [_change('2026-11-03T14:30:00+00:00')])
        self.assertEqual(out[0]['confidence'], HIGH)
        self.assertEqual(out[0]['time_basis'], 'commit')
        self.assertEqual(out[0]['time_since_commit_minutes'], 30.0)
        self.assertNotIn('time_since_deploy_minutes', out[0])

    def test_a_commit_deployed_to_this_environment_after_the_error_is_not_blamed(self):
        # Committed 30 min before the error (HIGH on commit time) but only
        # live here 10 min after it: the running code did not contain it.
        # Same rule as a commit made after the error: negative lag, dropped.
        out = correlate_logs_with_code_changes(
            LOGS, [_change('2026-11-03T14:30:00+00:00', deployed='2026-11-03T15:10:00+00:00')])
        self.assertEqual(out, [])

    def test_the_primary_correlation_is_the_deployed_commit(self):
        result = build_comprehensive_correlations(
            logs=LOGS, metrics_summary={},
            code_changes=[_change('2026-11-03T10:00:00+00:00', deployed='2026-11-03T14:50:00+00:00')],
        )
        primary = result['summary']['primary_correlation']
        self.assertEqual(primary['type'], 'file_to_error')
        self.assertEqual(primary['details']['confidence'], HIGH)


class DeployToMetricDeployTimeTests(SimpleTestCase):
    METRICS = {'memory': {'anomalies': [{'start_time': ERROR_AT, 'peak_value': 95}]}}

    def test_a_metric_spike_is_timed_from_the_deploy_not_the_commit(self):
        out = correlate_metrics_with_code_changes(
            self.METRICS, [_change('2026-11-03T10:00:00+00:00', deployed='2026-11-03T14:30:00+00:00')])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['confidence'], HIGH)
        self.assertEqual(out[0]['time_after_deploy_minutes'], 30.0)
        self.assertEqual(out[0]['time_basis'], 'deploy')

    def test_without_deployment_info_the_metric_lag_still_uses_commit_time(self):
        self.assertEqual(
            correlate_metrics_with_code_changes(self.METRICS, [_change('2026-11-03T10:00:00+00:00')]), [])


class PromptShowsDeployTimeTests(SimpleTestCase):
    def test_commit_lines_show_the_deploy_first_and_keep_the_commit_time(self):
        section = build_code_changes_section(
            [_change('2026-11-03T10:00:00+00:00', deployed='2026-11-03T14:50:00+00:00')], [],
            redact=lambda t: t)
        self.assertIn(
            '(deployed to production at 2026-11-03T14:50:00+00:00; committed 2026-11-03T10:00:00+00:00)',
            section)

    def test_commit_lines_without_a_deploy_keep_the_commit_time_alone(self):
        section = build_code_changes_section([_change('2026-11-03T10:00:00+00:00')], [], redact=lambda t: t)
        self.assertIn('[abc12345] dev (2026-11-03T10:00:00+00:00)', section)

    def test_correlation_lines_and_rule_14_time_errors_against_the_deploy(self):
        correlations = build_comprehensive_correlations(
            logs=LOGS, metrics_summary={},
            code_changes=[_change('2026-11-03T10:00:00+00:00', deployed='2026-11-03T14:50:00+00:00')],
        )
        prompt = get_batch_analysis_prompt(DataSourceContext(
            batch_data={'batch_id': 'b1', 'timestamp': ERROR_AT, 'environment': 'production'},
            correlations=correlations,
        ))
        self.assertIn(
            'error appeared 10.0 min after deploy to production at 2026-11-03T14:50:00+00:00 '
            '(300.0 min after commit)', prompt)
        self.assertIn('the time each commit reached this environment', prompt)
        self.assertNotIn('match error timestamps with commit timestamps', prompt)
