"""Cached dashboard responses are per user: one organisation's numbers
must never be served to another (cache_page keys on the URL and the
response's Vary headers, and the token is in a header)."""
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from knox.models import AuthToken
from rest_framework.test import APIClient

from Data.models import AIAnalyzedBatch, Issue
from Organisations.models import Organisations
from Projects.models import Project
from Users.models import User

LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'dash-isolation'}}
URLS = ['/api/data/analytics/feed/', '/api/data/analytics/mttr/', '/api/data/analytics/root-causes/',
        '/api/data/analytics/service-health/', '/api/data/analytics/correlations/']


@override_settings(CACHES=LOCMEM)
class DashboardCacheIsolationTest(TestCase):
    def setUp(self):
        cache.clear()
        self.clients = {}
        for name in ('alpha', 'beta'):
            org = Organisations.objects.create(name=f'{name} org')
            project = Project.objects.create(name=f'{name}-shop', organisation=org)
            batch = AIAnalyzedBatch.objects.create(
                batch_id=f'{name}-secret-batch', project=project, organisation=org, timestamp=timezone.now(),
                analyzed_at=timezone.now(), data={}, analysis_text=f'{name}-secret analysis')
            Issue.objects.create(batch=batch, project=project, organisation=org, severity='CRITICAL',
                                 description=f'{name}-secret issue', root_cause=f'{name}-secret cause',
                                 fingerprint=f'{name}-fp', component=f'{name}-secret-svc')
            user = User.objects.create_user(username=name, email=f'{name}@x.test', password='x', organisation=org,
                                            role='admin', is_active=True)
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION='Token ' + AuthToken.objects.create(user)[1])
            self.clients[name] = client

    def test_one_organisation_never_gets_anothers_cached_dashboard(self):
        leaks = []
        for url in URLS:
            self.clients['alpha'].get(url)                      # fills the cache
            body = self.clients['beta'].get(url).content.decode()
            if 'alpha-secret' in body or 'alpha-shop' in body:
                leaks.append(url)
        self.assertEqual(leaks, [], f'beta was served alpha\'s cached dashboard: {leaks}')
