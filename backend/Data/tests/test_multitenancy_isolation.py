"""
Cross-org multi-tenancy isolation tests.

Every test creates two organisations (A + B), puts data in each, then
authenticates as a user in org A and asserts that org B's data is
unreachable through every org-scoped endpoint.

**If any test in this file fails, a real cross-org leak has been
introduced.** Do not skip these, do not mock the models away. This
is the codified expectation for the multi-tenancy boundary — the
suite that catches regressions of the isolation fixes in commits
2870c69, d8d4b61, 361450f, 3478396.

Coverage:

  Batches
    - BatchDetailView              (GET /api/data/batches/<batch_id>/)
    - BatchAnalysisHistoryView     (GET /api/data/batches/<batch_id>/history/)
    - MetricCorrelationView        (GET /api/data/batches/<batch_id>/correlations/)
    - BatchReanalyzeView           (POST /api/data/batches/reanalyze/)
    - BatchIssuesView              (GET /api/data/issues/<batch_id>/)
    - trigger_batch_analysis       (POST /api/chat/analyze-batch/)
    - LogBatchView list            (GET /api/data/batches)

  Issues
    - IssueActionsView             (POST /api/data/issues/<issue_id>/<action>/)
    - IssueAcknowledgeView         (POST /api/notification/issues/<issue_id>/acknowledge/)
    - IssueListView                (GET /api/data/issues/)

  Chat sessions
    - get_chat_history             (GET /api/chat/chats/<chat_id>/)
    - update_chat_session          (PUT /api/chat/chats/<chat_id>/update/)
    - delete_chat_session          (DELETE /api/chat/chats/delete/<chat_id>)
    - list_chat_sessions           (GET /api/chat/chats/)

  Integrations
    - ObservabilityIntegrationViewSet CRUD
    - ProviderIntegrationViewSet CRUD

  Projects + Services
    - ProjectListView / ProjectDetailView
    - ProjectServiceView

  Notifications
    - ProjectSubscriptionListView / detail

Not covered here (covered elsewhere):
  - LogQuery.scope_services_to_org  → integrations/tests/test_logquery_scope.py
  - Dashboard analytics views       → aggregate stats only, filtered
    by user's org via OrgFilterMixin (Data/mixins.py) — regression
    caught by any bogus data leaking into a stats endpoint
"""

import uuid
from datetime import datetime, timezone as py_timezone
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from ai_model.models import ChatMessage, ChatSession
from Data.models import AIAnalyzedBatch, Issue
from integrations.models import ObservabilityIntegration
from notifications.models import ProjectSubscription
from Organisations.models import Organisations
from Projects.models import Project, ProjectService
from providers.models import ProviderIntegration
from Users.models import User


