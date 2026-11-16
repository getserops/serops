"""A code-review note is not attributed to a commit by the correlation
heuristics (held-out v2 v29: a note on a healthy deploy was counted as
blaming the deployed commit because its component matched the changed
file's path). An incident issue still gets the link."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from ai_model.prompts import get_batch_analysis_system_prompt
from ai_model.tasks import _populate_issue_correlations

CORRS = {'correlations': {
    'file_to_error': [{'commit_sha': 'd2e3f4a5', 'matching_files': ['pricing/rules.py'],
                       'confidence': 'medium', 'time_since_commit_minutes': 30}],
    'deployment_to_metric_spike': [],
}}


def issue(scope, issue_type):
    return SimpleNamespace(scope=scope, issue_type=issue_type, component='pricing',
                           has_metric_correlation=False, metric_correlation_type='', metric_anomaly_type='',
                           has_commit_correlation=False, linked_commits=[], correlation_confidence='',
                           correlation_details={}, has_cicd_correlation=False)


class ReviewNotesNotLinkedTest(SimpleTestCase):
    def test_review_note_gets_no_commit_link(self):
        i = issue('CODE', 'POTENTIAL_BUG')
        _populate_issue_correlations(i, CORRS, {})
        self.assertFalse(i.has_commit_correlation)
        self.assertEqual(i.linked_commits, [])

    def test_incident_issue_still_linked(self):
        i = issue('SERVICE', 'APPLICATION_ERROR')
        _populate_issue_correlations(i, CORRS, {})
        self.assertTrue(i.has_commit_correlation)
        self.assertEqual(i.linked_commits[0]['sha'], 'd2e3f4a5')


class ReviewSeverityRuleTest(SimpleTestCase):
    def test_placeholder_code_is_info(self):
        text = get_batch_analysis_system_prompt()
        self.assertIn('placeholder code', text)
        self.assertIn('`caused_by_commits` stays [] for every review note', text)
