"""E2E: log batch → AI analysis → issues persisted → read APIs return them.

This is the *main product path*: a batch is created (in production by
the 15-min ``create_log_batch_with_project_name`` scheduler; here by
direct ORM insert with a realistic ``data`` shape), the analyzer runs
against a stubbed AI adapter that returns a real-shaped JSON, and the
downstream deduplicator writes ``Issue`` rows the frontend reads via
``/api/data/batches/<id>/`` and ``/api/data/issues/<batch_id>/``.

No layer is mocked besides the AI network hop — DB, prompt builder,
capability gate, deduplicator, serialiser, and read views all run for
real. A regression in any of them fails this test loudly.
"""

from __future__ import annotations

from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from Data.models import AIAnalyzedBatch, Issue

from .base import E2ETestCase, fake_ai_json


class BatchAnalysisE2ETest(E2ETestCase):

    def _log(self, message: str, level: str = 'ERROR') -> dict:
        """One Elasticsearch-hit-shaped log entry.

        The batch pipeline reads ``log['_source']`` — the same shape
        the ES adapter emits. Building it here keeps the fixture close
        to what production actually loads out of Elasticsearch or
        Loki (via the adapter's ES-compat translation).
        """
        return {
            '_id': f'log-{abs(hash(message)) % 10 ** 8}',
            '_source': {
                '@timestamp': timezone.now().isoformat(),
                'message': message,
                'log_level': level,
                'service': {'name': 'checkout'},
                'host': {'name': 'checkout-pod-a'},
            },
        }

    def _make_batch(self, batch_id: str = 'e2e-batch-001') -> AIAnalyzedBatch:
        """Create the batch shape ``create_log_batch_with_project_name`` produces.

        ``data`` mirrors the real snapshot — ES-hit-shaped logs +
        capabilities marker + environment — so the prompt builder and
        capability gate exercise their production paths without any
        fixture-only branches.
        """
        return AIAnalyzedBatch.objects.create(
            batch_id=batch_id,
            project=self.project,
            organisation=self.org,
            environment='production',
            timestamp=timezone.now(),
            data={
                'batch_id': batch_id,
                'timestamp': timezone.now().isoformat(),
                'environment': 'production',
                'logs': [
                    self._log(
                        'ConnectionRefusedError [Errno 111] Connection refused',
                    ),
                    self._log(
                        'redis.exceptions.ConnectionError: Error 111 connecting '
                        'to redis:6379.',
                    ),
                ],
                'project_capabilities': ['logs'],
            },
        )

    def test_full_chain_creates_issues_visible_on_read_api(self):
        batch = self._make_batch()

        ai_payload = fake_ai_json(
            correlated_issues=[
                {
                    'component': 'checkout',
                    'error_target': 'redis:6379',
                    'severity': 'CRITICAL',
                },
                {
                    'issue_type': 'MEMORY_HIGH',
                    'scope': 'INFRASTRUCTURE',
                    'component': 'INFRASTRUCTURE',
                    'error_class': 'OUT_OF_MEMORY',
                    'error_target': 'node-42',
                    'severity': 'WARNING',
                    'description': 'Node-42 memory usage at 87%.',
                    'root_cause': 'Sustained cache-eviction thrashing after redis restart.',
                },
            ],
        )

        # Patch the imported reference inside ai_model.tasks — that is
        # the binding the analyzer actually calls. Patching
        # ai_service.generate_for_organisation would leave the tasks
        # module's rebound name pointing at the real function.
        with patch('ai_model.tasks.generate_for_organisation') as gen:
            gen.return_value = self._fake_generate(ai_payload)[1:]  # (model, err, tin, tout)
            # ai_service returns (result, model, err, tin, tout) — the
            # helper's first element is the JSON string. Rebuild the
            # 5-tuple here to keep the helper reusable.
            import json
            gen.return_value = (
                json.dumps(ai_payload), 'e2e-fake-model', None, 500, 700,
            )

            from ai_model.tasks import analyze_batch
            # ``analyze_batch`` is a bound Celery task — invoke the
            # underlying function directly to skip the queue.
            analyze_batch.run(batch.batch_id)

        gen.assert_called_once()

        # DB assertions — batch got marked analyzed, issues persisted.
        batch.refresh_from_db()
        self.assertIsNotNone(
            batch.analyzed_at,
            'analyzed_at must be set once analyze_batch completes.',
        )

        issues_qs = Issue.objects.filter(batch=batch)
        self.assertEqual(
            issues_qs.count(), 2,
            f'expected 2 issues, saw {list(issues_qs.values_list("component", "issue_type"))}',
        )

        components = set(issues_qs.values_list('component', flat=True))
        self.assertEqual(components, {'checkout', 'INFRASTRUCTURE'})

        severities = set(issues_qs.values_list('severity', flat=True))
        self.assertEqual(severities, {'CRITICAL', 'WARNING'})

        # Read API 1 — batch detail must return the analyzed batch.
        detail_url = reverse('batch-detail', kwargs={'batch_id': batch.batch_id})
        resp = self.client.get(detail_url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(resp.data['batch_id'], batch.batch_id)

        # Read API 2 — issues by batch (the ChatIssues / Issues page path).
        issues_url = reverse('batch-issues', kwargs={'batch_id': batch.batch_id})
        resp = self.client.get(issues_url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        results = resp.data.get('results', resp.data)
        # BatchIssuesView returns either a paginated envelope or a plain
        # list depending on view config — accept either shape as long as
        # both issues surface.
        if isinstance(results, dict) and 'results' in results:
            results = results['results']
        returned_components = {i['component'] for i in results}
        self.assertEqual(returned_components, {'checkout', 'INFRASTRUCTURE'})

    def test_other_org_cannot_see_analyzed_batch(self):
        """Tenant isolation — the parallel org's admin gets nothing back.

        The single most damaging regression in a multi-tenant system is
        a leaked queryset. E2e is the last checkpoint where that would
        surface before beta.
        """
        batch = self._make_batch()

        with patch('ai_model.tasks.generate_for_organisation') as gen:
            import json
            gen.return_value = (
                json.dumps(fake_ai_json()), 'e2e-fake-model', None, 100, 200,
            )
            from ai_model.tasks import analyze_batch
            analyze_batch.run(batch.batch_id)

        self._auth(self.other_admin)

        detail_url = reverse('batch-detail', kwargs={'batch_id': batch.batch_id})
        resp = self.client.get(detail_url)
        self.assertIn(
            resp.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
            f'other-org caller must not see this batch; got {resp.status_code}',
        )

        issues_url = reverse('batch-issues', kwargs={'batch_id': batch.batch_id})
        resp = self.client.get(issues_url)
        if resp.status_code == status.HTTP_200_OK:
            results = resp.data.get('results', resp.data)
            if isinstance(results, dict) and 'results' in results:
                results = results['results']
            self.assertEqual(
                len(results), 0,
                'other-org caller must see zero issues from another org.',
            )
        else:
            self.assertIn(
                resp.status_code,
                (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
            )

    def test_no_correlated_issues_still_marks_batch_analyzed(self):
        """AI can legitimately return zero issues — the batch must still
        be marked analyzed so the wizard's ``waiting_for_first_analysis``
        step advances and the UI doesn't hang on a spinner."""
        batch = self._make_batch(batch_id='e2e-batch-clean')

        clean_payload = fake_ai_json(
            correlated_issues=[], overall_health='HEALTHY',
        )
        with patch('ai_model.tasks.generate_for_organisation') as gen:
            import json
            gen.return_value = (
                json.dumps(clean_payload), 'e2e-fake-model', None, 100, 200,
            )
            from ai_model.tasks import analyze_batch
            analyze_batch.run(batch.batch_id)

        batch.refresh_from_db()
        self.assertIsNotNone(batch.analyzed_at)
        self.assertEqual(Issue.objects.filter(batch=batch).count(), 0)
