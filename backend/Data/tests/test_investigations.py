"""Investigations, and the batch-pipeline bugs fixed alongside them.

The pipeline runs for real here; only the log provider, the metrics switch
and the AI call are replaced.

R1  batches were linked to a project looked up by name across organisations
R2  alert batches moved the scheduler's window and left gaps
R3  a manual run shared the scheduler's lock
R4  manual runs must not touch Sentinel's state
R5  the alert path guessed which batch it had created
R9  dedup must not let an investigation hide logs from the scheduler
R10 alert analyses crashed: the environment arrived as a string
"""
import json
import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from Data.models import AIAnalyzedBatch, AlertEvent, Investigation
from integrations.ingestion import filter_unique_logs_for_project, get_scheduled_window_start
from integrations.schemas import LogEntry
from Organisations.models import Organisations
from Projects.models import Project, ProjectEnvironment, ProjectService
from Users.models import User


def make_world(org_name='Acme', project_name='api'):
    org = Organisations.objects.create(name=org_name)
    project = Project.objects.create(organisation=org, name=project_name, es_index_name='logs-*')
    env = ProjectEnvironment.objects.create(
        project=project, name='production', display_name='Production', log_label_value='production')
    for name in ('checkout', 'payments'):
        ProjectService.objects.create(project=project, name=name)
    return org, project, env


def log(message, service='checkout', minutes_ago=2, log_id=None, project='api'):
    return LogEntry(
        timestamp=timezone.now() - timedelta(minutes=minutes_ago),
        message=f'ERROR {message}',
        level='ERROR',
        service=service,
        labels={'service_name': service, 'environment': 'production',
                'project_name': project, '_index': 'logs-*'},
        raw_id=log_id or uuid.uuid4().hex,
    )


class PipelineMixin:
    """Run create_log_batch_with_project_name against a fake log provider."""

    def run_pipeline(self, logs, **kwargs):
        from Data import tasks
        provider = MagicMock()
        provider.get_indices.return_value = ['logs-*']
        provider.search.side_effect = lambda index, query, **kw: (
            [] if getattr(query, 'category', None) == 'cicd' else list(logs))
        self.provider = provider
        with patch.object(tasks, 'METRICS_ENABLED', False), \
             patch.object(tasks.IntegrationRegistry, 'get_log_provider_for_org', return_value=provider), \
             patch.object(tasks.IntegrationRegistry, 'get_metric_provider_for_org', return_value=None), \
             patch.object(tasks.analyze_batch, 'delay') as analyze:
            self.analyze = analyze
            return tasks.create_log_batch_with_project_name(**kwargs)

    def make_investigation(self, project, env, minutes=30, **fields):
        now = timezone.now()
        return Investigation.objects.create(
            organisation=project.organisation, project=project, environment=env,
            window_start=now - timedelta(minutes=minutes), window_end=now, **fields)


class ProjectOwnershipTest(PipelineMixin, TestCase):
    """R1: a batch belongs to the project the caller passed."""

    def test_same_project_name_in_two_organisations(self):
        org_a, project_a, env_a = make_world('Org A', 'api')
        org_b, project_b, env_b = make_world('Org B', 'api')
        self.run_pipeline([log('boom')], project_name='api', project=project_b.id,
                          environment=env_b.id, interval_minutes=15)
        batch = AIAnalyzedBatch.objects.get()
        self.assertEqual(batch.project, project_b)
        self.assertEqual(batch.organisation, org_b)

    def test_a_project_is_required(self):
        self.assertIn('Error', self.run_pipeline([log('boom')], project_name='api'))
        self.assertFalse(AIAnalyzedBatch.objects.exists())


