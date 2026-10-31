"""
Logs as real shippers write them reach SerOps intact.

SerOps used to understand only its own record shape: Elastic Common Schema
documents (Filebeat, Elastic Agent) crashed the batch or lost their level,
WARN and lowercase levels were never fetched, logs in ``logs-*`` or
``filebeat-*`` were never searched, CloudWatch logs all read as INFO with no
service, and logs tagged ``prod`` never matched ``production``. Each case
below is a record shape a real setup produces.
"""
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.test import SimpleTestCase

from integrations.adapters.cloudwatch_logs import CloudWatchLogProvider
from integrations.adapters.datadog_logs import DatadogLogProvider
from integrations.adapters.elasticsearch import discover_log_indices, parse_index_patterns
from integrations.adapters.loki import _loki_level
from integrations.field_aliases import environment_values, lookup
from integrations.ingestion import is_log_matching_environment
from integrations.schemas import LogEntry, LogQuery, level_from_value

FILEBEAT_ECS = {  # Filebeat / Elastic Agent, Kubernetes autodiscover
    '@timestamp': '2026-10-27T10:00:00.000Z',
    'message': 'payment gateway timeout after 30s',
    'log': {'level': 'error', 'file': {'path': '/var/log/containers/checkout.log'}},
    'service': {'name': 'checkout', 'environment': 'production'},
    'host': {'name': 'node-1'},
    'kubernetes': {'namespace': 'shop', 'labels': {'app': 'checkout'}, 'container': {'name': 'checkout'}},
}
OTEL_ES_EXPORTER = {  # OpenTelemetry Collector elasticsearch exporter
    '@timestamp': '2026-10-27T10:00:00Z',
    'body': 'cart service unreachable',
    'severity_text': 'WARN',
    'severity_number': 13,
    'service.name': 'cart',
    'deployment.environment.name': 'prod',
}
# The same exporter (contrib 0.111, ``mapping: {mode: otel}``, as Elastic
# recommends) into Elasticsearch 8.15: captured from the journey suite's
# "messy shop". Message in body_text, service and environment under
# resource.attributes.
OTEL_ES_EXPORTER_OTEL_MODE = {
    '@timestamp': '2026-10-28T14:05:32.153031168Z',
    'body_text': 'GET / 502 upstream checkout failed after 1003ms',
    'severity_text': 'ERROR',
    'severity_number': 17,
    'resource': {'attributes': {'deployment.environment.name': 'production', 'service.name': 'frontend',
                                'service.namespace': 'shop', 'service.version': '1.0.0'}},
    'scope': {'name': 'shop'},
}
FLUENT_BIT_K8S = {  # Fluent Bit kubernetes filter, Docker JSON log line
    '@timestamp': '2026-10-27T10:00:00Z',
    'log': 'Error: connection refused to redis:6379\n',
    'level': 'Warning',
    'kubernetes': {'namespace_name': 'shop', 'container_name': 'cart-api', 'labels': {'app': 'cart'}},
}
PINO = {'time': '2026-10-27T10:00:00Z', 'level': 50, 'msg': 'order failed', 'service_name': 'orders'}
UNSTRUCTURED = {'@timestamp': '2026-10-27T10:00:00Z',
                'message': '2026-10-27 10:00:00 ERROR [main] db pool exhausted', 'service_name': 'api'}
NGINX = {'@timestamp': '2026-10-27T10:00:00Z', 'message': 'GET / 200', 'status': 200, 'service_name': 'web'}


