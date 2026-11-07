"""Kubernetes changes and failures reach the RCA prompt (Online Boutique
scenarios B2 and B5: a config rollout and a broken release)."""

from dataclasses import replace

from django.test import SimpleTestCase

from ai_model.prompts import get_batch_analysis_prompt_parts
from ai_model.tests.test_prompt_capabilities import BASE_CTX


class KubernetesPromptTest(SimpleTestCase):

    def user_prompt(self, lifecycle):
        ctx = replace(BASE_CTX, metrics_summary={'memory': {'usage_percent': {'avg': 42}},
                                                 'container_lifecycle': lifecycle})
        return get_batch_analysis_prompt_parts(ctx)

    def test_changes_waiting_and_missing_replicas_are_listed(self):
        system, user = self.user_prompt({
            'restarts': {}, 'terminated': [],
            'waiting': [{'container': 'paymentservice', 'reason': 'ImagePullBackOff'}],
            'changes': [{'at': '2026-11-02T13:52:00+00:00', 'kind': 'Deployment', 'workload': 'checkoutservice',
                         'change': 'rollout', 'detail': 'spec changed, image unchanged (x): a configuration or environment change'}],
            'unavailable': [{'workload': 'paymentservice', 'available': 0, 'desired': 1}],
        })
        self.assertIn('Containers not starting: paymentservice ImagePullBackOff', user)
        self.assertIn('[2026-11-02T13:52:00+00:00] Deployment checkoutservice rollout: spec changed, image unchanged', user)
        self.assertIn('Workloads short of replicas: paymentservice 0/1 available', user)
        self.assertIn('A change made to a service is the first suspect', system)

    def test_cpu_throttling_is_listed(self):
        _system, user = self.user_prompt({'throttled': [{'service': 'productcatalogservice', 'percent': 93}]})
        self.assertIn('CPU throttling', user)
        self.assertIn('productcatalogservice 93%', user)

    def test_a_stuck_rollout_is_listed_and_not_an_outage(self):
        system, user = self.user_prompt({'stuck': [{'workload': 'currencyservice', 'not_ready': 1, 'available': 1, 'desired': 1}]})
        self.assertIn('Rollouts not completing', user)
        self.assertIn('currencyservice 1 new pod(s) not ready, 1/1 available', user)
        self.assertIn('report it as WARNING, not CRITICAL', system)

    def test_a_recovered_workload_says_so(self):
        _system, user = self.user_prompt({'unavailable': [{'workload': 'paymentservice', 'available': 0, 'desired': 1, 'now': 1}]})
        self.assertIn('paymentservice 0/1 available at worst, 1/1 now (recovered)', user)

    def test_nothing_to_say_adds_nothing(self):
        _system, user = self.user_prompt({'restarts': {}, 'terminated': [], 'waiting': [], 'changes': [], 'unavailable': []})
        self.assertNotIn('Kubernetes changes', user)
        self.assertNotIn('Containers not starting', user)
