"""
Google Cloud on GKE, as a real cluster writes it (GKE live test, 2026-11-05:
Online Boutique on GKE 1.36, read with a Logs Viewer + Monitoring Viewer key).

Before these fixes SerOps found no log and no metric of that cluster: GKE logs
carry no service_name or project_name, every metric query raised on the
SDK's datetimes, and a Google key did not fit the integration's password.
The entries and series below copy the shapes Google returned.
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from integrations.adapters.gcp_logging import GcpCloudLoggingProvider, _health_reason
from integrations.adapters.gcp_monitoring import GcpCloudMonitoringProvider, _point_time
from integrations.schemas import LogQuery


def gke_entry(message, container='server', app='cartservice', severity='ERROR', stream='stderr',
              namespace='boutique', node='gke-serops-gke-default-pool-5406b72d-zrcf'):
    """A container log line as Cloud Logging returns it for GKE."""
    return SimpleNamespace(
        payload=message, severity=severity, trace='', insert_id='x1',
        log_name=f'projects/serops-test/logs/{stream}',
        timestamp=datetime(2026, 11, 5, 15, 30, tzinfo=timezone.utc),
        labels={'compute.googleapis.com/resource_name': node, 'k8s-pod/app': app,
                'logging.gke.io/top_level_controller_name': app,
                'logging.gke.io/top_level_controller_type': 'Deployment',
                'k8s-pod/pod-template-hash': '8476c55bcc'},
        resource=SimpleNamespace(type='k8s_container', labels={
            'cluster_name': 'serops-gke', 'container_name': container, 'location': 'europe-west1-b',
            'namespace_name': namespace, 'pod_name': f'{app}-8476c55bcc-5x9zv', 'project_id': 'serops-test'}),
    )


def log_provider(client):
    with patch('integrations.adapters.gcp_logging._load_credentials', return_value='CREDS'), \
            patch('integrations.adapters.gcp_logging._build_client', return_value=client):
        return GcpCloudLoggingProvider({'project_id': 'serops-test', 'password': '{}'})


class GkeLogEntryTest(SimpleTestCase):
    def test_service_host_and_namespace_come_from_gke(self):
        entry = GcpCloudLoggingProvider._to_log_entry(gke_entry('level=error msg="redis: OOM command not allowed"'))
        self.assertEqual(entry.service, 'cartservice')       # not the container, "server"
        self.assertEqual(entry.host, 'gke-serops-gke-default-pool-5406b72d-zrcf')
        self.assertEqual(entry.labels['namespace'], 'boutique')

    def test_a_stderr_line_keeps_its_own_level(self):
        # GKE rates every plain stderr line ERROR.
        info = GcpCloudLoggingProvider._to_log_entry(gke_entry('2026-11-05T15:30:01Z info exporter started'))
        error = GcpCloudLoggingProvider._to_log_entry(gke_entry('2026-11-05T15:30:01Z error exporting failed'))
        self.assertEqual(info.level, 'INFO')
        self.assertEqual(error.level, 'ERROR')

    def test_a_stdout_line_keeps_its_own_level(self):
        # GKE rates every plain stdout line INFO (GKE 1.36 validation,
        # 2026-11-12: a bad rollout's "ERROR ... 503 pool exhausted" lines).
        line = ('2026-11-12T22:15:17.204Z ERROR payments GET /charge 503 pool exhausted: '
                'timeout acquiring database connection (pool_size=2, in_use=2)')
        error = GcpCloudLoggingProvider._to_log_entry(gke_entry(line, app='payments', severity='INFO', stream='stdout'))
        info = GcpCloudLoggingProvider._to_log_entry(gke_entry(
            '2026-11-12T22:15:17.240Z INFO payments GET /charge 200 152ms', app='payments',
            severity='INFO', stream='stdout'))
        self.assertEqual(error.level, 'ERROR')
        self.assertEqual(info.level, 'INFO')

    def test_a_stdout_line_rated_above_info_keeps_googles_severity(self):
        entry = gke_entry('disk almost full', severity='WARNING', stream='stdout')
        self.assertEqual(GcpCloudLoggingProvider._to_log_entry(entry).level, 'WARN')

    def test_a_structured_line_keeps_googles_severity(self):
        entry = gke_entry({'message': 'payment failed', 'severity': 'ERROR'})
        self.assertEqual(GcpCloudLoggingProvider._to_log_entry(entry).level, 'ERROR')

    def test_an_explicit_service_name_label_still_wins(self):
        entry = gke_entry('boom')
        entry.labels['service_name'] = 'cart-api'
        self.assertEqual(GcpCloudLoggingProvider._to_log_entry(entry).service, 'cart-api')

    def test_without_pod_labels_the_container_names_the_service(self):
        entry = gke_entry('boom', container='redis', app=None)
        entry.labels = {}
        self.assertEqual(GcpCloudLoggingProvider._to_log_entry(entry).service, 'redis')


class GkeLogQueryTest(SimpleTestCase):
    def test_a_project_matches_the_namespace_of_its_name(self):
        f = LogQuery(project='Boutique').to_gcp_filter()
        self.assertIn('labels.project_name="Boutique"', f)
        self.assertIn('resource.labels.namespace_name="boutique"', f)

    def test_a_namespace_rule_targets_the_resource(self):
        f = LogQuery(project='shop', project_rules=[('namespace', 'shop-prod'), ('k8s-pod/team', 'pay')]).to_gcp_filter()
        self.assertIn('resource.labels.namespace_name="shop-prod"', f)
        self.assertIn('labels."k8s-pod/team"="pay"', f)

    def test_an_environment_matches_its_namespace(self):
        f = LogQuery(project='shop', environment='staging').to_gcp_filter()
        self.assertIn('resource.labels.namespace_name="staging"', f)

    def test_stream_rated_stderr_lines_are_left_out_of_errors(self):
        f = LogQuery(severity=['WARN', 'ERROR']).to_gcp_filter()
        self.assertIn('NOT (resource.type="k8s_container" AND logName:"/logs/stderr"', f)
        self.assertIn('(severity<=INFO AND textPayload:* AND (', f)   # a stdout line naming ERROR is kept
        self.assertIn('textPayload:"ERROR"', f)
        self.assertNotIn('textPayload:"INFO"', f)


class GkeLogSearchTest(SimpleTestCase):
    def test_comma_joined_locations_are_not_one_log_name(self):
        client = MagicMock()
        client.list_entries.return_value = iter([])
        log_provider(client).search('projects/serops-test/logs/stdout,projects/serops-test/logs/stderr,'
                                    'projects/serops-test/logs/cloudaudit.googleapis.com%2Factivity', LogQuery())
        f = client.list_entries.call_args.kwargs['filter_']
        self.assertIn('(logName="projects/serops-test/logs/stdout" OR logName="projects/serops-test/logs/stderr")', f)
        self.assertNotIn('cloudaudit', f)
        self.assertNotIn(',', f.split(' AND ')[0])

    def test_no_location_reads_every_log_but_audit(self):
        client = MagicMock()
        client.list_entries.return_value = iter([gke_entry('x')])
        entries = log_provider(client).search('', LogQuery(project='boutique'))
        self.assertTrue(client.list_entries.call_args.kwargs['filter_'].startswith(
            'NOT logName:"cloudaudit.googleapis.com" AND'))
        self.assertEqual(entries[0].service, 'cartservice')


class GkeMetricsTest(SimpleTestCase):
    def provider(self, series):
        p = GcpCloudMonitoringProvider.__new__(GcpCloudMonitoringProvider)
        p._config = {'project_id': 'serops-test', 'topology_mode': 'kubernetes'}
        p._project_id, p._project_name, p._topology_mode = 'serops-test', 'projects/serops-test', 'kubernetes'
        p._client = MagicMock()
        p._client.list_time_series.return_value = iter(series)
        return p

    @staticmethod
    def series(workload, value, when):
        point = SimpleNamespace(interval=SimpleNamespace(end_time=when),
                                value=SimpleNamespace(double_value=value, int64_value=0))
        return SimpleNamespace(metric=SimpleNamespace(labels={}), resource=SimpleNamespace(labels={}),
                               metadata=SimpleNamespace(system_labels={'top_level_controller_name': workload}),
                               points=[point])

    @staticmethod
    def stub():
        class Aggregation(dict):
            Aligner = SimpleNamespace(ALIGN_RATE='ALIGN_RATE', ALIGN_MEAN='ALIGN_MEAN')
            Reducer = SimpleNamespace(REDUCE_SUM='REDUCE_SUM', REDUCE_MAX='REDUCE_MAX')
        m = MagicMock()
        m.TimeInterval = lambda d: d
        m.Aggregation = Aggregation
        m.ListTimeSeriesRequest.TimeSeriesView.FULL = 'FULL'
        cloud = MagicMock()
        cloud.monitoring_v3 = m
        return patch.dict('sys.modules', {'google': MagicMock(), 'google.cloud': cloud,
                                          'google.cloud.monitoring_v3': m})

    # The SDK's DatetimeWithNanoseconds is a datetime subclass.
    when = datetime(2026, 11, 5, 16, 28, 30, tzinfo=timezone.utc)
    labels = {'organisation_name': 'GKE Test', 'project_name': 'boutique', 'environment': 'production'}

    def test_cpu_is_a_rate_per_workload_in_the_projects_namespaces(self):
        p = self.provider([self.series('cartservice', 0.0044, self.when)])
        with self.stub():
            ts = p.query_range('node_cpu_seconds_total', self.labels, self.when - timedelta(hours=1), self.when)
        req = p._client.list_time_series.call_args.kwargs['request']
        self.assertIn('resource.labels.namespace_name = one_of("boutique", "production")', req['filter'])
        self.assertNotIn('organisation_name', req['filter'])     # no GKE metric carries it
        self.assertEqual(req['aggregation']['per_series_aligner'], 'ALIGN_RATE')
        self.assertEqual(req['aggregation']['group_by_fields'], ['metadata.system_labels.top_level_controller_name'])
        self.assertEqual(ts[0].labels['service_name'], 'cartservice')
        self.assertEqual(ts[0].points[0].value, 0.0044)
        self.assertEqual(ts[0].points[0].timestamp, datetime(2026, 11, 5, 16, 28, 30))

    def test_memory_is_the_share_of_the_limit_as_total_and_available(self):
        p = self.provider([self.series('cartservice', 0.4068, self.when)])
        with self.stub():
            available = p.query_range('node_memory_MemAvailable_bytes', self.labels, self.when, self.when)
        p._client.list_time_series.return_value = iter([self.series('cartservice', 0.4068, self.when)])
        with self.stub():
            total = p.query_range('node_memory_MemTotal_bytes', self.labels, self.when, self.when)
        self.assertEqual(available[0].points[0].value, 59.32)
        self.assertEqual(total[0].points[0].value, 100.0)
        req = p._client.list_time_series.call_args.kwargs['request']
        self.assertIn('kubernetes.io/container/memory/limit_utilization', req['filter'])

    def test_point_time_reads_sdk_datetimes_and_protobuf_timestamps(self):
        self.assertEqual(_point_time(self.when), datetime(2026, 11, 5, 16, 28, 30))
        legacy = SimpleNamespace(seconds=int(self.when.timestamp()), nanos=0)
        self.assertEqual(_point_time(legacy), datetime(2026, 11, 5, 16, 28, 30))

    def test_hosts_are_the_projects_pods_only(self):
        p = self.provider([])
        with self.stub():
            p.discover_hosts('GKE Test', project='boutique', environment='production')
        f = p._client.list_time_series.call_args.kwargs['request']['filter']
        self.assertIn('resource.labels.namespace_name = one_of("boutique", "production")', f)


class GcpHealthReasonTest(SimpleTestCase):
    def test_permission_denied_names_the_project_and_role(self):
        reason = _health_reason(Exception('403 Permission denied on resource project serops-test-513806'),
                                'serops-test-513806', 'Logs Viewer')
        self.assertIn('serops-test-513806', reason)
        self.assertIn('Logs Viewer', reason)


class GcpKeyFitsTest(TestCase):
    def test_a_google_key_is_saved_and_read_back(self):
        from Organisations.models import Organisations
        from integrations.models import ObservabilityIntegration
        key = json.dumps({'type': 'service_account', 'project_id': 'serops-test',
                          'private_key': '-----BEGIN PRIVATE KEY-----\n' + 'A' * 1700 + '\n-----END PRIVATE KEY-----\n',
                          'client_email': 'serops-reader@serops-test.iam.gserviceaccount.com'})
        self.assertGreater(len(key), 1000)
        org = Organisations.objects.create(name='GcpKeyOrg')
        integration = ObservabilityIntegration(organisation=org, provider='gcp', display_name='Google Cloud',
                                               capabilities=['logs', 'metrics'],
                                               extra_config={'project_id': 'serops-test'})
        integration.set_password(key)
        integration.save()
        integration.refresh_from_db()
        self.assertEqual(integration.get_password(), key)
