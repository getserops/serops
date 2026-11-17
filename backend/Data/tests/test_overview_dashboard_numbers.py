"""Overview dashboard: the numbers mean what their labels say, and every
endpoint honours the environment and cluster filters it is sent.

Owner's review of 17 Nov (MR 1): System Health window, MTTR filters and
sample size, open-issue tiles, one health formula for System Health, the
Service Health Map and Top Failing Services, Sentinel buckets and spend,
Recent Deployments' environment.
"""
import uuid
from urllib.parse import parse_qsl
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from ai_model.models import AITokenUsage
from Data.health import health_score
from Data.models import AIAnalyzedBatch, Issue
from integrations.models import Cluster
from Organisations.models import Organisations
from Projects.models import Project, ProjectService, SCMBinding
from providers.models import Pipeline, ProviderIntegration
from Users.models import User

LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                      'LOCATION': 'overview-numbers'}}

# Every endpoint the Overview page calls with the environment and cluster
# filters (Dashboard.jsx / dash.service.js). A new one goes here too.
OVERVIEW_ENDPOINTS = [
    '/api/data/analytics/health/',
    '/api/data/analytics/services/',
    '/api/data/analytics/trends/',
    '/api/data/analytics/mttr/',
    '/api/data/analytics/service-health/',
    '/api/data/analytics/root-causes/',
    '/api/data/analytics/deployments/',
    '/api/data/analytics/correlations/',
    '/api/data/analytics/feed/',
    '/api/data/analytics/sentinel/',
    '/api/data/recommendation-stats/?status=OPEN',
    '/api/data/issue-stats/?status=OPEN',
    '/api/data/issues/?status=OPEN',  # Needs attention
]


class HealthFormulaTest(SimpleTestCase):
    """The one formula (Data/health.py) and its thresholds."""

    def test_nothing_open_is_healthy(self):
        self.assertEqual(health_score(0, 0, 0, resolved_recent=5), (100, 'Healthy'))

    def test_one_open_warning_is_healthy_not_critical(self):
        # The old map formula gave this 40 % "Critical".
        self.assertEqual(health_score(0, 1), (94, 'Healthy'))

    def test_one_open_critical_is_degraded(self):
        self.assertEqual(health_score(1, 0), (80, 'Degraded'))

    def test_three_open_criticals_are_critical(self):
        self.assertEqual(health_score(3, 0), (40, 'Critical'))

    def test_thresholds(self):
        # Other (INFO) issues weigh 2, which lands on either side of 85.
        self.assertEqual(health_score(0, 0, other_open=7)[1], 'Healthy')    # 86
        self.assertEqual(health_score(0, 0, other_open=8)[1], 'Degraded')   # 84
        self.assertEqual(health_score(2, 0), (60, 'Degraded'))
        self.assertEqual(health_score(2, 0, other_open=1), (58, 'Critical'))

    def test_recovery_bonus_is_capped_and_never_hides_open_pain(self):
        self.assertEqual(health_score(3, 0, resolved_recent=100), (50, 'Critical'))


