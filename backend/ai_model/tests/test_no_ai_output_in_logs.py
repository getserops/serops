"""AI output stays out of the logs (audit 2026-11-20, item 11).

The chat view logged the intent classifier's raw answer, the same answer
again when it was not JSON, and the full chat answer; the analysis view
logged its whole prompt (the batch's log lines) and the answer. Only lengths
are logged now.
"""
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from Data.models import AIAnalyzedBatch
from Organisations.models import Organisations
from Projects.models import Project
from Users.models import User

MARKER = 'ZEBRA-' + 'ANSWER-7731'


class ChatLogsNoAiOutputTest(TestCase):
    def setUp(self):
        org = Organisations.objects.create(name='Log Org')
        user = User.objects.create_user(
            username='logger', email='logger@test.com', password='Pass1234!',
            organisation=org, role='admin', is_active=True,
        )
        project = Project.objects.create(name='logs-proj', organisation=org)
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='b-logs-1', project=project, organisation=org, timestamp=timezone.now(), data={})
        self.client = APIClient()
        self.client.force_authenticate(user=user)

    def test_chat_answer_and_intent_answer_not_logged(self):
        # No keyword matches "hello there", so the LLM intent classifier runs,
        # gets non-JSON back (the parse-failure path), then the chat answer.
        with patch('ai_model.views.process_ai_request', return_value=(MARKER + ' not json', None)) as ai, \
                self.assertLogs('ai_model', level='DEBUG') as logs:
            r = self.client.post('/api/chat/generate-text/', {
                'type': 'chat', 'ai_model': 'claude', 'prompt': {'message': 'hello there'},
                'batch_id': self.batch.batch_id,
            }, format='json')
        self.assertIn(r.status_code, (200, 201), r.content)
        self.assertGreaterEqual(ai.call_count, 2)
        joined = '\n'.join(logs.output)
        self.assertNotIn(MARKER, joined)
        self.assertIn('characters', joined)