class ShipperRecordsParseTest(SimpleTestCase):
    def parse(self, doc):
        return LogEntry.from_es_hit({'_id': 'x', '_source': doc})

    def test_filebeat_ecs(self):
        e = self.parse(FILEBEAT_ECS)
        self.assertEqual((e.level, e.service, e.host), ('ERROR', 'checkout', 'node-1'))
        e.service.lower()  # used to be a dict: AttributeError crashed the batch

    def test_opentelemetry_exporter(self):
        e = self.parse(OTEL_ES_EXPORTER)
        self.assertEqual((e.level, e.service, e.message), ('WARN', 'cart', 'cart service unreachable'))

    def test_opentelemetry_exporter_otel_mode(self):
        e = self.parse(OTEL_ES_EXPORTER_OTEL_MODE)
        self.assertEqual((e.level, e.service), ('ERROR', 'frontend'))
        self.assertEqual(e.message, 'GET / 502 upstream checkout failed after 1003ms')
        self.assertTrue(is_log_matching_environment(e, 'production'))
        self.assertFalse(is_log_matching_environment(e, 'staging'))
        dsl = str(LogQuery(environment='production', severity=['ERROR']).to_es_dsl())
        self.assertIn('resource.attributes.deployment.environment.name', dsl)

    def test_on_kubernetes_the_host_is_the_node_not_the_shipper(self):
        doc = dict(FILEBEAT_ECS, host={'name': 'filebeat-x7k2p'}, kubernetes={'node': {'name': 'node-c'}})
        self.assertEqual(self.parse(doc).host, 'node-c')

    def test_a_stored_ecs_record_keeps_the_service_name(self):
        source = self.parse(FILEBEAT_ECS).to_legacy_dict()['_source']
        self.assertEqual(source['service'], 'checkout')  # was the whole ECS service object
        self.assertEqual(source['host'], 'node-1')
        self.assertEqual(source['environment'], 'production')

    def test_errors_differing_only_by_a_duration_collapse(self):
        from integrations.ingestion import deduplicate_logs
        logs = [LogEntry.from_es_hit({'_id': str(i), '_source': {
            '@timestamp': f'2026-10-28T14:05:{i:02d}Z', 'level': 'error', 'service_name': 'checkout',
            'message': f'GET /checkout 502 upstream payments failed after {1000 + i}ms'}}) for i in range(20)]
        self.assertEqual(len(deduplicate_logs(logs)), 1)

    def test_fluent_bit_kubernetes(self):
        e = self.parse(FLUENT_BIT_K8S)
        self.assertEqual((e.level, e.service), ('WARN', 'cart'))
        self.assertIn('connection refused', e.message)

    def test_pino_numeric_level(self):
        e = self.parse(PINO)
        self.assertEqual((e.level, e.service, e.message), ('ERROR', 'orders', 'order failed'))

    def test_level_read_from_an_unstructured_line(self):
        self.assertEqual(self.parse(UNSTRUCTURED).level, 'ERROR')

    def test_http_status_is_not_a_level(self):
        self.assertEqual(self.parse(NGINX).level, 'INFO')

    def test_numeric_scales(self):
        self.assertEqual(level_from_value('severity_number', 17), 'ERROR')   # OpenTelemetry
        self.assertEqual(level_from_value('severity_number', 9), 'INFO')
        self.assertEqual(level_from_value('severity', 4), 'WARN')            # syslog
        self.assertEqual(level_from_value('severity', 3), 'ERROR')
        self.assertEqual(level_from_value('level', 40), 'WARN')              # Pino
        self.assertEqual(level_from_value('level', '60'), 'ERROR')
        self.assertEqual(level_from_value('level', 'emerg'), 'ERROR')
        self.assertEqual(level_from_value('level', True), 'INFO')

    def test_nested_and_flat_lookups(self):
        self.assertEqual(lookup({'a': {'b.c': 1}}, 'a.b.c'), 1)
        self.assertEqual(lookup({'app.kubernetes.io/name': 'x'}, 'app.kubernetes.io/name'), 'x')
        self.assertIsNone(lookup({'a': 'flat'}, 'a.b'))


class DatadogEventParseTest(SimpleTestCase):
    def test_tags_and_body_attributes(self):
        event = {'id': '1', 'attributes': {
            'timestamp': '2026-10-27T10:00:00Z', 'message': 'charge declined', 'status': 'info',
            'service': 'billing', 'host': 'i-123',
            'tags': ['env:prod', 'project_name:shop', 'kube_namespace:shop'],
            'attributes': {'level': 'error', 'dd': {'trace_id': '42'}}}}
        e = DatadogLogProvider._event_to_log_entry(event)
        self.assertEqual((e.level, e.service, e.host, e.trace_id), ('ERROR', 'billing', 'i-123', '42'))
        self.assertEqual((e.labels['env'], e.labels['project_name']), ('prod', 'shop'))
        self.assertTrue(is_log_matching_environment(e, 'production'))

    def test_status_wins_when_set(self):
        event = {'id': '1', 'attributes': {'message': 'disk almost full', 'status': 'warn', 'tags': []}}
        self.assertEqual(DatadogLogProvider._event_to_log_entry(event).level, 'WARN')