class ScheduledWindowTest(PipelineMixin, TestCase):
    """R2: only scheduled batches move the scheduler, from their window end."""

    def setUp(self):
        self.org, self.project, self.env = make_world()

    def batch(self, trigger, created_minutes_ago, window_end_minutes_ago, env='production'):
        now = timezone.now()
        end = (now - timedelta(minutes=window_end_minutes_ago)).isoformat()
        return AIAnalyzedBatch.objects.create(
            batch_id=f'api-batch-{uuid.uuid4().hex[:8]}', project=self.project, organisation=self.org,
            environment=env, trigger=trigger, timestamp=now - timedelta(minutes=created_minutes_ago),
            data={'statistics': {'time_range': {'end': end}}})

    def test_alert_and_manual_batches_do_not_move_the_window(self):
        self.batch('scheduled', 15, 15)
        self.batch('alert', 8, 5)
        self.batch('manual', 2, 2)
        start = get_scheduled_window_start(self.project, self.env)
        self.assertAlmostEqual((timezone.now() - start).total_seconds(), 15 * 60, delta=5)

    def test_continues_from_the_window_end_not_the_creation_time(self):
        self.batch('scheduled', 10, 16)   # created late, after a slow run
        start = get_scheduled_window_start(self.project, self.env)
        self.assertAlmostEqual((timezone.now() - start).total_seconds(), 16 * 60, delta=5)

    def test_other_environments_and_organisations_are_ignored(self):
        self.batch('scheduled', 3, 3, env='staging')
        other_org, other_project, _ = make_world('Other', 'api')
        AIAnalyzedBatch.objects.create(batch_id='api-batch-other', project=other_project,
                                       organisation=other_org, environment='production')
        self.assertIsNone(get_scheduled_window_start(self.project, self.env))

    def test_scheduled_run_after_an_alert_reads_from_the_last_scheduled_end(self):
        self.batch('scheduled', 12, 12)
        self.batch('alert', 4, 1)
        self.run_pipeline([log('boom')], project_name='api', project=self.project.id,
                          environment=self.env.id, interval_minutes=15)
        query = self.provider.search.call_args_list[0].args[1]
        self.assertAlmostEqual((timezone.now() - query.time_range[0]).total_seconds(), 12 * 60, delta=10)


class DedupHistoryTest(TestCase):
    """R9: what an investigation read is still new to the scheduler."""

    def setUp(self):
        self.org, self.project, self.env = make_world()
        self.entry = log('disk full', log_id='log-1')

    def stored(self, trigger):
        AIAnalyzedBatch.objects.create(
            batch_id=f'api-batch-{trigger}', project=self.project, organisation=self.org,
            trigger=trigger, data={'logs': [{
                '_id': 'log-1', '_source': {'message': self.entry.message,
                                            '@timestamp': self.entry.timestamp.isoformat()}}]})

    def unique(self, history=True):
        return filter_unique_logs_for_project(
            [self.entry], timezone.now() - timedelta(hours=1), 'api', organisation=self.org, history=history)

    def test_scheduled_batches_count_as_seen(self):
        self.stored('scheduled')
        self.assertEqual(self.unique(), [])

    def test_investigation_batches_do_not(self):
        self.stored('manual')
        self.assertEqual(len(self.unique()), 1)

    def test_an_investigation_reads_everything(self):
        self.stored('scheduled')
        self.assertEqual(len(self.unique(history=False)), 1)


