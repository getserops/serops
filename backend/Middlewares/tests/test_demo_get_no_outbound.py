"""The demo account never makes the server call out through a GET.

DemoUserMiddleware lets GET through for demo users (the demo is read-only,
not invisible), so any GET that calls a provider with stored credentials
could be triggered by anyone on the public demo. The audit of 2026-11-20
(item 2) found three: providers health-check-all, observability
ingest-health and the GitLab pipeline-logs view.

This test seeds the real demo organisation, replaces its placeholder
secrets with real-looking ones (so the placeholder short-circuits do not
hide anything), then walks every API route with GET as the demo user, with
every path parameter filled from the demo's own records. Any socket
connection or DNS lookup to a host other than the test's own database,
cache and broker is recorded and fails the test.
"""
import itertools
import re
import socket
from io import StringIO
from unittest.mock import patch
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase
from django.urls import get_resolver
from rest_framework.test import APIClient

from Middlewares.tests.test_permission_coverage import iter_routes

FAKE_SECRET = 'live' + '-looking-' + 'secret-123456'
MAX_URLS_PER_ROUTE = 60


def _internal_hosts():
    hosts = {'localhost', '127.0.0.1', '::1', 'testserver', ''}
    for db in settings.DATABASES.values():
        hosts.add(str(db.get('HOST') or ''))
    for cache in settings.CACHES.values():
        for loc in ([cache.get('LOCATION')] if isinstance(cache.get('LOCATION'), str) else cache.get('LOCATION') or []):
            hosts.add(urlsplit(loc).hostname or '')
    for url in (getattr(settings, 'CELERY_BROKER_URL', None), getattr(settings, 'CELERY_RESULT_BACKEND', None),
                getattr(settings, 'REDIS_URL', None)):
        if url:
            hosts.add(urlsplit(url).hostname or '')
    return {h.lower() for h in hosts}


class DemoGetNoOutboundTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo_org', stdout=StringIO())
        from integrations.models import ObservabilityIntegration
        from providers.models import ProviderIntegration
        from Users.models import User

        cls.demo = User.objects.filter(is_demo=True, is_active=True).order_by('id').first()
        org = cls.demo.organisation
        # The seed creates no integration any more, so the test adds one of
        # each kind the walk must cover, with real-looking secrets, plus any
        # the seed did create.
        ObservabilityIntegration.objects.create(
            organisation=org, provider='loki', display_name='walk-loki', capabilities=['logs'],
            host='https://loki.walk.example')
        ObservabilityIntegration.objects.create(
            organisation=org, provider='prometheus', display_name='walk-prom', capabilities=['metrics'],
            host='https://prom.walk.example')
        for kind, url in (('github', 'https://api.github.com'), ('gitlab', 'https://gitlab.walk.example')):
            ProviderIntegration.objects.create(
                organisation=org, provider_type=kind, name=f'walk-{kind}', base_url=url,
                verification_status='verified')
        for obs in ObservabilityIntegration.objects.filter(organisation=org):
            obs.set_password(FAKE_SECRET)
            obs.save()
        for prov in ProviderIntegration.objects.filter(organisation=org):
            creds = prov.get_credentials() or {}
            creds.update({k: FAKE_SECRET for k in ('access_token', 'api_token', 'app_password') if k in creds}
                         or {'access_token': FAKE_SECRET})
            prov.set_credentials(creds)
            prov.save()
        cls.ids, cls.strings = cls._parameter_values(org)

    @staticmethod
    def _parameter_values(org):
        from Data.models import AIAnalyzedBatch, Issue
        from integrations.models import ObservabilityIntegration
        from Projects.models import Project, ProjectService
        from providers.models import GitlabProject, Pipeline, ProviderIntegration

        def pks(model, **flt):
            try:
                return list(model.objects.filter(**flt).values_list('pk', flat=True)[:5])
            except Exception:  # noqa: BLE001 — a model without that field
                return []
        ids = {
            'project': pks(Project, organisation=org),
            'service': pks(ProjectService, project__organisation=org),
            'pipeline': pks(Pipeline, organisation=org),
            'gitlab': pks(GitlabProject, organisation=org),
            'integration': pks(ProviderIntegration, organisation=org) + pks(ObservabilityIntegration, organisation=org),
            'batch': pks(AIAnalyzedBatch, organisation=org),
            'issue': pks(Issue, organisation=org),
        }
        ids['any'] = sorted({i for v in ids.values() for i in v})
        batch_ids = list(AIAnalyzedBatch.objects.filter(organisation=org).values_list('batch_id', flat=True)[:3])
        strings = batch_ids + ['github', 'gitlab', 'loki', 'prometheus', 'logs', 'metrics']
        return ids, strings

    def _values_for(self, name, converter):
        if converter in ('str', 'slug', 'path', None) and not re.search(r'(^|_)(pk|id)$', name):
            return self.strings
        if converter == 'uuid':
            return ['00000000-0000-0000-0000-000000000000']
        for key in ('pipeline', 'project', 'service', 'batch', 'issue', 'integration', 'gitlab'):
            if key in name:
                return self.ids[key] or self.ids['any']
        return self.ids['any']

    def _urls(self):
        param = re.compile(r'<(?:(\w+):)?(\w+)>|\(\?P<(\w+)>[^)]*\)')
        for route, _ in iter_routes(get_resolver().url_patterns):
            if 'format' in route:
                continue
            path = route.replace('^', '').replace('$', '').replace('\\', '')
            names = []
            for m in param.finditer(path):
                conv, name = (m.group(1), m.group(2)) if m.group(2) else (None, m.group(3))
                names.append((m.group(0), self._values_for(name, conv)))
            if not names:
                yield '/' + path
                continue
            combos = itertools.product(*[[str(v) for v in vals] for _, vals in names])
            for combo in itertools.islice(combos, MAX_URLS_PER_ROUTE):
                url = path
                for (token, _), value in zip(names, combo):
                    url = url.replace(token, value, 1)
                yield '/' + url

    def test_demo_user_gets_never_reach_out(self):
        self._walk()

    def test_demo_user_gets_never_reach_out_even_if_the_org_flag_is_off(self):
        # The guards key on the user as well as on organisation.is_demo, so
        # a demo account never depends on one flag alone.
        from Organisations.models import Organisations
        Organisations.objects.filter(pk=self.demo.organisation_id).update(is_demo=False)
        self.demo.refresh_from_db()
        self._walk()

    def _walk(self):
        internal = _internal_hosts()
        attempts = []
        current = {'url': None}
        real_connect, real_create, real_gai = socket.socket.connect, socket.create_connection, socket.getaddrinfo

        def _host(address):
            return str(address[0] if isinstance(address, tuple) else address).lower()

        def connect(sock, address):
            if _host(address) not in internal and sock.family in (socket.AF_INET, socket.AF_INET6):
                attempts.append((current['url'], _host(address)))
                raise OSError('outbound blocked by test')
            return real_connect(sock, address)

        def create_connection(address, *a, **kw):
            if _host(address) not in internal:
                attempts.append((current['url'], _host(address)))
                raise OSError('outbound blocked by test')
            return real_create(address, *a, **kw)

        def getaddrinfo(host, *a, **kw):
            if str(host).lower() not in internal:
                attempts.append((current['url'], str(host).lower()))
                raise socket.gaierror('outbound blocked by test')
            return real_gai(host, *a, **kw)

        client = APIClient(raise_request_exception=False)
        client.force_authenticate(user=self.demo)
        visited = 0
        with patch.object(socket.socket, 'connect', connect), \
                patch.object(socket, 'create_connection', create_connection), \
                patch.object(socket, 'getaddrinfo', getaddrinfo):
            for url in self._urls():
                current['url'] = url
                client.get(url)
                visited += 1
        self.assertGreater(visited, 100)
        if attempts:
            self.fail('Demo-user GETs that reached out:\n' + '\n'.join(
                f'  GET {url} -> {host}' for url, host in sorted(set(attempts))))
