"""A window in which data stopped is reported, never called healthy
(phase 3 client C4, L3 and L5)."""
from django.test import SimpleTestCase

from ai_model.prompt_context import DataSourceContext
from ai_model.prompts import get_batch_analysis_prompt_parts
from ai_model.tasks import _ensure_data_gap_issue
from ai_model.trace_context import _traffic_drops, format_trace_context_for_prompt

GAP = {'window_logs': 0, 'previous_logs': 300, 'previous_capped': True, 'collapsed': True,
       'silent_services': []}


class EnsureDataGapIssueTest(SimpleTestCase):
    def test_empty_analysis_gets_a_warning(self):
        parsed = {'summary': {'overall_health': 'HEALTHY'}, 'correlated_issues': []}
        self.assertTrue(_ensure_data_gap_issue(parsed, {'data_gap': GAP}))
        issue = parsed['correlated_issues'][0]
        self.assertEqual(issue['severity'], 'WARNING')
        self.assertEqual(issue['scope'], 'INFRASTRUCTURE')
        self.assertIn('logs stopped', issue['description'])
        self.assertEqual(parsed['summary']['overall_health'], 'DEGRADED')

    def test_silent_service_names_it(self):
        parsed = {'correlated_issues': [{'severity': 'INFO', 'component': 'web'}]}
        gap = {**GAP, 'collapsed': False, 'silent_services': [{'service': 'payments', 'previous_logs': 40}]}
        self.assertTrue(_ensure_data_gap_issue(parsed, {'data_gap': gap}))
        self.assertEqual(parsed['correlated_issues'][-1]['component'], 'payments')

    def test_traffic_drop_alone(self):
        parsed = {'correlated_issues': []}
        traces = {'traffic_drops': [{'service': 'checkout', 'spans': 0, 'before': 400}]}
        self.assertTrue(_ensure_data_gap_issue(parsed, {'traces': traces}))
        self.assertEqual(parsed['correlated_issues'][0]['component'], 'checkout')

    def test_analysis_that_reported_it_is_left_alone(self):
        parsed = {'correlated_issues': [{'severity': 'WARNING', 'component': 'opensearch'}]}
        self.assertFalse(_ensure_data_gap_issue(parsed, {'data_gap': GAP}))
        self.assertEqual(len(parsed['correlated_issues']), 1)

    def test_no_gap_no_issue(self):
        parsed = {'correlated_issues': []}
        self.assertFalse(_ensure_data_gap_issue(parsed, {'logs': []}))
        self.assertEqual(parsed['correlated_issues'], [])


class TrafficDropTest(SimpleTestCase):
    def test_collapsed_service_is_listed(self):
        drops = _traffic_drops({'per_service': {'checkout': {'spans': 2, 'before': 400},
                                                'web': {'spans': 380, 'before': 400},
                                                'cron': {'spans': 0, 'before': 6}}})
        self.assertEqual([d['service'] for d in drops], ['checkout'])

    def test_prompt_shows_it_first_even_without_spans_now(self):
        text = format_trace_context_for_prompt({'span_count': 0, 'traffic_drops': [
            {'service': 'checkout', 'spans': 0, 'before': 400}]})
        self.assertIn('Traffic stopped or collapsed', text)
        self.assertIn('checkout: 0 spans now, 400', text)

    def test_nothing_without_spans_or_drops(self):
        self.assertEqual(format_trace_context_for_prompt({'span_count': 0}), '')


class PromptBlockTest(SimpleTestCase):
    def context(self, gap):
        return DataSourceContext(batch_data={'batch_id': 'b1'}, logs=[], data_gap=gap)

    def test_block_with_fenced_service_names(self):
        gap = {**GAP, 'silent_services': [{'service': 'payments', 'previous_logs': 40}]}
        _, user = get_batch_analysis_prompt_parts(self.context(gap))
        self.assertIn('Data that stopped (counted by SerOps)', user)
        self.assertIn('never a sign of health', user)
        block = user[user.index('Data that stopped'):]
        self.assertLess(block.index('never a sign of health'), block.index('<<<DATA'))
        self.assertIn('payments: 0 records now', block)

    def test_no_block_without_a_gap(self):
        _, user = get_batch_analysis_prompt_parts(self.context(None))
        self.assertNotIn('Data that stopped', user)
