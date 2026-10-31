"""
No API route lets one organisation see or touch another's data.

The admin of organisation B calls every API route:

* Routes without an id in the URL (lists, dashboards, settings): the
  response must not contain organisation A's data. Everything seeded for A
  carries MARKER in its name, so a missing organisation filter shows up as
  the marker in B's response. Each list is also called with A's ids in the
  usual query parameters (``?project=``, ``?batch_id=``…).
* Routes with an id: the id is replaced by A's object (TARGETS), and every
  method the route implements must fail. A 2xx on a write, or A's data in
  a read, is a leak.

A new route with an id fails this test until it is added to TARGETS, so
tenant isolation is checked for every endpoint, the way
test_permission_coverage checks permissions. Outbound HTTP and Celery are
stubbed: a leaking call fails the test without reaching anything.
"""
import re
import uuid
from unittest import mock

import requests
from django.test import TestCase
from django.urls import get_resolver
from django.utils import timezone
from rest_framework.test import APIClient

from Middlewares.tests.test_permission_coverage import HTTP_METHODS, is_public, iter_routes, view_class

MARKER = 'zzvictim'

# Route pattern -> how to fill its ids with organisation A's objects
# ({name: seed key}), or SHARED with the reason it isn't tenant data.
SHARED = 'shared'
TARGETS = {
    'api/organisation/member/<int:id>/': {'id': 'member'},
    'api/organisation/update/<int:id>/': {'id': 'org'},
    'api/organisation/delete/<int:id>/': {'id': 'org'},
    'api/chat/chats/<uuid:chat_id>/': {'chat_id': 'chat'},
    'api/chat/chats/delete/<uuid:chat_id>': {'chat_id': 'chat'},
    'api/chat/chats/<uuid:chat_id>/update/': {'chat_id': 'chat'},
    'api/chat/admin/circuits/<str:provider>/reset/': (SHARED, 'install-wide AI circuit breaker, platform staff only'),
    'api/chat/admin/circuits/<str:provider>/trip/': (SHARED, 'install-wide AI circuit breaker, platform staff only'),
    'api/data/batches/<str:batch_id>/correlations/': {'batch_id': 'batch'},
    'api/data/investigations/<int:pk>/': {'pk': 'investigation'},
    'api/data/batches/<str:batch_id>/history/': {'batch_id': 'batch'},
    'api/data/batches/<str:batch_id>/promote-analysis/': {'batch_id': 'batch'},
    'api/data/batches/<str:batch_id>/timeline/': {'batch_id': 'batch'},
    'api/data/batches/<str:batch_id>/postmortem/': {'batch_id': 'batch'},
    'api/data/batches/<str:batch_id>/': {'batch_id': 'batch'},
    'api/data/issues/<int:issue_id>/similar/': {'issue_id': 'issue'},
    'api/data/issues/<int:issue_id>/<str:action>/': {'issue_id': 'issue', 'action': '=resolve'},
    'api/data/issues/<str:batch_id>/': {'batch_id': 'batch'},
    'api/providers/<int:pk>/': {'pk': 'gitlab_project'},
    'api/providers/<int:project_id>/pipelines/<int:pipeline_id>/logs/': {'project_id': 'gitlab_project', 'pipeline_id': 'pipeline'},
    'api/providers/^integrations/(?P<pk>[^/.]+)/$': {'pk': 'integration'},
    'api/providers/^integrations/(?P<pk>[^/.]+)/health-check/$': {'pk': 'integration'},
    'api/providers/^integrations/(?P<pk>[^/.]+)/repos/$': {'pk': 'integration'},
    'api/providers/^integrations/(?P<pk>[^/.]+)/sync/$': {'pk': 'integration'},
    'api/providers/^integrations/(?P<pk>[^/.]+)/usage/$': {'pk': 'integration'},
    'api/providers/^integrations/(?P<pk>[^/.]+)/verify/$': {'pk': 'integration'},
    'api/notification/^incident-channels/(?P<pk>[^/.]+)/$': {'pk': 'channel'},
    'api/notification/^incident-channels/(?P<pk>[^/.]+)/test-send/$': {'pk': 'channel'},
    'api/notification/^routing-rules/(?P<pk>[^/.]+)/$': {'pk': 'routing_rule'},
    'api/notification/<int:pk>/': {'pk': 'notification'},
    'api/notification/subscriptions/<int:pk>/': {'pk': 'subscription'},
    'api/notification/issues/<int:issue_id>/acknowledge/': {'issue_id': 'issue'},
    'api/notification/escalation-rules/<int:pk>/': {'pk': 'escalation'},
    'api/projects/<int:pk>/': {'pk': 'project'},
    'api/projects/<int:project_id>/services/': {'project_id': 'project'},
    'api/projects/services/<int:pk>/': {'pk': 'project_service'},
    'api/projects/<int:project_id>/custom-services/': {'project_id': 'project'},
    'api/projects/<int:project_id>/data-check/': {'project_id': 'project'},
    'api/projects/<int:project_id>/data-check/fix/': {'project_id': 'project'},
    'api/projects/^scm-bindings/(?P<pk>[^/.]+)/$': {'pk': 'scm_binding'},
    'api/projects/^scm-bindings/(?P<pk>[^/.]+)/auto-link/$': {'pk': 'scm_binding'},
    'api/projects/^scm-bindings/(?P<pk>[^/.]+)/auto-link-suggestions/$': {'pk': 'scm_binding'},
    'api/projects/^scm-bindings/(?P<pk>[^/.]+)/setup-webhook/$': {'pk': 'scm_binding'},
    'api/projects/^scm-bindings/(?P<pk>[^/.]+)/sync/$': {'pk': 'scm_binding'},
    'api/projects/^cicd-bindings/(?P<pk>[^/.]+)/$': {'pk': 'cicd_binding'},
    'api/projects/^cicd-bindings/(?P<pk>[^/.]+)/setup-webhook/$': {'pk': 'cicd_binding'},
    'api/projects/^cicd-bindings/(?P<pk>[^/.]+)/sync/$': {'pk': 'cicd_binding'},
    'api/projects/^cicd-bindings/(?P<pk>[^/.]+)/trigger/$': {'pk': 'cicd_binding'},
    'api/projects/^deployments/(?P<pk>[^/.]+)/$': {'pk': 'deployment'},
    'api/services/^all/(?P<pk>[^/.]+)/$': {'pk': 'custom_service'},
    'api/services/^scm/(?P<pk>[^/.]+)/$': {'pk': 'scm_service'},
    'api/services/^scm/(?P<pk>[^/.]+)/setup_webhook/$': {'pk': 'scm_service'},
    'api/services/^infra/(?P<pk>[^/.]+)/$': {'pk': 'infra_service'},
    'api/services/^infra/(?P<pk>[^/.]+)/health_check/$': {'pk': 'infra_service'},
    'api/services/^custom/(?P<pk>[^/.]+)/$': {'pk': 'custom_service'},
    'api/settings/ai/providers/<int:pk>/': (SHARED, 'the AI provider catalogue is shared by every organisation (ai_catalogue.manage)'),
    'api/settings/api-keys/<int:provider_id>/': {'provider_id': 'api_key_provider'},
    'api/integrations/^observability/(?P<pk>[^/.]+)/$': {'pk': 'observability'},
    'api/integrations/^observability/(?P<pk>[^/.]+)/health-check/$': {'pk': 'observability'},
    'api/integrations/^observability/(?P<pk>[^/.]+)/ingest-health/$': {'pk': 'observability'},
    'api/integrations/^clusters/(?P<pk>[^/.]+)/$': {'pk': 'cluster'},
    'api/integrations/^clusters/(?P<pk>[^/.]+)/workloads/$': {'pk': 'cluster'},
    'api/traces/^keys/(?P<pk>[^/.]+)/$': {'pk': 'ingest_key'},
    'api/traces/^traces/(?P<trace_id>[0-9a-fA-F]{32})/$': {'trace_id': 'trace'},
}

