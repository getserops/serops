"""Tests for Q3.3 AI cost budget + Q4.1 Ollama probe (Batch 26)."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from ai_model.budget import BudgetCheck, BudgetExceeded, BudgetTracker
from ai_model.models import AITokenUsage
from Organisations.models import Organisations
from org_settings.models import OrganisationAISettings

User = get_user_model()


# ============================================================================
# BudgetTracker
# ============================================================================


class BudgetTrackerTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='BudgetOrg')

    def _add_usage(self, cost, when=None):
        u = AITokenUsage.objects.create(
            organisation=self.org, model_name='gemini-3.5-flash',
            tokens_input=1000, tokens_output=500, tokens_total=1500,
            cost_usd=Decimal(str(cost)),
        )
        if when is not None:
            AITokenUsage.objects.filter(pk=u.pk).update(timestamp=when)
        return u

    def test_unlimited_org_short_circuits(self):
        """No settings row / no budget = ok=True, no DB scan."""
        # No OrganisationAISettings row for this org.
        check = BudgetTracker.check_budget(self.org)
        self.assertTrue(check.ok)
        self.assertIsNone(check.budget)
        self.assertIsNone(check.remaining)

    def test_current_month_spend_sums_correctly(self):
        # This month
        self._add_usage('1.50')
        self._add_usage('2.25')
        # Last month (should be excluded)
        self._add_usage('99.00', when=BudgetTracker._month_start() - timedelta(days=1))
        self.assertEqual(BudgetTracker.current_month_spend(self.org), Decimal('3.75'))

    def test_current_month_spend_empty_returns_zero(self):
        self.assertEqual(BudgetTracker.current_month_spend(self.org), Decimal('0'))

    def test_check_budget_under_ok(self):
        OrganisationAISettings.objects.create(
            organisation=self.org, monthly_budget_usd=Decimal('10.00'),
        )
        self._add_usage('3.00')
        check = BudgetTracker.check_budget(self.org)
        self.assertTrue(check.ok)
        self.assertEqual(check.current, Decimal('3.00'))
        self.assertEqual(check.remaining, Decimal('7.00'))

    def test_check_budget_at_cap_ok(self):
        OrganisationAISettings.objects.create(
            organisation=self.org, monthly_budget_usd=Decimal('10.00'),
        )
        self._add_usage('10.00')
        check = BudgetTracker.check_budget(self.org)
        self.assertTrue(check.ok)   # exactly at cap = still ok

    def test_check_budget_over_not_ok(self):
        OrganisationAISettings.objects.create(
            organisation=self.org, monthly_budget_usd=Decimal('10.00'),
        )
        self._add_usage('11.50')
        check = BudgetTracker.check_budget(self.org)
        self.assertFalse(check.ok)

    def test_enforce_raises_when_over(self):
        OrganisationAISettings.objects.create(
            organisation=self.org, monthly_budget_usd=Decimal('10.00'),
        )
        self._add_usage('11.50')
        with self.assertRaises(BudgetExceeded) as cm:
            BudgetTracker.enforce(self.org)
        self.assertEqual(cm.exception.budget, Decimal('10.00'))
        self.assertEqual(cm.exception.org_id, self.org.id)

    def test_enforce_no_op_when_under(self):
        OrganisationAISettings.objects.create(
            organisation=self.org, monthly_budget_usd=Decimal('10.00'),
        )
        self._add_usage('3.00')
        BudgetTracker.enforce(self.org)   # must not raise

    def test_enforce_no_op_when_no_budget(self):
        # No settings row.
        BudgetTracker.enforce(self.org)

    def test_is_warning_below_threshold(self):
        OrganisationAISettings.objects.create(
            organisation=self.org, monthly_budget_usd=Decimal('100.00'),
            budget_warn_pct=80,
        )
        self._add_usage('50.00')
        self.assertFalse(BudgetTracker.is_warning(self.org))

    def test_is_warning_above_threshold(self):
        OrganisationAISettings.objects.create(
            organisation=self.org, monthly_budget_usd=Decimal('100.00'),
            budget_warn_pct=80,
        )
        self._add_usage('85.00')
        self.assertTrue(BudgetTracker.is_warning(self.org))

    def test_tracker_db_error_falls_open(self):
        """A broken observer must never block AI calls."""
        with patch.object(AITokenUsage.objects, 'filter',
                          side_effect=Exception('DB kaboom')):
            # Should return 0 rather than crash.
            self.assertEqual(
                BudgetTracker.current_month_spend(self.org),
                Decimal('0'),
            )


# ============================================================================
# generate_for_organisation gate
# ============================================================================


class BudgetGateTest(TestCase):
    """Verify ai_service.generate_for_organisation raises BudgetExceeded
    when the pre-flight refuses, and lets calls through otherwise."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='GateOrg')

    def test_over_budget_raises(self):
        from org_settings.models import AIModelProvider
        # Reuse an already-seeded provider (0011 seeds gemini, ollama,
        # claude, openai, deepseek). Creating a fresh one with the same
        # name collides with the seed's UNIQUE constraint after a
        # fresh test-DB setup. update_or_create keeps the test valid
        # whether the seed ran or not.
        provider, _ = AIModelProvider.objects.update_or_create(
            name='gemini',
            defaults=dict(
                display_name='G', default_model='m',
                adapter_class='x.y.Z', is_active=True,
            ),
        )
        settings = OrganisationAISettings.objects.create(
            organisation=self.org,
            default_provider=provider,
            monthly_budget_usd=Decimal('5.00'),
        )
        AITokenUsage.objects.create(
            organisation=self.org, model_name='m', cost_usd=Decimal('6.00'),
            tokens_input=0, tokens_output=0, tokens_total=0,
        )
        from ai_model.ai_service import generate_for_organisation
        with self.assertRaises(BudgetExceeded):
            generate_for_organisation('prompt', self.org)


