"""Dashboard widgets checked against the seeded demo org."""

from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from Data.dashboard_views import RecentAnalysisFeedView
from Data.management.commands.seed_demo_org import DEMO_ORG_SLUG
from Organisations.models import Organisations
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
        self.assertGreaterEqual(data['metric_breakdown']['cpu'], 1)
        # The staging test failure has no correlation, so the rate stays
        # below 100 % even though one issue has both a deploy and a metric.
        self.assertLess(data['correlation_rate'], 100)