class InvestigationPipelineTest(PipelineMixin, TestCase):

    def setUp(self):
        self.org, self.project, self.env = make_world()

    def test_creates_a_manual_batch_with_the_report(self):
        inv = self.make_investigation(self.project, self.env, hint='Checkout is slow for EU customers')
        result = self.run_pipeline([log('timeout'), log('refused', service='payments')], investigation_id=inv.id)
        batch = AIAnalyzedBatch.objects.get()
        inv.refresh_from_db()
        self.assertEqual(result, {'status': 'created', 'batch_id': batch.batch_id})
        self.assertEqual(batch.trigger, 'manual')
        self.assertEqual(batch.investigation, inv)
        self.assertEqual(batch.sentinel_decision, 'manual')
        self.assertEqual(batch.data['operator_context'], 'Checkout is slow for EU customers')
        self.assertEqual(inv.status, Investigation.STATUS_ANALYZING)
        self.assertEqual(inv.counts['logs'], 2)
        self.analyze.assert_called_once_with(batch.batch_id)

    def test_reads_exactly_the_requested_window(self):
        inv = self.make_investigation(self.project, self.env, minutes=60)
        self.run_pipeline([log('a', minutes_ago=30), log('old', minutes_ago=90)], investigation_id=inv.id)
        query = self.provider.search.call_args_list[0].args[1]
        self.assertEqual(query.time_range, (inv.window_start, inv.window_end))
        self.assertEqual(AIAnalyzedBatch.objects.get().logs_analyzed, 1)

    def test_service_scope(self):
        inv = self.make_investigation(self.project, self.env, services=['payments'])
        self.run_pipeline([log('a'), log('b', service='payments')], investigation_id=inv.id)
        logs = AIAnalyzedBatch.objects.get().data['logs']
        self.assertEqual(len(logs), 1)

    def test_logs_already_in_scheduled_batches_are_included(self):
        entry = log('known', log_id='seen-1')
        AIAnalyzedBatch.objects.create(
            batch_id='api-batch-prev', project=self.project, organisation=self.org,
            data={'logs': [{'_id': 'seen-1', '_source': {
                'message': entry.message, '@timestamp': entry.timestamp.isoformat()}}]})
        inv = self.make_investigation(self.project, self.env)
        self.run_pipeline([entry], investigation_id=inv.id)
        self.assertEqual(AIAnalyzedBatch.objects.get(trigger='manual').logs_analyzed, 1)

    def test_sentinel_is_never_consulted(self):
        """R4: no skip, and no change to Sentinel's rolling state."""
        inv = self.make_investigation(self.project, self.env)
        with patch('Data.sentinel.should_skip_batch_pre_creation') as pre, \
             patch('Data.sentinel.evaluate_batch') as evaluate:
            self.run_pipeline([log('a')], investigation_id=inv.id)
        pre.assert_not_called()
        evaluate.assert_not_called()

    def test_runs_while_the_scheduler_holds_its_lock(self):
        """R3"""
        from Data.tasks import _acquire_task_lock, _release_task_lock
        key = f"task_lock:batch_project:{self.project.id}:{self.env.id}"
        self.assertTrue(_acquire_task_lock(key, interval_minutes=15))
        try:
            inv = self.make_investigation(self.project, self.env)
            self.run_pipeline([log('a')], investigation_id=inv.id)
        finally:
            _release_task_lock(key)
        self.assertTrue(AIAnalyzedBatch.objects.filter(investigation=inv).exists())

    def test_empty_window_reports_no_data_with_counts(self):
        inv = self.make_investigation(self.project, self.env)
        self.run_pipeline([], investigation_id=inv.id)
        inv.refresh_from_db()
        self.assertEqual(inv.status, Investigation.STATUS_NO_DATA)
        self.assertEqual(inv.counts, {'logs': 0, 'metrics': 0, 'traces': 0, 'code_changes': 0, 'cicd': 0})
        self.assertIsNotNone(inv.finished_at)
        self.assertFalse(AIAnalyzedBatch.objects.exists())

    def test_collection_failure_fails_fast_without_retrying(self):
        inv = self.make_investigation(self.project, self.env)
        from Data import tasks
        with patch.object(tasks, 'deduplicate_logs', side_effect=RuntimeError('provider exploded')), \
             patch.object(tasks.create_log_batch_with_project_name, 'retry') as retry:
            result = self.run_pipeline([log('a')], investigation_id=inv.id)
        retry.assert_not_called()
        inv.refresh_from_db()
        self.assertEqual(result, {'status': 'error', 'reason': 'collection_failed'})
        self.assertEqual(inv.status, Investigation.STATUS_FAILED)
        self.assertEqual(inv.error_code, 'collection_failed')
        self.assertNotIn('exploded', inv.error)

    def test_scheduled_runs_keep_their_behaviour(self):
        """The scheduled path still consults Sentinel and is tagged scheduled."""
        with patch('Data.sentinel.evaluate_batch', return_value=('alert', ['errors'])) as evaluate:
            self.run_pipeline([log('a')], project_name='api', project=self.project.id,
                              environment=self.env.id, interval_minutes=15)
        evaluate.assert_called_once()
        batch = AIAnalyzedBatch.objects.get()
        self.assertEqual((batch.trigger, batch.investigation), ('scheduled', None))


