"""Tests for GCP + Azure K8s-mode metric adapters (Item #18).

Focus: the topology-aware routing layer — do we build the correct
metric names + filters when the integration is scoped to a K8s
cluster instead of a VM?

HTTP + SDK calls are fully mocked. We test the plain functions
(_build_filter, _build_dim_filter, METRIC_MAP selection) directly
where possible, and mock the client for query_range behaviour.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase


# ============================================================================
# GCP Cloud Monitoring — K8s topology
# ============================================================================


class GcpFilterTest(TestCase):
    """_build_filter routes labels correctly per topology."""

    def setUp(self):
        # Import lazily so an environment missing google-cloud-monitoring
        # can still import the test module (adapter itself imports lazily
        # inside __init__).
        from integrations.adapters.gcp_monitoring import GcpCloudMonitoringProvider
        self.Provider = GcpCloudMonitoringProvider

    def test_vm_mode_uses_metric_labels(self):
        f = self.Provider._build_filter(
            'compute.googleapis.com/instance/cpu/utilization',
            {'instance_id': 'i-123'},
            topology_mode='vm',
        )
        self.assertIn('metric.type="compute.googleapis.com/instance/cpu/utilization"', f)
        self.assertIn('metric.labels.instance_id="i-123"', f)
        # Resource-label routing MUST NOT fire in VM mode.
        self.assertNotIn('resource.labels', f)

    def test_k8s_mode_routes_service_to_container_name(self):
        f = self.Provider._build_filter(
            'kubernetes.io/container/cpu/core_usage_time',
            {'service_name': 'checkout', 'namespace': 'prod'},
            topology_mode='kubernetes',
        )
        # service_name → container_name on the RESOURCE
        self.assertIn('resource.labels.container_name="checkout"', f)
        # namespace → namespace_name on the RESOURCE
        self.assertIn('resource.labels.namespace_name="prod"', f)
        # Metric.labels routing MUST NOT fire for K8s canonical labels.
        self.assertNotIn('metric.labels.service_name', f)

    def test_k8s_mode_unmapped_label_still_uses_metric_labels(self):
        f = self.Provider._build_filter(
            'kubernetes.io/container/cpu/core_usage_time',
            {'custom_label': 'foo'},
            topology_mode='kubernetes',
        )
        self.assertIn('metric.labels.custom_label="foo"', f)

    def test_k8s_mode_alias_container_uses_container_name(self):
        f = self.Provider._build_filter(
            'kubernetes.io/container/cpu/core_usage_time',
            {'container': 'sidecar'},
            topology_mode='kubernetes',
        )
        self.assertIn('resource.labels.container_name="sidecar"', f)

    def test_empty_labels_skipped(self):
        f = self.Provider._build_filter(
            'metric.type', {'service_name': '', 'namespace': None},
            topology_mode='kubernetes',
        )
        # Only the metric.type clause survives.
        self.assertEqual(f.count('='), 1)

    def test_gcp_escape_prevents_injection(self):
        """A malicious value must not break out of the string."""
        f = self.Provider._build_filter(
            'metric.type', {'service_name': 'evil" OR 1=1--'},
            topology_mode='kubernetes',
        )
        # The quote is escaped (backslash-escaped in the output).
        self.assertNotIn('evil" OR 1=1--"', f)


class GcpMetricNameMapTest(TestCase):
    """Verify VM/K8s metric name maps route to the right GCP types."""

    def setUp(self):
        from integrations.adapters.gcp_monitoring import GcpCloudMonitoringProvider
        self.Provider = GcpCloudMonitoringProvider

    def test_vm_map_uses_compute_engine(self):
        self.assertTrue(
            self.Provider.METRIC_NAME_MAP['node_cpu_seconds_total']
            .startswith('compute.googleapis.com/')
        )

    def test_k8s_map_uses_gke_container_metrics(self):
        for canonical in ('node_cpu_seconds_total', 'node_memory_MemAvailable_bytes',
                          'container_cpu_usage_seconds_total', 'container_memory_usage_bytes'):
            self.assertTrue(
                self.Provider.K8S_METRIC_NAME_MAP[canonical].startswith('kubernetes.io/container/'),
                f'{canonical} should map to a GKE container metric',
            )


class GcpQueryRangeTest(TestCase):
    """Full query_range: mocked client, verify the filter + metric are correct."""

    def _make_provider(self, topology_mode='vm'):
        # Build without calling __init__ (which requires GCP SDK
        # + credentials) so tests stay unit-scoped.
        from integrations.adapters.gcp_monitoring import GcpCloudMonitoringProvider
        provider = GcpCloudMonitoringProvider.__new__(GcpCloudMonitoringProvider)
        provider._config = {'project_id': 'test-proj', 'topology_mode': topology_mode}
        provider._project_id = 'test-proj'
        provider._project_name = 'projects/test-proj'
        provider._topology_mode = topology_mode
        provider._client = MagicMock()
        provider._client.list_time_series.return_value = iter([])
        return provider

    def _install_monitoring_stub(self):
        """Stub google.cloud.monitoring_v3 so query_range doesn't import-fail."""
        stub = MagicMock()
        stub.TimeInterval = lambda d: d
        stub.ListTimeSeriesRequest.TimeSeriesView.FULL = 'FULL'
        stub.ListTimeSeriesRequest.TimeSeriesView.HEADERS = 'HEADERS'
        return patch.dict('sys.modules', {
            'google': MagicMock(),
            'google.cloud': MagicMock(),
            'google.cloud.monitoring_v3': stub,
        })

    def test_vm_mode_query_uses_vm_metric_and_filter(self):
        p = self._make_provider('vm')
        with self._install_monitoring_stub():
            p.query_range('node_cpu_seconds_total', {'instance_id': 'i-1'},
                          datetime.utcnow(), datetime.utcnow() + timedelta(minutes=5))
        p._client.list_time_series.assert_called_once()
        req = p._client.list_time_series.call_args.kwargs['request']
        self.assertIn('compute.googleapis.com/instance/cpu/utilization', req['filter'])
        self.assertIn('metric.labels.instance_id="i-1"', req['filter'])

    def test_k8s_mode_query_uses_gke_metric_and_resource_labels(self):
        p = self._make_provider('kubernetes')
        with self._install_monitoring_stub():
            p.query_range('node_cpu_seconds_total', {'service_name': 'checkout'},
                          datetime.utcnow(), datetime.utcnow() + timedelta(minutes=5))
        req = p._client.list_time_series.call_args.kwargs['request']
        self.assertIn('kubernetes.io/container/cpu/core_usage_time', req['filter'])
        self.assertIn('resource.labels.container_name="checkout"', req['filter'])


