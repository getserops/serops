"""Azure behaviour found against a live AKS cluster with Container Insights
and a Log Analytics workspace (2026-11-01). SDK calls are mocked with the
shapes that came back."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from integrations.adapters.azure_logs import AzureLogAnalyticsProvider
from integrations.adapters.azure_metrics import AzureMonitorProvider
from integrations.base import LogSearchError
from integrations.schemas import LogQuery

T0 = datetime(2026, 11, 1, 6, 2, tzinfo=timezone.utc)
CL_COLUMNS = ['TimeGenerated', 'Computer', 'ContainerId', 'ContainerName', 'PodName', 'PodNamespace',
              'LogMessage', 'LogSource', 'LogLevel', 'KubernetesMetadata', '_ResourceId']


def _table(columns, rows):
    return SimpleNamespace(columns=columns, rows=rows)


def _logs(client):
    with patch('integrations.adapters.azure_logs._build_credential', return_value='C'), \
            patch('integrations.adapters.azure_logs._build_logs_client', return_value=client):
        return AzureLogAnalyticsProvider({'tenant_id': 't', 'client_id': 'c', 'password': 's', 'workspace_id': 'w'})


class ContainerLogV2QueryTest(SimpleTestCase):
    """ContainerLogV2 has no Properties and no SeverityLevel: the query
    that used them failed, and the failure read as "no logs"."""

    def kql(self, **kw):
        q = LogQuery(project='shop', environment='production', severity=['ERROR'],
                     project_rules=[('kubernetes.namespace_name', 'production')], **kw)
        return q.to_azure_kql(table='ContainerLogV2')

    def test_fields_are_columns_or_json_of_the_line(self):
        kql = self.kql(services=['payments'])
        self.assertNotIn('Properties', kql)
        self.assertNotIn('SeverityLevel', kql)
        self.assertIn('PodNamespace == "production"', kql)           # the rule, as a column
        self.assertIn('tostring(LogMessage["project_name"]) == "shop"', kql)
        self.assertIn('ContainerName in ("payments")', kql)

    def test_the_level_is_read_from_the_line(self):
        """Container Insights writes LogLevel info for "ERROR payments ..."."""
        kql = self.kql()
        self.assertIn('LogLevel in~ (', kql)
        self.assertIn('tostring(LogMessage) has_any (', kql)
        self.assertIn('"error"', kql)

    def test_apptraces_keeps_its_schema(self):
        kql = LogQuery(project='shop', severity=['ERROR'], services=['api']).to_azure_kql(table='AppTraces')
        self.assertIn('SeverityLevel >= 3', kql)
        self.assertIn('AppRoleName in ("api")', kql)


class ContainerLogV2ParseTest(SimpleTestCase):

    def parse(self, message, level='info'):
        row = [T0, 'aks-node', 'cid', 'payments', 'payments-1', 'production', message, 'stdout', level, None, '/sub/x']
        resp = SimpleNamespace(tables=[_table(CL_COLUMNS, [row])])
        [entry] = AzureLogAnalyticsProvider._parse_response(resp, 'ContainerLogV2', 10)
        return entry

    def test_a_plain_text_error_line(self):
        e = self.parse('2026-11-01T06:02:55Z ERROR payments GET /charge 503 pool exhausted')
        self.assertEqual((e.level, e.service), ('ERROR', 'payments'))
        self.assertIn('pool exhausted', e.message)
        self.assertEqual(e.labels['PodNamespace'], 'production')
        self.assertEqual(e.timestamp, T0)
        # The batch pipeline drops a log without an id: every line gets one.
        self.assertEqual(len(e.raw_id), 40)
        self.assertNotEqual(e.raw_id, self.parse('another line').raw_id)

    def test_a_json_line(self):
        e = self.parse({'level': 'warning', 'message': 'slow query', 'service_name': 'orders', 'environment': 'staging'})
        self.assertEqual((e.level, e.service, e.message), ('WARN', 'orders', 'slow query'))
        self.assertEqual(e.labels['environment'], 'staging')


class AzureLogSearchTest(SimpleTestCase):

    def test_a_refused_query_raises_instead_of_no_logs(self):
        client = MagicMock()
        client.query_workspace.side_effect = Exception('(Forbidden) InsufficientAccessError')
        with self.assertRaisesRegex(LogSearchError, 'Log Analytics Reader'):
            _logs(client).search('ContainerLogV2', LogQuery(project='shop'))

    def test_several_tables_are_queried_one_by_one(self):
        client = MagicMock()
        client.query_workspace.return_value = SimpleNamespace(tables=[])
        _logs(client).search('AppTraces,ContainerLogV2', LogQuery(project='shop'))
        queries = [c.kwargs['query'] for c in client.query_workspace.call_args_list]
        self.assertEqual([q.split('\n')[0] for q in queries], ['AppTraces', 'ContainerLogV2'])

    def test_get_indices_lists_the_tables_with_records(self):
        client = MagicMock()
        client.query_workspace.return_value = SimpleNamespace(tables=[_table(['SerOpsTable'], [['ContainerLogV2']])])
        self.assertEqual(_logs(client).get_indices(None), ['ContainerLogV2'])
        self.assertIn('union isfuzzy=true', client.query_workspace.call_args.kwargs['query'])

    def test_health_check_says_why(self):
        client = MagicMock()
        client.query_workspace.side_effect = Exception('AADSTS7000215: Invalid client secret provided')
        provider = _logs(client)
        self.assertFalse(provider.health_check())
        self.assertIn('client secret', provider.last_error)


def _metrics(metrics_client, logs_client=None, **config):
    with patch('integrations.adapters.azure_metrics._build_credential', return_value='C'), \
            patch('integrations.adapters.azure_metrics._build_metrics_client', return_value=metrics_client), \
            patch('integrations.adapters.azure_metrics._build_logs_client', return_value=logs_client):
        return AzureMonitorProvider({'tenant_id': 't', 'client_id': 'c', 'password': 's', **config})


AKS = '/subscriptions/s/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks'


class AksMetricsTest(SimpleTestCase):
    """AKS platform metrics are per node; SerOps compares services."""

    def test_with_a_workspace_each_container_is_a_series(self):
        logs = MagicMock()
        logs.query_workspace.return_value = SimpleNamespace(tables=[_table(
            ['TimeGenerated', 'service', 'value'],
            [[T0, 'checkout', 117972992.0], [T0, 'payments', 117903360.0]])])
        p = _metrics(MagicMock(), logs, topology_mode='kubernetes', workspace_id='w')
        series = p.query_range('node_memory_MemFree_bytes', {'project_name': 'shop', 'environment': 'production'},
                               T0 - timedelta(minutes=30), T0)
        self.assertEqual(sorted(s.labels['service_name'] for s in series), ['checkout', 'payments'])
        kql = logs.query_workspace.call_args.kwargs['query']
        self.assertIn('ObjectName == "K8SContainer"', kql)
        self.assertIn('Namespace in~ ("shop", "production")', kql)
        self.assertIn('max_of(lim - ws, 0.0)', kql)
        self.assertIn('lim > 0 and ws > 0', kql)  # a minute without its working set is left out

    def test_cpu_is_in_cores(self):
        logs = MagicMock()
        logs.query_workspace.return_value = SimpleNamespace(tables=[])
        p = _metrics(MagicMock(), logs, topology_mode='kubernetes', workspace_id='w', default_resource_uri=AKS)
        p.query_range('node_cpu_seconds_total', {}, T0 - timedelta(minutes=30), T0)
        self.assertIn('cpu / 1000000000.0', logs.query_workspace.call_args.kwargs['query'])
        self.assertFalse(p.cpu_is_percent)

    def test_without_a_workspace_the_cluster_in_the_right_units(self):
        client = MagicMock()

        def resource(resource_uri, metric_names, **kw):
            values = {'kube_node_status_allocatable_memory_bytes': 2922803200.0,
                      'node_memory_working_set_bytes': 2162905088.0,
                      'node_cpu_usage_millicores': 150.0}[metric_names[0]]
            return SimpleNamespace(metrics=[SimpleNamespace(name=metric_names[0], timeseries=[
                SimpleNamespace(metadata_values=[], data=[SimpleNamespace(timestamp=T0, average=values)])])])
        client.query_resource.side_effect = resource
        p = _metrics(client, topology_mode='kubernetes', default_resource_uri=AKS)
        [free] = p.query_range('node_memory_MemFree_bytes', {}, T0 - timedelta(minutes=30), T0)
        self.assertEqual(free.points[0].value, 2922803200.0 - 2162905088.0)
        [cpu] = p.query_range('node_cpu_seconds_total', {}, T0 - timedelta(minutes=30), T0)
        self.assertEqual((cpu.points[0].value, cpu.labels['host']), (0.15, 'aks'))
        # Allocatable memory has no node dimension: no node filter is sent.
        self.assertNotIn('filter', client.query_resource.call_args.kwargs)

    def test_aks_with_a_workspace_needs_no_resource_uri(self):
        p = _metrics(MagicMock(), MagicMock(), topology_mode='kubernetes', workspace_id='w')
        self.assertEqual(p.discover_hosts('acme'), [])

    def test_vm_cpu_is_a_percentage(self):
        p = _metrics(MagicMock(), default_resource_uri='/subscriptions/s/resourceGroups/rg/providers/'
                                                      'Microsoft.Compute/virtualMachines/vm')
        self.assertTrue(p.cpu_is_percent)


class AppTracesFromFilelogTest(SimpleTestCase):
    """What Application Insights stored for a plain-text line shipped by an
    OpenTelemetry filelog receiver: SeverityLevel 1, the level in the text."""

    def test_the_line_says_the_level_and_properties_keep_their_names(self):
        cols = ['TimeGenerated', 'Message', 'SeverityLevel', 'AppRoleName', 'Properties', 'ItemId']
        props = '{"k8s.container.name":"payments","k8s.namespace.name":"production"}'
        row = [T0, '2026-11-01T06:43:29Z ERROR payments GET /charge 503 pool exhausted', 1, 'payments', props, 'i1']
        [e] = AzureLogAnalyticsProvider._parse_response(SimpleNamespace(tables=[_table(cols, [row])]), 'AppTraces', 10)
        self.assertEqual((e.level, e.service), ('ERROR', 'payments'))
        self.assertEqual(e.labels['k8s.namespace.name'], 'production')

    def test_the_query_reaches_lines_without_a_severity(self):
        kql = LogQuery(severity=['ERROR']).to_azure_kql()
        self.assertIn('SeverityLevel >= 3 or (SeverityLevel <= 1 and Message has_any (', kql)