class OverviewFixture(TestCase):
    """Two clusters, two projects, production and staging.

    pA (cluster A): 3 production units (one CRITICAL) + 1 staging unit.
    pB (cluster B): 2 production units + 1 staging unit.
    A unit = a batch, an open issue, a resolved issue, an AI usage row and
    a pipeline run, all in the unit's environment. Staging and cluster B
    are strict subsets, so an endpoint that ignores a filter returns the
    unfiltered answer.
    """

    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.org = Organisations.objects.create(name='Overview Numbers Org')
        cls.user = User.objects.create_user(
            username='ov-admin', email='ov@test.com', password='Test123!',
            organisation=cls.org, role='admin', is_active=True)
        cls.cluster_a = Cluster.objects.create(organisation=cls.org, name='eks-a')
        cls.cluster_b = Cluster.objects.create(organisation=cls.org, name='gke-b')
        cls.pa = Project.objects.create(organisation=cls.org, name='pa', cluster=cls.cluster_a)
        cls.pb = Project.objects.create(organisation=cls.org, name='pb', cluster=cls.cluster_b)
        gh = ProviderIntegration.objects.create(organisation=cls.org, name='GH', provider_type='github')
        for project, svc in ((cls.pa, 'api'), (cls.pb, 'web')):
            ps = ProjectService.objects.create(project=project, name=svc)
            SCMBinding.objects.create(project_service=ps, integration=gh, repository_id=f'repo-{svc}')

        units = [(cls.pa, 'api', 'production', 'CRITICAL'), (cls.pa, 'api', 'production', 'WARNING'),
                 (cls.pa, 'api', 'production', 'WARNING'), (cls.pa, 'api', 'staging', 'WARNING'),
                 (cls.pb, 'web', 'production', 'WARNING'), (cls.pb, 'web', 'production', 'WARNING'),
                 (cls.pb, 'web', 'staging', 'WARNING')]
        for i, (project, svc, env, severity) in enumerate(units):
            batch = AIAnalyzedBatch.objects.create(
                batch_id=f'ov-{i}', organisation=cls.org, project=project, environment=env,
                timestamp=now - timedelta(minutes=10 + i), analyzed_at=now - timedelta(minutes=10 + i),
                analysis_text=f'Analysis {i} of {svc} in {env}.', token_count=1000,
                sentinel_decision='alert' if i % 2 == 0 else 'quiet', ai_skipped=i % 2 == 1)
            common = dict(batch=batch, project=project, organisation=cls.org, environment=env,
                          component=svc, recommendation='Roll back.', root_cause='memory leak in the pool',
                          has_commit_correlation=True)
            Issue.objects.create(severity=severity, status='OPEN', description=f'open {i}',
                                 fingerprint=uuid.uuid4().hex, **common)
            resolved = Issue.objects.create(severity='WARNING', status='RESOLVED', description=f'fixed {i}',
                                            resolved_at=now - timedelta(hours=1),
                                            fingerprint=uuid.uuid4().hex, **common)
            Issue.objects.filter(pk=resolved.pk).update(created_at=now - timedelta(hours=2 + i))
            AITokenUsage.objects.create(organisation=cls.org, batch=batch, model_name='m',
                                        tokens_total=1000, cost_usd=Decimal('0.010000') * (i + 1))
            Pipeline.objects.create(organisation=cls.org, cicd_provider='github', pipeline_id=f'run-{i}',
                                    status='success', branch='main', environment=env,
                                    external_project_id=f'repo-{svc}')

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def get(self, url, **params):
        # The test client drops a path's own query string when it is
        # given data, so merge the two.
        path, _, query = url.partition('?')
        response = self.client.get(path, {**dict(parse_qsl(query)), **params})
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()


@override_settings(CACHES=LOCMEM)
class EveryEndpointHonoursItsFiltersTest(OverviewFixture):
    """Point 10: fails when a dashboard endpoint ignores a filter it is sent.

    Both orders are checked, because a cache key that leaves a filter out
    serves whichever answer was computed first."""

    def _filters(self):
        return [('environment', 'staging'), ('cluster', self.cluster_b.id)]

    def test_filter_changes_the_answer(self):
        ignored = []
        for url in OVERVIEW_ENDPOINTS:
            for name, value in self._filters():
                for filtered_first in (False, True):
                    cache.clear()
                    if filtered_first:
                        filtered = self.get(url, **{name: value})
                        unfiltered = self.get(url)
                    else:
                        unfiltered = self.get(url)
                        filtered = self.get(url, **{name: value})
                    if filtered == unfiltered:
                        ignored.append(f'{url} ignores {name} ({"filtered" if filtered_first else "unfiltered"} first)')
        self.assertEqual(ignored, [], '\n'.join(ignored))