# ============================================================================
# Azure Monitor — K8s topology
# ============================================================================


class AzureDimFilterTest(TestCase):
    """Azure Container Insights dimension filter routing."""

    def setUp(self):
        from integrations.adapters.azure_metrics import AzureMonitorProvider
        self.Provider = AzureMonitorProvider

    def test_service_name_maps_to_controllerName(self):
        f = self.Provider._build_dim_filter({'service_name': 'checkout'})
        self.assertEqual(f, 'controllerName eq "checkout"')

    def test_multiple_labels_joined(self):
        f = self.Provider._build_dim_filter({
            'namespace': 'prod', 'pod': 'checkout-abc',
        })
        # Order is dict-iteration order — both must be present.
        self.assertIn('kubernetesNamespace eq "prod"', f)
        self.assertIn('podName eq "checkout-abc"', f)
        self.assertIn(' and ', f)

    def test_unknown_label_skipped(self):
        # 'random_label' isn't in the alias map.
        f = self.Provider._build_dim_filter({'random_label': 'x'})
        self.assertIsNone(f)

    def test_empty_labels_skipped(self):
        self.assertIsNone(self.Provider._build_dim_filter({}))
        self.assertIsNone(self.Provider._build_dim_filter({'service_name': ''}))

    def test_resource_uri_skipped(self):
        """resource_uri controls which resource to query — not a dim filter."""
        f = self.Provider._build_dim_filter({
            'resource_uri': '/subscriptions/x/y', 'service_name': 'api',
        })
        self.assertEqual(f, 'controllerName eq "api"')

    def test_double_quote_in_value_silently_dropped(self):
        """Defensive: never let a hostile value break out of the filter string."""
        f = self.Provider._build_dim_filter({'service_name': 'evil" or 1=1'})
        self.assertIsNone(f)