# ============================================================================
# API — AIBudgetStatusView
# ============================================================================


class AIBudgetStatusViewTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='BudgetAPIOrg')
        self.user = User.objects.create_user(
            username='bu', email='b@t.com', password='p',
            organisation=self.org, role='user', is_active=True,
        )
        self.client = APIClient()

    def test_requires_auth(self):
        self.assertIn(
            self.client.get('/api/settings/ai/budget/').status_code,
            (401, 403),
        )

    def test_no_budget_returns_null(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/settings/ai/budget/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsNone(body['monthly_budget_usd'])
        self.assertEqual(body['current_spend_usd'], '0')
        self.assertFalse(body['is_exceeded'])

    def test_with_budget_returns_snapshot(self):
        OrganisationAISettings.objects.create(
            organisation=self.org, monthly_budget_usd=Decimal('50.00'),
        )
        AITokenUsage.objects.create(
            organisation=self.org, model_name='m', cost_usd=Decimal('10.00'),
            tokens_input=0, tokens_output=0, tokens_total=0,
        )
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/settings/ai/budget/')
        body = response.json()
        # Values are formatted from Decimal via str() — 6 decimal
        # places (matches AITokenUsage.cost_usd precision). Assert on
        # numeric value, not string form, so a precision change here
        # doesn't spuriously break tests.
        self.assertEqual(Decimal(body['monthly_budget_usd']), Decimal('50'))
        self.assertEqual(Decimal(body['current_spend_usd']), Decimal('10'))
        self.assertEqual(Decimal(body['remaining_usd']), Decimal('40'))
        self.assertFalse(body['is_exceeded'])


# ============================================================================
# API — OllamaProbeView
# ============================================================================


class OllamaProbeViewTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='OllamaProbeOrg')
        self.admin = User.objects.create_user(
            username='oadmin', email='o@t.com', password='p',
            organisation=self.org, role='admin', is_active=True,
        )
        self.user = User.objects.create_user(
            username='ouser', email='ou@t.com', password='p',
            organisation=self.org, role='user', is_active=True,
        )
        self.client = APIClient()
        self.url = '/api/settings/ai/ollama/probe/'

    def test_non_admin_forbidden(self):
        self.client.force_authenticate(user=self.user)
        r = self.client.post(self.url, {'base_url': 'http://x/v1/'}, format='json')
        self.assertIn(r.status_code, (401, 403))

    def test_missing_url_400(self):
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(self.url, {}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_bad_scheme_400(self):
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(self.url, {'base_url': 'ftp://x/v1/'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_cloud_metadata_ip_rejected(self):
        """BE-P1-06 (audit 2026-09-05): SSRF guard.

        Admin-only doesn't equal safe — a compromised admin session or
        a rogue admin could point the probe at AWS/GCP/Azure metadata
        (169.254.169.254) and exfiltrate short-lived cloud credentials
        via the returned response. The URL validator rejects the
        specific metadata endpoints while still allowing legitimate
        intra-cluster / localhost Ollama URLs.
        """
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(
            self.url, {'base_url': 'http://169.254.169.254/'}, format='json',
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn('metadata', r.json()['error'].lower())

    def test_localhost_still_allowed(self):
        """Regression guard for the metadata-only ban.

        Self-hosted Ollama on ``http://localhost:11434`` is the intended
        common case. If we tighten the validator to reject all private
        ranges the whole feature breaks — this test ensures we don't
        over-correct.
        """
        with patch('requests.get') as get:
            mock = MagicMock()
            mock.status_code = 200
            mock.raise_for_status = MagicMock()
            mock.json.return_value = {'data': []}
            get.return_value = mock
            self.client.force_authenticate(user=self.admin)
            r = self.client.post(
                self.url,
                {'base_url': 'http://localhost:11434/v1'},
                format='json',
            )
            self.assertEqual(r.status_code, 200)

    @patch('requests.get')
    def test_ok_returns_models(self, get):
        mock = MagicMock()
        mock.status_code = 200
        mock.raise_for_status = MagicMock()
        mock.json.return_value = {
            'data': [{'id': 'qwen3:8b'}, {'id': 'llama3.1:8b'}],
        }
        get.return_value = mock
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(self.url, {'base_url': 'http://ollama:11434/v1'},
                             format='json')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body['reachable'])
        self.assertEqual(body['models'], ['qwen3:8b', 'llama3.1:8b'])
        # Trailing slash normalisation happened.
        called_url = get.call_args.args[0]
        self.assertTrue(called_url.endswith('/models'))

    @patch('requests.get')
    def test_network_error_returns_unreachable(self, get):
        from requests.exceptions import ConnectionError as ReqConnErr
        get.side_effect = ReqConnErr('down')
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(self.url, {'base_url': 'http://x/v1/'},
                             format='json')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body['reachable'])
        self.assertIn('Could not reach', body['error'])

    @patch('requests.get')
    def test_malformed_response_returns_error(self, get):
        mock = MagicMock()
        mock.status_code = 200
        mock.raise_for_status = MagicMock()
        mock.json.side_effect = ValueError('not json')
        get.return_value = mock
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(self.url, {'base_url': 'http://x/v1/'},
                             format='json')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body['reachable'])
