"""Cloud adapters read the right data (phase 3 integration review, F5).

Each test pins one finding of the review (CL-n) with the response shapes the
vendors document. No live calls.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from integrations.adapters.gcp_monitoring import GcpCloudMonitoringProvider


def _gcp_stub():
    """A minimal google.cloud.monitoring_v3 for request building."""
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


WHEN = datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc)


def _gce_series(instance, value, user_labels=None, when=WHEN):
    """A Compute Engine series as the SDK returns it (resource gce_instance,
    no metric labels, the instance's labels under metadata.user_labels)."""
    point = SimpleNamespace(interval=SimpleNamespace(end_time=when),
                            value=SimpleNamespace(double_value=float(value), int64_value=0))
    return SimpleNamespace(
        metric=SimpleNamespace(labels={}),
        resource=SimpleNamespace(labels={'instance_id': instance, 'zone': 'europe-west1-b',
                                         'project_id': 'acme-prod'}),
        metadata=SimpleNamespace(system_labels={}, user_labels=user_labels or {}),
        points=[point])


def _vm_provider(responses):
    """``responses``: metric type → list of series."""
    p = GcpCloudMonitoringProvider.__new__(GcpCloudMonitoringProvider)
    p._config = {'project_id': 'acme-prod'}
    p._project_id, p._project_name, p._topology_mode = 'acme-prod', 'projects/acme-prod', 'vm'
    p.last_error = None

    def list_time_series(request):
        for gcp_type, series in responses.items():
            if f'metric.type="{gcp_type}"' in request['filter']:
                return iter(series)
        return iter([])
    p._client = MagicMock()
    p._client.list_time_series.side_effect = list_time_series
    return p


SIZE = 'compute.googleapis.com/instance/memory/balloon/ram_size'
USED = 'compute.googleapis.com/instance/memory/balloon/ram_used'
CPU = 'compute.googleapis.com/instance/cpu/utilization'
AGENT = 'agent.googleapis.com/memory/percent_used'
LABELS = {'organisation_name': 'Acme', 'project_name': 'shop', 'environment': 'production'}
GIB = 1024 ** 3


class GcpVmMetricsTest(SimpleTestCase):
    """CL-2: VM mode never returned a series. CL-3: memory inverted, CPU
    differentiated as a counter."""

    def test_scope_labels_are_not_sent_as_metric_labels(self):
        f = GcpCloudMonitoringProvider._build_filter(CPU, LABELS, 'vm')
        self.assertEqual(f, f'metric.type="{CPU}"')

    def test_cpu_is_a_percentage_and_the_pipeline_is_told(self):
        p = _vm_provider({CPU: [_gce_series('i-1', 0.9)]})
        with _gcp_stub():
            ts = p.query_range('node_cpu_seconds_total', LABELS, WHEN - timedelta(minutes=5), WHEN)
        self.assertEqual(ts[0].points[0].value, 90.0)
        self.assertTrue(p.cpu_is_percent)
        request = p._client.list_time_series.call_args.kwargs['request']
        self.assertNotIn('organisation_name', request['filter'])

    def test_available_memory_is_size_minus_used(self):
        p = _vm_provider({SIZE: [_gce_series('i-1', 8 * GIB)], USED: [_gce_series('i-1', 7.6 * GIB)]})
        with _gcp_stub():
            total = p.query_range('node_memory_MemTotal_bytes', LABELS, WHEN, WHEN)
            available = p.query_range('node_memory_MemAvailable_bytes', LABELS, WHEN, WHEN)
        self.assertEqual(total[0].points[0].value, 8 * GIB)
        self.assertAlmostEqual(available[0].points[0].value, 0.4 * GIB, delta=1)

    def test_pipeline_reports_95_percent_memory_and_90_percent_cpu(self):
        from integrations import metrics_processing as mp
        p = _vm_provider({SIZE: [_gce_series('i-1', 8 * GIB)], USED: [_gce_series('i-1', 7.6 * GIB)],
                          CPU: [_gce_series('i-1', 0.9)]})
        project = SimpleNamespace(organisation=SimpleNamespace(name='Acme'), cluster=None)
        with _gcp_stub(), patch('integrations.registry.IntegrationRegistry.get_metric_provider_for_org',
                                return_value=p):
            raw = mp.fetch_metrics_with_provider(WHEN - timedelta(minutes=5), WHEN, project_obj=project,
                                                 project_name_str='shop', environment_str='production')
        usage = mp.calculate_memory_usage(raw)
        self.assertEqual(len(usage), 1)
        self.assertAlmostEqual(usage[0]['value'], 95.0, delta=0.1)
        self.assertEqual([pt['value'] for pt in raw['cpu_usage_percent']], [90.0])

    def test_instances_carrying_the_project_label_narrow_the_result(self):
        p = _vm_provider({CPU: [_gce_series('i-shop', 0.5, {'project_name': 'shop'}),
                                _gce_series('i-crm', 0.7, {'project_name': 'crm'})]})
        with _gcp_stub():
            ts = p.query_range('node_cpu_seconds_total', LABELS, WHEN, WHEN)
        self.assertEqual([t.labels['instance'] for t in ts], ['i-shop'])

    def test_unlabelled_instances_are_all_kept(self):
        p = _vm_provider({CPU: [_gce_series('i-1', 0.5), _gce_series('i-2', 0.7)]})
        with _gcp_stub():
            ts = p.query_range('node_cpu_seconds_total', LABELS, WHEN, WHEN)
        self.assertEqual(len(ts), 2)

    def test_without_balloon_metrics_the_ops_agent_percentage_is_used(self):
        p = _vm_provider({AGENT: [_gce_series('i-1', 93.5)]})
        with _gcp_stub():
            total = p.query_range('node_memory_MemTotal_bytes', LABELS, WHEN, WHEN)
            available = p.query_range('node_memory_MemAvailable_bytes', LABELS, WHEN, WHEN)
        self.assertEqual(total[0].points[0].value, 100.0)
        self.assertEqual(available[0].points[0].value, 6.5)
        request = p._client.list_time_series.call_args.kwargs['request']
        self.assertIn('metric.labels.state="used"', request['filter'])


def _gcp_entry(payload, severity='DEFAULT', resource_type='cloud_run_revision', log_name='run.googleapis.com/stdout'):
    return SimpleNamespace(payload=payload, severity=severity, labels={}, timestamp=WHEN,
                           resource=SimpleNamespace(type=resource_type, labels={'service_name': 'orders'}),
                           log_name=f'projects/acme-prod/logs/{log_name}', trace='', insert_id='1')


class GcpJsonLevelTest(SimpleTestCase):
    """CL-4: the level of JSON logs was ignored, and severity queries left
    them out."""

    def test_cloud_run_json_error_is_read_as_error_with_its_msg(self):
        from integrations.adapters.gcp_logging import GcpCloudLoggingProvider
        e = GcpCloudLoggingProvider._to_log_entry(_gcp_entry({'level': 'error', 'msg': 'db timeout'}))
        self.assertEqual((e.level, e.message), ('ERROR', 'db timeout'))

    def test_pino_numeric_level_is_read(self):
        from integrations.adapters.gcp_logging import GcpCloudLoggingProvider
        e = GcpCloudLoggingProvider._to_log_entry(_gcp_entry({'level': 50, 'msg': 'payment failed'}))
        self.assertEqual(e.level, 'ERROR')

    def test_gke_stderr_json_info_is_not_an_error(self):
        from integrations.adapters.gcp_logging import GcpCloudLoggingProvider
        e = GcpCloudLoggingProvider._to_log_entry(_gcp_entry(
            {'level': 'info', 'msg': 'listening'}, severity='ERROR', resource_type='k8s_container', log_name='stderr'))
        self.assertEqual(e.level, 'INFO')

    def test_an_entry_with_a_real_severity_keeps_it(self):
        from integrations.adapters.gcp_logging import GcpCloudLoggingProvider
        e = GcpCloudLoggingProvider._to_log_entry(_gcp_entry({'level': 'info', 'msg': 'x'}, severity='ERROR'))
        self.assertEqual(e.level, 'ERROR')

    def test_severity_filter_fetches_json_levels(self):
        from integrations.schemas import LogQuery
        f = LogQuery(severity=['ERROR', 'WARNING']).to_gcp_filter()
        self.assertIn('severity<=INFO AND jsonPayload:*', f)
        self.assertIn('jsonPayload.level="error"', f)
        self.assertIn('jsonPayload.level="warn"', f)
        self.assertIn('jsonPayload.level=50', f)
        self.assertIn('jsonPayload.level=40', f)
        self.assertNotIn('jsonPayload.level="info"', f)
        self.assertNotIn('>=40', f)


def _resp(status=200, body=None, headers=None):
    r = MagicMock(status_code=status, ok=200 <= status < 300, headers=headers or {}, text='')
    r.json.return_value = body if body is not None else {}
    if status >= 400:
        from requests.exceptions import HTTPError
        r.raise_for_status.side_effect = HTTPError(response=r)
    return r


def _dd_event(i):
    return {'id': str(i), 'attributes': {'message': f'err {i}', 'status': 'error',
                                         'timestamp': f'2026-11-16T10:{i // 60 % 60:02d}:{i % 60:02d}Z'}}


class DatadogLogPagingTest(SimpleTestCase):
    """CL-5: only the first page (newest 1000) was read. CL-15: 429 was not
    retried."""

    def provider(self):
        from integrations.adapters.datadog_logs import DatadogLogProvider
        p = DatadogLogProvider({'site': 'datadoghq.eu', 'api_key': 'k', 'app_key': 'a'})
        p._session = MagicMock()
        return p

    def test_every_page_is_read_oldest_first(self):
        from integrations.schemas import LogQuery
        p = self.provider()
        p._session.post.side_effect = [
            _resp(body={'data': [_dd_event(i) for i in range(1000)], 'meta': {'page': {'after': 'c1'}}}),
            _resp(body={'data': [_dd_event(i) for i in range(1000, 1500)], 'meta': {}}),
        ]
        out = p.search('*', LogQuery(max_results=5000, time_range=(WHEN - timedelta(minutes=5), WHEN)))
        self.assertEqual(len(out), 1500)
        first, second = (c.kwargs['json'] for c in p._session.post.call_args_list)
        self.assertEqual(first['sort'], 'timestamp')
        self.assertEqual(second['page']['cursor'], 'c1')
        self.assertFalse(p.last_truncated)
        self.assertEqual(out[0].message, 'err 1499')     # newest first for the callers

    def test_at_the_cap_the_earliest_are_kept_and_truncation_is_flagged(self):
        from integrations.schemas import LogQuery
        p = self.provider()
        p._session.post.side_effect = [
            _resp(body={'data': [_dd_event(i) for i in range(1000)], 'meta': {'page': {'after': 'c1'}}}),
            _resp(body={'data': [_dd_event(i) for i in range(1000, 2000)], 'meta': {'page': {'after': 'c2'}}}),
        ]
        out = p.search('*', LogQuery(max_results=1500, time_range=(WHEN - timedelta(minutes=5), WHEN)))
        self.assertEqual(len(out), 1500)
        self.assertTrue(p.last_truncated)
        self.assertEqual(out[-1].message, 'err 0')
        self.assertEqual(p._session.post.call_args_list[1].kwargs['json']['page']['limit'], 500)

    def test_429_is_retried_after_the_rate_limit_reset(self):
        from integrations.adapters.datadog_logs import dd_request
        session = MagicMock()
        session.post.side_effect = [_resp(429, headers={'X-RateLimit-Reset': '1'}), _resp(body={'data': []})]
        waits = []
        resp = dd_request(session, 'post', 'u', sleep=waits.append, json={})
        self.assertEqual((resp.status_code, waits), (200, [1.0]))

    def test_the_wait_is_capped(self):
        from integrations.adapters.datadog_logs import dd_request
        session = MagicMock()
        session.get.side_effect = [_resp(429, headers={'X-RateLimit-Reset': '3500'}), _resp(503), _resp(503)]
        waits = []
        resp = dd_request(session, 'get', 'u', sleep=waits.append)
        self.assertEqual(resp.status_code, 503)        # the caller still sees the refusal
        self.assertEqual(waits[0], 10.0)
        self.assertEqual(len(waits), 2)


class DatadogMetricGapsTest(SimpleTestCase):
    """CL-9: a null point became 0, faking a 100 % memory spike."""

    def test_null_points_are_left_out(self):
        from integrations.adapters.datadog_metrics import DatadogMetricProvider
        t1, t2 = 1763287200000, 1763287260000
        ts = DatadogMetricProvider._parse_series(
            {'series': [{'pointlist': [[t1, 5.0], [t2, None]], 'scope': 'service:a'}]}, 'm')
        self.assertEqual([p.value for p in ts[0].points], [5.0])


def _table(columns, rows):
    return SimpleNamespace(columns=columns, rows=rows)


class AzureTablesTest(SimpleTestCase):
    """CL-6: exceptions and failed calls were never read. CL-18: the
    documented Syslog / ContainerLog tables failed every query."""

    def test_discovery_looks_for_exceptions_and_failed_calls(self):
        from integrations.adapters.azure_logs import AzureLogAnalyticsProvider
        p = AzureLogAnalyticsProvider.__new__(AzureLogAnalyticsProvider)
        p._default_table, p._workspace_id = 'AppTraces', 'w'
        p._client = MagicMock()
        p._client.query_workspace.return_value = SimpleNamespace(
            tables=[_table(['SerOpsTable'], [['AppTraces'], ['AppExceptions']])])
        self.assertEqual(p.get_indices(None), ['AppExceptions', 'AppTraces'])
        query = p._client.query_workspace.call_args.kwargs['query']
        for table in ('AppExceptions', 'AppRequests', 'AppDependencies'):
            self.assertIn(table, query)
        self.assertNotIn('Syslog', query)

    def test_exceptions_kql_has_no_severity_filter_and_valid_columns(self):
        from integrations.schemas import LogQuery
        kql = LogQuery(project='shop', severity=['ERROR', 'WARNING']).to_azure_kql('AppExceptions')
        self.assertNotIn('SeverityLevel >=', kql)
        self.assertIn('tostring(Properties["project_name"]) == "shop"', kql)

    def test_failed_requests_only(self):
        from integrations.schemas import LogQuery
        kql = LogQuery(severity=['ERROR']).to_azure_kql('AppDependencies')
        self.assertIn('| where Success == false', kql)

    def test_exception_row_is_an_error_naming_the_exception(self):
        from integrations.adapters.azure_logs import AzureLogAnalyticsProvider
        cols = ['TimeGenerated', 'ProblemId', 'OuterType', 'OuterMessage', 'InnermostType', 'InnermostMessage',
                'SeverityLevel', 'AppRoleName', 'OperationId', 'Properties']
        row = [WHEN, 'SqlException at Orders.Save', 'Microsoft.Data.SqlClient.SqlException',
               'Execution Timeout Expired', 'System.ComponentModel.Win32Exception', 'The wait operation timed out',
               3, 'orders-api', 'op1', '{"environment": "production"}']
        e = AzureLogAnalyticsProvider._parse_response(SimpleNamespace(tables=[_table(cols, [row])]),
                                                      'AppExceptions', 10)[0]
        self.assertEqual((e.level, e.service), ('ERROR', 'orders-api'))
        self.assertIn('Microsoft.Data.SqlClient.SqlException: Execution Timeout Expired', e.message)
        self.assertIn('The wait operation timed out', e.message)
        self.assertTrue(e.raw_id)
        self.assertEqual(e.labels['environment'], 'production')

    def test_failed_dependency_row(self):
        from integrations.adapters.azure_logs import AzureLogAnalyticsProvider
        cols = ['TimeGenerated', 'Target', 'DependencyType', 'Name', 'ResultCode', 'DurationMs', 'Success', 'AppRoleName']
        row = [WHEN, 'payments.internal', 'HTTP', 'POST /charge', '503', 30012.4, False, 'checkout']
        e = AzureLogAnalyticsProvider._parse_response(SimpleNamespace(tables=[_table(cols, [row])]),
                                                      'AppDependencies', 10)[0]
        self.assertEqual(e.level, 'ERROR')
        self.assertEqual(e.message, 'Call to payments.internal (HTTP POST /charge) failed: 503 after 30012 ms')

    def test_syslog_kql_uses_only_syslog_columns(self):
        from integrations.schemas import LogQuery
        kql = LogQuery(project='shop', severity=['ERROR']).to_azure_kql('Syslog')
        self.assertNotIn('Properties', kql)
        self.assertNotIn('SeverityLevel >=', kql)
        self.assertIn('SeverityLevel in~ (', kql)
        self.assertIn('"err"', kql)

    def test_syslog_row(self):
        from integrations.adapters.azure_logs import AzureLogAnalyticsProvider
        cols = ['TimeGenerated', 'Computer', 'ProcessName', 'SeverityLevel', 'SyslogMessage', 'Facility']
        row = [WHEN, 'vm-1', 'nginx', 'err', 'upstream timed out', 'daemon']
        e = AzureLogAnalyticsProvider._parse_response(SimpleNamespace(tables=[_table(cols, [row])]), 'Syslog', 10)[0]
        self.assertEqual((e.level, e.message, e.service, e.host), ('ERROR', 'upstream timed out', 'nginx', 'vm-1'))

    def test_legacy_container_log_kql_and_row(self):
        from integrations.adapters.azure_logs import AzureLogAnalyticsProvider
        from integrations.schemas import LogQuery
        kql = LogQuery(severity=['ERROR']).to_azure_kql('ContainerLog')
        self.assertNotIn('Properties', kql)
        self.assertIn('LogEntry has_any', kql)
        cols = ['TimeGenerated', 'Computer', 'ContainerID', 'Name', 'LogEntry', 'LogEntrySource']
        row = [WHEN, 'aks-1', 'c1', 'payments', '{"level":"error","msg":"card declined upstream"}', 'stdout']
        e = AzureLogAnalyticsProvider._parse_response(SimpleNamespace(tables=[_table(cols, [row])]),
                                                      'ContainerLog', 10)[0]
        self.assertEqual((e.level, e.message, e.service), ('ERROR', 'card declined upstream', 'payments'))


class AzureMetricGrainsTest(SimpleTestCase):
    """CL-8: grains without an aggregate became 0."""

    def test_empty_grains_are_left_out(self):
        from integrations.adapters.azure_metrics import AzureMonitorProvider
        points = [SimpleNamespace(timestamp=WHEN, average=90.0, total=None, count=None),
                  SimpleNamespace(timestamp=WHEN + timedelta(minutes=1), average=None, total=None, count=None)]
        response = SimpleNamespace(metrics=[SimpleNamespace(timeseries=[SimpleNamespace(metadata_values=[],
                                                                                        data=points)])])
        ts = AzureMonitorProvider._parse_metrics(response, 'cpu')
        self.assertEqual([p.value for p in ts[0].points], [90.0])


class CloudWatchPagingTest(SimpleTestCase):
    """CL-13: log groups past the first 50 were dropped. CL-12: metric
    series were capped at 1000 before scoping."""

    def log_provider(self):
        from integrations.adapters.cloudwatch_logs import CloudWatchLogProvider
        with patch('integrations.adapters.cloudwatch_logs._get_boto3_client') as factory:
            factory.return_value = MagicMock()
            p = CloudWatchLogProvider(config={'aws_region': 'eu-central-1', 'username': 'k', 'password': 's'})
        return p

    def test_discovery_follows_next_token(self):
        p = self.log_provider()
        pages = {None: (['/ecs/shop-%d' % i for i in range(50)], 't1'),
                 't1': (['/ecs/shop-%d' % i for i in range(50, 100)], 't2'),
                 't2': (['/ecs/shop-%d' % i for i in range(100, 120)], None)}

        def describe(limit, nextToken=None, **kw):
            if kw.get('logGroupNamePattern') != 'shop':
                return {'logGroups': []}
            names, token = pages[nextToken]
            return {'logGroups': [{'logGroupName': n} for n in names], **({'nextToken': token} if token else {})}
        p.client.describe_log_groups.side_effect = describe
        project = MagicMock()
        project.name = 'shop'
        self.assertEqual(len(p.get_indices(project)), 120)

    def test_more_than_50_groups_run_as_several_queries(self):
        from integrations.schemas import LogQuery
        p = self.log_provider()
        p.client.start_query.return_value = {'queryId': 'q'}
        p.client.get_query_results.return_value = {'status': 'Complete', 'results': []}
        groups = ','.join('/ecs/shop-%d' % i for i in range(80))
        p.search(groups, LogQuery(time_range=(WHEN - timedelta(minutes=5), WHEN)))
        calls = p.client.start_query.call_args_list
        self.assertEqual([len(c.kwargs['logGroupNames']) for c in calls], [50, 30])

    def test_metric_series_are_scoped_while_paging(self):
        from integrations.adapters.cloudwatch_metrics import K8S_METRIC_MAP, CloudWatchMetricProvider
        with patch('integrations.adapters.cloudwatch_metrics._get_boto3_client') as factory:
            factory.return_value = MagicMock()
            p = CloudWatchMetricProvider(config={'aws_region': 'eu-central-1', 'username': 'k', 'password': 's',
                                                 'topology_mode': 'kubernetes'})
        mapping = K8S_METRIC_MAP['node_cpu_seconds_total']
        host = mapping['host']
        other = [{'Dimensions': [{'Name': 'ClusterName', 'Value': 'c%d' % (i % 3)},
                                 {'Name': 'Namespace', 'Value': 'ns%d' % i}, {'Name': host, 'Value': 's%d' % i}]}
                 for i in range(1200)]
        ours = [{'Dimensions': [{'Name': 'ClusterName', 'Value': 'c1'}, {'Name': 'Namespace', 'Value': 'shop'},
                                {'Name': host, 'Value': 'checkout'}]}]
        seen = {}

        def paginate(**kw):
            seen.update(kw)
            return [{'Metrics': other[:500]}, {'Metrics': other[500:1000]}, {'Metrics': other[1000:] + ours}]
        p.client.get_paginator.return_value.paginate.side_effect = paginate
        series = p._series(mapping, {'project_name': 'shop'}, recent=True)
        self.assertEqual([d[host] for d in series], ['checkout'])
        self.assertEqual(seen.get('RecentlyActive'), 'PT3H')