class AzureMetricNameMapTest(TestCase):

    def setUp(self):
        from integrations.adapters.azure_metrics import AzureMonitorProvider
        self.Provider = AzureMonitorProvider

    def test_vm_map_uses_vm_metrics(self):
        self.assertEqual(
            self.Provider.METRIC_NAME_MAP['node_cpu_seconds_total'],
            'Percentage CPU',
        )

    def test_k8s_map_uses_aks_container_insights(self):
        # AKS Container Insights uses lowercase-underscore names.
        self.assertEqual(
            self.Provider.K8S_METRIC_NAME_MAP['node_cpu_seconds_total'],
            'node_cpu_usage_percentage',
        )
        self.assertEqual(
            self.Provider.K8S_METRIC_NAME_MAP['container_cpu_usage_seconds_total'],
            'container_cpu_usage_percentage',
        )


class AzureQueryRangeTest(TestCase):
    """Full query_range with mocked client — verify metric + filter routing."""

    def _make_provider(self, topology_mode='vm'):
        from integrations.adapters.azure_metrics import AzureMonitorProvider
        provider = AzureMonitorProvider.__new__(AzureMonitorProvider)
        provider._config = {
            'default_resource_uri': '/subscriptions/x/y/resource',
            'topology_mode': topology_mode,
        }
        provider._default_resource = '/subscriptions/x/y/resource'
        provider._topology_mode = topology_mode
        provider._client = MagicMock()
        provider._client.query_resource.return_value = MagicMock(metrics=[])
        return provider

    def _install_azure_stub(self):
        stub_module = MagicMock()
        # Enum-like — mimics the class.
        stub_module.MetricAggregationType.AVERAGE = 'AVERAGE'
        return patch.dict('sys.modules', {
            'azure': MagicMock(),
            'azure.monitor': MagicMock(),
            'azure.monitor.query': stub_module,
        })

    def test_vm_mode_uses_vm_metric_name_no_filter(self):
        p = self._make_provider('vm')
        with self._install_azure_stub():
            p.query_range('node_cpu_seconds_total', {'instance_id': 'i-1'},
                          datetime.utcnow(), datetime.utcnow() + timedelta(minutes=5))
        kwargs = p._client.query_resource.call_args.kwargs
        self.assertEqual(kwargs['metric_names'], ['Percentage CPU'])
        # VM mode does NOT build a dim filter — kwarg absent.
        self.assertNotIn('filter', kwargs)

    def test_k8s_mode_uses_aks_metric_and_filter(self):
        p = self._make_provider('kubernetes')
        with self._install_azure_stub():
            p.query_range('node_cpu_seconds_total', {'service_name': 'checkout'},
                          datetime.utcnow(), datetime.utcnow() + timedelta(minutes=5))
        kwargs = p._client.query_resource.call_args.kwargs
        self.assertEqual(kwargs['metric_names'], ['node_cpu_usage_percentage'])
        self.assertEqual(kwargs['filter'], 'controllerName eq "checkout"')

    def test_k8s_mode_no_matching_labels_no_filter(self):
        """If we're in K8s mode but no K8s labels are supplied, don't pass
        an empty filter string — Azure would 400."""
        p = self._make_provider('kubernetes')
        with self._install_azure_stub():
            p.query_range('node_cpu_seconds_total', {'random': 'x'},
                          datetime.utcnow(), datetime.utcnow() + timedelta(minutes=5))
        kwargs = p._client.query_resource.call_args.kwargs
        self.assertNotIn('filter', kwargs)
