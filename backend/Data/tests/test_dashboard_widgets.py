"""Dashboard widgets checked against the seeded demo org."""

from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from Data.dashboard_views import RecentAnalysisFeedView
from Data.management.commands.seed_demo_org import DEMO_ORG_SLUG
from Data.models import AIAnalyzedBatch, Issue
from Organisations.models import Organisations
from Projects.models import CICDBinding, Project, ProjectService, SCMBinding
from providers.models import Pipeline, ProviderIntegration
from Users.models import User


class DashboardWidgetsTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo_org', stdout=StringIO())
        cls.org = Organisations.objects.get(slug=DEMO_ORG_SLUG)
        cls.user = User.objects.get(organisation=cls.org, is_demo=True)

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_trend_ends_today_and_counts_todays_issues(self):
        # The window used to stop at yesterday, so today's issues never showed.
        # The seeded analyses end yesterday: this one is raised today.
        batch = AIAnalyzedBatch.objects.filter(organisation=self.org).first()
        Issue.objects.create(
            batch=batch, project=batch.project, organisation=self.org, severity='WARNING',
            description='Raised today', issue_type='OTHER', component='web', environment='production',
            fingerprint='trend-today',
        )
        days = self.client.get('/api/data/analytics/trends/').json()
        self.assertEqual(len(days), 7)
        self.assertEqual(days[-1]['date'], timezone.now().date().isoformat())
        self.assertEqual(days[-1]['warning'], 1)

    def test_feed_summary_keeps_dotted_words(self):
        summary = RecentAnalysisFeedView._extract_summary(
            'The hotfix in v2.3.4 raised the timeout. Pool sizing was untouched.'
        )
        self.assertEqual(summary, 'The hotfix in v2.3.4 raised the timeout.')

    def test_deployments_card_matches_pipelines_to_services(self):
        # The demo has no integration, so the card's rows are built here: one
        # service whose CI has a run, one bound to a CI with no run yet.
        project = Project.objects.filter(organisation=self.org).first()
        scm = ProviderIntegration.objects.create(
            organisation=self.org, provider_type='github', name='scm', category='devops',
            base_url='https://github.acme.example', credentials={'access_token': 'x'}, is_active=True)
        ci = {
            kind: ProviderIntegration.objects.create(
                organisation=self.org, provider_type=kind, name=kind, category='cicd',
                base_url=f'https://{kind}.acme.example', credentials={'access_token': 'x'}, is_active=True)
            for kind in ('gitlab', 'jenkins')
        }
        for name, kind, pipeline_id in (('backend-api', 'gitlab', '842'), ('payment-worker', 'jenkins', 'job/build')):
            service = ProjectService.objects.create(project=project, name=name, service_type='application')
            SCMBinding.objects.create(
                project_service=service, integration=scm, repository_id=f'acme-cloud/{name}',
                repository_name=f'acme-cloud/{name}', repository_url=f'https://github.acme.example/acme-cloud/{name}',
                default_branch='main')
            CICDBinding.objects.create(
                project_service=service, integration=ci[kind], pipeline_id=pipeline_id,
                binding_type='build', pipeline_name=name)
        Pipeline.objects.create(
            organisation=self.org, pipeline_id='f0aabb01-1', cicd_provider='gitlab',
            external_project_id='acme-cloud/backend-api', status='success', branch='main',
            environment='production', provider_metadata={'commit_sha': 'f0aabb01'})

        services = {
            s['service_name']: s
            for s in self.client.get('/api/data/analytics/deployments/').json()['services']
        }
        self.assertIsNotNone(services['backend-api']['latest_pipeline'])
        self.assertEqual(services['backend-api']['provider'], 'gitlab')
        # No runs yet: the provider comes from the service's CI binding.
        self.assertIsNone(services['payment-worker']['latest_pipeline'])
        self.assertEqual(services['payment-worker']['provider'], 'jenkins')

    def test_correlation_insights_count_the_seeded_deploy_links(self):
        data = self.client.get('/api/data/analytics/correlations/').json()
        self.assertGreaterEqual(data['commit_correlations'], 1)
        self.assertGreaterEqual(data['metric_breakdown']['memory'], 1)
        # The frontend CPU throttling had no commit behind it, so the rate
        # stays below 100 %.
        self.assertLess(data['correlation_rate'], 100)