@override_settings(CACHES=LOCMEM)
class OverviewNumbersTest(OverviewFixture):

    # 1. System Health ------------------------------------------------

    def test_system_health_scores_open_issues_whatever_their_age(self):
        Issue.objects.filter(status='OPEN').update(created_at=timezone.now() - timedelta(days=5))
        data = self.get('/api/data/analytics/health/', environment='staging')
        # 2 open warnings, 2 resolved in the last 24 h: 100 - 12 + 4.
        self.assertEqual(data['health_score'], 92)
        self.assertEqual(data['status'], 'Healthy')
        self.assertEqual(data['metrics'], {'open_critical': 0, 'open_warning': 2, 'open_total': 2,
                                           'resolved_last_24h': 2})

    # 2. MTTR -----------------------------------------------------------

    def test_mttr_small_sample_says_not_enough_data(self):
        data = self.get('/api/data/analytics/mttr/', environment='staging')
        self.assertEqual(data['sample_size'], 2)
        self.assertEqual(data['trend'], 'INSUFFICIENT_DATA')
        self.assertEqual(data['period_days'], 30)

    def test_mttr_keeps_info_apart_from_warning(self):
        Issue.objects.filter(status='RESOLVED', batch__batch_id='ov-0').update(severity='INFO')
        data = self.get('/api/data/analytics/mttr/')
        self.assertEqual(data['by_severity']['INFO']['count'], 1)
        self.assertEqual(data['by_severity']['WARNING']['count'], 6)

    def test_mttr_trend_from_twelve_resolved_issues(self):
        batch = AIAnalyzedBatch.objects.get(batch_id='ov-0')
        now = timezone.now()
        for i in range(5):
            issue = Issue.objects.create(batch=batch, project=self.pa, organisation=self.org,
                                         severity='WARNING', status='RESOLVED', description=f'x{i}',
                                         resolved_at=now, fingerprint=uuid.uuid4().hex)
            Issue.objects.filter(pk=issue.pk).update(created_at=now - timedelta(hours=1))
        data = self.get('/api/data/analytics/mttr/')
        self.assertEqual(data['sample_size'], 12)
        self.assertIn(data['trend'], ('IMPROVING', 'DEGRADING', 'STABLE'))

    # 3. Tiles ----------------------------------------------------------

    def test_tiles_count_open_issues(self):
        stats = self.get('/api/data/issue-stats/', status='OPEN')['statistics']
        self.assertEqual(stats['critical']['count'], 1)
        self.assertEqual(stats['summary']['total_issues'], 7)
        recs = self.get('/api/data/recommendation-stats/', status='OPEN')['statistics']
        self.assertEqual(recs['summary']['total_recommendations'], 7)
        # Without the parameter: every issue, as before.
        self.assertEqual(self.get('/api/data/issue-stats/')['statistics']['summary']['total_issues'], 14)

    # 4 + 5. One formula for the map and Top Failing Services ------------

    def test_one_open_warning_is_a_healthy_tile(self):
        data = self.get('/api/data/analytics/service-health/', environment='staging', cluster=self.cluster_b.id)
        web = {s['name']: s for s in data['services']}['web']
        # 1 open warning, 1 resolved in the last 24 h: 100 - 6 + 2.
        self.assertEqual((web['health_score'], web['status'], web['open_issues']), (96, 'healthy', 1))

    def test_map_and_top_failing_agree(self):
        Issue.objects.filter(component='web', status='OPEN').update(status='RESOLVED', resolved_at=timezone.now())
        tiles = {s['name']: s for s in self.get('/api/data/analytics/service-health/')['services']}
        top = {s['name']: s for s in self.get('/api/data/analytics/services/')}
        self.assertEqual(tiles['web']['health_score'], 100)
        self.assertNotIn('web', top)  # healthy: not "failing"
        self.assertEqual(top['api']['health_score'], tiles['api']['health_score'])
        self.assertEqual(top['api']['status'], tiles['api']['status'])
        self.assertEqual(top['api']['count'], tiles['api']['open_issues'])

    def test_top_failing_ranks_a_critical_service_above_a_noisy_one(self):
        batch = AIAnalyzedBatch.objects.get(batch_id='ov-4')
        for i in range(8):  # lots of resolved history, nothing open
            Issue.objects.create(batch=batch, project=self.pb, organisation=self.org, component='noisy',
                                 severity='WARNING', status='RESOLVED', description=f'n{i}',
                                 fingerprint=uuid.uuid4().hex)
        Issue.objects.create(batch=batch, project=self.pb, organisation=self.org, component='db',
                             severity='CRITICAL', status='OPEN', description='db down',
                             fingerprint=uuid.uuid4().hex)
        Issue.objects.create(batch=batch, project=self.pb, organisation=self.org, component='db',
                             severity='CRITICAL', status='OPEN', description='db down again',
                             fingerprint=uuid.uuid4().hex)
        names = [s['name'] for s in self.get('/api/data/analytics/services/')]
        self.assertNotIn('noisy', names)
        self.assertEqual(names[0], 'db')

    # 6. Sentinel -------------------------------------------------------

    def test_sentinel_decisions_add_up_and_spend_follows_filters(self):
        AIAnalyzedBatch.objects.filter(batch_id='ov-6').update(sentinel_decision='manual')
        data = self.get('/api/data/analytics/sentinel/')
        self.assertEqual(sum(data['decisions'].values()), data['total_batches'])
        self.assertEqual(data['decisions']['manual'], 1)
        # Usage rows cost 0.01 x (i + 1); staging is ov-3 and ov-6.
        self.assertAlmostEqual(self.get('/api/data/analytics/sentinel/', environment='staging')['ai_spend_usd'],
                               0.04 + 0.07)
        # Cluster B is ov-4, ov-5, ov-6.
        self.assertAlmostEqual(self.get('/api/data/analytics/sentinel/', cluster=self.cluster_b.id)['ai_spend_usd'],
                               0.05 + 0.06 + 0.07)
        self.assertAlmostEqual(self.get('/api/data/analytics/sentinel/')['ai_spend_usd'], 0.28)

    # 7. Recent deployments ---------------------------------------------

    def test_recent_deployments_follow_the_environment(self):
        services = self.get('/api/data/analytics/deployments/', environment='staging')['services']
        envs = {p['environment'] for s in services for p in s['recent_pipelines']}
        self.assertEqual(envs, {'staging'})
        self.assertEqual(sorted(s['service_name'] for s in services), ['api', 'web'])
