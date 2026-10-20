"""
Resolving an issue can confirm or correct its root cause and fix. Past-incident
memory and similar-incident search then prefer the team's version, and tell
the AI when it was corrected.
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from Data.embeddings import text_for_issue
from Data.memory import find_past_memories, format_memories_for_prompt
from Data.models import AIAnalyzedBatch, Issue
from Organisations.models import Organisations
from Projects.models import Project
from Users.models import User

AI_CAUSE = 'Redis connection pool exhausted after the v2.3.3 deploy shrank it to 20'
TEAM_CAUSE = 'A network policy change blocked payment-worker from reaching Redis on 6379'


class ResolutionTestBase(APITestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Resolution Org')
        self.project = Project.objects.create(name='shop', organisation=self.org)
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='b-resolution', project=self.project, organisation=self.org,
            timestamp=timezone.now(), data={})
        self.user = User.objects.create_user(
            username='r', email='resolver@example.com', password='x', organisation=self.org,
            role='admin', first_name='Ada', last_name='Ops')
        self.client.force_authenticate(user=self.user)

    def issue(self, n=1, **fields):
        data = dict(batch=self.batch, project=self.project, organisation=self.org,
                    severity='CRITICAL', description=f'payment-worker cannot reach Redis {n}',
                    root_cause=AI_CAUSE, recommendation='Raise the pool size back to 50',
                    issue_type='CONNECTION_REFUSED', component='payment-worker',
                    environment='production', fingerprint=f'fp-{n}')
        data.update(fields)
        return Issue.objects.create(**data)

    def resolve(self, issue, **body):
        return self.client.post(
            reverse('issue-action', kwargs={'issue_id': issue.id, 'action': 'resolve'}), body, format='json')


class ResolveWithCorrectionTest(ResolutionTestBase):
    def test_correction_is_stored_with_who_resolved(self):
        issue = self.issue()
        response = self.resolve(issue, root_cause=f'  {TEAM_CAUSE}  ', fix='Restore the network policy')
        self.assertEqual(response.status_code, 200, response.data)
        issue.refresh_from_db()
        self.assertEqual(issue.status, 'RESOLVED')
        self.assertEqual(issue.resolution_root_cause, TEAM_CAUSE)
        self.assertEqual(issue.resolution_fix, 'Restore the network policy')
        self.assertEqual(issue.resolved_by, self.user)
        self.assertEqual(response.data['resolved_by_name'], 'Ada Ops')
        self.assertEqual(response.data['resolution_root_cause'], TEAM_CAUSE)

    def test_plain_resolve_keeps_ai_root_cause(self):
        issue = self.issue()
        self.assertEqual(self.resolve(issue, root_cause='   ').status_code, 200)
        issue.refresh_from_db()
        self.assertIsNone(issue.resolution_root_cause)
        self.assertEqual(issue.effective_root_cause, AI_CAUSE)

    def test_bulk_resolve_records_who(self):
        issue = self.issue()
        self.client.post(reverse('issue-bulk-action'), {'issue_ids': [issue.id], 'action': 'resolve'}, format='json')
        issue.refresh_from_db()
        self.assertEqual(issue.resolved_by, self.user)


class MemoryPrefersTheTeamTest(ResolutionTestBase):
    def resolved(self, n, days_ago=1, **fields):
        issue = self.issue(n, status='RESOLVED', **fields)
        Issue.objects.filter(pk=issue.pk).update(resolved_at=timezone.now() - timedelta(days=days_ago))
        issue.refresh_from_db()
        return issue

    def test_correction_is_shown_with_what_the_ai_said(self):
        self.resolved(1, resolution_root_cause=TEAM_CAUSE, resolution_fix='Restore the network policy')
        text = format_memories_for_prompt(find_past_memories(self.project, 'production', self.org))
        self.assertIn(f'Root cause (corrected by the team): {TEAM_CAUSE}', text)
        self.assertIn(f'The AI had said: {AI_CAUSE}', text)
        self.assertIn('Fix: Restore the network policy', text)

    def test_confirmation_is_labelled(self):
        self.resolved(1, resolution_root_cause=AI_CAUSE)
        text = format_memories_for_prompt(find_past_memories(self.project, 'production', self.org))
        self.assertIn(f'Root cause (confirmed by the team): {AI_CAUSE}', text)
        self.assertNotIn('The AI had said', text)

    def test_unconfirmed_is_labelled(self):
        self.resolved(1)
        text = format_memories_for_prompt(find_past_memories(self.project, 'production', self.org))
        self.assertIn(f'Root cause (AI, not confirmed): {AI_CAUSE}', text)

    def test_team_cause_rescues_a_thin_ai_cause(self):
        self.resolved(1, root_cause='n/a', resolution_root_cause=TEAM_CAUSE)
        self.assertEqual(len(find_past_memories(self.project, 'production', self.org)), 1)

    def test_confirmed_come_first(self):
        self.resolved(1, days_ago=1)
        self.resolved(2, days_ago=1)
        self.resolved(3, days_ago=1)
        old_confirmed = self.resolved(4, days_ago=20, resolution_root_cause=TEAM_CAUSE)
        memories = find_past_memories(self.project, 'production', self.org)
        self.assertEqual(memories[0][0].pk, old_confirmed.pk)


class EmbeddingTextTest(ResolutionTestBase):
    def test_team_version_is_embedded(self):
        issue = self.issue(resolution_root_cause=TEAM_CAUSE, resolution_fix='Restore the network policy')
        text = text_for_issue(issue)
        self.assertIn(f'Root cause: {TEAM_CAUSE}', text)
        self.assertIn('Recommendation: Restore the network policy', text)
        self.assertNotIn(AI_CAUSE, text)