PARAM = re.compile(r'<(?:\w+:)?(\w+)>|\(\?P<(\w+)>[^)]*\)')


def route_params(pattern):
    return [a or b for a, b in PARAM.findall(pattern)]


def fill(pattern, values):
    """Turn a route pattern into a concrete URL."""
    url = PARAM.sub(lambda m: str(values[m.group(1) or m.group(2)]), pattern)
    return '/' + url.replace('^', '').replace('$', '')


def implemented(callback, cls):
    actions = getattr(callback, 'actions', None)
    if actions:
        return [m.upper() for m in actions]
    return [m.upper() for m in HTTP_METHODS if hasattr(cls, m)]


def api_routes():
    for pattern, callback in iter_routes(get_resolver().url_patterns):
        if not pattern.startswith('api/') or pattern.startswith('api/admin') or is_public(pattern):
            continue
        if 'format' in route_params(pattern):
            continue  # DRF ".json" suffix duplicates of the same views
        cls = view_class(callback)
        if cls is None or cls.__module__.startswith('rest_framework.routers'):
            continue
        yield pattern, callback, cls


def _offline(*args, **kwargs):
    raise requests.ConnectionError('outbound HTTP is disabled in the tenant coverage test')


class TenantCoverageTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        from ai_model.models import ChatSession
        from Data.models import AIAnalyzedBatch, Investigation, Issue
        from integrations.models import Cluster, ObservabilityIntegration
        from notifications.models import (EscalationRule, IncidentNotificationChannel, Notification,
                                          NotificationRoutingRule, ProjectSubscription)
        from org_settings.models import AIModelProvider, OrganisationAPIKey
        from Organisations.models import Organisations
        from Projects.models import CICDBinding, Project, ProjectDeployment, ProjectEnvironment, ProjectService, SCMBinding
        from providers.models import GitlabProject, Pipeline, ProviderIntegration
        from Services.models import CustomService, InfraService, SCMService
        from traces.models import IngestKey, Trace
        from Users.models import User

        now = timezone.now()
        m = MARKER
        a = Organisations.objects.create(name=f'{m} org')
        b = Organisations.objects.create(name='Other org')
        cls.attacker = User.objects.create_user(
            username='attacker', email='attacker@b.example', password='x', organisation=b, role='admin', is_active=True)
        # Install operators get no way around the organisation boundary either.
        cls.superuser = User.objects.create_user(
            username='operator', email='operator@b.example', password='x', organisation=b, role='admin',
            is_active=True, is_staff=True, is_superuser=True)
        owner = User.objects.create_user(
            username=f'{m}admin', email=f'{m}-admin@a.example', password='x', organisation=a, role='admin',
            is_active=True, first_name=m)
        member = User.objects.create_user(
            username=f'{m}member', email=f'{m}-member@a.example', password='x', organisation=a, role='user',
            is_active=True, first_name=m)
        project = Project.objects.create(name=f'{m}-shop', organisation=a)
        service = ProjectService.objects.create(project=project, name=f'{m}-checkout')
        env = ProjectEnvironment.objects.create(project=project, name='production')
        batch = AIAnalyzedBatch.objects.create(
            batch_id=f'{m}-batch-1', project=project, organisation=a, timestamp=now,
            data={'logs': [f'{m} log line']}, analysis_text=f'{m} analysis')
        issue = Issue.objects.create(
            batch=batch, project=project, organisation=a, severity='CRITICAL', description=f'{m} redis down',
            root_cause=f'{m} root cause', fingerprint=f'{m}-fp', component=f'{m}-redis')
        integration = ProviderIntegration.objects.create(
            name=f'{m} gitlab', provider_type='gitlab', organisation=a)
        gitlab_project = GitlabProject.objects.create(
            gitlab_url='https://gitlab.example', username=m, name=f'{m}-repo', project_id='9001',
            access_token=f'{m}-token', organisation=a)
        pipeline = Pipeline.objects.create(
            organisation=a, project=gitlab_project, pipeline_id='9001001', status='failed', branch=f'{m}-main')
        scm_binding = SCMBinding.objects.create(
            project_service=service, integration=integration, repository_id=f'{m}/repo')
        cicd_binding = CICDBinding.objects.create(
            project_service=service, integration=integration, pipeline_id=f'{m}-pipeline')
        cluster = Cluster.objects.create(organisation=a, name=f'{m}-cluster')
        deployment = ProjectDeployment.objects.create(project=project, cluster=cluster, namespace=f'{m}-ns')
        # The provider catalogue is shared by every organisation: no marker.
        provider = AIModelProvider.objects.create(name='tenant-test-provider', display_name='Tenant test provider')
        OrganisationAPIKey.objects.create(organisation=a, provider=provider, api_key=f'{m}-key')
        trace_id = uuid.uuid4().hex
        cls.seed = {
            'org': a.id,
            'member': member.id,
            'project': project.id,
            'project_service': service.id,
            'batch': batch.batch_id,
            'issue': issue.id,
            'investigation': Investigation.objects.create(
                organisation=a, project=project, requested_by=owner, environment=env,
                window_start=now, window_end=now).id,
            'chat': ChatSession.objects.create(user=owner, title=f'{m} chat').chat_id,
            'gitlab_project': gitlab_project.id,
            'pipeline': pipeline.id,
            'integration': integration.id,
            'scm_binding': scm_binding.id,
            'cicd_binding': cicd_binding.id,
            'deployment': deployment.id,
            'channel': IncidentNotificationChannel.objects.create(organisation=a, name=f'{m} slack', kind='slack').id,
            'routing_rule': NotificationRoutingRule.objects.create(organisation=a, name=f'{m} rule').id,
            'notification': Notification.objects.create(
                user=owner, subject=f'{m} subject', message=f'{m} message', notification_type='issue').id,
            'subscription': ProjectSubscription.objects.create(user=owner, project=project).id,
            'escalation': EscalationRule.objects.create(organisation=a, project=project).id,
            'scm_service': SCMService.objects.create(
                project=project, name=f'{m}-scm', category='scm', provider='gitlab',
                external_id='9001', access_token=f'{m}-token').id,
            'infra_service': InfraService.objects.create(
                project=project, name=f'{m}-redis-infra', category='infra', infra_type='redis').id,
            'custom_service': CustomService.objects.create(project=project, name=f'{m}-custom', category='custom').id,
            'api_key_provider': provider.id,
            'observability': ObservabilityIntegration.objects.create(
                organisation=a, provider='loki', display_name=f'{m} loki').id,
            'cluster': cluster.id,
            'ingest_key': IngestKey.objects.create(
                organisation=a, name=f'{m} key', key_hash=f'{m}-hash', key_prefix='zzv').id,
            'trace': Trace.objects.create(
                trace_id=trace_id, organisation=a, start_time=now, end_time=now, root_service_name=f'{m}-svc').trace_id,
        }

    def setUp(self):
        # A crash comes back as a 500 (listed by test_no_route_crashes) rather
        # than stopping the walk.
        self.client = APIClient(raise_request_exception=False)
        self.client.force_authenticate(user=self.caller())
        for target in ('requests.Session.request', 'httpx.Client.send', 'celery.app.task.Task.apply_async'):
            patcher = mock.patch(target, side_effect=_offline) if 'celery' not in target else \
                mock.patch(target, return_value=mock.MagicMock(id='stub'))
            patcher.start()
            self.addCleanup(patcher.stop)

    def caller(self):
        return self.attacker

    def call(self, method, url, query=None):
        if method in ('GET', 'HEAD'):
            return self.client.get(url, query or {})
        return getattr(self.client, method.lower())(url, {}, format='json')

    def leaked(self, response):
        body = response.content.decode('utf-8', 'replace').lower() if hasattr(response, 'content') else ''
        return MARKER in body

    def test_every_route_with_an_id_is_mapped(self):
        missing = [p for p, _, _ in api_routes() if route_params(p) and p not in TARGETS]
        stale = sorted(set(TARGETS) - {p for p, _, _ in api_routes()})
        self.assertEqual(missing, [], '\nAdd these routes to TARGETS:\n' + '\n'.join(missing))
        self.assertEqual(stale, [], '\nRemove these routes from TARGETS:\n' + '\n'.join(stale))

    def test_lists_do_not_show_other_organisations_data(self):
        s = self.seed
        queries = [{}, {
            'project': s['project'], 'project_id': s['project'], 'service': s['project_service'],
            'service_id': s['project_service'], 'batch_id': s['batch'], 'batch': s['batch'],
            'issue_id': s['issue'], 'cluster': s['cluster'], 'cluster_id': s['cluster'],
            'organisation': s['org'], 'organisation_id': s['org'], 'trace_id': s['trace'],
        }]
        leaks = []
        for pattern, callback, cls in api_routes():
            if route_params(pattern) or 'GET' not in implemented(callback, cls):
                continue
            for query in queries:
                response = self.call('GET', fill(pattern, {}), query)
                if 200 <= response.status_code < 300 and self.leaked(response):
                    leaks.append(f'GET {fill(pattern, {})}{" (with A ids)" if query else ""}')
        self.assertEqual(leaks, [], '\nOrganisation A data in B\'s response:\n' + '\n'.join(leaks))

    def test_objects_of_other_organisations_are_out_of_reach(self):
        leaks = []
        for pattern, callback, cls in api_routes():
            target = TARGETS.get(pattern)
            if not route_params(pattern) or not isinstance(target, dict):
                continue
            values = {k: v[1:] if v.startswith('=') else self.seed[v] for k, v in target.items()}
            url = fill(pattern, values)
            for method in implemented(callback, cls):
                response = self.call(method, url)
                ok = 200 <= response.status_code < 300
                if ok and (method not in ('GET', 'HEAD', 'OPTIONS') or self.leaked(response)):
                    leaks.append(f'{method} {url} -> {response.status_code}')
        self.assertEqual(leaks, [], '\nOrganisation B reached organisation A\'s objects:\n' + '\n'.join(leaks))

    def test_no_route_crashes_on_other_organisations_ids(self):
        crashes = []
        for pattern, callback, cls in api_routes():
            target = TARGETS.get(pattern)
            if route_params(pattern) and not isinstance(target, dict):
                continue
            values = {k: v[1:] if v.startswith('=') else self.seed[v] for k, v in (target or {}).items()}
            url = fill(pattern, values)
            for method in implemented(callback, cls):
                if self.call(method, url).status_code >= 500:
                    crashes.append(f'{method} {url}')
        self.assertEqual(crashes, [], '\n5xx:\n' + '\n'.join(crashes))


class SuperuserTenantCoverageTest(TenantCoverageTest):
    """The same walk as the superuser of organisation B."""

    def caller(self):
        return self.superuser
