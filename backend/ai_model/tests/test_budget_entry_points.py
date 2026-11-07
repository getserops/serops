"""Every AI entry point honours the monthly AI budget.

Security review 2026-11, finding 4: batch analysis is refused through
``generate_for_organisation``, but chat and re-analysis / compare called the
provider directly and skipped the cap; chat spend was not even recorded, so
it never counted towards it.
"""

import uuid
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from Data.models import AIAnalyzedBatch
from Organisations.models import Organisations
from Projects.models import Project
from Users.models import User
from ai_model.models import AITokenUsage
from ai_model.tasks import reanalyze_batch_with_model
from org_settings.models import OrganisationAISettings


class _OverBudgetFixture(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name=f'budget-{uuid.uuid4().hex[:8]}')
        self.user = User.objects.create_user(
            username=f'u-{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@t.com',
            password='Pass1234!', organisation=self.org, role='admin', is_active=True,
        )
        self.project = Project.objects.create(name='budget-proj', organisation=self.org)
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id=f'b-{uuid.uuid4().hex[:8]}', project=self.project, organisation=self.org,
            timestamp=timezone.now(), data={'logs': [], 'metrics_summary': {}},
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _use_up_budget(self):
        OrganisationAISettings.objects.update_or_create(
            organisation=self.org, defaults={'monthly_budget_usd': Decimal('5.00')},
        )
        AITokenUsage.objects.create(
            organisation=self.org, model_name='gemini', tokens_input=1, tokens_output=1,
            tokens_total=2, cost_usd=Decimal('6.00'),
        )

    def _chat(self):
        return self.client.post('/api/chat/generate-text/', {
            'type': 'chat', 'ai_model': 'gemini', 'prompt': {'message': 'why is checkout failing?'},
        }, format='json')


class ChatBudgetTest(_OverBudgetFixture):

    @patch('ai_model.views.generate_text_unified')
    def test_chat_is_refused_with_409_once_the_budget_is_used_up(self, generate):
        self._use_up_budget()

        response = self._chat()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error'], 'over_budget')
        self.assertIn('monthly AI budget', response.json()['message'])
        generate.assert_not_called()

    @patch('ai_model.views.generate_text_unified', return_value=('Checkout is fine.', None, 120, 30))
    def test_chat_spend_is_recorded_against_the_organisation(self, _generate):
        response = self._chat()

        self.assertEqual(response.status_code, 200, response.content)
        usage = AITokenUsage.objects.filter(organisation=self.org, usage_type='chat_message')
        self.assertTrue(usage.exists())
        self.assertGreaterEqual(sum(u.tokens_total for u in usage), 150)


class ReanalysisBudgetTest(_OverBudgetFixture):

    @patch('ai_model.tasks.reanalyze_batch_with_model.delay')
    def test_reanalysis_is_refused_with_409_and_nothing_is_queued(self, delay):
        self._use_up_budget()

        response = self.client.post('/api/data/batches/reanalyze/', {
            'batch_ids': [self.batch.batch_id], 'model': 'gemini', 'mode': 'compare',
        }, format='json')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'over_budget')
        delay.assert_not_called()

    @patch('ai_model.tasks.generate_text_unified')
    def test_a_queued_reanalysis_stops_before_calling_the_model_once_over_budget(self, generate):
        self._use_up_budget()

        result = reanalyze_batch_with_model(self.batch.batch_id, 'gemini', mode='compare')

        self.assertIn('budget', result)
        generate.assert_not_called()
