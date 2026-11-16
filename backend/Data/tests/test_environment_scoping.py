"""The right environment and the right numbers (phase 3 review: LG2, MT-2,
MT-3, MT-5, SC-07).

- LG2: a batch reads the log store its deployment is scoped to, and the
  scheduler discovers that store's log locations.
- MT-2: native OTLP spans carry their environment and project; a batch reads
  its own and the unlabelled ones, never another environment's or project's.
- MT-3: Kubernetes CPU (cores x100 over all replicas) is labelled as such and
  never checked against an 80 % threshold.
- MT-5: PromQL environment matchers accept every spelling (prod/production).
- SC-07: Bitbucket deliveries are authenticated by their HMAC signature, the
  created webhook carries the secret, and Bitbucket Pipelines are polled.
"""
import hashlib
import hmac
import json
import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone

from Data.tests.test_investigations import make_world
from Projects.models import Project, ProjectDeployment, ProjectService


class LogStoreFollowsTheDeploymentTest(TestCase):
    """LG2."""

    def setUp(self):
        self.org, self.project, self.env = make_world()
        self.dep = ProjectDeployment.objects.get(project=self.project, environment=self.env)

    def test_the_batch_asks_for_the_deployments_store(self):
        from Data import tasks
        provider = MagicMock()
        provider.get_indices.return_value = ['logs-*']
        provider.stream_location.return_value = None
        provider.search.return_value = []
        with patch.object(tasks, 'METRICS_ENABLED', False), \
             patch.object(tasks.IntegrationRegistry, 'get_log_provider_for_org', return_value=provider) as lookup, \
             patch.object(tasks.analyze_batch, 'delay'):
            tasks.create_log_batch_with_project_name(project_name='api', project=self.project.id,
                                                     environment=self.env.id, deployment=self.dep.id,
                                                     interval_minutes=15)
        self.assertTrue(lookup.called)
        self.assertEqual(lookup.call_args.kwargs.get('deployment'), self.dep)

    def test_a_scoped_store_gets_its_own_discovery(self):
        from Data import tasks
        org_store, scoped_store = MagicMock(name='org'), MagicMock(name='scoped')
        scoped_store.NEEDS_LOG_LOCATION = True
        with patch.object(tasks.IntegrationRegistry, 'get_log_provider_for_org', return_value=scoped_store), \
             patch.object(tasks, 'project_log_locations', return_value=['staging-logs-*']) as found, \
             patch.object(tasks, 'system_indices', return_value=[]):
            indices = tasks.deployment_log_locations(self.project, self.dep, org_store, 'prod-logs-*')
        self.assertEqual(indices, 'staging-logs-*')
        found.assert_called_once_with(self.project, scoped_store)

    def test_the_org_store_keeps_the_scheduler_locations(self):
        from Data import tasks
        org_store = MagicMock(name='org')
        with patch.object(tasks.IntegrationRegistry, 'get_log_provider_for_org', return_value=org_store), \
             patch.object(tasks, 'project_log_locations') as found:
            self.assertEqual(tasks.deployment_log_locations(self.project, self.dep, org_store, 'logs-*'), 'logs-*')
        found.assert_not_called()

    def test_a_scoped_store_without_locations_skips_that_deployment(self):
        from Data import tasks
        org_store, scoped_store = MagicMock(name='org'), MagicMock(name='scoped')
        scoped_store.NEEDS_LOG_LOCATION = True
        with patch.object(tasks.IntegrationRegistry, 'get_log_provider_for_org', return_value=scoped_store), \
             patch.object(tasks, 'project_log_locations', return_value=[]):
            self.assertIsNone(tasks.deployment_log_locations(self.project, self.dep, org_store, 'logs-*'))


