"""integrations.kubernetes_state — what Kubernetes did around an incident.

Shaped on the Online Boutique production scenarios (2026-11-02): every
container is called ``server``, the agents say environment=production for
namespace ``boutique``, and the failures were a config rollout (B2), a
scale to zero (B1), an OOM crash loop (B3) and a release with an image that
does not exist (B5).
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase

from integrations.kubernetes_state import fetch_kubernetes_state, workload_name

T0 = datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc)
START, END = T0, T0 + timedelta(minutes=15)


def series(labels, *values, step=60, start=None):
    start = start or T0 - timedelta(minutes=30)
    return SimpleNamespace(labels=labels, points=[
        SimpleNamespace(timestamp=start + timedelta(seconds=i * step), value=v) for i, v in enumerate(values)])


class FakeProm:
    """Answers each query by the metric it names; records the expressions."""

    def __init__(self, answers):
        self.answers = answers
        self.queries = []

    def query_range_expr(self, expr, start, end):
        self.queries.append(expr)
        for metric, result in self.answers.items():
            if metric in expr:
                return result
        return []


LABELS = {'organisation_name': 'acme', 'project_name': 'boutique', 'environment': 'production'}
NAMESPACE = {'container_memory_working_set_bytes': [series({'namespace': 'boutique'}, 1)]}


class WorkloadNameTest(SimpleTestCase):

    def test_names(self):
        self.assertEqual(workload_name('checkoutservice-7d9f8c6b5-x2k4q', 'server'), 'checkoutservice')
        self.assertEqual(workload_name('redis-cart-5b6f9d7c8-abcde', 'redis'), 'redis-cart/redis')
        self.assertEqual(workload_name('db-0', 'db'), 'db')
        self.assertEqual(workload_name('node-agent-x2k4q', 'node-agent'), 'node-agent')
        self.assertEqual(workload_name('checkout-7d9f8c6b5-x2k4q', 'istio-proxy'), 'checkout/istio-proxy')
        self.assertEqual(workload_name('', 'cache'), 'cache')


class KubernetesStateTest(SimpleTestCase):

    def test_namespaces_come_from_the_projects_cadvisor_series(self):
        prom = FakeProm(NAMESPACE)
        fetch_kubernetes_state(prom, LABELS, START, END)
        ksm = [q for q in prom.queries if 'kube_' in q]
        self.assertTrue(ksm)
        self.assertTrue(all('namespace=~"boutique"' in q for q in ksm), ksm)

    def test_without_cadvisor_series_the_environment_stands_for_the_namespace(self):
        prom = FakeProm({})
        fetch_kubernetes_state(prom, {'environment': 'staging'}, START, END)
        self.assertTrue(all('namespace=~"staging"' in q for q in prom.queries if 'kube_' in q))

    def test_b3_oom_crash_loop_is_named_after_the_workload(self):
        pod = {'namespace': 'boutique', 'pod': 'recommendationservice-6d8f7c9b4-k2j3h', 'container': 'server'}
        prom = FakeProm({**NAMESPACE,
            'last_terminated_reason': [series({**pod, 'reason': 'OOMKilled'}, 1)],
            'restarts_total': [series(pod, 0, 2, 4)],
            'waiting_reason': [series({**pod, 'reason': 'CrashLoopBackOff'}, 1),
                               series({**pod, 'reason': 'ContainerCreating'}, 1)],
        })
        state = fetch_kubernetes_state(prom, LABELS, START, END)
        self.assertEqual(state['restarts'], {'recommendationservice': 4})
        self.assertEqual(state['terminated'], [{'container': 'recommendationservice', 'reason': 'OOMKilled'}])
        self.assertEqual(state['waiting'], [{'container': 'recommendationservice', 'reason': 'CrashLoopBackOff'}])

    def test_a_reason_without_a_restart_in_the_window_is_not_reported(self):
        pod = {'namespace': 'boutique', 'pod': 'cartservice-6d8f7c9b4-k2j3h', 'container': 'server'}
        prom = FakeProm({**NAMESPACE, 'last_terminated_reason': [series({**pod, 'reason': 'OOMKilled'}, 1)]})
        self.assertEqual(fetch_kubernetes_state(prom, LABELS, START, END)['terminated'], [])

    def test_b2_config_rollout_with_the_same_image(self):
        dep = {'namespace': 'boutique', 'deployment': 'checkoutservice'}
        image = 'gcr.io/google-samples/microservices-demo/checkoutservice:v0.10.7'
        prom = FakeProm({**NAMESPACE,
            'kube_deployment_metadata_generation': [series(dep, 3, 3, 4, 4)],
            'kube_deployment_spec_replicas': [series(dep, 1, 1, 1, 1)],
            'kube_pod_container_info': [
                series({'pod': 'checkoutservice-6d8f7c9b4-aaaaa', 'container': 'server', 'image': image}, 1, 1),
                series({'pod': 'checkoutservice-79c5d8f6b-bbbbb', 'container': 'server', 'image': image}, 1, 1,
                       start=T0 - timedelta(minutes=28))],
        })
        [change] = fetch_kubernetes_state(prom, LABELS, START, END)['changes']
        self.assertEqual((change['workload'], change['change']), ('checkoutservice', 'rollout'))
        self.assertIn('image unchanged', change['detail'])
        self.assertIn('configuration or environment change', change['detail'])
        self.assertEqual(change['at'], (T0 - timedelta(minutes=28)).isoformat())

    def test_b5_release_with_a_new_image_and_no_replica_left(self):
        dep = {'namespace': 'boutique', 'deployment': 'paymentservice'}
        prom = FakeProm({**NAMESPACE,
            'kube_deployment_metadata_generation': [series(dep, 2, 3, 3)],
            'kube_deployment_spec_replicas': [series(dep, 1, 1, 1)],
            'kube_deployment_status_replicas_available': [series(dep, 1, 0, 0)],
            'kube_pod_container_info': [
                series({'pod': 'paymentservice-6d8f7c9b4-aaaaa', 'container': 'server', 'image': 'payments:v0.10.7'}, 1),
                series({'pod': 'paymentservice-79c5d8f6b-bbbbb', 'container': 'server', 'image': 'payments:v9.9.9'}, 1, 1,
                       start=T0 - timedelta(minutes=29))],
            'waiting_reason': [series({'pod': 'paymentservice-79c5d8f6b-bbbbb', 'container': 'server',
                                       'reason': 'ImagePullBackOff'}, 1)],
        })
        state = fetch_kubernetes_state(prom, LABELS, START, END)
        self.assertEqual(state['changes'][0]['detail'], 'image payments:v0.10.7 -> payments:v9.9.9')
        self.assertEqual(state['unavailable'], [{'workload': 'paymentservice', 'available': 0, 'desired': 1, 'now': 0}])
        self.assertEqual(state['waiting'], [{'container': 'paymentservice', 'reason': 'ImagePullBackOff'}])

    def test_b3_rollout_that_cuts_the_memory_limit(self):
        dep = {'namespace': 'boutique', 'deployment': 'recommendationservice'}
        image = 'recommendationservice:v0.10.7'
        old, new = 'recommendationservice-6d8f7c9b4-aaaaa', 'recommendationservice-79c5d8f6b-bbbbb'
        prom = FakeProm({**NAMESPACE,
            'kube_deployment_metadata_generation': [series(dep, 1, 2, 2)],
            'kube_deployment_spec_replicas': [series(dep, 1, 1, 1)],
            'kube_pod_container_info': [
                series({'pod': old, 'container': 'server', 'image': image}, 1),
                series({'pod': new, 'container': 'server', 'image': image}, 1, start=T0 - timedelta(minutes=29))],
            'resource="memory"': [
                series({'pod': old, 'container': 'server'}, 450 * 1048576),
                series({'pod': new, 'container': 'server'}, 40 * 1048576, start=T0 - timedelta(minutes=29))],
        })
        [change] = fetch_kubernetes_state(prom, LABELS, START, END)['changes']
        self.assertEqual(change['detail'], 'memory limit 450Mi -> 40Mi')
        self.assertTrue([q for q in prom.queries if 'resource="memory"' in q and 'namespace=~"boutique"' in q])

    def test_r1_rollout_that_cuts_the_cpu_limit_and_the_throttling_it_causes(self):
        dep = {'namespace': 'boutique', 'deployment': 'productcatalogservice'}
        image = 'productcatalogservice:v0.10.7'
        old, new = 'productcatalogservice-6d8f7c9b4-aaaaa', 'productcatalogservice-79c5d8f6b-bbbbb'
        prom = FakeProm({**NAMESPACE,
            'kube_deployment_metadata_generation': [series(dep, 1, 2, 2)],
            'kube_deployment_spec_replicas': [series(dep, 1, 1, 1)],
            'kube_pod_container_info': [
                series({'pod': old, 'container': 'server', 'image': image}, 1),
                series({'pod': new, 'container': 'server', 'image': image}, 1, start=T0 - timedelta(minutes=29))],
            'resource="cpu"': [
                series({'pod': old, 'container': 'server'}, 0.2),
                series({'pod': new, 'container': 'server'}, 0.01, start=T0 - timedelta(minutes=29))],
            'container_cpu_cfs_throttled_periods_total': [
                series({'service_name': 'productcatalogservice'}, float('nan'), 40, 93),
                series({'service_name': 'frontend'}, 3, 5)],
        })
        state = fetch_kubernetes_state(prom, LABELS, START, END)
        self.assertEqual(state['changes'][0]['detail'], 'cpu limit 200m -> 10m')
        self.assertEqual(state['throttled'], [{'service': 'productcatalogservice', 'percent': 93}])
        throttle_query = next(q for q in prom.queries if 'cfs_throttled' in q)
        self.assertIn('project_name="boutique"', throttle_query)

    def test_r7_rollout_stuck_while_the_old_version_serves(self):
        dep = {'namespace': 'boutique', 'deployment': 'currencyservice'}
        prom = FakeProm({**NAMESPACE,
            'kube_deployment_spec_replicas': [series(dep, 1, 1)],
            'kube_deployment_status_replicas_updated': [series(dep, 1, 0)],
            'kube_deployment_status_replicas_available': [series(dep, 1, 1)],
        })
        state = fetch_kubernetes_state(prom, LABELS, START, END)
        self.assertEqual(state['stuck'], [{'workload': 'currencyservice', 'not_ready': 1, 'available': 1, 'desired': 1}])
        self.assertEqual(state['unavailable'], [])

    def test_r7_one_replica_the_crash_looping_pod_already_counts_as_updated(self):
        # What kube-state-metrics reported in the R7 run: updated 1/1, a second
        # pod (the new one) unavailable, the old one still available.
        dep = {'namespace': 'boutique', 'deployment': 'currencyservice'}
        prom = FakeProm({**NAMESPACE,
            'kube_deployment_spec_replicas': [series(dep, 1, 1)],
            'kube_deployment_status_replicas_updated': [series(dep, 1, 1)],
            'kube_deployment_status_replicas_unavailable': [series(dep, 0, 1)],
            'kube_deployment_status_replicas_available': [series(dep, 1, 1)],
        })
        state = fetch_kubernetes_state(prom, LABELS, START, END)
        self.assertEqual(state['stuck'], [{'workload': 'currencyservice', 'not_ready': 1, 'available': 1, 'desired': 1}])
        self.assertEqual(state['unavailable'], [])

    def test_a_finished_rollout_is_not_stuck(self):
        dep = {'namespace': 'boutique', 'deployment': 'currencyservice'}
        prom = FakeProm({**NAMESPACE,
            'kube_deployment_spec_replicas': [series(dep, 1, 1)],
            'kube_deployment_status_replicas_updated': [series(dep, 0, 1)],
            'kube_deployment_status_replicas_available': [series(dep, 1, 1)],
        })
        self.assertEqual(fetch_kubernetes_state(prom, LABELS, START, END)['stuck'], [])

    def test_r12_a_rollback_is_described_as_the_rollback_and_the_recovery_is_seen(self):
        dep = {'namespace': 'boutique', 'deployment': 'paymentservice'}
        good, bad = 'payments:v0.10.7', 'payments:v0.10.99'
        m = lambda minutes: T0 - timedelta(minutes=minutes)
        prom = FakeProm({**NAMESPACE,
            # release at -20 min, rollback at -17 min
            'kube_deployment_metadata_generation': [series(dep, *([1] * 10 + [2] * 3 + [3] * 17))],
            'kube_deployment_spec_replicas': [series(dep, *([1] * 30))],
            'kube_deployment_status_replicas_available': [series(dep, *([1] * 10 + [0] * 4 + [1] * 16))],
            'kube_pod_container_info': [
                series({'pod': 'paymentservice-6d8f7c9b4-aaaaa', 'container': 'server', 'image': good}, *([1] * 10)),
                series({'pod': 'paymentservice-79c5d8f6b-bbbbb', 'container': 'server', 'image': bad}, 1, 1, 1, start=m(20)),
                series({'pod': 'paymentservice-6d8f7c9b4-ccccc', 'container': 'server', 'image': good}, *([1] * 17), start=m(17))],
        })
        state = fetch_kubernetes_state(prom, LABELS, START, END)
        details = [c['detail'] for c in state['changes']]       # newest first
        self.assertEqual(details, [f'image {bad} -> {good}', f'image {good} -> {bad}'])
        self.assertEqual(state['unavailable'], [{'workload': 'paymentservice', 'available': 0, 'desired': 1, 'now': 1}])

    def test_b1_scale_to_zero_is_a_scale_not_a_rollout(self):
        dep = {'namespace': 'boutique', 'deployment': 'redis-cart'}
        prom = FakeProm({**NAMESPACE,
            'kube_deployment_metadata_generation': [series(dep, 1, 2, 2)],
            'kube_deployment_spec_replicas': [series(dep, 1, 0, 0)],
            'kube_deployment_status_replicas_available': [series(dep, 1, 0, 0)],
        })
        state = fetch_kubernetes_state(prom, LABELS, START, END)
        self.assertEqual([(c['workload'], c['change'], c['detail']) for c in state['changes']],
                         [('redis-cart', 'scaled', 'replicas 1 -> 0')])
        # Desired is 0: nothing is missing.
        self.assertEqual(state['unavailable'], [])

    def test_times_carry_their_utc_offset(self):
        dep = {'namespace': 'boutique', 'deployment': 'redis-cart'}
        naive = series(dep, 1, 0, start=(T0 - timedelta(minutes=5)).replace(tzinfo=None))
        state = fetch_kubernetes_state(FakeProm({**NAMESPACE, 'kube_deployment_spec_replicas': [naive]}),
                                       LABELS, START, END)
        self.assertTrue(state['changes'][0]['at'].endswith('+00:00'))

    def test_failing_queries_leave_the_rest(self):
        class Broken(FakeProm):
            def query_range_expr(self, expr, start, end):
                if 'restarts_total' in expr:
                    raise ConnectionError('prometheus down')
                return super().query_range_expr(expr, start, end)
        dep = {'namespace': 'boutique', 'deployment': 'redis-cart'}
        state = fetch_kubernetes_state(Broken({**NAMESPACE, 'kube_deployment_spec_replicas': [series(dep, 1, 0)]}),
                                       LABELS, START, END)
        self.assertEqual(state['restarts'], {})
        self.assertEqual(len(state['changes']), 1)

    def test_odd_namespace_values_are_not_put_into_promql(self):
        prom = FakeProm({'container_memory_working_set_bytes': [series({'namespace': 'x"}) or vector(1'}, 1)]})
        fetch_kubernetes_state(prom, {'environment': 'prod'}, START, END)
        ksm = [q for q in prom.queries if 'kube_' in q]
        self.assertTrue(all('namespace=~"prod"' in q for q in ksm), ksm)
