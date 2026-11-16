"""Prometheus family in VM mode on a Kubernetes-only store (phase 3 client
test C1, 2026-11-16): the health check said OK and every investigation read
0 metrics. The health check now says to switch Topology Mode."""
from unittest.mock import patch

from django.test import SimpleTestCase

from integrations.adapters.mimir import MimirMetricProvider
from integrations.adapters.prometheus import PrometheusMetricProvider
from integrations.base import MetricQueryError


def _answer(node, container):
    def fake(self, expr, start, end):
        if 'node_cpu_seconds_total' in expr:
            return ['series'] if node else []
        return ['series'] if container else []
    return fake


class TopologyHintTest(SimpleTestCase):
    def provider(self, cls=PrometheusMetricProvider, mode='vm'):
        return cls({'host': 'http://prometheus:9090', 'topology_mode': mode})

    def test_vm_mode_on_a_kubernetes_store_says_so(self):
        with patch.object(PrometheusMetricProvider, 'query_range_expr', _answer(node=False, container=True)):
            hint = self.provider().topology_hint()
        self.assertIn('Topology Mode to Kubernetes', hint)

    def test_mimir_inherits_it(self):
        with patch.object(PrometheusMetricProvider, 'query_range_expr', _answer(node=False, container=True)), \
             patch.object(MimirMetricProvider, 'query_range_expr', _answer(node=False, container=True)):
            self.assertIsNotNone(self.provider(MimirMetricProvider).topology_hint())

    def test_node_metrics_present_or_kubernetes_mode_no_hint(self):
        with patch.object(PrometheusMetricProvider, 'query_range_expr', _answer(node=True, container=True)):
            self.assertIsNone(self.provider().topology_hint())
        with patch.object(PrometheusMetricProvider, 'query_range_expr', _answer(node=False, container=True)):
            self.assertIsNone(self.provider(mode='kubernetes').topology_hint())

    def test_a_refused_query_gives_no_hint(self):
        def refuse(self, expr, start, end):
            raise MetricQueryError('401')
        with patch.object(PrometheusMetricProvider, 'query_range_expr', refuse):
            self.assertIsNone(self.provider().topology_hint())
