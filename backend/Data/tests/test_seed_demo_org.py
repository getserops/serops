"""
Tests for the seed_demo_org management command.

The demo organisation is loaded from the seed files in Data/demo_seed/
(real analyses, converted by tools/demo-seed). We cover what gets
created and that it is what the files hold, the rules the loader adds
(one time shift, one issue per deduplicated issue, resolution notes, no
AI usage), idempotency (the command can be safely re-run), the rebuild
over what an earlier version of the command left, and isolation (the
command never touches data outside the demo org).
"""

import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from Organisations.models import Organisations
from Users.models import User
from Projects.models import CICDBinding, Project, ProjectDeployment, ProjectEnvironment, ProjectService
from providers.models import CodeChange, Pipeline, ProviderIntegration
from Data import demo_seed_loader as seed_files
from Data.demo_seed_time import TimeContext, parse_time, walk_times
from Data.models import AIAnalyzedBatch, AlertEvent, AuditLog, Investigation, Issue, IssueOccurrence
from ai_model.models import ChatSession, ChatMessage, AITokenUsage
from integrations.models import Cluster, ObservabilityIntegration
from notifications.models import IncidentNotificationChannel, Notification, NotificationRoutingRule
from org_settings.models import AIModelProvider, OrganisationAISettings, OrganisationAPIKey
from traces.models import IngestKey, Span, Trace

from Data.management.commands.seed_demo_org import (
    DEMO_AI_PROVIDER,
    DEMO_MAIL_DOMAIN,
    DEMO_ORG_SLUG,
    DEMO_USER_EMAIL,
    SEED_DEMO_PLACEHOLDER,
    cluster_name,
)

MODEL_USED = 'claude-sonnet-5-5'
MARGIN = timedelta(minutes=15)

# The three issues the demo keeps open, as (project, component).
OPEN_ISSUES = {
    ('Fleet', 'fleet-redis'),          # K7
    ('Shopfront', 'shippingservice'),  # I8
    ('Studio', 'pricing'),             # L10
}

# Analyses per issue, as the seed files have them. SerOps had attached the
# two runs of the Studio payments incident to one issue, the two runs of
# the Fleet database incident (the same fault twice) to one, and the two
# paymentservice findings to one; the two checkoutservice runs were two
# issues. Every other issue was raised by one seeded analysis.
OCCURRENCES = {
    ('Fleet', 'fleet-db'): 2,
    ('Shopfront', 'paymentservice'): 2,
    ('Studio', 'payments'): 2,
}

RX_EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}')
RX_URL = re.compile(r'\bhttps?://([A-Za-z0-9._\-]+)(?::\d+)?(/[^\s"\'<>\\)]*)?')
# Every domain that is not Acme's is renamed by the converter (the registry
# of the images, for one). The exception: an unmodified message of an
# open-source tool keeps the tool's own domain, here the address in pip's
# "running as root" warning line.
KEPT_PUBLIC_HOSTS = {'pip.pypa.io'}


def _seed():
    call_command('seed_demo_org', stdout=StringIO())
    return Organisations.objects.get(slug=DEMO_ORG_SLUG)


def _ensure_claude():
    # Present on every real install via the org_settings migrations; created
    # here so the tests do not depend on migration data surviving test setup.
    provider, _ = AIModelProvider.objects.get_or_create(
        name=DEMO_AI_PROVIDER,
        defaults={'display_name': 'Anthropic Claude', 'default_model': 'claude-sonnet-5', 'is_active': True},
    )
    if not provider.is_active:
        provider.is_active = True
        provider.save(update_fields=['is_active'])
    return provider


def _demo_client(org):
    client = APIClient()
    client.force_authenticate(User.objects.get(organisation=org, is_demo=True))
    return client