class AlertPathTest(PipelineMixin, TestCase):
    """R5 and R10, through the real pipeline (the old tests mocked it)."""

    def test_alert_creates_and_links_its_own_batch(self):
        org, project, env = make_world()
        event = AlertEvent.objects.create(
            organisation=org, source='alertmanager', alertname='HighErrorRate', state='firing',
            severity='critical', service='checkout', environment='production')
        from Data import tasks
        provider = MagicMock()
        provider.get_indices.return_value = ['logs-*']
        provider.search.side_effect = lambda index, query, **kw: (
            [] if getattr(query, 'category', None) == 'cicd' else [log('boom')])
        with patch.object(tasks, 'METRICS_ENABLED', False), \
             patch.object(tasks.IntegrationRegistry, 'get_log_provider_for_org', return_value=provider), \
             patch.object(tasks.IntegrationRegistry, 'get_metric_provider_for_org', return_value=None), \
             patch.object(tasks.analyze_batch, 'delay'), \
             patch('notifications.incident_dispatcher.dispatch'):
            result = tasks.analyze_alert_ondemand(event.pk)
        event.refresh_from_db()
        batch = AIAnalyzedBatch.objects.get()
        self.assertEqual(result['status'], 'analysed')
        self.assertEqual(event.triggered_batch, batch)
        self.assertEqual(batch.trigger, 'alert')
        self.assertIn('-alert-', batch.batch_id)


class SettleTest(TestCase):

    def setUp(self):
        self.org, self.project, self.env = make_world()
        now = timezone.now()
        self.inv = Investigation.objects.create(
            organisation=self.org, project=self.project, environment=self.env,
            window_start=now - timedelta(minutes=30), window_end=now,
            status=Investigation.STATUS_ANALYZING, started_at=now)

    def attach_batch(self, **fields):
        return AIAnalyzedBatch.objects.create(
            batch_id=f'api-batch-{uuid.uuid4().hex[:6]}', project=self.project, organisation=self.org,
            trigger='manual', investigation=self.inv, **fields)

    def test_waits_for_the_analysis(self):
        self.attach_batch()
        self.inv.settle()
        self.assertEqual(self.inv.status, Investigation.STATUS_ANALYZING)

    def test_done(self):
        self.attach_batch(analyzed_at=timezone.now(), model_name='gemini-2.5-flash')
        self.inv.settle()
        self.assertEqual(self.inv.status, Investigation.STATUS_DONE)

    def test_budget(self):
        self.attach_batch(analyzed_at=timezone.now(), data={'error': {
            'error_code': 'AI_BUDGET_EXCEEDED', 'error_message': 'Monthly AI spend cap reached.'}})
        self.inv.settle()
        self.assertEqual((self.inv.status, self.inv.error_code), (Investigation.STATUS_FAILED, 'over_budget'))

    def test_timeout(self):
        Investigation.objects.filter(pk=self.inv.pk).update(started_at=timezone.now() - timedelta(minutes=20))
        self.inv.refresh_from_db()
        self.inv.settle()
        self.assertEqual((self.inv.status, self.inv.error_code), (Investigation.STATUS_FAILED, 'timeout'))