class MultiTenancyIsolationTest(APITestCase):
    """
    Standard fixture: two orgs, one admin user each, sample data in
    both. Cross-authenticate to test every org-scoped endpoint.
    """

    @classmethod
    def setUpTestData(cls):
        # ── Orgs ───────────────────────────────────────────────
        cls.org_a = Organisations.objects.create(
            name='Org A', website='https://a.example',
        )
        cls.org_b = Organisations.objects.create(
            name='Org B', website='https://b.example',
        )

        # ── Admin users (one per org) ──────────────────────────
        cls.user_a = User.objects.create_user(
            username='usera', email='usera@a.example',
            password='TestPass123!', organisation=cls.org_a,
            role='admin', is_active=True,
        )
        cls.user_b = User.objects.create_user(
            username='userb', email='userb@b.example',
            password='TestPass123!', organisation=cls.org_b,
            role='admin', is_active=True,
        )

        # ── Projects + Services (one per org) ──────────────────
        cls.project_a = Project.objects.create(
            name='proj-a', organisation=cls.org_a,
        )
        cls.project_b = Project.objects.create(
            name='proj-b', organisation=cls.org_b,
        )
        cls.service_a = ProjectService.objects.create(
            project=cls.project_a, name='svc-a', service_type='application',
        )
        cls.service_b = ProjectService.objects.create(
            project=cls.project_b, name='svc-b', service_type='application',
        )

        # ── Batches (one per org) ──────────────────────────────
        now = timezone.now()
        cls.batch_a = AIAnalyzedBatch.objects.create(
            batch_id='batch-a-001',
            organisation=cls.org_a,
            project=cls.project_a,
            timestamp=now,
            environment='production',
            model_name='claude-sonnet-4',
            data={'correlation_results': {'correlations': {}, 'summary': {}}},
        )
        cls.batch_b = AIAnalyzedBatch.objects.create(
            batch_id='batch-b-001',
            organisation=cls.org_b,
            project=cls.project_b,
            timestamp=now,
            environment='production',
            model_name='claude-sonnet-4',
            data={'correlation_results': {'correlations': {}, 'summary': {}}},
        )

        # ── Issues (one per org) ───────────────────────────────
        cls.issue_a = Issue.objects.create(
            batch=cls.batch_a,
            organisation=cls.org_a,
            project=cls.project_a,
            issue_type='CONNECTION_REFUSED',
            severity='CRITICAL',
            status='OPEN',
            description='org A issue',
            fingerprint=uuid.uuid4().hex,
            component='svc-a',
            environment='production',
        )
        cls.issue_b = Issue.objects.create(
            batch=cls.batch_b,
            organisation=cls.org_b,
            project=cls.project_b,
            issue_type='CONNECTION_REFUSED',
            severity='CRITICAL',
            status='OPEN',
            description='org B issue',
            fingerprint=uuid.uuid4().hex,
            component='svc-b',
            environment='production',
        )

        # ── Chat sessions (one per user) ───────────────────────
        cls.chat_a = ChatSession.objects.create(
            chat_id=uuid.uuid4(),
            user=cls.user_a,
            title='A chat',
        )
        cls.chat_b = ChatSession.objects.create(
            chat_id=uuid.uuid4(),
            user=cls.user_b,
            title='B chat',
        )

        # ── ObservabilityIntegration (one per org) ─────────────
        cls.obs_a = ObservabilityIntegration.objects.create(
            organisation=cls.org_a, provider='elasticsearch',
            display_name='ES A', capabilities=['logs'],
            host='https://es-a.example:9200',
        )
        cls.obs_b = ObservabilityIntegration.objects.create(
            organisation=cls.org_b, provider='elasticsearch',
            display_name='ES B', capabilities=['logs'],
            host='https://es-b.example:9200',
        )

        # ── ProviderIntegration (SCM) — one per org ────────────
        cls.prov_a = ProviderIntegration.objects.create(
            organisation=cls.org_a, provider_type='github',
            name='GH A', base_url='https://api.github.com',
        )
        cls.prov_b = ProviderIntegration.objects.create(
            organisation=cls.org_b, provider_type='github',
            name='GH B', base_url='https://api.github.com',
        )

        # ── ProjectSubscription (one per user) ─────────────────
        cls.sub_a = ProjectSubscription.objects.create(
            user=cls.user_a, project=cls.project_a,
        )
        cls.sub_b = ProjectSubscription.objects.create(
            user=cls.user_b, project=cls.project_b,
        )

    def _as_a(self):
        self.client.force_authenticate(user=self.user_a)

    def _as_b(self):
        self.client.force_authenticate(user=self.user_b)

    # ══════════════════════════════════════════════════════════
    # BATCHES
    # ══════════════════════════════════════════════════════════

    def test_batch_detail_hides_other_org_batch(self):
        # User A authenticates and tries to read org B's batch.
        # Must 404 (not 200, not 403 — same as "doesn't exist" so
        # no cross-org enumeration oracle).
        self._as_a()
        resp = self.client.get(f'/api/data/batches/{self.batch_b.batch_id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_batch_detail_returns_own_batch(self):
        # Sanity check: the same endpoint returns 200 for the user's own batch.
        self._as_a()
        resp = self.client.get(f'/api/data/batches/{self.batch_a.batch_id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_batch_analysis_history_hides_other_org_batch(self):
        self._as_a()
        resp = self.client.get(f'/api/data/batches/{self.batch_b.batch_id}/history/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_metric_correlations_hides_other_org_batch(self):
        self._as_a()
        resp = self.client.get(f'/api/data/batches/{self.batch_b.batch_id}/correlations/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_batch_reanalyze_rejects_other_org_batch(self):
        # Even if the user sends their own batch AND org B's batch in
        # the same request, the whole request must be rejected — one
        # bad id doesn't leak the good ones.
        self._as_a()
        with patch('org_settings.models.AIModelProvider.objects.filter') as mock_filter:
            mock_filter.return_value.exists.return_value = True
            resp = self.client.post(
                '/api/data/batches/reanalyze/',
                {'batch_ids': [self.batch_a.batch_id, self.batch_b.batch_id],
                 'model': 'claude-sonnet-4'},
                format='json',
            )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_trigger_batch_analysis_rejects_other_org_batch(self):
        # This is the CRITICAL fix from commit d8d4b61 — prior code
        # had NO org check at all. Regression here = full cross-org
        # exploit.
        self._as_a()
        # Manual trigger endpoint now dispatches analyze_batch directly
        # (severity filter moved inline; standalone preprocess_logs
        # removed). Patch the direct dispatch to prove we never call
        # it for another org's batch.
        with patch('ai_model.tasks.analyze_batch.delay') as mock_task:
            resp = self.client.post(
                '/api/chat/analyze-batch/',
                {'batch_id': self.batch_b.batch_id},
                format='json',
            )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        # Absolutely critical: the Celery task must NOT be dispatched
        # on a batch that doesn't belong to the caller.
        mock_task.assert_not_called()

    def test_batch_issues_hides_other_org_batch(self):
        self._as_a()
        resp = self.client.get(f'/api/data/issues/{self.batch_b.batch_id}/')
        # BatchIssuesView should return no issues (batch not in org A).
        # Response is 200 with empty issues list OR 404 depending on
        # implementation; either way, org B's issue must not appear.
        if resp.status_code == 200:
            issues = resp.data if isinstance(resp.data, list) else resp.data.get('issues', [])
            ids = [i.get('id') for i in issues]
            self.assertNotIn(self.issue_b.id, ids)

    def test_batch_list_scoped_to_own_org(self):
        self._as_a()
        resp = self.client.get('/api/data/batches')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        body = resp.data if isinstance(resp.data, dict) else {'results': resp.data}
        rows = body.get('results') or body.get('batches') or []
        batch_ids = [r.get('batch_id') for r in rows if isinstance(r, dict)]
        self.assertIn(self.batch_a.batch_id, batch_ids)
        self.assertNotIn(self.batch_b.batch_id, batch_ids)

    # ══════════════════════════════════════════════════════════
    # ISSUES
    # ══════════════════════════════════════════════════════════

    def test_issue_action_resolve_hides_other_org_issue(self):
        self._as_a()
        resp = self.client.post(f'/api/data/issues/{self.issue_b.id}/resolve/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        # Confirm no mutation happened.
        self.issue_b.refresh_from_db()
        self.assertEqual(self.issue_b.status, 'OPEN')

    def test_issue_action_reopen_hides_other_org_issue(self):
        self._as_a()
        resp = self.client.post(f'/api/data/issues/{self.issue_b.id}/reopen/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_issue_action_mute_hides_other_org_issue(self):
        self._as_a()
        resp = self.client.post(
            f'/api/data/issues/{self.issue_b.id}/mute/',
            {'days': 7}, format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_issue_acknowledge_hides_other_org_issue(self):
        # This is the fix from commit d8d4b61 for the
        # `issue.project and issue.project.organisation != …` bug that
        # silently skipped the check for project=None issues.
        self._as_a()
        resp = self.client.post(
            f'/api/notification/issues/{self.issue_b.id}/acknowledge/'
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.issue_b.refresh_from_db()
        self.assertIsNone(self.issue_b.acknowledged_at)

    def test_issue_acknowledge_project_none_still_scoped(self):
        # Reproduce the exact bug commit d8d4b61 closed: an issue with
        # project=None used to silently bypass the org check because
        # the guard was `if issue.project and issue.project.organisation != …`.
        # Now Issue.organisation FK is checked directly.
        orphan_issue = Issue.objects.create(
            batch=self.batch_b,
            organisation=self.org_b,
            project=None,  # ← the exact bug trigger
            issue_type='CONNECTION_REFUSED',
            severity='CRITICAL',
            status='OPEN',
            description='org B orphan',
            fingerprint=uuid.uuid4().hex,
            component='misc',
        )
        self._as_a()
        resp = self.client.post(
            f'/api/notification/issues/{orphan_issue.id}/acknowledge/'
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        orphan_issue.refresh_from_db()
        self.assertIsNone(orphan_issue.acknowledged_at)

    def test_issue_list_scoped_to_own_org(self):
        self._as_a()
        resp = self.client.get('/api/data/issues/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        body = resp.data if isinstance(resp.data, dict) else {'results': resp.data}
        rows = body.get('results', body.get('issues', []))
        ids = [r.get('id') for r in rows if isinstance(r, dict)]
        self.assertIn(self.issue_a.id, ids)
        self.assertNotIn(self.issue_b.id, ids)

    def test_issue_bulk_action_rejects_other_org_ids(self):
        self._as_a()
        resp = self.client.post(
            '/api/data/issues/bulk-action/',
            {'issue_ids': [self.issue_a.id, self.issue_b.id],
             'action': 'resolve'},
            format='json',
        )
        # Bulk action must not mutate org B's issue. Either the whole
        # request rejects, or org B's issue is silently skipped.
        # Either way, issue_b must still be OPEN.
        self.issue_b.refresh_from_db()
        self.assertEqual(self.issue_b.status, 'OPEN')

    # ══════════════════════════════════════════════════════════
    # CHAT SESSIONS
    # ══════════════════════════════════════════════════════════

    def test_chat_history_hides_other_user_chat(self):
        self._as_a()
        resp = self.client.get(f'/api/chat/chats/{self.chat_b.chat_id}/')
        self.assertIn(resp.status_code, (404, 403))

    def test_chat_update_hides_other_user_chat(self):
        # update_chat_session is decorated @api_view(['PATCH']) — using
        # PUT here would return 405 and mask the real cross-user check.
        self._as_a()
        resp = self.client.patch(
            f'/api/chat/chats/{self.chat_b.chat_id}/update/',
            {'title': 'HIJACKED'},
            format='json',
        )
        self.assertIn(resp.status_code, (404, 403))
        self.chat_b.refresh_from_db()
        self.assertEqual(self.chat_b.title, 'B chat')

    def test_chat_delete_hides_other_user_chat(self):
        self._as_a()
        resp = self.client.delete(f'/api/chat/chats/delete/{self.chat_b.chat_id}')
        self.assertIn(resp.status_code, (404, 403))
        # Confirm the chat still exists.
        self.assertTrue(
            ChatSession.objects.filter(chat_id=self.chat_b.chat_id).exists()
        )

    def test_chat_list_scoped_to_own_user(self):
        self._as_a()
        resp = self.client.get('/api/chat/chats/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        body = resp.data if isinstance(resp.data, dict) else {'results': resp.data}
        rows = body.get('results') or body.get('sessions') or (
            body if isinstance(body, list) else []
        )
        ids = [str(r.get('chat_id')) for r in rows if isinstance(r, dict)]
        self.assertNotIn(str(self.chat_b.chat_id), ids)

    # ══════════════════════════════════════════════════════════
    # INTEGRATIONS
    # ══════════════════════════════════════════════════════════

    def test_observability_list_scoped_to_own_org(self):
        self._as_a()
        resp = self.client.get('/api/integrations/observability/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        rows = resp.data if isinstance(resp.data, list) else resp.data.get('results', [])
        ids = [r.get('id') for r in rows if isinstance(r, dict)]
        self.assertIn(self.obs_a.id, ids)
        self.assertNotIn(self.obs_b.id, ids)

    def test_observability_detail_hides_other_org(self):
        self._as_a()
        resp = self.client.get(f'/api/integrations/observability/{self.obs_b.id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_observability_delete_hides_other_org(self):
        self._as_a()
        resp = self.client.delete(f'/api/integrations/observability/{self.obs_b.id}/')
        self.assertIn(resp.status_code, (403, 404))
        # Org B's integration must still exist.
        self.assertTrue(
            ObservabilityIntegration.objects.filter(pk=self.obs_b.pk).exists()
        )

    def test_provider_integration_list_scoped_to_own_org(self):
        self._as_a()
        resp = self.client.get('/api/providers/integrations/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        rows = resp.data if isinstance(resp.data, list) else resp.data.get('results', [])
        ids = [r.get('id') for r in rows if isinstance(r, dict)]
        self.assertIn(self.prov_a.id, ids)
        self.assertNotIn(self.prov_b.id, ids)

    def test_provider_integration_detail_hides_other_org(self):
        self._as_a()
        resp = self.client.get(f'/api/providers/integrations/{self.prov_b.id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_provider_integration_delete_hides_other_org(self):
        self._as_a()
        resp = self.client.delete(f'/api/providers/integrations/{self.prov_b.id}/')
        self.assertIn(resp.status_code, (403, 404))
        self.assertTrue(
            ProviderIntegration.objects.filter(pk=self.prov_b.pk).exists()
        )

    # ══════════════════════════════════════════════════════════
    # PROJECTS + SERVICES
    # ══════════════════════════════════════════════════════════

    def test_project_list_scoped_to_own_org(self):
        self._as_a()
        resp = self.client.get('/api/projects/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        rows = resp.data if isinstance(resp.data, list) else resp.data.get('results', [])
        ids = [r.get('id') for r in rows if isinstance(r, dict)]
        self.assertIn(self.project_a.id, ids)
        self.assertNotIn(self.project_b.id, ids)

    def test_project_detail_hides_other_org(self):
        self._as_a()
        resp = self.client.get(f'/api/projects/{self.project_b.id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_org_list_hides_other_orgs(self):
        """Regression guard for the pre-2026-08-30 leak in
        OrganisationListPublicView that returned every org in the DB
        to any authenticated user (customer enumeration). Non-superuser
        callers should now only see their own org."""
        self._as_a()
        resp = self.client.get('/api/organisation/list/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        rows = resp.data.get('organisations', [])
        ids = [r.get('id') for r in rows if isinstance(r, dict)]
        self.assertIn(self.org_a.id, ids)
        self.assertNotIn(self.org_b.id, ids)

    def test_service_list_scoped_to_own_project(self):
        # Trying to list services under another org's project must
        # not reveal that project's services.
        self._as_a()
        resp = self.client.get(f'/api/projects/{self.project_b.id}/services/')
        # Either 404 (project not visible) or 200 with empty list.
        if resp.status_code == 200:
            rows = resp.data if isinstance(resp.data, list) else resp.data.get('results', [])
            names = [r.get('name') for r in rows if isinstance(r, dict)]
            self.assertNotIn('svc-b', names)

    # ══════════════════════════════════════════════════════════
    # NOTIFICATIONS
    # ══════════════════════════════════════════════════════════

    def test_subscription_list_scoped_to_own_user(self):
        self._as_a()
        resp = self.client.get('/api/notification/subscriptions/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        rows = resp.data if isinstance(resp.data, list) else resp.data.get('results', [])
        ids = [r.get('id') for r in rows if isinstance(r, dict)]
        self.assertIn(self.sub_a.id, ids)
        self.assertNotIn(self.sub_b.id, ids)

    def test_subscription_detail_hides_other_user(self):
        self._as_a()
        resp = self.client.get(f'/api/notification/subscriptions/{self.sub_b.id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_subscription_delete_hides_other_user(self):
        self._as_a()
        resp = self.client.delete(f'/api/notification/subscriptions/{self.sub_b.id}/')
        self.assertIn(resp.status_code, (403, 404))
        self.assertTrue(
            ProjectSubscription.objects.filter(pk=self.sub_b.pk).exists()
        )

    # ══════════════════════════════════════════════════════════
    # NEGATIVE-CONTROL: user with no organisation is fully locked out
    # ══════════════════════════════════════════════════════════

    def test_orgless_user_sees_nothing(self):
        # A user without organisation set is a degenerate state
        # (invited-but-not-activated, or org deleted mid-session).
        # They must not see anything from either org.
        orphan = User.objects.create_user(
            username='orphan', email='orphan@none.example',
            password='TestPass123!', organisation=None,
            role='admin', is_active=True,
        )
        self.client.force_authenticate(user=orphan)

        resp = self.client.get(f'/api/data/batches/{self.batch_a.batch_id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

        resp = self.client.get(f'/api/data/batches/{self.batch_b.batch_id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

        resp = self.client.get('/api/integrations/observability/')
        # List endpoint returns 200 with empty results, not 500.
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        rows = resp.data if isinstance(resp.data, list) else resp.data.get('results', [])
        self.assertEqual(len(rows), 0)

        resp = self.client.get('/api/projects/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        rows = resp.data if isinstance(resp.data, list) else resp.data.get('results', [])
        self.assertEqual(len(rows), 0)
