"""
"Check my data" and the reasons a scheduled run records when it makes no
analysis.

The log store is a fake that applies the query's filters the way a real
store does (project exact, every environment spelling, error/warn levels),
so each step of the check sees what a real store would return.
"""
import uuid
from datetime import timedelta
from unittest.mock import MagicMock, Mock, patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from Data.data_check import apply_fix, check_project_data
from Data.models import DataRunStatus
from Data.tests.test_investigations import PipelineMixin, make_world
from integrations.field_aliases import first_present, lookup
from integrations.field_aliases import ENVIRONMENT_ALIASES, PROJECT_NAME_ALIASES
from integrations.schemas import LogEntry, LogQuery
from Projects.models import ProjectEnvironment, ProjectService
from Users.models import User


def entry(message='boom', level='ERROR', service='checkout', project='api', environment='production', **labels):
    doc = {'service_name': service, **labels}
    if project is not None:
        doc['project_name'] = project
    if environment is not None:
        doc['environment'] = environment
    return LogEntry(timestamp=timezone.now() - timedelta(minutes=2), message=message, level=level,
                    service=service, labels=doc, raw_id=uuid.uuid4().hex)


class FakeStore:
    """Answers a LogQuery the way a log store does."""

    def __init__(self, logs, locations=('logs-*',), error=None):
        self.logs, self.locations, self.error = logs, list(locations), error
        self.queries = []
        self.client = None

    def get_indices(self, project):
        return self.locations

    def search(self, index, query):
        self.queries.append(query)
        if self.error:
            raise RuntimeError(self.error)
        out = []
        for e in self.logs:
            if query.project and first_present(e.labels, PROJECT_NAME_ALIASES) != query.project and not any(
                    str(lookup(e.labels, f)) == v for f, v in (query.project_rules or [])):
                continue
            if query.environment:
                wanted = {v.lower() for v in query.environment_values()}
                if str(first_present(e.labels, ENVIRONMENT_ALIASES, default='')).lower() not in wanted:
                    continue
            if query.severity and e.level not in ('ERROR', 'WARN', 'WARNING', 'CRITICAL'):
                continue
            out.append(e)
        return out[:query.max_results]