class AnalysisRoutingTest(TestCase):
    """R6: an investigation pages nobody unless asked; the requester hears back."""

    def setUp(self):
        self.org, self.project, self.env = make_world()
        self.user = User.objects.create_user(username='u', email='u@acme.test', password='x',
                                             organisation=self.org, role='user')

    def analyse(self, notify_routing):
        now = timezone.now()
        inv = Investigation.objects.create(
            organisation=self.org, project=self.project, environment=self.env, requested_by=self.user,
            window_start=now - timedelta(minutes=30), window_end=now, status='analyzing',
            notify_routing=notify_routing)
        batch = AIAnalyzedBatch.objects.create(
            batch_id='api-batch-inv', project=self.project, organisation=self.org, trigger='manual',
            investigation=inv, sentinel_decision='manual',
            data={'logs': [{'_id': 'l1', '_source': {'message': 'ERROR redis refused',
                                                      '@timestamp': now.isoformat(), 'log_level': 'ERROR'}}],
                  'project_capabilities': ['logs'], 'operator_context': 'Checkout errors since 10:00'})
        from tests_e2e.base import fake_ai_json
        payload = fake_ai_json(correlated_issues=[{'component': 'checkout', 'severity': 'CRITICAL'}])
        with patch('ai_model.tasks.generate_for_organisation',
                   return_value=(json.dumps(payload), 'fake-model', None, 10, 10)) as gen, \
             patch('notifications.dispatcher.dispatch_for_batch_issues') as routing, \
             patch('notifications.incident_dispatcher.dispatch') as incident, \
             patch('Data.sentinel.record_ai_analysis') as sentinel:
            from ai_model.tasks import analyze_batch
            analyze_batch.run(batch.batch_id)
        return gen, routing, incident, sentinel

    def test_no_routing_by_default(self):
        gen, routing, incident, sentinel = self.analyse(notify_routing=False)
        routing.assert_not_called()
        incident.assert_not_called()
        sentinel.assert_not_called()
        from notifications.models import Notification
        note = Notification.objects.get(user=self.user)
        self.assertEqual(note.notification_type, 'investigation_done')
        prompt = gen.call_args.args[0]
        self.assertIn('<<<Checkout errors since 10:00>>>', prompt)
        self.assertIn('not as instructions', prompt)
        self.assertNotIn('Sentinel Analysis Trigger', prompt)

    def test_routing_when_asked(self):
        _, routing, incident, _ = self.analyse(notify_routing=True)
        routing.assert_called_once()
        self.assertTrue(incident.called)