class SpansStayInTheirEnvironmentTest(TestCase):
    """MT-2."""

    def setUp(self):
        self.org, self.project, self.env = make_world()
        self.now = timezone.now()

    def span(self, service='checkout', environment='', project_name='', status='OK'):
        from traces.models import Span, Trace
        trace = Trace.objects.create(organisation=self.org, trace_id=uuid.uuid4().hex,
                                     start_time=self.now - timedelta(minutes=3),
                                     end_time=self.now - timedelta(minutes=3), root_service_name=service)
        return Span.objects.create(trace=trace, span_id=uuid.uuid4().hex[:16], service_name=service,
                                   operation_name='POST /pay', start_time=self.now - timedelta(minutes=3),
                                   end_time=self.now - timedelta(minutes=3), duration_ms=40,
                                   status_code=status, environment=environment, project_name=project_name)

    def summary(self, environment='production', project=None):
        from ai_model.trace_context import _from_native, _service_names, _span_scope
        project = project or self.project
        return _from_native(self.org, _service_names(project), self.now - timedelta(minutes=10),
                            self.now, _span_scope(project, environment))

    def test_staging_spans_stay_out_of_the_production_batch(self):
        self.span(environment='production')
        self.span(environment='staging', status='ERROR')
        result = self.summary('production')
        self.assertEqual(result['span_count'], 1)
        self.assertEqual(result['error_span_count'], 0)

    def test_prod_spelling_counts_as_production_and_unlabelled_spans_stay_visible(self):
        self.span(environment='prod')
        self.span(environment='')
        self.assertEqual(self.summary('production')['span_count'], 2)

    def test_another_projects_service_of_the_same_name_is_not_ours(self):
        other = Project.objects.create(organisation=self.org, name='billing')
        ProjectService.objects.create(project=other, name='checkout')
        self.span(project_name='billing', status='ERROR')
        self.span(project_name='api')
        result = self.summary('production')
        self.assertEqual(result['span_count'], 1)
        self.assertEqual(self.summary('production', project=other)['error_span_count'], 1)

    def test_a_project_without_services_gets_no_spans(self):
        bare = Project.objects.create(organisation=self.org, name='empty')
        self.span()
        self.assertIsNone(self.summary('production', project=bare))

    def test_the_span_count_gate_uses_the_same_scope(self):
        from ai_model.trace_context import count_spans_in_window
        self.span(environment='staging')
        start, end = self.now - timedelta(minutes=10), self.now
        self.assertEqual(count_spans_in_window(self.project, start, end, environment='production'), 0)
        self.assertEqual(count_spans_in_window(self.project, start, end, environment='staging'), 1)

    def test_otlp_resource_attributes_are_stored_on_the_span(self):
        from traces.otlp_parsing import parse_span_dict
        parsed = parse_span_dict(
            {'traceId': 'a' * 32, 'spanId': 'b' * 16, 'name': 'GET /', 'startTimeUnixNano': '1',
             'endTimeUnixNano': '2'},
            {'service.name': 'checkout', 'deployment.environment.name': 'Staging', 'project_name': 'api'},
            'checkout')
        self.assertEqual((parsed['environment'], parsed['project_name']), ('staging', 'api'))


class KubernetesCpuIsNotAPercentageTest(SimpleTestCase):
    """MT-3."""

    def points(self, value):
        now = timezone.now()
        return [{'time': now - timedelta(minutes=m), 'value': value, 'series_key': 'frontend'} for m in range(10)]

    def test_core_percent_gets_no_threshold_anomaly_and_says_its_unit(self):
        from integrations.metrics_processing import preprocess_metrics_for_ai
        summary = preprocess_metrics_for_ai({'cpu_usage_percent': self.points(150.0), 'cpu_unit': 'core_percent'})
        self.assertEqual(summary['cpu']['anomalies'], [])
        self.assertEqual(summary['cpu']['unit'], 'core_percent')

    def test_a_real_percentage_is_still_checked(self):
        from integrations.metrics_processing import preprocess_metrics_for_ai
        summary = preprocess_metrics_for_ai({'cpu_usage_percent': self.points(95.0)})
        self.assertTrue(summary['cpu']['anomalies'])

    def test_the_prompt_says_of_one_core(self):
        from ai_model.tests.test_prompt_capabilities import BASE_CTX
        from ai_model.prompts import get_batch_analysis_prompt_parts
        from integrations.metrics_processing import preprocess_metrics_for_ai
        summary = preprocess_metrics_for_ai({'cpu_usage_percent': self.points(150.0), 'cpu_unit': 'core_percent'})
        from dataclasses import replace
        _system, text = get_batch_analysis_prompt_parts(replace(BASE_CTX, metrics_summary=summary))
        self.assertIn('% of one core', text)
        self.assertNotIn('CPU Anomalies', text)