class CheckMyDataTest(TestCase):
    def setUp(self):
        self.org, self.project, self.env = make_world()

    def check(self, store, environment='default'):
        with patch('integrations.registry.IntegrationRegistry.get_log_provider_for_org', return_value=store):
            return check_project_data(self.project, self.env if environment == 'default' else environment)

    def counts(self, report):
        return {s['key']: s['count'] for s in report['stages']}

    def test_everything_in_place(self):
        report = self.check(FakeStore([entry(), entry(service='payments', level='WARN'), entry(level='INFO')]))
        self.assertEqual(report['diagnosis']['code'], 'ok')
        self.assertEqual(self.counts(report), {'found': 3, 'project': 3, 'environment': 3, 'level': 2, 'services': 2})
        self.assertEqual(report['fixes'], [])

    def test_no_log_integration(self):
        report = self.check(None)
        self.assertEqual(report['diagnosis']['code'], 'no_log_provider')

    def test_nowhere_to_read_logs_from(self):
        self.project.es_index_name = ''
        self.project.save()
        report = self.check(FakeStore([entry()], locations=()))
        self.assertEqual(report['diagnosis']['code'], 'no_log_location')
        self.assertEqual(report['stages'], [])

    def test_the_store_refuses_the_query(self):
        report = self.check(FakeStore([], error='index_not_found_exception'))
        self.assertEqual(report['diagnosis']['code'], 'search_failed')
        self.assertIn('index_not_found_exception', report['diagnosis']['message'])

    def test_no_logs_at_all(self):
        report = self.check(FakeStore([]))
        self.assertEqual(report['diagnosis']['code'], 'no_logs')

    def test_logs_tagged_with_another_project_name(self):
        report = self.check(FakeStore([entry(project='shop')] * 3 + [entry(project='API')]))
        self.assertEqual(report['diagnosis']['code'], 'project_not_tagged')
        self.assertEqual(report['diagnosis']['same_but_case'], ['API'])
        self.assertEqual(report['seen']['project'][0], {'value': 'shop', 'count': 3, 'field': 'project_name'})
        self.assertEqual(self.counts(report), {'found': 4, 'project': 0})

    def test_project_values_are_read_from_any_alias(self):
        log = entry(project=None)
        log.labels['project'] = 'shop'
        report = self.check(FakeStore([log]))
        self.assertEqual(report['seen']['project'], [{'value': 'shop', 'count': 1, 'field': 'project'}])

    def test_environment_spelled_another_way_offers_a_fix(self):
        store = FakeStore([entry(environment='live'), entry(environment='live', level='INFO')])
        report = self.check(store)
        self.assertEqual(report['diagnosis']['code'], 'environment_not_tagged')
        self.assertEqual(report['seen']['environment'][0]['value'], 'live')
        fix = report['fixes'][0]
        self.assertEqual(fix, {'action': 'use_environment_label', 'environment': self.env.id, 'value': 'live'})

        apply_fix(self.project, fix)
        self.env.refresh_from_db()
        self.assertEqual(self.env.log_labels(), ['production', 'live'])
        report = self.check(store)
        self.assertEqual(report['diagnosis']['code'], 'ok')

    def test_a_second_spelling_is_offered_even_when_some_logs_match(self):
        store = FakeStore([entry(environment='prod'), entry(environment='live', service='payments')])
        report = self.check(store)
        self.assertEqual(report['diagnosis']['code'], 'ok')
        self.assertEqual(report['diagnosis']['count'], 1)
        self.assertIn({'action': 'use_environment_label', 'environment': self.env.id, 'value': 'live'},
                      report['fixes'])
        apply_fix(self.project, report['fixes'][0])
        self.env.refresh_from_db()
        self.assertEqual(self.check(store)['diagnosis']['count'], 2)

    def test_another_environment_of_the_project_is_never_offered(self):
        ProjectEnvironment.objects.create(project=self.project, name='staging', display_name='Staging')
        store = FakeStore([entry(environment='production'), entry(environment='stg'), entry(environment='live')])
        values = [f['value'] for f in self.check(store)['fixes'] if f['action'] == 'use_environment_label']
        self.assertEqual(values, ['live'])

    def test_usual_environment_spellings_are_not_offered(self):
        report = self.check(FakeStore([entry(environment='prod')]))
        self.assertEqual(report['diagnosis']['code'], 'ok')

    def test_no_errors_is_good_news(self):
        report = self.check(FakeStore([entry(level='INFO'), entry(level='DEBUG')]))
        self.assertEqual(report['diagnosis']['code'], 'no_errors')
        self.assertIn('good news', report['diagnosis']['message'])
        self.assertEqual({v['value'] for v in report['seen']['level']}, {'INFO', 'DEBUG'})

    def test_unlisted_services_can_be_listed_in_one_click(self):
        report = self.check(FakeStore([entry(service='cart'), entry(service='Orders')]))
        self.assertEqual(report['diagnosis']['code'], 'unregistered_services')
        self.assertEqual(report['fixes'], [{'action': 'register_services', 'names': ['cart', 'orders']}])
        self.assertEqual({(s['value'], s['registered']) for s in report['seen']['service']},
                         {('cart', False), ('orders', False)})

        self.assertEqual(apply_fix(self.project, report['fixes'][0]), {'added': ['cart', 'orders']})
        self.assertEqual(apply_fix(self.project, report['fixes'][0]), {'added': []})
        report = self.check(FakeStore([entry(service='cart'), entry(service='Orders')]))
        self.assertEqual(report['diagnosis']['code'], 'ok')

    def test_a_project_without_services(self):
        ProjectService.objects.filter(project=self.project).delete()
        report = self.check(FakeStore([entry()]))
        self.assertEqual(report['diagnosis']['code'], 'no_services')
        self.assertEqual(report['fixes'], [{'action': 'register_services', 'names': ['checkout']}])

    def test_each_step_is_the_scheduled_query_plus_one_filter(self):
        store = FakeStore([entry()])
        self.check(store)
        found, project, env, level = store.queries
        self.assertIsNone(found.project)
        self.assertEqual(project.project, 'api')
        self.assertEqual(env.environment, 'production')
        self.assertEqual(level.severity, ['ERROR', 'WARNING', 'CRITICAL'])
        self.assertTrue(all(q.time_range for q in store.queries))

    def test_without_an_environment_the_environment_step_is_left_out(self):
        report = self.check(FakeStore([entry()]), environment=None)
        self.assertEqual([s['key'] for s in report['stages']], ['found', 'project', 'level', 'services'])

    def test_the_report_carries_identifiers_never_messages(self):
        report = self.check(FakeStore([entry(message='card 4111 1111 1111 1111 declined')]))
        self.assertNotIn('4111', str(report))


