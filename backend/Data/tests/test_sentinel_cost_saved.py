"""
Tests for the cost-saved hero metric on SentinelStatsView.

The endpoint must:
  - report estimated_cost_saved_usd derived from this org's own AI
    token-cost rate, not a marketing estimate
  - report 0 cost saved when the org has no AI usage history
  - never raise: failures degrade to 0 with an error string
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from Organisations.models import Organisations
from Users.models import User
from Projects.models import Project
from Data.models import AIAnalyzedBatch
from ai_model.models import AITokenUsage


class SentinelCostSavedTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Sav Org')
        self.user = User.objects.create_user(
            username='savadmin', email='savadmin@test.com',
            password='Pass1234!', organisation=self.org,
            role='admin', is_active=True,
        )
        self.project = Project.objects.create(name='proj', organisation=self.org)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _make_batch(self, *, skipped, token_count=10_000, days_ago=1):
        return AIAnalyzedBatch.objects.create(
            batch_id=f'b-{skipped}-{token_count}-{days_ago}-{AIAnalyzedBatch.objects.count()}',
            project=self.project, organisation=self.org,
            timestamp=timezone.now() - timedelta(days=days_ago),
            environment='production',
            data={},
            ai_skipped=skipped,
            token_count=token_count,
            sentinel_decision='quiet' if skipped else 'alert',
        )

    def test_no_usage_history_yields_zero_cost_saved(self):
        # One analyzed and one skipped batch — there is data to count
        # tokens saved against, but no AITokenUsage rows to derive
        # cost-per-token from. The hero metric must be exactly 0, not
        # NaN or a guessed default.
        self._make_batch(skipped=False, token_count=10_000)
        self._make_batch(skipped=True)

        response = self.client.get('/api/data/analytics/sentinel/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreater(body['estimated_tokens_saved'], 0)
        self.assertEqual(body['estimated_cost_saved_usd'], 0)
        self.assertEqual(body['ai_spend_usd'], 0)

    def test_cost_saved_derived_from_real_usage_rate(self):
        # 10 analyzed batches, each ~10k tokens. 10 skipped batches.
        # Real usage: 100k tokens cost $0.50 → rate is $5/1M tokens.
        # Expected savings = 100k tokens skipped * $5/1M = $0.50.
        for _ in range(10):
            self._make_batch(skipped=False, token_count=10_000)
        for _ in range(10):
            self._make_batch(skipped=True)

        AITokenUsage.objects.create(
            organisation=self.org, model_name='gemini-2.5-flash',
            tokens_input=80_000, tokens_output=20_000, tokens_total=100_000,
            cost_usd=Decimal('0.50'),
        )

        response = self.client.get('/api/data/analytics/sentinel/')
        body = response.json()
        # avg tokens per analyzed batch = 10_000; skipped = 10 →
        # tokens_saved = 100_000 → cost saved ≈ $0.50.
        self.assertEqual(body['estimated_tokens_saved'], 100_000)
        self.assertAlmostEqual(body['estimated_cost_saved_usd'], 0.50, places=2)
        self.assertAlmostEqual(body['ai_spend_usd'], 0.50, places=2)

    def test_other_orgs_usage_does_not_bleed_into_cost_rate(self):
        # If another org has expensive usage, that must not inflate our
        # savings claim. Multi-tenancy guard.
        other_org = Organisations.objects.create(name='Other Sav Org')
        AITokenUsage.objects.create(
            organisation=other_org, model_name='claude-sonnet-4-20250514',
            tokens_input=100, tokens_output=100, tokens_total=200,
            cost_usd=Decimal('100.00'),  # an absurd rate for other org
        )

        self._make_batch(skipped=False, token_count=10_000)
        self._make_batch(skipped=True)

        response = self.client.get('/api/data/analytics/sentinel/')
        body = response.json()
        self.assertEqual(body['estimated_cost_saved_usd'], 0)