class CloudWatchTest(SimpleTestCase):
    def provider(self, **config):
        with mock.patch('integrations.adapters.cloudwatch_logs._get_boto3_client') as client:
            p = CloudWatchLogProvider({'aws_region': 'us-east-1', **config})
        p.client = client.return_value
        return p

    def test_json_event_fields_come_from_the_body(self):
        rows = [[{'field': '@timestamp', 'value': '2026-10-27 10:00:00.000'},
                 {'field': '@message', 'value': '{"level":"warn","service_name":"api","environment":"prod",'
                                                '"message":"slow query 3s"}'},
                 {'field': '@logStream', 'value': 'ecs/api/abc'},
                 {'field': '@log', 'value': '123456789012:/ecs/shop'}]]
        [e] = CloudWatchLogProvider._parse_results(rows, '/ecs/shop')
        self.assertEqual((e.level, e.service, e.message), ('WARN', 'api', 'slow query 3s'))
        self.assertEqual(e.labels['log_group'], '/ecs/shop')
        self.assertTrue(is_log_matching_environment(e, 'production'))

    def test_plain_line_level_from_text_and_service_from_stream(self):
        rows = [[{'field': '@message', 'value': '[ERROR] payment failed'},
                 {'field': '@logStream', 'value': 'checkout/web/123'}]]
        [e] = CloudWatchLogProvider._parse_results(rows, '/ecs/shop')
        self.assertEqual((e.level, e.service), ('ERROR', 'checkout'))

    def test_several_log_groups_are_passed_as_a_list(self):
        p = self.provider()
        p.client.start_query.return_value = {'queryId': 'q'}
        p.client.get_query_results.return_value = {'status': 'Complete', 'results': []}
        now = datetime.now(timezone.utc)
        p.search('/ecs/a,/ecs/b', LogQuery(time_range=(now - timedelta(minutes=5), now)))
        kwargs = p.client.start_query.call_args.kwargs
        self.assertEqual(kwargs['logGroupNames'], ['/ecs/a', '/ecs/b'])
        self.assertNotIn('logGroupName', kwargs)

    def test_no_time_range_does_not_crash_at_midnight(self):
        p = self.provider()
        p.client.start_query.return_value = {'queryId': 'q'}
        p.client.get_query_results.return_value = {'status': 'Complete', 'results': []}
        with mock.patch('integrations.adapters.cloudwatch_logs.datetime') as dt:
            dt.now.return_value = datetime(2026, 10, 27, 0, 5, tzinfo=timezone.utc)
            p.search(None, LogQuery())
        start = p.client.start_query.call_args.kwargs['startTime']
        self.assertEqual(start, int(datetime(2026, 10, 26, 23, 5, tzinfo=timezone.utc).timestamp()))

    def test_configured_log_groups_win(self):
        p = self.provider(log_groups='/ecs/shop-api, /aws/lambda/checkout')
        self.assertEqual(p.get_indices(mock.Mock(name='shop')), ['/ecs/shop-api', '/aws/lambda/checkout'])
        p.client.describe_log_groups.assert_not_called()

    def test_discovery_finds_groups_named_after_the_project(self):
        p = self.provider()
        p.client.describe_log_groups.side_effect = [
            {'logGroups': [{'logGroupName': '/aws/shop/api'}]},
            {'logGroups': [{'logGroupName': '/aws/shop/api'}, {'logGroupName': '/ecs/shop-web'}]},
        ]
        project = mock.Mock(); project.name = 'Shop'
        self.assertEqual(p.get_indices(project), ['/aws/shop/api', '/ecs/shop-web'])

    def test_query_reads_lowercased_levels_and_backticks_odd_fields(self):
        q = LogQuery(severity=['ERROR'], services=['api']).to_cloudwatch_insights()
        self.assertIn("tolower(log.level) in ['error', 'err', '50']", q)
        self.assertIn('`app.kubernetes.io/name` in', q)
        self.assertIn('@message like /(?i)(error|', q)