class FixesRefuseWhatTheCheckNeverOffersTest(TestCase):
    def setUp(self):
        self.org, self.project, self.env = make_world()

    def test_unknown_action(self):
        with self.assertRaises(ValueError):
            apply_fix(self.project, {'action': 'drop_table'})

    def test_environment_of_another_project(self):
        _, other, other_env = make_world('Other', 'web')
        with self.assertRaises(ValueError):
            apply_fix(self.project, {'action': 'use_environment_label', 'environment': other_env.id, 'value': 'x'})

    def test_one_value_at_a_time(self):
        with self.assertRaises(ValueError):
            apply_fix(self.project, {'action': 'use_environment_label', 'environment': self.env.id, 'value': 'a,b'})


class EnvironmentLabelReachesEveryQueryTest(TestCase):
    """The value accepted by the fix is queried by the scheduled run."""

    def test_query_builders(self):
        q = LogQuery(environment='production', environment_labels=['live'], project='api',
                     time_range=(timezone.now() - timedelta(minutes=5), timezone.now()))
        self.assertIn('live', str(q.to_es_dsl()))
        self.assertIn('live', q.to_logql())
        self.assertIn('live', q.to_datadog_query())
        self.assertIn('live', q.to_cloudwatch_insights())
        self.assertIn('live', q.to_splunk_spl())
        self.assertIn('live', q.to_azure_kql())
        self.assertIn('live', q.to_gcp_filter())

    def test_scheduled_query_carries_the_label(self):
        org, project, env = make_world()
        env.log_label_value = 'production,live'
        env.save()
        runner = PipelineMixin()
        runner.run_pipeline([entry(environment='live')], project_name='api', project=project.id,
                            environment=env.id, interval_minutes=15)
        query = runner.provider.search.call_args_list[0].args[1]
        self.assertIn('live', query.environment_values())
        self.assertTrue(DataRunStatus.objects.get(project=project, environment=env).outcome in ('batch', 'skipped'))


class ScheduledRunRecordsWhyTest(PipelineMixin, TestCase):
    def setUp(self):
        self.org, self.project, self.env = make_world()

    def run_scheduled(self, logs):
        with patch('Data.sentinel.evaluate_batch', return_value=('alert', ['errors'])):
            self.run_pipeline(logs, project_name='api', project=self.project.id,
                              environment=self.env.id, interval_minutes=15)
        return DataRunStatus.objects.get(project=self.project, environment=self.env)

    def test_a_batch(self):
        run = self.run_scheduled([entry()])
        self.assertEqual(run.outcome, 'batch')
        self.assertEqual(run.counts['environment'], 1)

    def test_nothing_returned(self):
        run = self.run_scheduled([])
        self.assertEqual((run.outcome, run.reason), ('empty', 'no_matching_logs'))
        self.assertIn('Check my data', run.detail)

    def test_only_unlisted_services(self):
        run = self.run_scheduled([entry('db down', service='cart'), entry('cache miss storm', service='cart'),
                                  entry(service='orders')])
        self.assertEqual((run.outcome, run.reason), ('empty', 'no_registered_service'))
        self.assertIn('cart (2)', run.detail)
        self.assertIn('orders (1)', run.detail)

    def test_only_info(self):
        run = self.run_scheduled([entry(level='INFO', message='GET / 200')])
        self.assertEqual(run.reason, 'not_important')

    def test_the_store_fails(self):
        from Data import tasks
        provider = MagicMock()
        provider.search.side_effect = RuntimeError('connection refused')
        with patch.object(tasks, 'METRICS_ENABLED', False), \
             patch.object(tasks.IntegrationRegistry, 'get_log_provider_for_org', return_value=provider), \
             patch.object(tasks.IntegrationRegistry, 'get_metric_provider_for_org', return_value=None):
            tasks.create_log_batch_with_project_name(project_name='api', project=self.project.id,
                                                     environment=self.env.id, interval_minutes=15)
        run = DataRunStatus.objects.get(project=self.project, environment=self.env)
        self.assertEqual((run.outcome, run.reason), ('error', 'search_failed'))
        self.assertIn('connection refused', run.detail)

    def test_investigations_record_nothing(self):
        inv = self.make_investigation(self.project, self.env)
        self.run_pipeline([], project_name='api', project=self.project.id, environment=self.env.id,
                          investigation_id=inv.id)
        self.assertFalse(DataRunStatus.objects.exists())

    def test_the_latest_run_replaces_the_last(self):
        self.run_scheduled([])
        self.assertEqual(self.run_scheduled([entry()]).outcome, 'batch')
        self.assertEqual(DataRunStatus.objects.count(), 1)


