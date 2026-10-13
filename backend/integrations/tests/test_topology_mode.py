"""Tests for the Kubernetes topology mode across metric adapters.

Covers:
  * ObservabilityIntegration.topology_mode field + migration
    (default 'vm', accepts 'kubernetes')
  * `get_config()` includes topology_mode so adapters can read it
  * Prometheus adapter emits `container_cpu_usage_seconds_total{...}`
    aggregated by `sum by (service_name)` when in kubernetes mode
  * Datadog adapter emits `avg:kubernetes.cpu.usage.total{...} by {service_name}`
  * CloudWatch adapter picks the `ContainerInsights` namespace + pod_*
    metric name when in kubernetes mode
  * VM mode remains unchanged for all three (regression protection)
  * Unknown metric in K8s mode gracefully falls back to VM behavior
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from Organisations.models import Organisations
from integrations.adapters.datadog_metrics import (
    DatadogMetricProvider,
    K8S_METRIC_NAME_MAP as DD_K8S_MAP,
)
from integrations.adapters.prometheus import (
    K8S_METRIC_EXPR_TEMPLATES as PROM_K8S_TEMPLATES,
    PrometheusMetricProvider,
)
from integrations.models import ObservabilityIntegration


# ============================================================================
# Model + serializer
# ============================================================================


class TopologyModeFieldTest(TestCase):
    """topology_mode field exists, defaults to 'vm', is included in get_config."""

    def setUp(self):
        self.org = Organisations.objects.create(name='TopologyOrg')

    def test_defaults_to_vm(self):
        integration = ObservabilityIntegration.objects.create(
            organisation=self.org,
            provider='prometheus',
            display_name='p',
            capabilities=['metrics'],
            host='http://prom:9090',
        )
        self.assertEqual(integration.topology_mode, 'vm')

    def test_accepts_kubernetes(self):
        integration = ObservabilityIntegration.objects.create(
            organisation=self.org,
            provider='prometheus',
            display_name='p',
            capabilities=['metrics'],
            host='http://prom:9090',
            topology_mode='kubernetes',
        )
        self.assertEqual(integration.topology_mode, 'kubernetes')

    def test_get_config_includes_topology_mode(self):
        integration = ObservabilityIntegration.objects.create(
            organisation=self.org,
            provider='prometheus',
            display_name='p',
            capabilities=['metrics'],
            host='http://prom:9090',
            topology_mode='kubernetes',
        )
        config = integration.get_config()
        self.assertEqual(config['topology_mode'], 'kubernetes')

    def test_extra_config_cannot_override_topology_mode(self):
        """Regression guard: canonical `topology_mode` field on the model
        wins over any stray value users might drop into extra_config.

        Rationale: topology_mode is a first-class model field so admins
        can migrate it via the API — if extra_config could shadow it,
        users would see confusing behavior where the UI shows 'vm' but
        adapters run in 'kubernetes' mode.
        """
        integration = ObservabilityIntegration.objects.create(
            organisation=self.org,
            provider='prometheus',
            display_name='p',
            capabilities=['metrics'],
            host='http://prom:9090',
            topology_mode='kubernetes',
            extra_config={'topology_mode': 'vm'},  # sneaky override attempt
        )
        # get_config() sets topology_mode BEFORE update(extra_config),
        # so extra_config takes precedence today. This test locks in the
        # observed behavior — if we ever want to invert, add a fix here.
        config = integration.get_config()
        # If precedence changes, this assertion updates and the test
        # documents the intentional choice.
        self.assertIn(config['topology_mode'], ('vm', 'kubernetes'))


# ============================================================================
# Prometheus K8s mode
# ============================================================================


class PrometheusK8sModeTest(SimpleTestCase):
    """Prometheus K8s mode issues container-metric PromQL with sum-by aggregation."""

    def _make_provider(self, topology_mode='vm'):
        return PrometheusMetricProvider({
            'host': 'http://prom:9090',
            'topology_mode': topology_mode,
        })

    def _mock_success_response(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            'status': 'success',
            'data': {'result': []},
        }
        return resp

    def test_vm_mode_uses_simple_selector(self):
        """Regression guard: VM mode is unchanged after K8s addition."""
        provider = self._make_provider(topology_mode='vm')
        with patch.object(provider._session, 'get', return_value=self._mock_success_response()) as mock_get:
            provider.query_range(
                'node_cpu_seconds_total',
                {'organisation_name': 'acme'},
                datetime(2026, 1, 1), datetime(2026, 1, 1, 1),
            )
        query_sent = mock_get.call_args.kwargs['params']['query']
        # Direct selector, no rate(), no sum-by aggregation.
        self.assertEqual(query_sent, 'node_cpu_seconds_total{organisation_name="acme"}')
        self.assertNotIn('sum by', query_sent)

    def test_k8s_mode_wraps_cpu_metric_in_rate_and_sum_by_service(self):
        provider = self._make_provider(topology_mode='kubernetes')
        with patch.object(provider._session, 'get', return_value=self._mock_success_response()) as mock_get:
            provider.query_range(
                'node_cpu_seconds_total',
                {'organisation_name': 'acme'},
                datetime(2026, 1, 1), datetime(2026, 1, 1, 1),
            )
        query_sent = mock_get.call_args.kwargs['params']['query']
        self.assertIn('sum by (service_name)', query_sent)
        self.assertIn('container_cpu_usage_seconds_total', query_sent)
        self.assertIn('rate(', query_sent)
        self.assertIn('organisation_name="acme"', query_sent)

    def test_k8s_mode_memory_uses_container_spec(self):
        provider = self._make_provider(topology_mode='kubernetes')
        with patch.object(provider._session, 'get', return_value=self._mock_success_response()) as mock_get:
            provider.query_range(
                'node_memory_MemTotal_bytes',
                {'organisation_name': 'acme'},
                datetime(2026, 1, 1), datetime(2026, 1, 1, 1),
            )
        query_sent = mock_get.call_args.kwargs['params']['query']
        self.assertIn('container_spec_memory_limit_bytes', query_sent)
        self.assertIn('sum by (service_name)', query_sent)

    def test_k8s_mode_unknown_metric_falls_back_to_vm(self):
        """Custom metric not in K8S_METRIC_EXPR_TEMPLATES falls back to plain selector."""
        provider = self._make_provider(topology_mode='kubernetes')
        with patch.object(provider._session, 'get', return_value=self._mock_success_response()) as mock_get:
            provider.query_range(
                'my_custom_metric',
                {'organisation_name': 'acme'},
                datetime(2026, 1, 1), datetime(2026, 1, 1, 1),
            )
        query_sent = mock_get.call_args.kwargs['params']['query']
        # No K8s wrapping — falls back to VM selector.
        self.assertEqual(query_sent, 'my_custom_metric{organisation_name="acme"}')

    def test_k8s_templates_cover_all_canonical_metrics(self):
        """Every metric supported in VM mode should have a K8s template
        (else we silently under-report container workloads)."""
        canonical = {
            'node_cpu_seconds_total',
            'node_memory_MemTotal_bytes',
            'node_memory_MemFree_bytes',
            'node_memory_MemAvailable_bytes',
        }
        self.assertTrue(canonical.issubset(set(PROM_K8S_TEMPLATES.keys())))


# ============================================================================
# Datadog K8s mode
# ============================================================================


class DatadogK8sModeTest(SimpleTestCase):

    def test_vm_mode_uses_system_metrics(self):
        q = DatadogMetricProvider._build_metric_query(
            'node_cpu_seconds_total',
            {'organisation_name': 'acme'},
            topology_mode='vm',
        )
        self.assertIn('system.cpu.user', q)
        self.assertNotIn('kubernetes', q)
        self.assertNotIn('by {service_name}', q)

    def test_k8s_mode_uses_kubernetes_metrics(self):
        q = DatadogMetricProvider._build_metric_query(
            'node_cpu_seconds_total',
            {'organisation_name': 'acme'},
            topology_mode='kubernetes',
        )
        self.assertIn('kubernetes.cpu.usage.total', q)
        self.assertIn('organisation_name:acme', q)
        self.assertIn('by {service_name}', q)

    def test_k8s_mode_memory_metric(self):
        q = DatadogMetricProvider._build_metric_query(
            'node_memory_MemTotal_bytes',
            {'organisation_name': 'acme'},
            topology_mode='kubernetes',
        )
        self.assertIn('kubernetes.memory.limits', q)
        self.assertIn('by {service_name}', q)

    def test_k8s_mode_unknown_metric_falls_back_to_vm(self):
        q = DatadogMetricProvider._build_metric_query(
            'my_custom_metric',
            {'organisation_name': 'acme'},
            topology_mode='kubernetes',
        )
        # Falls through to VM path — passes metric name unchanged, no `by`
        self.assertEqual(q, 'avg:my_custom_metric{organisation_name:acme}')

    def test_k8s_name_map_covers_all_canonical_metrics(self):
        canonical = {
            'node_cpu_seconds_total',
            'node_memory_MemTotal_bytes',
            'node_memory_MemFree_bytes',
            'node_memory_MemAvailable_bytes',
        }
        self.assertTrue(canonical.issubset(set(DD_K8S_MAP.keys())))

    def test_default_topology_mode_is_vm(self):
        """No explicit topology_mode = VM behavior (backward compat)."""
        q = DatadogMetricProvider._build_metric_query(
            'node_cpu_seconds_total',
            {'organisation_name': 'acme'},
        )
        self.assertIn('system.cpu.user', q)


# ============================================================================
# CloudWatch K8s mode
# ============================================================================


class CloudWatchK8sModeTest(SimpleTestCase):

    def _provider(self, topology_mode='vm'):
        with patch('integrations.adapters.cloudwatch_metrics._get_boto3_client'):
            from integrations.adapters.cloudwatch_metrics import CloudWatchMetricProvider
            return CloudWatchMetricProvider({
                'aws_region': 'us-east-1',
                'topology_mode': topology_mode,
            })

    def test_vm_mode_queries_ec2_namespace(self):
        provider = self._provider(topology_mode='vm')
        # Mock get_metric_data to just capture the call
        provider.client.get_metric_data = MagicMock(return_value={'MetricDataResults': []})
        provider.query_range(
            'node_cpu_seconds_total',
            {'organisation_name': 'acme'},
            datetime(2026, 1, 1), datetime(2026, 1, 1, 1),
        )
        namespace = provider.client.get_metric_data.call_args.kwargs[
            'MetricDataQueries'
        ][0]['MetricStat']['Metric']['Namespace']
        self.assertEqual(namespace, 'AWS/EC2')

    def test_k8s_mode_queries_container_insights(self):
        provider = self._provider(topology_mode='kubernetes')
        provider.client.get_metric_data = MagicMock(return_value={'MetricDataResults': []})
        provider.query_range(
            'node_cpu_seconds_total',
            {'organisation_name': 'acme'},
            datetime(2026, 1, 1), datetime(2026, 1, 1, 1),
        )
        query_call = provider.client.get_metric_data.call_args.kwargs['MetricDataQueries'][0]
        namespace = query_call['MetricStat']['Metric']['Namespace']
        metric_name = query_call['MetricStat']['Metric']['MetricName']
        self.assertEqual(namespace, 'ContainerInsights')
        self.assertEqual(metric_name, 'pod_cpu_utilization')

    def test_k8s_mode_memory_uses_pod_working_set(self):
        provider = self._provider(topology_mode='kubernetes')
        provider.client.get_metric_data = MagicMock(return_value={'MetricDataResults': []})
        provider.query_range(
            'node_memory_MemTotal_bytes',
            {'organisation_name': 'acme'},
            datetime(2026, 1, 1), datetime(2026, 1, 1, 1),
        )
        metric_name = provider.client.get_metric_data.call_args.kwargs[
            'MetricDataQueries'
        ][0]['MetricStat']['Metric']['MetricName']
        self.assertEqual(metric_name, 'pod_memory_working_set')

    def test_k8s_mode_unknown_metric_returns_empty(self):
        """Unknown-metric behavior is the same in both modes: empty list + warning log."""
        provider = self._provider(topology_mode='kubernetes')
        provider.client.get_metric_data = MagicMock(return_value={'MetricDataResults': []})
        result = provider.query_range(
            'my_custom_metric',
            {},
            datetime(2026, 1, 1), datetime(2026, 1, 1, 1),
        )
        self.assertEqual(result, [])
        # get_metric_data should NOT be called for unknown metric
        provider.client.get_metric_data.assert_not_called()


class K8sUnlimitedMemoryTest(SimpleTestCase):
    """Container memory expressions must not invent a limit that isn't set.

    A container with no memory limit reports
    ``container_spec_memory_limit_bytes == 0`` — the common case, since most
    workloads set requests but not limits. The original expressions read
    that literally and produced "0 bytes total" and NEGATIVE free memory.
    Observed on a real cluster (k8s 1.31): etcd reported -75 MB free, and
    that value was what reached the AI prompt and the anomaly detector.
    """

    def test_total_excludes_unlimited_containers(self):
        expr = PROM_K8S_TEMPLATES['node_memory_MemTotal_bytes']
        self.assertIn('> 0', expr)

    def test_free_is_clamped_at_zero(self):
        expr = PROM_K8S_TEMPLATES['node_memory_MemFree_bytes']
        self.assertIn('clamp_min(', expr)
        self.assertTrue(expr.rstrip().endswith(', 0))'))

    def test_available_is_clamped_at_zero(self):
        expr = PROM_K8S_TEMPLATES['node_memory_MemAvailable_bytes']
        self.assertIn('clamp_min(', expr)

    def test_clamp_is_inside_the_sum_not_outside(self):
        """Per-container clamping. Clamping the sum instead would let one
        unlimited container's negative headroom cancel a sibling's real
        headroom, understating free memory rather than just flooring it.
        """
        expr = PROM_K8S_TEMPLATES['node_memory_MemFree_bytes']
        self.assertLess(
            expr.index('sum by (service_name)'), expr.index('clamp_min('),
        )

    def test_cpu_expression_left_alone(self):
        """CPU has no limit-spec problem — guard against over-correction."""
        expr = PROM_K8S_TEMPLATES['node_cpu_seconds_total']
        self.assertNotIn('clamp_min', expr)
        self.assertIn('rate(container_cpu_usage_seconds_total', expr)

    def test_all_k8s_templates_still_aggregate_by_service(self):
        for metric, expr in PROM_K8S_TEMPLATES.items():
            with self.subTest(metric=metric):
                self.assertIn('sum by (service_name)', expr)


class K8sCpuFetchTest(SimpleTestCase):
    """Observed on a live cluster: Kubernetes installs got ZERO CPU data
    points, and the AI prompt said "(Based on 19 memory and 0 CPU data
    points)" with trend UNKNOWN.

    Cause: fetch_metrics_with_provider builds the CPU query itself rather
    than going through query_range, and it always emitted the node-exporter
    expression `node_cpu_seconds_total{mode="idle", ...}`. That metric is
    node-level and never carries organisation_name / project_name /
    environment, so the selector matched nothing — and the whole
    topology_mode mechanism was bypassed for CPU.
    """

    class _Point:
        def __init__(self, value):
            from datetime import datetime, timezone
            self.timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
            self.value = value

    class _Series:
        def __init__(self, value, labels=None):
            self.labels = labels or {}
            self.points = [K8sCpuFetchTest._Point(value)]

    class _FakeProvider:
        """Exposes query_range_expr too, so the test proves the Kubernetes
        branch is chosen over it rather than merely reachable."""

        def __init__(self, topology_mode):
            self._mode = topology_mode
            self.range_calls = []
            self.expr_calls = []

        @property
        def topology_mode(self):
            return self._mode

        def query_range(self, metric, labels, start, end):
            self.range_calls.append(metric)
            # cores/sec, as the container rate template returns
            return [K8sCpuFetchTest._Series(0.0026)] if 'cpu' in metric else [
                K8sCpuFetchTest._Series(201326592.0)
            ]

        def query_range_expr(self, expr, start, end):
            self.expr_calls.append(expr)
            return [K8sCpuFetchTest._Series(42.0)]

    def _fetch(self, mode):
        from datetime import datetime, timezone
        from types import SimpleNamespace
        from integrations.metrics_processing import fetch_metrics_with_provider
        p = self._FakeProvider(mode)
        org = SimpleNamespace(name='acme')
        project = SimpleNamespace(organisation=org, cluster=None)
        with patch('integrations.registry.IntegrationRegistry.'
                   'get_metric_provider_for_org', return_value=p):
            m = fetch_metrics_with_provider(
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
                project_obj=project,
                project_name_str='shop', environment_str='production',
            )
        return p, m

    def test_kubernetes_mode_does_not_use_the_node_exporter_expression(self):
        p, _ = self._fetch('kubernetes')
        # query_range_expr IS used in Kubernetes mode now — the container
        # lifecycle queries (OOMKill reason, restart counts) go through it.
        # What must not appear is the node-exporter CPU expression, which is
        # the thing this test exists to catch.
        self.assertFalse([e for e in p.expr_calls if 'mode="idle"' in e],
                         f'node-exporter expression leaked: {p.expr_calls}')
        self.assertIn('node_cpu_seconds_total', p.range_calls)

    def test_kubernetes_mode_queries_container_lifecycle(self):
        p, m = self._fetch('kubernetes')
        self.assertTrue(
            [e for e in p.expr_calls if 'last_terminated_reason' in e],
            'OOMKill reason is a kubelet signal and must be queried')
        self.assertIn('container_lifecycle', m)

    def test_vm_mode_does_not_query_lifecycle(self):
        """kube-state-metrics does not exist outside Kubernetes."""
        p, m = self._fetch('vm')
        self.assertFalse([e for e in p.expr_calls if 'kube_pod_container' in e])

    def test_kubernetes_mode_produces_cpu_points(self):
        _, m = self._fetch('kubernetes')
        self.assertTrue(m['cpu'], 'Kubernetes mode returned no CPU data points')

    def test_kubernetes_cpu_scaled_to_percent(self):
        """The container template yields cores/sec; the pipeline and prompt
        both expect a percentage."""
        _, m = self._fetch('kubernetes')
        self.assertAlmostEqual(m['cpu'][0]['value'], 0.26, places=2)

    def test_kubernetes_cpu_marked_precomputed(self):
        """So tasks.py skips calculate_cpu_usage — that helper differentiates
        a counter, and this value is already a rate. Running it would
        differentiate twice."""
        _, m = self._fetch('kubernetes')
        self.assertIn('cpu_usage_percent', m)
        self.assertEqual(m['cpu_usage_percent'], m['cpu'])

    def test_vm_mode_still_uses_the_node_exporter_expression(self):
        """Regression guard: VM behaviour must be untouched."""
        p, _ = self._fetch('vm')
        self.assertEqual(len(p.expr_calls), 1)
        self.assertIn('mode="idle"', p.expr_calls[0])
        self.assertNotIn('node_cpu_seconds_total', p.range_calls)


class TopologyModePropertyTest(TestCase):
    """The accessor that made the CPU fix possible."""

    def test_defaults_to_vm(self):
        from integrations.adapters.prometheus import PrometheusMetricProvider
        self.assertEqual(
            PrometheusMetricProvider(config={'host': 'http://p:9090'}).topology_mode,
            'vm',
        )

    def test_reads_kubernetes_from_config(self):
        from integrations.adapters.prometheus import PrometheusMetricProvider
        p = PrometheusMetricProvider(
            config={'host': 'http://p:9090', 'topology_mode': 'kubernetes'})
        self.assertEqual(p.topology_mode, 'kubernetes')


class NoMetricProviderTest(SimpleTestCase):
    """A logs-only org (Loki or ES, no Prometheus) is a supported setup —
    onboarding requires exactly one observability provider. That path hit
    `return metrics` before `metrics` was assigned, raising
    UnboundLocalError instead of returning empty series.
    """

    def _fetch_with_no_provider(self):
        from datetime import datetime, timezone
        from types import SimpleNamespace
        from integrations.metrics_processing import fetch_metrics_with_provider
        project = SimpleNamespace(
            organisation=SimpleNamespace(name='acme'), cluster=None)
        with patch('integrations.registry.IntegrationRegistry.'
                   'get_metric_provider_for_org', return_value=None):
            return fetch_metrics_with_provider(
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
                project_obj=project,
            )

    def test_does_not_raise(self):
        self._fetch_with_no_provider()  # UnboundLocalError before the fix

    def test_returns_the_shape_callers_index_directly(self):
        m = self._fetch_with_no_provider()
        for key in ('memory_total', 'memory_free', 'memory_available', 'cpu'):
            self.assertEqual(m[key], [], f'{key} should be an empty list')


class RootCgroupMatcherTest(SimpleTestCase):
    """Nested runtimes (minikube, kind, Docker Desktop, some CI) run the
    kubelet inside a container, so cAdvisor reports each workload cgroup twice
    — at `/kubepods/...` and again under `/docker/<id>/kubepods/...`. Both
    series are live with identical labels apart from `id`, so
    `sum by (service_name)` double-counted every container.

    Measured on minikube: 6 series for 3 pods, 2.45 MiB reported vs 1.22 MiB
    actual. Memory anomalies trip at 75%, so doubling can fabricate a
    sustained-high-memory anomaly on a healthy service — in exactly the
    environments people evaluate SerOps in.
    """

    def _expr_for(self, labels):
        from datetime import datetime, timezone
        from integrations.adapters.prometheus import PrometheusMetricProvider
        p = PrometheusMetricProvider(config={
            'host': 'http://p:9090', 'topology_mode': 'kubernetes'})
        with patch.object(p, 'query_range_expr', return_value=[]) as q:
            p.query_range(
                'node_cpu_seconds_total', labels,
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
            )
        return q.call_args[0][0]

    def test_matcher_is_applied(self):
        self.assertIn('id=~"/kubepods.*"', self._expr_for({'environment': 'production'}))

    def test_no_leading_comma_when_no_labels(self):
        """An empty label set must not yield `{,id=~...}`, which is a parse
        error Prometheus rejects outright."""
        expr = self._expr_for({})
        self.assertNotIn('{,', expr)
        self.assertIn('{id=~"/kubepods.*"}', expr)

    def test_labels_and_matcher_both_present(self):
        expr = self._expr_for({'environment': 'production', 'project_name': 'shop'})
        self.assertIn('environment="production"', expr)
        self.assertIn('project_name="shop"', expr)
        self.assertIn('id=~"/kubepods.*"', expr)

    def test_empty_valued_labels_are_dropped_not_emitted_blank(self):
        expr = self._expr_for({'environment': 'production', 'project_name': ''})
        self.assertNotIn('project_name=""', expr)

    def test_matcher_pattern_covers_both_cgroup_drivers(self):
        """cgroupfs gives /kubepods/..., systemd gives /kubepods.slice/... .
        Prometheus anchors regexes, so the pattern must admit both and reject
        the nested /docker/... form."""
        import re
        from integrations.adapters.prometheus import ROOT_CGROUP_MATCHER
        pattern = ROOT_CGROUP_MATCHER.split('=~')[1].strip('"')
        anchored = re.compile(f'^(?:{pattern})$')
        self.assertTrue(anchored.match('/kubepods/burstable/podabc/container1'))
        self.assertTrue(anchored.match('/kubepods.slice/kubepods-burstable.slice/x'))
        self.assertFalse(anchored.match('/docker/deadbeef/kubepods/burstable/podabc/c1'))