class IndexDiscoveryTest(SimpleTestCase):
    def project(self, name='Shop Front', slug='acme'):
        p = mock.Mock(); p.name = name; p.organisation.slug = slug
        return p

    def test_setting_wins(self):
        client = mock.Mock()
        self.assertEqual(discover_log_indices(client, self.project(), ['logs-shop-*']), ['logs-shop-*'])
        client.cat.indices.assert_not_called()

    def test_serops_naming_first(self):
        client = mock.Mock()
        client.cat.indices.side_effect = lambda index, **kw: (
            [{'index': 'application-logs-shop-front-2026.10'}] if index.startswith('application') else [])
        self.assertEqual(discover_log_indices(client, self.project(), []),
                         ['application-logs-shop-front-2026.10'])
        client.count.assert_not_called()

    def test_falls_back_to_shipper_defaults_that_hold_data(self):
        client = mock.Mock()
        client.cat.indices.return_value = []
        client.count.side_effect = lambda index, **kw: {'count': 12 if index == 'filebeat-*' else 0}
        self.assertEqual(discover_log_indices(client, self.project(), []), ['filebeat-*'])

    def test_setting_parsing(self):
        self.assertEqual(parse_index_patterns(' logs-*, ,filebeat-* '), ['logs-*', 'filebeat-*'])
        self.assertEqual(parse_index_patterns(['a-*']), ['a-*'])
        self.assertEqual(parse_index_patterns(None), [])


class EnvironmentSpellingsTest(SimpleTestCase):
    def test_values(self):
        self.assertEqual(environment_values('Production'), ['Production', 'production', 'prod', 'prd'])
        self.assertEqual(environment_values('stg'), ['stg', 'staging', 'stage', 'preprod'])
        self.assertEqual(environment_values(None), [])

    def test_post_fetch_matching_works_both_ways(self):
        prod_log = LogEntry.from_es_hit({'_source': {**FILEBEAT_ECS, 'service': {'name': 'x', 'environment': 'prod'}}})
        self.assertTrue(is_log_matching_environment(prod_log, 'production'))
        production_log = LogEntry.from_es_hit({'_source': {'environment': 'production', 'message': 'm'}})
        self.assertTrue(is_log_matching_environment(production_log, 'prod'))  # used to fail
        self.assertFalse(is_log_matching_environment(production_log, 'staging'))

    def test_loki_selector_matches_every_spelling(self):
        self.assertIn('environment=~"production|prod|prd"', LogQuery(environment='production').to_logql())
        self.assertIn(r'environment=~"eu\\.prod"', LogQuery(environment='eu.prod').to_logql())


class LokiLevelTest(SimpleTestCase):
    def test_sources_in_order(self):
        self.assertEqual(_loki_level({'detected_level': 'warn'}, 'x'), 'WARN')       # Loki 3
        self.assertEqual(_loki_level({}, '{"level":50,"msg":"boom"}'), 'ERROR')      # Pino line
        self.assertEqual(_loki_level({}, 'level=error msg="boom"'), 'ERROR')         # logfmt
        self.assertEqual(_loki_level({}, 'all good'), 'INFO')


class DatadogQueryTest(SimpleTestCase):
    def test_values_with_spaces_are_quoted(self):
        dd = LogQuery(project='My Shop').to_datadog_query()
        self.assertIn('project_name:"My Shop"', dd)
        self.assertIn('@project_name:"My Shop"', dd)


class IngestHealthReadsNestedFieldsTest(SimpleTestCase):
    def test_ecs_record_counts_its_aliases(self):
        from integrations.field_aliases import ENVIRONMENT_ALIASES, SERVICE_NAME_ALIASES
        from integrations.health import analyze_records
        service, env = analyze_records([FILEBEAT_ECS], {'service_name': SERVICE_NAME_ALIASES,
                                                        'environment': ENVIRONMENT_ALIASES})
        self.assertEqual((service.missing_count, service.alias_counts.get('service.name')), (0, 1))
        self.assertEqual((env.missing_count, env.alias_counts.get('service.environment')), (0, 1))