class SchedulerRecordsSkippedProjectsTest(TestCase):
    def setUp(self):
        cache.clear()
        self.org, self.project, self.env = make_world()

    def schedule(self, provider):
        from Data.tasks import create_batches_for_all_projects
        cache.clear()
        with patch('Data.tasks.IntegrationRegistry') as registry, \
             patch('providers.tasks.sync_recent_deployments'), \
             patch('celery.group') as group:
            registry.get_log_provider_for_org.return_value = provider
            group.return_value.apply_async.return_value = Mock(id='g')
            create_batches_for_all_projects()

    def note(self):
        return DataRunStatus.objects.filter(project=self.project, environment__isnull=True).first()

    def test_no_services(self):
        ProjectService.objects.filter(project=self.project).delete()
        self.schedule(FakeStore([]))
        self.assertEqual(self.note().reason, 'no_services')

    def test_no_log_provider(self):
        self.schedule(None)
        self.assertEqual(self.note().reason, 'no_log_provider')

    def test_nowhere_to_read_from(self):
        self.project.es_index_name = ''
        self.project.save()
        self.schedule(FakeStore([], locations=()))
        self.assertEqual(self.note().reason, 'no_log_location')

    def test_the_note_goes_once_the_project_is_fixed(self):
        self.schedule(None)
        self.assertIsNotNone(self.note())
        self.schedule(FakeStore([]))
        self.assertIsNone(self.note())


class DataCheckApiTest(TestCase):
    def setUp(self):
        self.org, self.project, self.env = make_world()
        self.url = f'/api/projects/{self.project.id}/data-check/'

    def client_for(self, role, org=None):
        user = User.objects.create_user(username=f'{role}-{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.io',
                                        password='x', organisation=org or self.org, role=role, is_active=True)
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_viewer_sees_the_last_runs_but_cannot_run_or_fix(self):
        DataRunStatus.record(self.project, self.env, 'empty', 'no_matching_logs', 'nothing')
        client = self.client_for('viewer')
        response = client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['runs'][0]['reason'], 'no_matching_logs')
        self.assertEqual(client.post(self.url, {}, format='json').status_code, 403)
        self.assertEqual(client.post(self.url + 'fix/', {'action': 'register_services', 'names': ['x']},
                                     format='json').status_code, 403)

    def test_user_runs_the_check_and_applies_a_fix(self):
        client = self.client_for('user')
        store = FakeStore([entry(service='cart')])
        with patch('integrations.registry.IntegrationRegistry.get_log_provider_for_org', return_value=store):
            response = client.post(self.url, {'environment': self.env.id, 'minutes': 30}, format='json')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['window_minutes'], 30)
        self.assertEqual(body['diagnosis']['code'], 'unregistered_services')
        response = client.post(self.url + 'fix/', body['fixes'][0], format='json')
        self.assertEqual(response.json(), {'added': ['cart']})
        self.assertTrue(ProjectService.objects.filter(project=self.project, name='cart').exists())

    def test_bad_input(self):
        client = self.client_for('user')
        self.assertEqual(client.post(self.url, {'environment': 999999}, format='json').status_code, 404)
        self.assertEqual(client.post(self.url, {'minutes': 'soon'}, format='json').status_code, 400)
        self.assertEqual(client.post(self.url + 'fix/', {'action': 'nope'}, format='json').status_code, 400)

    def test_another_organisation_gets_404(self):
        from Organisations.models import Organisations
        client = self.client_for('admin', org=Organisations.objects.create(name='Other'))
        self.assertEqual(client.get(self.url).status_code, 404)
        self.assertEqual(client.post(self.url, {}, format='json').status_code, 404)
        self.assertEqual(client.post(self.url + 'fix/', {'action': 'register_services', 'names': ['x']},
                                     format='json').status_code, 404)
        self.assertFalse(ProjectService.objects.filter(name='x').exists())


