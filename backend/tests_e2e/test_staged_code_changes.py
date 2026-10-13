"""E2E regression: staged code_changes must survive the pipeline
Deployment-derivation step (RCA audit finding #1, 2026-09-19).

Before this fix, ``analyze_batch`` (and ``reanalyze_batch_with_model``)
would query ``Deployment`` rows for the batch's project + env + window.
When that query returned nothing, ``code_changes`` was reset to ``[]``
regardless of whether ``batch.data['code_changes']`` already carried a
staged list. That silently killed every code correlation on batches
created outside the full webhook chain — alert-triggered analyses,
backfills, migrations, and any manual batch.

This file pins the fallback: when the Deployment chain is empty AND
staged code_changes exist on ``batch.data``, the pipeline uses the
staged data.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from django.utils import timezone

from Data.models import AIAnalyzedBatch, Issue

from .base import E2ETestCase, fake_ai_json


class StagedCodeChangesFallbackTest(E2ETestCase):

    def _make_batch_with_staged_changes(
        self, batch_id: str = "audit-staged-cc"
    ) -> AIAnalyzedBatch:
        return AIAnalyzedBatch.objects.create(
            batch_id=batch_id,
            project=self.project,
            organisation=self.org,
            environment="production",
            timestamp=timezone.now(),
            data={
                "batch_id": batch_id,
                "timestamp": timezone.now().isoformat(),
                "environment": "production",
                "logs": [
                    {
                        "_id": "log-1",
                        "_source": {
                            "@timestamp": timezone.now().isoformat(),
                            "message": (
                                'Traceback (most recent call last):\n'
                                '  File "services/checkout/api.py", line 42, in process_order\n'
                                '    total = order.total_cents / 0\n'
                                'ZeroDivisionError: division by zero'
                            ),
                            "log_level": "ERROR",
                            "service": {"name": "checkout"},
                            "host": {"name": "checkout-pod-a"},
                        },
                    },
                ],
                # Staged code_changes — no Deployment row exists for this
                # project. Pre-fix pipeline discarded these; post-fix
                # keeps them.
                "code_changes": [
                    {
                        "sha": "abc123def456",
                        "message": "feat(checkout): improve total calculation",
                        "files": ["services/checkout/api.py"],
                        "timestamp": (
                            timezone.now() - timezone.timedelta(minutes=20)
                        ).isoformat(),
                        "branch": "main",
                        "author": "Alice",
                    },
                ],
                "project_capabilities": ["logs", "code"],
            },
        )

    def test_analyze_batch_falls_back_to_staged_code_changes(self):
        batch = self._make_batch_with_staged_changes()

        # Stub the AI so the test focuses on correlation-engine wiring
        # rather than provider behaviour.
        with patch("ai_model.tasks.generate_for_organisation") as gen:
            gen.return_value = (
                json.dumps(fake_ai_json()),
                "test-fake-model",
                None, 100, 200,
            )
            from ai_model.tasks import analyze_batch
            analyze_batch.run(batch.batch_id)

        batch.refresh_from_db()
        correlations = (batch.data or {}).get("correlation_results") or {}
        summary = correlations.get("summary") or {}

        # The whole point of this fix: file_to_error must fire on
        # staged code_changes when no Deployment row exists.
        by_type = correlations.get("correlations") or {}
        file_to_error = by_type.get("file_to_error") or []
        self.assertGreaterEqual(
            len(file_to_error), 1,
            "Expected at least one file_to_error correlation; got zero. "
            "Pipeline dropped the staged code_changes when Deployment "
            "query returned empty. See ai_model/tasks.py fallback."
        )
        self.assertEqual(file_to_error[0]["confidence"], "HIGH")
        self.assertEqual(
            file_to_error[0]["commit_sha"], "abc123de",  # engine truncates to 8 chars
        )
        self.assertIn(
            "services/checkout/api.py", file_to_error[0]["matching_files"],
        )

        primary = summary.get("primary_correlation") or {}
        self.assertEqual(primary.get("type"), "file_to_error")

    def test_analyze_batch_still_returns_empty_when_no_staged_and_no_deployments(self):
        """Regression guard: fallback only kicks in when staged data exists.

        A truly-empty batch (no logs, no code_changes, no anything) must
        not produce spurious correlations from the fallback path.
        """
        batch = AIAnalyzedBatch.objects.create(
            batch_id="audit-empty-batch",
            project=self.project,
            organisation=self.org,
            environment="production",
            timestamp=timezone.now(),
            data={
                "logs": [{"_id": "l", "_source": {
                    "@timestamp": timezone.now().isoformat(),
                    "message": "some log",
                    "log_level": "INFO",
                    "service": {"name": "checkout"},
                    "host": {"name": "h"},
                }}],
                "code_changes": [],   # Explicitly empty
                "project_capabilities": ["logs"],
            },
        )
        with patch("ai_model.tasks.generate_for_organisation") as gen:
            gen.return_value = (
                json.dumps(fake_ai_json()),
                "test-fake-model",
                None, 100, 200,
            )
            from ai_model.tasks import analyze_batch
            analyze_batch.run(batch.batch_id)

        batch.refresh_from_db()
        correlations = (batch.data or {}).get("correlation_results") or {}
        file_to_error = (correlations.get("correlations") or {}).get(
            "file_to_error", []
        )
        self.assertEqual(
            file_to_error, [],
            "Fallback must not fabricate correlations when staged "
            "code_changes are empty.",
        )