class SeedDemoOrgContentShapeTest(TestCase):
    """First run creates what the seed files hold."""

    @classmethod
    def setUpTestData(cls):
        _ensure_claude()
        cls.org = _seed()
        cls.index = seed_files.load_index()
        cls.captured = seed_files.load_seeds(index=cls.index)

    def setUp(self):
        cache.clear()

    # ── Organisation, people ──────────────────────────────────────────

    def test_org_is_flagged_is_demo(self):
        self.assertTrue(self.org.is_demo)
        self.assertEqual(self.org.name, 'Acme Cloud')

    def test_demo_user_exists_and_is_flagged(self):
        user = User.objects.get(email=DEMO_USER_EMAIL)
        self.assertTrue(user.is_demo)
        # Demo user is admin (not viewer) so visitors can *see* every
        # admin surface (Team, AI settings, Sentinel, Audit Log). Writes
        # are blocked by DemoUserMiddleware regardless of role — that
        # middleware is the security boundary, not RBAC.
        self.assertEqual(user.role, 'admin')
        self.assertTrue(user.is_active)
        self.assertEqual(user.organisation_id, self.org.id)

    def test_team_page_shows_everyone_as_active(self):
        users = _demo_client(self.org).get('/api/organisation/team/').json()['users']
        self.assertEqual(len(users), 4)
        self.assertEqual({u['status'] for u in users}, {'active'})
        names = {f"{u['first_name']} {u['last_name']}" for u in users}
        self.assertEqual(names, {'SerOps Demo', *seed_files.requesters(self.captured)})

    def test_team_members_are_the_people_of_the_seed_files(self):
        members = User.objects.filter(organisation=self.org, is_demo=False)
        self.assertEqual(members.count(), 3)
        for member in members:
            self.assertTrue(member.email.endswith('@' + DEMO_MAIL_DOMAIN))
            self.assertFalse(member.has_usable_password())
            self.assertLess(member.last_login, timezone.now())

    def test_team_members_cannot_sign_in(self):
        client = APIClient()
        for member in User.objects.filter(organisation=self.org, is_demo=False):
            for password in ('demo', SEED_DEMO_PLACEHOLDER, member.password or 'x'):
                response = client.post('/api/auth/login', {'email': member.email, 'password': password}, format='json')
                self.assertEqual(response.status_code, 401, member.email)

    def test_demo_sign_in_still_finds_the_demo_user(self):
        response = APIClient().post('/api/auth/demo-login')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['user']['email'], DEMO_USER_EMAIL)

    # ── Projects, services, clusters ──────────────────────────────────

    def test_three_projects_each_on_its_cluster_with_services(self):
        projects = Project.objects.filter(organisation=self.org)
        self.assertEqual(set(projects.values_list('name', flat=True)), {'Fleet', 'Shopfront', 'Studio'})
        for project in projects:
            with self.subTest(project=project.name):
                self.assertEqual(project.cluster.name, cluster_name(project.name.lower()))
                self.assertGreater(project.services.count(), 0)
                self.assertEqual(list(project.environments.values_list('name', flat=True)), ['production'])
                deployment = ProjectDeployment.objects.get(project=project)
                self.assertEqual(deployment.cluster_id, project.cluster_id)
                self.assertEqual(deployment.environment.name, 'production')

    def test_no_cluster_is_left_without_a_project(self):
        clusters = Cluster.objects.filter(organisation=self.org)
        self.assertEqual(clusters.count(), 3)
        for cluster in clusters:
            self.assertEqual(Project.objects.filter(cluster=cluster).count(), 1, cluster.name)
            self.assertEqual(ProjectDeployment.objects.filter(cluster=cluster).count(), 1, cluster.name)

    def test_services_are_the_ones_the_analyses_name(self):
        expected = seed_files.project_services(self.captured)
        for project in Project.objects.filter(organisation=self.org):
            names = sorted(project.services.values_list('name', flat=True))
            self.assertEqual(names, expected[project.name.lower()])
        for (project, component) in OPEN_ISSUES:
            self.assertTrue(ProjectService.objects.filter(project__name=project, name=component).exists())

    def test_integrations_are_the_stores_each_environment_had_with_no_address_or_credential(self):
        stores = {(i.cluster.name, i.provider, tuple(i.capabilities))
                  for i in ObservabilityIntegration.objects.filter(organisation=self.org).select_related('cluster')}
        self.assertEqual(stores, {
            (cluster_name('fleet'), 'elasticsearch', ('logs',)),
            (cluster_name('fleet'), 'gcp', ('metrics',)),
            (cluster_name('fleet'), 'jaeger', ('traces',)),
            (cluster_name('shopfront'), 'loki', ('logs',)),
            (cluster_name('shopfront'), 'prometheus', ('metrics',)),
            (cluster_name('studio'), 'opensearch', ('logs',)),
            (cluster_name('studio'), 'victoriametrics', ('metrics',)),
        })
        for row in ObservabilityIntegration.objects.filter(organisation=self.org):
            with self.subTest(row=row.display_name):
                self.assertEqual((row.host, row.username, row.password, row.extra_config), ('', '', '', {}))
                self.assertIsNone(row.last_health_status)
        delivery = {(i.name, i.provider_type) for i in ProviderIntegration.objects.filter(organisation=self.org)}
        self.assertEqual(delivery, {('Fleet GitHub', 'github'), ('Fleet Jenkins', 'jenkins'),
                                    ('Shopfront GitHub', 'github'), ('Studio Flux', 'flux')})
        for row in ProviderIntegration.objects.filter(organisation=self.org):
            with self.subTest(row=row.name):
                self.assertFalse(row.base_url)
                self.assertEqual((row.credentials, row.token_hint), ({}, ''))
                self.assertEqual(row.get_access_token() or '', '')
        self.assertFalse(CICDBinding.objects.filter(project_service__project__organisation=self.org).exists())

    def test_integration_pages_show_no_address_and_nothing_is_called(self):
        client = _demo_client(self.org)
        listed = client.get('/api/integrations/observability/')
        self.assertEqual(listed.status_code, 200)
        rows = listed.json()
        rows = rows['results'] if isinstance(rows, dict) else rows
        self.assertEqual(len(rows), 7)
        for row in rows:
            self.assertEqual((row['host'], row['username'], row['has_password']), ('', '', False), row['display_name'])
        delivery = client.get('/api/providers/integrations/')
        self.assertEqual(delivery.status_code, 200)
        text = delivery.content.decode()
        self.assertNotIn(SEED_DEMO_PLACEHOLDER, text + listed.content.decode())
        self.assertEqual(len(re.findall(r'"base_url":\s*"[^"]+"', text)), 0)

        # Reads that would reach a store answer without calling one.
        from integrations.registry import IntegrationRegistry
        cluster = Cluster.objects.get(organisation=self.org, name=cluster_name('fleet'))
        for capability in ('logs', 'metrics', 'traces'):
            self.assertIsNone(IntegrationRegistry._first_matching_integration(self.org, capability, cluster=cluster))
        with patch('requests.sessions.Session.request', side_effect=AssertionError('the demo called out')), \
                patch('integrations.views.collect_ingest_health', side_effect=AssertionError('the demo called out')):
            first = ObservabilityIntegration.objects.filter(organisation=self.org).first()
            health = client.get(f'/api/integrations/observability/{first.pk}/ingest-health/')
            self.assertEqual(health.status_code, 200)
            self.assertTrue(health.json()['demo'])
            # health-check-all is a POST since audit item 2 (20 Nov): a GET is
            # refused (405). A POST reaches no provider either (the patches
            # above raise if it did); with a real token the demo guard
            # middleware refuses it before the view.
            self.assertEqual(client.get('/api/providers/integrations/health-check-all/').status_code, 405)
            self.assertEqual(client.post('/api/providers/integrations/health-check-all/').status_code, 200)
            github = ProviderIntegration.objects.filter(organisation=self.org, provider_type='github').first()
            self.assertEqual(client.get(f'/api/providers/integrations/{github.pk}/repos/').json()['results'], [])
            from providers.services import IntegrationHealthService
            for row in ProviderIntegration.objects.filter(organisation=self.org):
                self.assertEqual(IntegrationHealthService(row).check_health()['details'], {'demo': True})
            # A health check is a write, which the demo middleware refuses
            # (Middlewares tests); were it to get through, it calls nothing.
            checked = client.post(f'/api/integrations/observability/{first.pk}/health-check/')
            self.assertTrue(checked.json()['demo'])

    def test_one_oncall_channel_that_cannot_send_and_no_budget(self):
        from notifications.incident_dispatcher import _is_demo_placeholder
        from notifications.incident_channel_views import IncidentNotificationChannelSerializer
        channels = IncidentNotificationChannel.objects.filter(organisation=self.org)
        self.assertEqual([(c.name, c.kind, c.min_severity, c.is_active) for c in channels],
                         [('Acme on-call (Slack)', 'slack', 'CRITICAL', True)])
        channel = channels.get()
        self.assertEqual(channel.get_webhook_url(), SEED_DEMO_PLACEHOLDER)
        self.assertEqual(channel.api_key, '')
        # The dispatcher skips it, and the API says only that a webhook is set.
        self.assertTrue(_is_demo_placeholder(channel))
        shown = IncidentNotificationChannelSerializer(channel).data
        self.assertTrue(shown['has_webhook_url'])
        self.assertNotIn('SEED_DEMO_PLACEHOLDER', str(shown))
        self.assertIsNone(OrganisationAISettings.objects.get(organisation=self.org).monthly_budget_usd)

    def test_one_routing_rule_by_severity_and_environment(self):
        rule = NotificationRoutingRule.objects.get(organisation=self.org, name='Production critical to on-call')
        self.assertEqual((rule.is_active, rule.min_severity, rule.environments, rule.services, rule.event_types),
                         (True, 'CRITICAL', ['production'], [], []))
        self.assertEqual(list(rule.targets.values_list('name', flat=True)), ['Acme on-call (Slack)'])
        self.assertTrue(rule.matches(event='batch_analyzed', severity='CRITICAL', environment='production', service=''))
        self.assertFalse(rule.matches(event='batch_analyzed', severity='WARNING', environment='production', service=''))

    # ── Analyses ──────────────────────────────────────────────────────

    def test_one_batch_per_seed_file_all_started_by_hand(self):
        batches = AIAnalyzedBatch.objects.filter(organisation=self.org)
        self.assertEqual(batches.count(), 14)
        self.assertEqual(batches.count(), len(self.index['files']))
        for batch in batches:
            with self.subTest(batch=batch.batch_id):
                self.assertEqual(batch.trigger, 'manual')
                self.assertEqual((batch.sentinel_decision, batch.sentinel_triggers), ('manual', []))
                self.assertFalse(batch.ai_skipped)
                self.assertIsNotNone(batch.investigation)
                self.assertEqual(batch.investigation.status, 'done')
                self.assertEqual(batch.investigation.project_id, batch.project_id)
                self.assertIsNotNone(batch.investigation.requested_by)
                self.assertTrue(batch.analyzed_at)
                self.assertEqual(batch.deployment.project_id, batch.project_id)
        self.assertEqual(Investigation.objects.filter(organisation=self.org).count(), 14)
        self.assertFalse(AlertEvent.objects.filter(organisation=self.org).exists())

    def test_batches_are_written_as_captured(self):
        delta = AIAnalyzedBatch.objects.filter(organisation=self.org).latest('timestamp').timestamp \
            - max(parse_time(doc['anchor']) for _, doc in self.captured)
        self.assertEqual(delta, timedelta(days=delta.days))
        for name, doc in self.captured:
            shifted = seed_files.shift_seed(doc, delta, self.index)
            captured = shifted['batch']
            batch = AIAnalyzedBatch.objects.get(batch_id=seed_files.stable_batch_id(name))
            with self.subTest(batch=batch.batch_id):
                self.assertEqual(batch.analysis_text, doc['batch']['analysis_text'])
                self.assertEqual(batch.timestamp, parse_time(captured['timestamp']))
                self.assertEqual(batch.created_at, parse_time(captured['created_at']))
                self.assertEqual(batch.analyzed_at, parse_time(captured['analyzed_at']))
                for field in ('issue_count', 'logs_analyzed', 'token_count', 'logs_raw_count',
                              'logs_after_severity_filter', 'logs_unique_patterns', 'logs_sent_to_ai',
                              'indices_covered'):
                    self.assertEqual(getattr(batch, field), captured[field], field)
                for key, value in captured['data'].items():
                    self.assertEqual(batch.data[key], value, key)
                self.assertEqual(len(batch.data['logs']), doc['trim']['logs_kept'])
                self.assertEqual((batch.data['logs_kept'], batch.data['logs_total']),
                                 (doc['trim']['logs_kept'], doc['trim']['logs_total']))
                inv = batch.investigation
                self.assertEqual(inv.window_start, parse_time(shifted['investigation']['window_start']))
                self.assertEqual(inv.counts, doc['investigation']['counts'])
                self.assertEqual(f'{inv.requested_by.first_name} {inv.requested_by.last_name}',
                                 doc['investigation']['requested_by'])

    def test_batch_ids_are_stable_and_the_captured_ids_are_gone(self):
        batches = AIAnalyzedBatch.objects.filter(organisation=self.org)
        expected = {seed_files.stable_batch_id(name) for name, _ in self.captured}
        self.assertEqual(set(batches.values_list('batch_id', flat=True)), expected)
        self.assertIn('acme-fleet-k7-r1', expected)
        self.assertEqual(len(expected), 14)
        for batch_id in expected:
            self.assertRegex(batch_id, r'^acme-[a-z0-9-]+$')
            self.assertNotRegex(batch_id, r'\d{6}')

        # A captured id is <project>-batch-<14 digits>-<hex>: none is left in
        # what is stored, nor in what the pages are served.
        captured_id = re.compile(r'-batch-\d{14}-')
        client = _demo_client(self.org)
        for batch in batches:
            stored = json.dumps([batch.data, batch.analysis_text, batch.analysis_history, batch.indices_covered])
            self.assertIsNone(captured_id.search(stored), batch.batch_id)
            for url in (f'/api/data/batches/{batch.batch_id}/', f'/api/data/batches/{batch.batch_id}/timeline/',
                        f'/api/data/batches/{batch.batch_id}/history/', f'/api/data/issues/{batch.batch_id}/'):
                response = client.get(url)
                self.assertEqual(response.status_code, 200, url)
                self.assertIsNone(captured_id.search(response.content.decode()), url)
        for url in ('/api/data/issues/', '/api/data/investigations/', '/api/data/batches',
                    '/api/data/analytics/feed/', '/api/notification/noti/', '/api/data/settings/audit-log/'):
            body = client.get(url).content.decode()
            self.assertIsNone(captured_id.search(body), url)
        for row in client.get('/api/data/issues/').json()['results']:
            self.assertIn(row['batch_id_str'], expected)
        for row in client.get('/api/data/investigations/').json()['results']:
            self.assertIn(row['batch_id'], expected)
        for model, fields in ((Issue, ('description', 'root_cause', 'recommendation', 'reasoning',
                                       'correlation_details', 'linked_commits')),
                              (Notification, ('batch_id', 'subject', 'message'))):
            lookup = {'organisation': self.org} if model is Issue else {'user__organisation': self.org}
            for row in model.objects.filter(**lookup):
                self.assertIsNone(captured_id.search(json.dumps([getattr(row, f) for f in fields])))

    def test_the_model_shown_is_the_one_that_answered(self):
        batches = AIAnalyzedBatch.objects.filter(organisation=self.org)
        self.assertEqual(set(batches.values_list('model_name', flat=True)), {MODEL_USED})
        for batch in batches:
            self.assertEqual({entry['model_name'] for entry in batch.analysis_history}, {MODEL_USED})
        client = _demo_client(self.org)
        batch = batches.first()
        self.assertEqual(client.get(f'/api/data/batches/{batch.batch_id}/').json()['model_name'], MODEL_USED)
        self.assertEqual(client.get(f'/api/data/batches/{batch.batch_id}/history/').json()['current_model'], MODEL_USED)
        listed = client.get('/api/data/batches').json()['results']
        self.assertEqual({row['model_name'] for row in listed}, {MODEL_USED})

    def test_batch_detail_says_how_many_log_lines_are_kept(self):
        client = _demo_client(self.org)
        trimmed = [b for b in AIAnalyzedBatch.objects.filter(organisation=self.org)
                   if b.data['logs_kept'] < b.data['logs_total']]
        self.assertGreater(len(trimmed), 0)
        data = client.get(f'/api/data/batches/{trimmed[0].batch_id}/').json()['data']
        self.assertEqual(len(data['logs']), data['logs_kept'])
        self.assertLess(data['logs_kept'], data['logs_total'])

    # ── Issues ────────────────────────────────────────────────────────

    def _issues(self):
        return {(i.project.name, i.component, i.pk): i
                for i in Issue.objects.filter(organisation=self.org).select_related('project', 'resolved_by')}

    def test_issue_count_and_statuses(self):
        issues = Issue.objects.filter(organisation=self.org).select_related('project', 'resolved_by')
        self.assertEqual(issues.count(), 10)
        still_open = {(i.project.name, i.component) for i in issues if i.status == 'OPEN'}
        self.assertEqual(still_open, OPEN_ISSUES)
        resolved = [i for i in issues if i.status == 'RESOLVED']
        self.assertEqual(len(resolved), 7)
        self.assertEqual(len(resolved) + len(still_open), issues.count())
        team = set(User.objects.filter(organisation=self.org, is_demo=False).values_list('pk', flat=True))
        for issue in resolved:
            with self.subTest(issue=issue.component):
                self.assertTrue(issue.resolution_root_cause.strip())
                self.assertTrue(issue.resolution_fix.strip())
                self.assertIn(issue.resolved_by_id, team)
                self.assertGreaterEqual(issue.resolved_at, issue.last_seen_at)
        for issue in issues:
            if issue.status == 'OPEN':
                self.assertIsNone(issue.resolved_at)
                self.assertIsNone(issue.resolved_by)
                self.assertFalse(issue.resolution_root_cause)
                self.assertFalse(issue.resolution_fix)

    def test_severities(self):
        issues = Issue.objects.filter(organisation=self.org)
        by_severity = {s: issues.filter(severity=s).count() for s in ('CRITICAL', 'WARNING', 'INFO')}
        self.assertEqual(by_severity, {'CRITICAL': 7, 'WARNING': 3, 'INFO': 0})
        self.assertEqual(issues.filter(status='OPEN', severity='CRITICAL').count(), 3)

    def test_one_issue_per_deduplicated_issue_with_an_occurrence_per_analysis(self):
        issues = Issue.objects.filter(organisation=self.org).select_related('project')
        for issue in issues:
            expected = OCCURRENCES.get((issue.project.name, issue.component), 1)
            with self.subTest(issue=f'{issue.project.name}/{issue.component}'):
                occurrences = list(IssueOccurrence.objects.filter(issue=issue).order_by('seen_at'))
                self.assertEqual(len(occurrences), expected)
                # The owner's rule: counted and dated from the seeded analyses.
                self.assertEqual(issue.occurrence_count, expected)
                self.assertEqual(issue.last_seen_at, occurrences[-1].seen_at)
                self.assertLessEqual(abs((issue.created_at - occurrences[0].seen_at).total_seconds()), 1)
                self.assertEqual(issue.batch_id, occurrences[-1].batch_id)
        self.assertEqual(IssueOccurrence.objects.filter(issue__organisation=self.org).count(), 13)
        # Both runs of the checkoutservice incident raised an issue of their own.
        self.assertEqual(issues.filter(project__name='Shopfront', component='checkoutservice').count(), 2)

    def test_the_repeated_payments_incident_is_one_issue_seen_twice(self):
        issue = Issue.objects.get(organisation=self.org, project__name='Studio', component='payments')
        batches = [o.batch.batch_id for o in issue.occurrences.order_by('seen_at')]
        self.assertEqual(len(batches), 2)
        self.assertEqual(issue.occurrence_count, 2)
        self.assertNotEqual(batches[0], batches[1])

    def test_issue_rows_are_the_last_analysis_version(self):
        merged = {e['capture_ref']: e for e in seed_files.merge_issues(self.captured)}
        self.assertEqual(len(merged), 10)
        for entry in merged.values():
            row = entry['sightings'][-1]['issue']
            issue = Issue.objects.get(organisation=self.org, description=row['description'])
            for field in ('severity', 'root_cause', 'recommendation', 'reasoning', 'confidence', 'issue_type',
                          'scope', 'component', 'affected_services', 'environment', 'error_class', 'error_target',
                          'has_commit_correlation', 'has_metric_correlation', 'linked_commits',
                          'metric_correlation_type', 'correlation_confidence', 'metric_anomaly_type',
                          'correlation_details', 'has_cicd_correlation'):
                self.assertEqual(getattr(issue, field), row[field], f"{entry['capture_ref']} {field}")
            # Each analysis keeps the severity and type it reported.
            for sighting, occurrence in zip(entry['sightings'], issue.occurrences.order_by('seen_at')):
                self.assertEqual((occurrence.severity, occurrence.issue_type),
                                 (sighting['issue']['severity'], sighting['issue']['issue_type']))

    def test_every_batch_with_an_issue_lists_it_on_its_issues_page(self):
        # The batch issues page reads through IssueOccurrence; seeding only
        # Issue.batch made each batch say "1 issue" yet list none.
        client = _demo_client(self.org)
        batches = AIAnalyzedBatch.objects.filter(organisation=self.org, issue_occurrences__isnull=False).distinct()
        self.assertEqual(batches.count(), 12)
        for batch in batches:
            response = client.get(f'/api/data/issues/{batch.batch_id}/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()['results']), batch.issue_count, batch.batch_id)
            self.assertEqual(batch.issue_occurrences.count(), batch.issue_count, batch.batch_id)

    def test_resolution_notes_are_the_teams_not_the_ais(self):
        resolutions = seed_files.load_resolutions()
        merged = {e['capture_ref']: e for e in seed_files.merge_issues(self.captured)}
        self.assertEqual(set(resolutions), set(merged))
        self.assertEqual(sum(1 for r in resolutions.values() if r['keep_open']), 3)
        for ref, note in resolutions.items():
            with self.subTest(issue=ref):
                self.assertEqual(note['written_by'], 'SerOps team, from the injection record')
                self.assertEqual(note['seeds'], [s['seed'] for s in merged[ref]['sightings']])
                row = merged[ref]['sightings'][-1]['issue']
                issue = Issue.objects.get(organisation=self.org, description=row['description'])
                if note['keep_open']:
                    self.assertEqual(issue.status, 'OPEN')
                    continue
                self.assertEqual(issue.resolution_root_cause, note['resolution_root_cause'])
                self.assertEqual(issue.resolution_fix, note['resolution_fix'])
                # The AI's own text stays what the analysis wrote.
                self.assertEqual(issue.root_cause, row['root_cause'])
                self.assertNotEqual(issue.resolution_root_cause, issue.root_cause)
        payload = _demo_client(self.org).get('/api/data/issues/?status=RESOLVED').json()['results']
        self.assertTrue(payload)
        for row in payload:
            self.assertIn(row['resolved_by_name'], seed_files.requesters(self.captured))

    def test_replaced_values_file_is_what_the_loader_computes(self):
        path = os.path.join(seed_files.SEED_DIR, seed_files.REPLACED_VALUES_FILE)
        with open(path, encoding='utf-8') as handle:
            stored = handle.read()
        self.assertEqual(stored, seed_files.dump_replaced_values(self.captured))
        rows = json.loads(stored)['issues']
        self.assertEqual(len(rows), 10)
        noted = sorted(r['capture_ref'] for r in rows if r.get('note'))
        self.assertEqual(noted, ['shopfront-issue-7'])
        # Batch ids: the stable id per seed file, and no captured id.
        stable = json.loads(stored)['batch_ids']['stable_ids']
        self.assertEqual(stable, {name + '.json.gz': seed_files.stable_batch_id(name) for name, _ in self.captured})
        self.assertNotRegex(stored, r'-batch-\d{14}-')

    # ── No AI spend ───────────────────────────────────────────────────

    def test_a_demo_visitor_cannot_reopen_a_resolved_issue(self):
        """The Reopen button is shown on a resolved issue; the demo refuses it."""
        issue = Issue.objects.filter(organisation=self.org, status='RESOLVED').first()
        note = issue.resolution_root_cause
        token = APIClient().post('/api/auth/demo-login').json()['token']
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {token}')
        response = client.post(f'/api/data/issues/{issue.pk}/reopen/')
        self.assertEqual(response.status_code, 403)
        issue.refresh_from_db()
        self.assertEqual(issue.status, 'RESOLVED')
        self.assertEqual(issue.resolution_root_cause, note)

    def test_no_ai_usage_is_seeded(self):
        self.assertFalse(AITokenUsage.objects.filter(organisation=self.org).exists())
        self.assertFalse(Pipeline.objects.filter(organisation=self.org).exists())
        self.assertFalse(CodeChange.objects.filter(organisation=self.org).exists())

    def test_dashboards_answer_with_zero_spend(self):
        client = _demo_client(self.org)
        cluster = Cluster.objects.filter(organisation=self.org).first()
        urls = [
            '/api/data/analytics/health/', '/api/data/analytics/services/', '/api/data/analytics/trends/',
            '/api/data/analytics/mttr/', '/api/data/analytics/service-health/', '/api/data/analytics/root-causes/',
            '/api/data/analytics/deployments/', '/api/data/analytics/correlations/', '/api/data/analytics/feed/',
            '/api/data/analytics/sentinel/', '/api/data/issue-stats/', '/api/data/recommendation-stats/',
            '/api/settings/ai/', '/api/settings/ai/budget/', '/api/settings/sentinel/',
            '/api/notification/noti/', '/api/data/investigations/', '/api/data/settings/audit-log/',
            '/api/data/settings/data-usage/', '/api/data/batches', '/api/data/issues/', '/api/traces/traces/',
            '/api/chat/chat-sessions/',
        ]
        for url in urls:
            for query in ('', '?days=30', f'?environment=production&cluster={cluster.pk}'):
                response = client.get(url + query)
                self.assertEqual(response.status_code, 200, url + query)
                self.assertNotIn('error', response.json() if isinstance(response.json(), dict) else {}, url + query)

        sentinel = client.get('/api/data/analytics/sentinel/?days=30').json()
        self.assertEqual(sentinel['total_batches'], 14)
        self.assertEqual(sentinel['decisions']['manual'], 14)
        self.assertEqual((sentinel['ai_spend_usd'], sentinel['estimated_cost_saved_usd'],
                          sentinel['estimated_tokens_saved'], sentinel['ai_skipped']), (0, 0, 0, 0))
        budget = client.get('/api/settings/ai/budget/').json()
        self.assertEqual(float(budget['current_spend_usd']), 0)
        self.assertIsNone(budget['monthly_budget_usd'])
        self.assertFalse(budget['is_warning'] or budget['is_exceeded'])

    def test_digest_figures_are_counted_from_the_seeded_issues(self):
        digest = Notification.objects.get(user__organisation=self.org, notification_type='digest')
        issues = Issue.objects.filter(organisation=self.org)
        resolved, still_open = issues.filter(status='RESOLVED').count(), issues.filter(status='OPEN').count()
        self.assertEqual(digest.subject, f'Digest: {resolved} issues resolved, {still_open} open')
        self.assertIn(f'raised {issues.count()} issues', digest.message)
        for component in issues.filter(status='OPEN').values_list('component', flat=True):
            self.assertIn(component, digest.message)
        unread = Notification.objects.filter(user__organisation=self.org, is_read=False)
        self.assertEqual(unread.count(), issues.filter(status='OPEN', severity='CRITICAL').count())

    def test_audit_log_holds_the_investigations_and_nothing_else(self):
        entries = AuditLog.objects.filter(organisation=self.org)
        self.assertEqual(set(entries.values_list('action', flat=True)), {'INVESTIGATION_RUN'})
        self.assertEqual(entries.count(), 14)
        for inv in Investigation.objects.filter(organisation=self.org):
            entry = entries.get(details__investigation_id=inv.id)
            self.assertEqual((entry.user_id, entry.created_at), (inv.requested_by_id, inv.created_at))

    # ── Time ──────────────────────────────────────────────────────────

    def test_newest_analysis_is_yesterday(self):
        newest = AIAnalyzedBatch.objects.filter(organisation=self.org).latest('timestamp')
        self.assertEqual(newest.timestamp.date(), timezone.now().date() - timedelta(days=1))

    def test_every_time_of_a_batch_lies_in_its_window(self):
        """Logs, metrics, change events, issue sightings and the
        investigation itself, between the start of the window and the end
        of the analysis, 15 minutes either side.

        One kind of value is outside on purpose and is only checked
        against the end: ``container_lifecycle.changes`` in the metrics,
        the rollouts SerOps reads from before the window to explain what
        it sees in it. The seed index does not flag them; the two things
        it does flag do not reach this check (an issue first raised
        before its batch is dated by the owner's rule, and the trace rows
        stored after the window are within the 15 minutes).
        """
        now = timezone.now()
        checked = 0
        for batch in AIAnalyzedBatch.objects.filter(organisation=self.org).select_related('investigation'):
            inv = batch.investigation
            low, high = inv.window_start - MARGIN, batch.analyzed_at + MARGIN
            times = {'investigation': [inv.window_start, inv.window_end, inv.created_at,
                                       inv.started_at, inv.finished_at],
                     'batch': [batch.timestamp, batch.created_at, batch.analyzed_at],
                     'log': [parse_time(line['_source']['@timestamp']) for line in batch.data['logs']],
                     'cicd log': [parse_time(line['timestamp']) for line in batch.data.get('cicd_logs') or []],
                     'change event': [parse_time(e['timestamp']) for e in batch.data.get('change_events') or []],
                     'metric': [], 'issue': []}
            before_window = []
            for name, series in (batch.data.get('metrics') or {}).items():
                if isinstance(series, list):
                    times['metric'] += [parse_time(p['time']) for p in series if isinstance(p, dict) and p.get('time')]
                elif name == 'container_lifecycle':
                    before_window += [parse_time(c['at']) for c in series.get('changes') or []]
            for occurrence in batch.issue_occurrences.select_related('issue'):
                times['issue'].append(occurrence.seen_at)
            for issue in Issue.objects.filter(batch=batch):
                times['issue'] += [issue.last_seen_at] + ([issue.resolved_at] if issue.resolved_at else [])
            first_sightings = IssueOccurrence.objects.filter(batch=batch)
            for occurrence in first_sightings:
                if not IssueOccurrence.objects.filter(issue=occurrence.issue, seen_at__lt=occurrence.seen_at).exists():
                    times['issue'].append(occurrence.issue.created_at)
            for kind, values in times.items():
                for value in values:
                    self.assertTrue(low <= value <= high, f'{batch.batch_id}: {kind} time {value} outside window')
                    checked += 1
            for value in before_window:
                self.assertLessEqual(value, high, f'{batch.batch_id}: container change {value}')
            for value in [v for values in times.values() for v in values] + before_window:
                self.assertLess(value, now)
        self.assertGreater(checked, 5000)

    def test_nothing_is_in_the_future(self):
        now = timezone.now()
        naive_now = now.astimezone(dt_timezone.utc).replace(tzinfo=None)
        for batch in AIAnalyzedBatch.objects.filter(organisation=self.org):
            stored = {'data': batch.data, 'history': batch.analysis_history, 'id': batch.batch_id}
            for path, fmt, moment in walk_times(stored, TimeContext(batch.timestamp)):
                if fmt != 'date':
                    self.assertLess(moment, naive_now, f'{batch.batch_id} {path}')
        for model, fields in ((Issue, ('created_at', 'last_seen_at', 'resolved_at')),
                              (Investigation, ('created_at', 'started_at', 'finished_at', 'window_end')),
                              (Trace, ('start_time', 'end_time')),
                              (AuditLog, ('created_at',))):
            for row in model.objects.filter(organisation=self.org):
                for field in fields:
                    value = getattr(row, field)
                    if value is not None:
                        self.assertLess(value, now, f'{model.__name__}.{field}')
        for span in Span.objects.filter(trace__organisation=self.org):
            self.assertLess(span.end_time, now)
        for occurrence in IssueOccurrence.objects.filter(issue__organisation=self.org):
            self.assertLess(occurrence.seen_at, now)
        for user in User.objects.filter(organisation=self.org):
            self.assertLessEqual(user.last_login, now)

    # ── Traces and links ──────────────────────────────────────────────

    def test_only_the_traces_of_the_seed_files_are_stored(self):
        stored = set(Trace.objects.filter(organisation=self.org).values_list('trace_id', flat=True))
        in_files = {item['trace_id'] for _, doc in self.captured for item in doc['traces'].get('items') or []}
        self.assertTrue(stored)
        self.assertLessEqual(stored, in_files)
        # One trace has a span id SerOps' own redaction masked at capture
        # time: it is left out rather than stored with a made-up id.
        self.assertEqual(len(in_files - stored), 1)
        for trace in Trace.objects.filter(organisation=self.org):
            self.assertEqual(trace.spans.count(), trace.span_count)

    def test_batch_detail_marks_the_traces_that_cannot_be_opened(self):
        client = _demo_client(self.org)
        stored = set(Trace.objects.filter(organisation=self.org).values_list('trace_id', flat=True))
        seen = 0
        for batch in AIAnalyzedBatch.objects.filter(organisation=self.org):
            if not (batch.data.get('traces') or {}).get('top_errors'):
                continue
            detail = client.get(f'/api/data/batches/{batch.batch_id}/').json()
            spans = detail['data']['traces']['top_errors'] + detail['data']['traces']['top_slow']
            spans += [s for i in detail['issues'] for s in i['related_traces']['top_errors']]
            for span in spans:
                self.assertEqual(span['trace_stored'], span['trace_id'] in stored)
                seen += 1
            timeline = client.get(f'/api/data/batches/{batch.batch_id}/timeline/').json()
            for event in timeline['events']:
                if event['detail'].get('trace_id'):
                    self.assertEqual(event['detail']['trace_stored'], event['detail']['trace_id'] in stored)
            # The stored row is not changed by the answer.
            batch.refresh_from_db()
            self.assertNotIn('trace_stored', batch.data['traces']['top_errors'][0])
        self.assertGreater(seen, 0)

    def test_linked_commits_say_whether_the_batch_holds_them(self):
        rows = _demo_client(self.org).get('/api/data/issues/').json()['results']
        flags = {}
        for row in rows:
            batch = AIAnalyzedBatch.objects.get(batch_id=row['batch_id_str'])
            shas = [c['sha'] for c in batch.data['code_changes']]
            for commit in row['linked_commits']:
                self.assertEqual(commit['in_batch'], any(s.startswith(commit['sha']) for s in shas))
                flags[commit['sha']] = commit['in_batch']
            for entry in row['correlation_summary']:
                if entry['type'] == 'commit':
                    self.assertEqual(entry['in_batch'], flags[entry['value']])
        self.assertIn(True, flags.values())
        self.assertIn(False, flags.values())

    # ── Nothing real ──────────────────────────────────────────────────

    def test_no_real_address_host_or_mailbox_in_the_seeded_content(self):
        chunks = []
        for batch in AIAnalyzedBatch.objects.filter(organisation=self.org):
            chunks.append(json.dumps([batch.batch_id, batch.data, batch.analysis_text, batch.analysis_history,
                                      batch.indices_covered]))
        for issue in Issue.objects.filter(organisation=self.org):
            chunks.append(json.dumps([issue.description, issue.root_cause, issue.recommendation, issue.reasoning,
                                      issue.error_target, issue.affected_services, issue.linked_commits,
                                      issue.correlation_details, issue.resolution_root_cause, issue.resolution_fix]))
        for inv in Investigation.objects.filter(organisation=self.org):
            chunks.append(json.dumps([inv.hint, inv.services, inv.counts, inv.error]))
        for span in Span.objects.filter(trace__organisation=self.org):
            chunks.append(json.dumps([span.service_name, span.operation_name, span.status_message,
                                      span.attributes, span.events]))
        for user in User.objects.filter(organisation=self.org, is_demo=False):
            chunks.append(json.dumps([user.email, user.username, user.first_name, user.last_name]))
        for note in Notification.objects.filter(user__organisation=self.org):
            chunks.append(json.dumps([note.subject, note.message]))
        for project in Project.objects.filter(organisation=self.org):
            chunks.append(json.dumps([project.name, project.description, project.cluster.name,
                                      list(project.services.values_list('name', 'description'))]))
        chunks.append(json.dumps([self.org.name, self.org.website]))
        text = '\n'.join(chunks)

        self.assertNotIn('gmail', text.lower())
        mailboxes = {m.group(0) for m in RX_EMAIL.finditer(text)}
        self.assertEqual({m for m in mailboxes if not m.lower().endswith('@' + DEMO_MAIL_DOMAIN)}, set())

        # In-cluster service names (http://payments.studio:8080) are not hosts
        # on the internet: their last label is the namespace or "svc".
        internal = {'fleet', 'shopfront', 'studio', 'shop', 'svc', 'local'}
        bad = set()
        for match in RX_URL.finditer(text):
            host, path = match.group(1).lower().rstrip('.'), match.group(2) or ''
            if host == DEMO_MAIL_DOMAIN or host.endswith('.' + DEMO_MAIL_DOMAIN):
                continue
            if host in KEPT_PUBLIC_HOSTS or host.rsplit('.', 1)[-1] in internal:
                continue
            bad.add(host)
        self.assertEqual(bad, set())


class SeedDemoOrgIdempotencyTest(TestCase):
    """Running the command twice must not produce duplicates or fail."""

    @staticmethod
    def _state(org):
        return {
            'projects': sorted(Project.objects.filter(organisation=org).values_list('id', 'name')),
            'services': sorted(ProjectService.objects.filter(project__organisation=org).values_list('id', 'name')),
            'clusters': sorted(Cluster.objects.filter(organisation=org).values_list('id', 'name')),
            'environments': sorted(ProjectEnvironment.objects.filter(
                project__organisation=org).values_list('id', 'name')),
            'deployments': sorted(ProjectDeployment.objects.filter(
                project__organisation=org).values_list('id', flat=True)),
            'users': sorted(User.objects.filter(organisation=org).values_list('id', 'email')),
            'ingest keys': sorted(IngestKey.objects.filter(organisation=org).values_list('id', 'key_hash')),
            'batches': sorted(AIAnalyzedBatch.objects.filter(organisation=org).values_list('batch_id', flat=True)),
            'issues': Issue.objects.filter(organisation=org).count(),
            'open': Issue.objects.filter(organisation=org, status='OPEN').count(),
            'occurrences': IssueOccurrence.objects.filter(issue__organisation=org).count(),
            'investigations': Investigation.objects.filter(organisation=org).count(),
            'traces': Trace.objects.filter(organisation=org).count(),
            'spans': Span.objects.filter(trace__organisation=org).count(),
            'chats': ChatSession.objects.filter(user__organisation=org).count(),
            'notifications': Notification.objects.filter(user__organisation=org).count(),
            'audit': AuditLog.objects.filter(organisation=org).count(),
            'usage': AITokenUsage.objects.filter(organisation=org).count(),
            'channels': sorted(IncidentNotificationChannel.objects.filter(
                organisation=org).values_list('name', flat=True)),
            'rules': sorted(NotificationRoutingRule.objects.filter(
                organisation=org).values_list('id', 'name')),
        }

    def test_second_run_gives_the_same_rows_and_keeps_the_stable_ids(self):
        org = _seed()
        first = self._state(org)
        _seed()
        self.assertEqual(self._state(org), first)
        self.assertEqual(len(first['batches']), 14)


class SeedDemoOrgStableLinksTest(TestCase):
    """A link to a demo analysis works whatever day the seed last ran."""

    @staticmethod
    def _links(org):
        issues = Issue.objects.filter(organisation=org).select_related('batch')
        return {
            'batches': sorted(AIAnalyzedBatch.objects.filter(organisation=org).values_list('batch_id', flat=True)),
            'issue batch': sorted((i.description, i.batch.batch_id) for i in issues),
            'occurrences': sorted(IssueOccurrence.objects.filter(issue__organisation=org).values_list(
                'issue__description', 'batch__batch_id')),
            'investigations': sorted(
                (inv.batch.batch_id, inv.project.name, inv.requested_by.email, inv.window_end - inv.window_start)
                for inv in Investigation.objects.filter(organisation=org).select_related(
                    'batch', 'project', 'requested_by')),
            'notifications': sorted(Notification.objects.filter(
                user__organisation=org, notification_type='critical_issue').values_list('batch_id', flat=True)),
        }

    def test_two_seed_dates_give_the_same_ids_and_links(self):
        from Data.management.commands.seed_demo_org import Command
        first_now = datetime(2027, 3, 1, 2, 0, 0, tzinfo=dt_timezone.utc)
        second_now = first_now + timedelta(days=5, hours=7)
        with patch.object(Command, '_now', staticmethod(lambda: first_now)):
            org = _seed()
        first, first_newest = self._links(org), AIAnalyzedBatch.objects.filter(organisation=org).latest(
            'timestamp').timestamp
        with patch.object(Command, '_now', staticmethod(lambda: second_now)):
            _seed()
        second, second_newest = self._links(org), AIAnalyzedBatch.objects.filter(organisation=org).latest(
            'timestamp').timestamp

        # The dates moved by five days; no id and no link did.
        self.assertEqual(first_newest.date(), first_now.date() - timedelta(days=1))
        self.assertEqual(second_newest - first_newest, timedelta(days=5))
        self.assertEqual(second, first)
        self.assertEqual(len(first['batches']), 14)
        self.assertEqual(len(first['investigations']), 14)
        self.assertEqual(len(first['occurrences']), 13)
        self.assertIn('acme-studio-l10-r1', first['batches'])


class SeedDemoOrgRebuildTest(TestCase):
    """The rebuild removes what an earlier version of the command created."""

    def test_old_seed_content_is_removed(self):
        claude = _ensure_claude()
        gemini, _ = AIModelProvider.objects.get_or_create(
            name='gemini', defaults={'display_name': 'Google Gemini', 'default_model': 'gemini-3.6-flash',
                                     'is_active': True})
        org = Organisations.objects.create(name='Acme Cloud', slug=DEMO_ORG_SLUG, is_demo=True)
        user = User.objects.create(email=DEMO_USER_EMAIL, username='demo', role='admin', is_active=True,
                                   is_demo=True, organisation=org)
        old_cluster = Cluster.objects.create(organisation=org, name='prod-eks', provider='eks')
        old_project = Project.objects.create(name='acme-checkout', organisation=org, cluster=old_cluster)
        ProjectService.objects.create(project=old_project, name='backend-api', service_type='application')
        ObservabilityIntegration.objects.create(
            organisation=org, provider='loki', display_name='Loki', host='https://loki.acme.cloud',
            capabilities=['logs'])
        ProviderIntegration.objects.create(
            organisation=org, provider_type='jenkins', name='Jenkins', category='cicd',
            base_url='https://ci.acme.cloud', credentials={'access_token': SEED_DEMO_PLACEHOLDER})
        IncidentNotificationChannel.objects.create(organisation=org, name='SRE Slack (#incidents)', kind='slack')
        old_batch = AIAnalyzedBatch.objects.create(
            batch_id='demo-05-2-production', organisation=org, project=old_project,
            timestamp=timezone.now(), environment='production', data={})
        AlertEvent.objects.create(organisation=org, source='grafana', external_id='GRF-1', alertname='Old',
                                  triggered_batch=old_batch)
        Pipeline.objects.create(organisation=org, pipeline_id='old-1', cicd_provider='gitlab', status='success')
        AITokenUsage.objects.create(organisation=org, batch=old_batch, model_name='gemini-3.6-flash',
                                    tokens_input=1, tokens_output=1, tokens_total=2, cost_usd='0.01')
        ChatSession.objects.create(user=user, title='Old chat')
        OrganisationAPIKey.objects.create(organisation=org, provider=gemini, api_key='old')
        OrganisationAISettings.objects.create(organisation=org, default_provider=gemini, monthly_budget_usd='100.00')
        IngestKey.objects.create(organisation=org, name='prod-eks-otel-collector', key_hash='0' * 64)

        _seed()

        self.assertEqual(set(Project.objects.filter(organisation=org).values_list('name', flat=True)),
                         {'Fleet', 'Shopfront', 'Studio'})
        self.assertFalse(Cluster.objects.filter(organisation=org, name='prod-eks').exists())
        self.assertFalse(ProjectService.objects.filter(project__organisation=org, name='backend-api').exists())
        # The old rows that pointed at hosts are gone; the ones the demo
        # shows now hold no address.
        self.assertFalse(ObservabilityIntegration.objects.filter(organisation=org).exclude(host='').exists())
        self.assertFalse(ProviderIntegration.objects.filter(organisation=org, base_url__isnull=False).exists())
        self.assertFalse(ProviderIntegration.objects.filter(organisation=org, name='Jenkins').exists())
        # The old placeholder channel is gone; only the on-call example is left.
        self.assertEqual(list(IncidentNotificationChannel.objects.filter(organisation=org)
                              .values_list('name', flat=True)), ['Acme on-call (Slack)'])
        self.assertIsNone(OrganisationAISettings.objects.get(organisation=org).monthly_budget_usd)
        self.assertFalse(AIAnalyzedBatch.objects.filter(batch_id='demo-05-2-production').exists())
        self.assertFalse(AlertEvent.objects.filter(organisation=org).exists())
        self.assertFalse(Pipeline.objects.filter(organisation=org).exists())
        self.assertFalse(AITokenUsage.objects.filter(organisation=org).exists())
        # The old chat is gone; the three seeded conversations take its place.
        self.assertFalse(ChatSession.objects.filter(user__organisation=org, title='Old chat').exists())
        self.assertEqual(ChatSession.objects.filter(user__organisation=org).count(), 3)
        self.assertEqual(list(OrganisationAPIKey.objects.filter(organisation=org).values_list('provider', flat=True)),
                         [claude.pk])
        self.assertEqual(OrganisationAISettings.objects.get(organisation=org).default_provider, claude)
        self.assertEqual(list(IngestKey.objects.filter(organisation=org).values_list('name', flat=True)),
                         ['otel-collector'])
        # The demo user is the same row.
        self.assertEqual(User.objects.get(email=DEMO_USER_EMAIL).pk, user.pk)


class SeedDemoOrgIsolationTest(TestCase):
    """The command must never touch data outside the demo org."""

    def test_existing_org_data_is_left_untouched(self):
        # An unrelated org with its own project, batch, and issue.
        other_org = Organisations.objects.create(name='Real Customer Inc')
        other_project = Project.objects.create(
            name='Fleet', organisation=other_org,
        )
        other_batch = AIAnalyzedBatch.objects.create(
            batch_id='real-batch-1', organisation=other_org,
            project=other_project, timestamp=timezone.now(),
            environment='production', data={},
        )
        other_issue = Issue.objects.create(
            batch=other_batch, project=other_project, organisation=other_org,
            severity='WARNING', description='Real customer issue',
            issue_type='OTHER', component='backend',
            environment='production', fingerprint='real-fp-1',
        )
        other_user = User.objects.create(email='someone@real.example', organisation=other_org, is_active=True)

        _seed()

        # Nothing about the real org should have changed.
        self.assertTrue(Organisations.objects.filter(pk=other_org.pk).exists())
        self.assertTrue(Project.objects.filter(pk=other_project.pk).exists())
        self.assertTrue(AIAnalyzedBatch.objects.filter(pk=other_batch.pk).exists())
        self.assertTrue(Issue.objects.filter(pk=other_issue.pk).exists())
        self.assertTrue(User.objects.filter(pk=other_user.pk, organisation=other_org).exists())

    def test_a_team_address_owned_by_another_org_is_not_taken_over(self):
        other_org = Organisations.objects.create(name='Real Customer Inc')
        taken = User.objects.create(email=f'fleet.on-call@{DEMO_MAIL_DOMAIN}', organisation=other_org, is_active=True)
        taken.set_password('their-own-password')
        taken.save()

        org = _seed()

        taken.refresh_from_db()
        self.assertEqual(taken.organisation_id, other_org.id)
        self.assertTrue(taken.check_password('their-own-password'))
        self.assertEqual(User.objects.filter(organisation=org, is_demo=False).count(), 2)
        self.assertEqual(Investigation.objects.filter(organisation=org).count(), 14)

    def test_dry_run_creates_nothing(self):
        call_command('seed_demo_org', '--dry-run', stdout=StringIO())
        self.assertFalse(
            Organisations.objects.filter(slug=DEMO_ORG_SLUG).exists()
        )


class SeedDemoOrgAIProviderTest(TestCase):
    """The demo org shows the provider that answered its analyses.

    The nightly reset re-runs this command, so the seed is the only place the
    choice can live — a database edit would be undone at 02:00.
    """

    @classmethod
    def setUpTestData(cls):
        cls.claude = _ensure_claude()
        cls.org = _seed()

    def test_primary_provider_is_claude(self):
        settings_row = OrganisationAISettings.objects.get(organisation=self.org)
        self.assertEqual(settings_row.default_provider.name, 'claude')
        self.assertIsNone(settings_row.fallback_provider)

    def test_key_row_is_decryptable_placeholder(self):
        # The model picker lists providers whose key decrypts; a row
        # encrypted under an older SECRET_KEY decrypts to '' and hid the provider.
        from ai_model.ai_service import get_api_key_for_org
        api_key, _, _ = get_api_key_for_org(self.org, 'claude')
        self.assertEqual(api_key, SEED_DEMO_PLACEHOLDER)

    def test_reseed_replaces_an_undecryptable_key(self):
        from ai_model.ai_service import get_api_key_for_org
        OrganisationAPIKey.objects.filter(organisation=self.org, provider=self.claude).update(
            api_key='gAAAAAencrypted-under-a-rotated-secret-key',
        )
        self.assertFalse(get_api_key_for_org(self.org, 'claude')[0])
        _seed()
        self.assertTrue(get_api_key_for_org(self.org, 'claude')[0])

    def test_available_models_lists_claude_for_the_demo_user(self):
        response = _demo_client(self.org).get('/api/settings/ai/available-models/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([m['id'] for m in response.json()['models']], ['claude'])

    def test_model_does_not_follow_the_catalogue(self):
        # The analyses were answered by one model: a later default-model
        # migration must not relabel them.
        self.claude.default_model = 'claude-9-test'
        self.claude.save()
        _seed()
        models = set(AIAnalyzedBatch.objects.filter(organisation=self.org).values_list('model_name', flat=True))
        self.assertEqual(models, {MODEL_USED})


class SeedDemoChatSessionsTest(TestCase):
    """Three real conversations ship with the seed, one per environment."""

    QUESTIONS = [
        'What changed right before this started?',
        'Which services were affected, and what is the evidence for each?',
        'What should I do now, and how do I check that it worked?',
    ]
    ANALYSES = ['acme-fleet-k7-r1', 'acme-shopfront-i1-r1', 'acme-studio-l4-r1']

    def test_the_shipped_files_are_three_conversations_of_three_questions(self):
        chats = seed_files.load_chats()
        self.assertEqual([seed_files.stable_batch_id(c['batch']) for c in chats], self.ANALYSES)
        for chat in chats:
            self.assertEqual(chat['model'], MODEL_USED)
            exchanges = seed_files.chat_exchanges(chat)
            self.assertEqual([question for question, _, _ in exchanges], self.QUESTIONS)
            self.assertTrue(all(len(answer) > 500 for _, answer, _ in exchanges))
            offsets = [m['offset_seconds'] for m in chat['messages']]
            self.assertEqual(offsets, sorted(set(offsets)))
            # What the answers cost is recorded with them, per answer.
            answers = [m for m in chat['messages'] if m['role'] == 'assistant']
            self.assertTrue(all(m['tokens_input'] > 0 and m['tokens_output'] > 0 and m['cost_usd'] for m in answers))

    def test_a_visitor_reads_them_on_their_analyses_and_no_spend_is_loaded(self):
        org = _seed()
        _seed()  # still three after a rebuild
        sessions = ChatSession.objects.filter(user__organisation=org)
        self.assertEqual(sorted(sessions.values_list('batch_id', flat=True)), self.ANALYSES)
        for session in sessions:
            self.assertTrue(session.user.is_demo)
            self.assertTrue(session.is_active)
            batch = AIAnalyzedBatch.objects.get(organisation=org, batch_id=session.batch_id)
            messages = list(ChatMessage.objects.filter(chat_session=session).order_by('timestamp'))
            self.assertEqual([m.message for m in messages], self.QUESTIONS)
            self.assertTrue(all(m.response for m in messages))
            self.assertEqual({m.metadata['ai_model'] for m in messages}, {MODEL_USED})
            self.assertGreater(messages[0].timestamp, batch.analyzed_at)
            self.assertLess(session.last_message_at, timezone.now())
        # The chat's token and cost figures stay in the seed files: the
        # analyses show no cost, so the conversations add none either.
        self.assertFalse(AITokenUsage.objects.filter(organisation=org).exists())
        client = _demo_client(org)
        listed = client.get('/api/chat/chat-sessions/').json()['sessions']
        self.assertEqual(len(listed), 3)
        history = client.get(f"/api/chat/chats/{sessions.first().chat_id}/")
        self.assertEqual(history.status_code, 200)

    def test_a_visitor_still_cannot_send_a_message(self):
        org = _seed()
        user = User.objects.get(organisation=org, is_demo=True)
        from knox.models import AuthToken
        _, token = AuthToken.objects.create(user)
        response = APIClient().post(
            '/api/chat/generate-text/',
            {'type': 'chat', 'ai_model': 'claude', 'prompt': {'message': 'hello'}, 'batch_id': self.ANALYSES[0]},
            format='json', HTTP_AUTHORIZATION=f'Token {token}')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['error'], 'demo_read_only')
        self.assertEqual(ChatMessage.objects.filter(chat_session__user=user).count(), 9)

    def test_chat_files_are_loaded_onto_their_analysis(self):
        chat = {
            'schema': seed_files.CHAT_SCHEMA, 'title': 'Synthetic test chat', 'batch': 'studio-L7-r1',
            'model': MODEL_USED,
            'messages': [
                {'role': 'user', 'text': 'First question', 'offset_seconds': 60},
                {'role': 'assistant', 'text': 'First answer', 'offset_seconds': 70},
                {'role': 'user', 'text': 'Second question', 'offset_seconds': 120},
                {'role': 'assistant', 'text': 'Second answer', 'offset_seconds': 135},
            ],
        }
        with tempfile.TemporaryDirectory() as seed_dir:
            os.mkdir(os.path.join(seed_dir, seed_files.CHAT_DIR))
            with open(os.path.join(seed_dir, seed_files.CHAT_DIR, '01-test.json'), 'w', encoding='utf-8') as out:
                json.dump(chat, out)
            # A chat for an analysis that is not seeded is passed by.
            with open(os.path.join(seed_dir, seed_files.CHAT_DIR, '02-unknown.json'), 'w', encoding='utf-8') as out:
                json.dump(dict(chat, batch='no-such-seed'), out)
            real = seed_files.load_chats
            with patch.object(seed_files, 'load_chats', lambda: real(seed_dir)):
                org = _seed()
                _seed()  # still one session after a rebuild

        session = ChatSession.objects.get(user__organisation=org)
        batch = AIAnalyzedBatch.objects.get(organisation=org, project__name='Studio', issues__component='notifier')
        self.assertEqual((session.title, session.batch_id, session.project_id),
                         ('Synthetic test chat', batch.batch_id, str(batch.project_id)))
        self.assertTrue(session.user.is_demo)
        messages = list(ChatMessage.objects.filter(chat_session=session).order_by('timestamp'))
        self.assertEqual([(m.message, m.response) for m in messages],
                         [('First question', 'First answer'), ('Second question', 'Second answer')])
        self.assertEqual([m.metadata['ai_model'] for m in messages], [MODEL_USED, MODEL_USED])
        self.assertEqual([m.timestamp - batch.analyzed_at for m in messages],
                         [timedelta(seconds=70), timedelta(seconds=135)])
        self.assertLess(session.last_message_at, timezone.now())
        listed = _demo_client(org).get('/api/chat/chat-sessions/').json()['sessions']
        self.assertEqual(len(listed), 1)

    def test_an_unknown_chat_schema_is_refused(self):
        with tempfile.TemporaryDirectory() as seed_dir:
            os.mkdir(os.path.join(seed_dir, seed_files.CHAT_DIR))
            with open(os.path.join(seed_dir, seed_files.CHAT_DIR, 'x.json'), 'w', encoding='utf-8') as out:
                json.dump({'schema': 'other', 'messages': []}, out)
            with self.assertRaises(ValueError):
                seed_files.load_chats(seed_dir)


class SeedDemoTimeShiftTest(SimpleTestCase):
    """One whole number of days, the newest analysis on yesterday."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.index = seed_files.load_index()
        cls.captured = seed_files.load_seeds(index=cls.index)

    def test_delta_is_whole_days_and_lands_on_yesterday_at_any_hour(self):
        newest = seed_files.latest_time(self.captured)
        for now in (datetime(2027, 3, 1, 0, 0, 1, tzinfo=dt_timezone.utc),
                    datetime(2027, 3, 1, 2, 0, 0, tzinfo=dt_timezone.utc),
                    datetime(2027, 3, 1, 23, 59, 59, tzinfo=dt_timezone.utc),
                    datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt_timezone.utc)):
            delta = seed_files.whole_day_delta(self.captured, now)
            self.assertEqual(delta, timedelta(days=delta.days))
            self.assertEqual((newest + delta).date(), now.date() - timedelta(days=1))
            self.assertLess(newest + delta, now)

    def test_every_time_of_a_file_moves_and_clock_times_stay(self):
        delta = timedelta(days=400)
        name, doc = self.captured[0]
        moved = seed_files.shift_seed(doc, delta, self.index)
        scope = {key: moved[key] for key in ('batch', 'investigation', 'issues', 'traces')}
        left = {path for path, fmt, _ in walk_times(scope, TimeContext(doc['anchor']))}
        self.assertEqual(left, set(), name)
        self.assertEqual(parse_time(moved['batch']['timestamp']) - parse_time(doc['batch']['timestamp']), delta)
        # The prose names times of day without a date: it is not touched.
        self.assertEqual(moved['batch']['analysis_text'], doc['batch']['analysis_text'])
        self.assertNotEqual(moved['batch']['batch_id'], doc['batch']['batch_id'])
        stable = seed_files.with_stable_batch_id(name, moved)
        self.assertEqual(stable['batch']['batch_id'], seed_files.stable_batch_id(name))
        self.assertEqual(stable['batch']['data'], moved['batch']['data'])


class SeedDemoSchedulersTest(TestCase):
    """Nothing scheduled reaches out for a demo organisation."""

    def setUp(self):
        cache.clear()
        self.org = _seed()

    def tearDown(self):
        cache.clear()

    @patch('Data.tasks.IntegrationRegistry')
    @patch('providers.tasks.sync_recent_deployments')
    def test_the_batch_scheduler_passes_the_demo_by(self, mock_sync, mock_registry):
        from Data.models import DataRunStatus
        from Data.tasks import create_batches_for_all_projects
        asked = []
        mock_registry.get_log_provider_for_org.side_effect = lambda org, *a, **kw: asked.append(org) or MagicMock()
        before = AIAnalyzedBatch.objects.filter(organisation=self.org).count()
        with patch('celery.group') as mock_group:
            mock_group.return_value.apply_async.return_value = MagicMock(id='grp-1')
            create_batches_for_all_projects()
        self.assertEqual(asked, [])
        self.assertEqual(AIAnalyzedBatch.objects.filter(organisation=self.org).count(), before)
        self.assertFalse(DataRunStatus.objects.filter(project__organisation=self.org).exists())

    def _bind_ci(self, org, project):
        integration = ProviderIntegration.objects.create(
            organisation=org, provider_type='jenkins', name='ci', category='cicd',
            base_url='https://ci.acme.example', credentials={'access_token': 'x'}, is_active=True)
        service = ProjectService.objects.filter(project=project).first() or ProjectService.objects.create(
            project=project, name='svc', service_type='application')
        return CICDBinding.objects.create(
            project_service=service, integration=integration, pipeline_id='job/deploy',
            binding_type='build', pipeline_name='deploy', is_active=True)

    def test_deployment_sync_passes_the_demo_by(self):
        from providers.tasks import sync_recent_deployments
        other_org = Organisations.objects.create(name='Real Customer Inc')
        other_project = Project.objects.create(name='real-app', organisation=other_org)
        demo_binding = self._bind_ci(self.org, Project.objects.filter(organisation=self.org).first())
        real_binding = self._bind_ci(other_org, other_project)

        called = []

        def _provider(binding):
            called.append(binding.pk)
            provider = MagicMock()
            provider.list_recent_pipelines.return_value = []
            return provider

        with patch.object(CICDBinding, 'get_provider', _provider):
            sync_recent_deployments(hours=2)
        self.assertEqual(called, [real_binding.pk])
        self.assertNotIn(demo_binding.pk, called)
        self.assertFalse(Pipeline.objects.filter(organisation=self.org).exists())