class ProjectLogRulesTest(TestCase):
    """Phase C: a project's logs tagged another way than project_name."""

    def setUp(self):
        self.org, self.project, self.env = make_world()
        ProjectService.objects.create(project=self.project, name='frontend')

    def check(self, store):
        with patch('integrations.registry.IntegrationRegistry.get_log_provider_for_org', return_value=store):
            return check_project_data(self.project, self.env)

    def otel(self, message='GET / 502 upstream checkout failed', level='ERROR'):
        log = entry(message, level=level, service='frontend', project=None)
        log.labels['resource'] = {'attributes': {'service.namespace': 'api', 'service.name': 'frontend'}}
        return log

    def test_untagged_logs_show_how_they_are_grouped_and_the_rule_is_offered(self):
        store = FakeStore([entry(), self.otel(), self.otel()])
        report = self.check(store)
        self.assertEqual(report['seen']['groupings'][0], {
            'field': 'resource.attributes.service.namespace', 'value': 'api', 'count': 2, 'matches_name': True})
        fix = {'action': 'add_project_rule', 'field': 'resource.attributes.service.namespace', 'value': 'api'}
        self.assertIn(fix, report['fixes'])
        self.assertEqual(report['diagnosis']['count'], 1, 'only the project-tagged log so far')

        apply_fix(self.project, fix)
        self.project.refresh_from_db()
        report = self.check(store)
        self.assertEqual(report['project_rules'], [{'field': 'resource.attributes.service.namespace', 'value': 'api'}])
        self.assertEqual(report['diagnosis']['count'], 3, 'the rule adds logs; project_name still counts')
        self.assertIn('frontend', [s['value'] for s in report['seen']['service']])
        self.assertEqual(report['seen']['groupings'], [], 'nothing left to map')

    def test_a_grouping_of_another_name_is_listed_but_not_recommended(self):
        log = entry(project=None)
        log.labels['kubernetes'] = {'namespace': 'kube-system'}
        report = self.check(FakeStore([log]))
        self.assertEqual(report['seen']['groupings'][0]['value'], 'kube-system')
        self.assertFalse(any(f['action'] == 'add_project_rule' for f in report['fixes']))

    def test_rules_can_be_removed_and_are_validated(self):
        apply_fix(self.project, {'action': 'add_project_rule', 'field': 'kubernetes.namespace', 'value': 'shop'})
        self.assertEqual(apply_fix(self.project, {'action': 'remove_project_rule', 'field': 'kubernetes.namespace',
                                                  'value': 'shop'}), {'project_rules': []})
        for bad in ({'field': 'a b', 'value': 'x'}, {'field': 'x', 'value': ''}, {'field': 'x"; drop', 'value': 'v'},
                    {'field': 'ok', 'value': 'two\nlines'}):
            with self.assertRaises(ValueError):
                apply_fix(self.project, {'action': 'add_project_rule', **bad})

    def test_at_most_five_rules(self):
        for i in range(5):
            apply_fix(self.project, {'action': 'add_project_rule', 'field': 'team', 'value': f't{i}'})
        with self.assertRaises(ValueError):
            apply_fix(self.project, {'action': 'add_project_rule', 'field': 'team', 'value': 't5'})

    def test_the_scheduled_query_carries_the_rules(self):
        self.project.log_rules = [{'field': 'service.namespace', 'value': 'api'}]
        self.project.save()
        runner = PipelineMixin()
        runner.run_pipeline([entry()], project_name='api', project=self.project.id,
                            environment=self.env.id, interval_minutes=15)
        query = runner.provider.search.call_args_list[0].args[1]
        self.assertEqual(query.project_rules, [('service.namespace', 'api')])