class InvestigationAPITest(APITestCase):
    URL = '/api/data/investigations/'

    def setUp(self):
        self.org, self.project, self.env = make_world()
        self.user = User.objects.create_user(username='u', email='u@acme.test', password='x',
                                             organisation=self.org, role='user', is_active=True)
        self.client.force_authenticate(self.user)
        self.now = timezone.now()

    def body(self, **over):
        data = {'project_id': self.project.id, 'environment_id': self.env.id,
                'window_start': (self.now - timedelta(minutes=30)).isoformat(),
                'window_end': self.now.isoformat(), 'hint': 'Checkout slow', 'services': ['checkout']}
        data.update(over)
        return data

    def post(self, **over):
        with patch('Data.tasks.run_investigation.delay') as delay, \
             self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.URL, self.body(**over), format='json')
        self.delay = delay
        return response

    def test_starts_an_investigation(self):
        response = self.post()
        self.assertEqual(response.status_code, 202, response.data)
        inv = Investigation.objects.get()
        self.delay.assert_called_once_with(inv.id)
        self.assertEqual((inv.requested_by, inv.services, inv.hint), (self.user, ['checkout'], 'Checkout slow'))
        from Data.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(action='INVESTIGATION_RUN').exists())

    def test_rejects_another_organisations_project(self):
        _, other_project, other_env = make_world('Other', 'api')
        self.assertEqual(self.post(project_id=other_project.id, environment_id=None).status_code, 400)
        self.assertEqual(self.post(environment_id=other_env.id).data['error'], 'invalid_environment')

    def test_window_rules(self):
        cases = {
            'too short': dict(window_start=(self.now - timedelta(minutes=2)).isoformat()),
            'too long': dict(window_start=(self.now - timedelta(hours=7)).isoformat()),
            'future': dict(window_end=(self.now + timedelta(hours=1)).isoformat()),
            'too old': dict(window_start=(self.now - timedelta(days=40)).isoformat(),
                            window_end=(self.now - timedelta(days=40) + timedelta(hours=1)).isoformat()),
            'no time zone': dict(window_start='2026-10-14T10:00:00'),
            'garbage': dict(window_end='yesterday'),
        }
        for name, over in cases.items():
            with self.subTest(name):
                response = self.post(**over)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data['error'], 'invalid_window')

    def test_other_field_rules(self):
        self.assertEqual(self.post(hint='x' * 501).data['error'], 'invalid_hint')
        self.assertEqual(self.post(services=['not-a-service']).data['error'], 'invalid_services')
        self.assertEqual(self.post(services='checkout').data['error'], 'invalid_services')
        self.assertEqual(self.post(notify_routing='yes').data['error'], 'invalid_notify_routing')
        self.assertFalse(Investigation.objects.exists())

    def test_hint_is_cleaned(self):
        self.post(hint='  slow\x00 checkout\x1b  ')
        self.assertEqual(Investigation.objects.get().hint, 'slow checkout')

    def test_viewers_cannot_start_one(self):
        self.user.role = 'viewer'
        self.user.save()
        self.assertEqual(self.post().status_code, 403)

    def test_demo_users_cannot_start_one(self):
        # Through the real token path: DemoUserMiddleware resolves the Knox
        # token itself, which force_authenticate would bypass.
        from knox.models import AuthToken
        self.user.is_demo = True
        self.user.save()
        _, token = AuthToken.objects.create(self.user)
        self.client.force_authenticate(None)
        response = self.client.post(self.URL, self.body(), format='json', HTTP_AUTHORIZATION=f'Token {token}')
        self.assertEqual((response.status_code, response.json()['error']), (403, 'demo_read_only'))
        self.assertFalse(Investigation.objects.exists())

    def test_a_double_click_returns_the_same_run(self):
        first = self.post()
        second = self.post()
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data['id'], second.data['id'])
        self.assertEqual(Investigation.objects.count(), 1)

    def test_two_at_a_time(self):
        self.post(hint='a')
        self.post(hint='b')
        response = self.post(hint='c')
        self.assertEqual((response.status_code, response.data['error']), (429, 'too_many_running'))

    def test_ten_an_hour(self):
        for i in range(10):
            Investigation.objects.create(organisation=self.org, project=self.project, status='done',
                                         window_start=self.now - timedelta(minutes=30), window_end=self.now)
        response = self.post()
        self.assertEqual((response.status_code, response.data['error']), (429, 'rate_limited'))

    def test_budget_used_up(self):
        from ai_model.budget import BudgetCheck
        with patch('ai_model.budget.BudgetTracker.check_budget',
                   return_value=BudgetCheck(ok=False, current=10, remaining=0, budget=10)):
            response = self.post()
        self.assertEqual((response.status_code, response.data['error']), (409, 'over_budget'))

    def test_list_and_detail_are_scoped_to_the_organisation(self):
        mine = self.post().data['id']
        other_org, other_project, _ = make_world('Other', 'api')
        theirs = Investigation.objects.create(organisation=other_org, project=other_project,
                                              window_start=self.now - timedelta(minutes=30), window_end=self.now)
        listed = self.client.get(self.URL).data
        self.assertEqual([r['id'] for r in listed['results']], [mine])
        self.assertEqual(self.client.get(f'{self.URL}{theirs.id}/').status_code, 404)
        self.assertEqual(self.client.get(f'{self.URL}{mine}/').data['status'], 'queued')

    def test_viewers_can_read(self):
        self.post()
        self.user.role = 'viewer'
        self.user.save()
        self.assertEqual(self.client.get(self.URL).status_code, 200)

    def test_options_are_scoped(self):
        make_world('Other', 'secret-project')
        data = self.client.get(f'{self.URL}options/').data
        self.assertEqual([p['name'] for p in data['projects']], ['api'])
        self.assertEqual(data['projects'][0]['services'], ['checkout', 'payments'])
        self.assertEqual(data['limits']['max_window_hours'], 6)

    def test_requires_authentication(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(self.URL).status_code, (401, 403))
