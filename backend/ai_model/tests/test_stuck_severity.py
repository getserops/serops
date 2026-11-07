"""
A rollout whose new pods fail while the previous version still serves every
replica is a WARNING: Claude rated it CRITICAL while writing that users were
unaffected (Online Boutique, Fastly-2021 scenario R7).
"""
from django.test import SimpleTestCase

from ai_model.tasks import _cap_stuck_rollout_severity

STUCK = {'workload': 'currencyservice', 'not_ready': 1, 'available': 1, 'desired': 1}


def batch(**lifecycle):
    return {'metrics_summary': {'container_lifecycle': lifecycle}}


def issue(component, severity='CRITICAL'):
    return {'component': component, 'severity': severity, 'scope': 'SERVICE'}


class CapStuckRolloutSeverityTest(SimpleTestCase):
    def test_r7_a_stuck_rollout_is_a_warning(self):
        result = {'correlated_issues': [issue('currencyservice'), issue('paymentservice', 'WARNING')]}
        self.assertEqual(_cap_stuck_rollout_severity(result, batch(stuck=[STUCK])), 1)
        self.assertEqual([i['severity'] for i in result['correlated_issues']], ['WARNING', 'WARNING'])

    def test_a_workload_also_short_of_replicas_now_stays_critical(self):
        result = {'correlated_issues': [issue('currencyservice')]}
        short = {'workload': 'currencyservice', 'available': 0, 'desired': 1, 'now': 0}
        self.assertEqual(_cap_stuck_rollout_severity(result, batch(stuck=[STUCK], unavailable=[short])), 0)
        self.assertEqual(result['correlated_issues'][0]['severity'], 'CRITICAL')

    def test_a_recovered_shortage_does_not_block_the_cap(self):
        result = {'correlated_issues': [issue('currencyservice')]}
        recovered = {'workload': 'currencyservice', 'available': 0, 'desired': 1, 'now': 1}
        self.assertEqual(_cap_stuck_rollout_severity(result, batch(stuck=[STUCK], unavailable=[recovered])), 1)

    def test_another_service_keeps_its_critical(self):
        result = {'correlated_issues': [issue('redis-cart')]}
        self.assertEqual(_cap_stuck_rollout_severity(result, batch(stuck=[STUCK])), 0)
        self.assertEqual(result['correlated_issues'][0]['severity'], 'CRITICAL')

    def test_no_kubernetes_data_changes_nothing(self):
        result = {'correlated_issues': [issue('currencyservice')]}
        self.assertEqual(_cap_stuck_rollout_severity(result, {}), 0)
        self.assertEqual(_cap_stuck_rollout_severity(result, None), 0)
        self.assertEqual(result['correlated_issues'][0]['severity'], 'CRITICAL')