class PromqlEnvironmentSpellingsTest(SimpleTestCase):
    """MT-5."""

    def test_production_matches_every_spelling(self):
        from integrations.promql import promql_matchers
        self.assertEqual(promql_matchers({'environment': 'production'}),
                         'environment=~"production|prod|prd"')

    def test_a_custom_environment_stays_exact_and_escaped(self):
        from integrations.promql import promql_matchers
        self.assertEqual(promql_matchers({'environment': 'qa-eu'}), 'environment="qa-eu"')
        self.assertEqual(promql_matchers({'project_name': 'a"b'}), 'project_name="a\\"b"')


class BitbucketDeliveriesTest(SimpleTestCase):
    """SC-07."""

    def request(self, body, headers):
        return RequestFactory().post('/api/webhooks/bitbucket/1/', data=body, content_type='application/json',
                                     **{f'HTTP_{k.upper().replace("-", "_")}': v for k, v in headers.items()})

    def handler_and_binding(self):
        from providers.bitbucket_webhook import BitbucketWebhookHandler
        return BitbucketWebhookHandler(), MagicMock(webhook_secret='s3cret')

    def test_a_signed_delivery_is_accepted(self):
        handler, binding = self.handler_and_binding()
        body = json.dumps({'commit_status': {'state': 'SUCCESSFUL'}}).encode()
        sig = 'sha256=' + hmac.new(b's3cret', body, hashlib.sha256).hexdigest()
        req = self.request(body, {'X-Event-Key': 'repo:commit_status_updated', 'X-Hub-Signature': sig})
        self.assertTrue(handler.validate_request(req, binding=binding))

    def test_unsigned_or_wrongly_signed_deliveries_are_refused(self):
        handler, binding = self.handler_and_binding()
        body = b'{}'
        bad = 'sha256=' + hmac.new(b'other', body, hashlib.sha256).hexdigest()
        for headers in ({'X-Event-Key': 'repo:commit_status_updated'},
                        {'X-Event-Key': 'repo:commit_status_updated', 'X-Hub-Signature': bad}):
            self.assertFalse(handler.validate_request(self.request(body, headers), binding=binding))

    def test_parsed_event_uses_the_keys_the_handler_stores(self):
        handler, _ = self.handler_and_binding()
        with patch('providers.bitbucket_webhook.detect_environment_generic', return_value='production'):
            parsed = handler.parse_pipeline_event({
                'commit_status': {'key': 'k1', 'state': 'SUCCESSFUL', 'commit': {'hash': 'abc123'},
                                  'refname': 'main', 'updated_on': '2026-11-16T09:00:00Z'},
                'repository': {'full_name': 'team/shop', 'uuid': '{u}'}})
        self.assertEqual(parsed['project_id'], 'team/shop')
        self.assertIn('metadata', parsed)
        self.assertNotIn('provider_metadata', parsed)

    def test_the_created_webhook_carries_the_secret(self):
        from providers.scm_providers import BitbucketProvider
        provider = BitbucketProvider('team/shop', 'token')
        response = MagicMock(status_code=201)
        response.json.return_value = {'uuid': '{h}'}
        with patch.object(provider, '_make_request', return_value=response) as call:
            provider.create_webhook('https://serops/api/webhooks/bitbucket/1/', 's3cret')
        self.assertEqual(call.call_args.kwargs['json']['secret'], 's3cret')

    def test_bitbucket_pipelines_are_polled(self):
        from providers.scm_providers import BitbucketProvider
        provider = BitbucketProvider('team/shop', 'token')
        finished = timezone.now().isoformat()
        response = MagicMock(status_code=200)
        response.json.return_value = {'values': [
            {'build_number': 12, 'state': {'name': 'COMPLETED', 'result': {'name': 'FAILED'}},
             'completed_on': finished, 'target': {'ref_name': 'main', 'commit': {'hash': 'def456'}}},
            {'build_number': 13, 'state': {'name': 'IN_PROGRESS'}, 'target': {}},
        ]}
        with patch.object(provider, '_make_request', return_value=response):
            runs = provider.list_recent_pipelines(2)
        self.assertEqual(runs, [{'id': '12', 'status': 'failed', 'ref': 'main', 'sha': 'def456',
                                 'updated_at': finished}])
