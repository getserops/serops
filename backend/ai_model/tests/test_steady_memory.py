"""Client C2 rerun: memory flat near its limit, no restart, still came back as
a WARNING MEMORY_HIGH issue in every window, the healthy control included."""
from django.test import SimpleTestCase

from ai_model.tasks import _demote_steady_memory


def batch(steady=('accounting',), anomalies=(), peak=(), restarts=None):
    return {'metrics_summary': {
        'memory': {'steady_near_limit': [{'service': s, 'level_percent': 84.1} for s in steady],
                   'anomalies': [{'service': s, 'peak_value': 91} for s in anomalies]},
        'peak_pod': {'memory_anomalies': [{'service': s, 'peak_value': 93} for s in peak]},
        'container_lifecycle': {'restarts': restarts or {}}}}


def issue(component='accounting', issue_type='MEMORY_HIGH', severity='WARNING'):
    return {'component': component, 'issue_type': issue_type, 'severity': severity, 'scope': 'INFRASTRUCTURE'}


class SteadyMemoryTest(SimpleTestCase):
    def test_flat_memory_issue_becomes_info(self):
        result = {'correlated_issues': [issue()]}
        self.assertEqual(_demote_steady_memory(result, batch()), 1)
        self.assertEqual(result['correlated_issues'][0]['severity'], 'INFO')

    def test_other_services_and_types_are_untouched(self):
        result = {'correlated_issues': [issue(component='email'), issue(issue_type='MEMORY_LEAK'),
                                        issue(issue_type='API_ERROR')]}
        self.assertEqual(_demote_steady_memory(result, batch()), 0)
        self.assertEqual([i['severity'] for i in result['correlated_issues']], ['WARNING'] * 3)

    def test_an_anomaly_or_a_restart_on_the_same_service_keeps_it(self):
        for data in (batch(anomalies=['accounting']), batch(peak=['accounting']),
                     batch(restarts={'accounting': 2})):
            result = {'correlated_issues': [issue(severity='CRITICAL')]}
            self.assertEqual(_demote_steady_memory(result, data), 0)
            self.assertEqual(result['correlated_issues'][0]['severity'], 'CRITICAL')

    def test_nothing_steady_nothing_changes(self):
        result = {'correlated_issues': [issue()]}
        self.assertEqual(_demote_steady_memory(result, batch(steady=())), 0)
        self.assertEqual(_demote_steady_memory(result, {}), 0)
        self.assertEqual(_demote_steady_memory(result, None), 0)
