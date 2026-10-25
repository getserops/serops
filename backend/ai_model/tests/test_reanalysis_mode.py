"""Tests for ``reanalyze_batch_with_model(mode=...)`` and
``promote_history_entry_to_primary`` — RCA audit finding #11 (2026-09-20).

Before finding #11, the re-analyse action always ran in "compare"
mode: it appended to ``analysis_history`` and nothing else. The
button labelled "Re-Analyze" produced no visible change on the Issues
page. These tests pin the fix:

* ``mode='compare'`` (default, back-compat): analysis_text unchanged,
  Issues untouched, a new entry lands in analysis_history with
  ``is_primary=False``.
* ``mode='primary'``: analysis_text updated (via the PR-AUDIT6 narrative
  extraction), Issues created/updated via the same fingerprint dedup
  used by the primary flow, prior history entries demoted, new entry
  marked ``is_primary=True``.
* ``promote_history_entry_to_primary``: takes an existing history
  entry and promotes it — no AI call, same persistence tail.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from Data.models import AIAnalyzedBatch, Issue
from Organisations.models import Organisations
from Projects.models import Project
from ai_model.tasks import (
    _apply_primary_analysis_to_batch,
    promote_history_entry_to_primary,
    reanalyze_batch_with_model,
)


def _analysis(root_cause: str, error_target: str = 'redis:6379'):
    """Return a minimal parsed analysis dict the real AI would return."""
    return {
        'summary': {'total_entries': 5},
        'correlated_issues': [
            {
                'issue_type': 'INFRASTRUCTURE_ERROR',
                'scope': 'SERVICE',
                'component': 'checkout',
                'severity': 'CRITICAL',
                'error_class': 'CONNECTION_REFUSED',
                'error_target': error_target,
                'description': root_cause,
                'root_cause': root_cause,
            },
        ],
    }


class _BatchFixture(TestCase):
    """Shared setUp for reanalysis-mode + promote tests."""

    def setUp(self):
        self.org = Organisations.objects.create(
            name=f'test-org-{uuid.uuid4().hex[:8]}',
            website='https://t.com',
        )
        self.project = Project.objects.create(
            name=f'test-project-{uuid.uuid4().hex[:8]}',
            organisation=self.org,
        )
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id=f'test-batch-{uuid.uuid4().hex[:8]}',
            project=self.project,
            organisation=self.org,
            timestamp=timezone.now(),
            data={'logs': [], 'metrics_summary': {}},
        )


class ApplyPrimaryAnalysisHelperTest(_BatchFixture):
    """The extracted helper the compare→primary flow shares."""

    def test_creates_issues_and_updates_narrative(self):
        summary = _apply_primary_analysis_to_batch(
            self.batch, _analysis('Redis @ 6379 unreachable'),
            model_name='claude-sonnet-4-5',
        )
        self.batch.refresh_from_db()
        self.assertEqual(summary['issues_created'], 1)
        self.assertEqual(summary['issue_count'], 1)
        # analysis_text is now the narrative, not the dict repr.
        self.assertEqual(self.batch.analysis_text, 'Redis @ 6379 unreachable')
        self.assertEqual(self.batch.model_name, 'claude-sonnet-4-5')
        self.assertFalse(self.batch.analysis_text.startswith('{'))

    def test_second_run_dedups_via_fingerprint_and_bumps_occurrence(self):
        _apply_primary_analysis_to_batch(
            self.batch, _analysis('first pass'), model_name='claude',
        )
        first_issue = Issue.objects.get(batch=self.batch)
        first_count = first_issue.occurrence_count

        # Second run with same shape: same fingerprint → dedup, bump.
        _apply_primary_analysis_to_batch(
            self.batch, _analysis('second pass same target'), model_name='claude',
        )
        self.assertEqual(Issue.objects.filter(batch=self.batch).count(), 1)
        first_issue.refresh_from_db()
        self.assertGreater(first_issue.occurrence_count, first_count)


def _fake_ai_stack(result_str: str):
    """Patch stack that returns ``result_str`` from every AI adapter call.

    The reanalyze task calls ``generate_text_unified`` (imported at
    module scope in ``ai_model.tasks``) and reads the org's API key
    via ``get_api_key_for_org``. We stub both so the test doesn't need
    a real provider or key.
    """
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(patch(
        'ai_model.tasks.generate_text_unified',
        return_value=(result_str, None, 100, 50),
    ))
    stack.enter_context(patch(
        'ai_model.tasks.get_api_key_for_org',
        return_value=(None, None, {}),
    ))
    return stack


class ReanalyseModeCompareTest(_BatchFixture):
    """Default mode — no side-effects on primary/Issues (back-compat)."""

    def test_compare_appends_history_entry_without_touching_primary(self):
        self.batch.analysis_text = 'PRIMARY: original narrative'
        self.batch.model_name = 'gemini'
        self.batch.save()

        with _fake_ai_stack(
            '{"correlated_issues": [{"root_cause": "reanalysed"}]}'
        ):
            reanalyze_batch_with_model.run(
                self.batch.batch_id, 'claude', mode='compare',
            )

        self.batch.refresh_from_db()
        # Primary untouched.
        self.assertEqual(self.batch.analysis_text, 'PRIMARY: original narrative')
        self.assertEqual(self.batch.model_name, 'gemini')
        # No Issues created.
        self.assertEqual(Issue.objects.filter(batch=self.batch).count(), 0)
        # But a history entry landed.
        self.assertEqual(len(self.batch.analysis_history), 1)
        entry = self.batch.analysis_history[0]
        self.assertEqual(entry['model_name'], 'claude')
        self.assertFalse(entry['is_primary'])
        self.assertEqual(entry['mode'], 'compare')


class ReanalyseNonEcsLogsTest(_BatchFixture):
    """Batches from Loki / Splunk / Datadog store ``service`` as a string and
    ``level`` instead of ``log_level``; re-analysis used to crash on them."""

    def test_loki_shaped_logs(self):
        self.batch.data = {'logs': [{'_source': {
            '@timestamp': '2026-10-23T20:00:00Z', 'level': 'ERROR', 'service': 'payments',
            'service_name': 'payments', 'message': 'pool exhausted',
        }}], 'metrics_summary': {}}
        self.batch.save()
        with _fake_ai_stack('{"correlated_issues": []}') as _, \
                patch('ai_model.tasks.generate_text_unified',
                      return_value=('{"correlated_issues": []}', None, 1, 1)) as gen:
            reanalyze_batch_with_model.run(self.batch.batch_id, 'claude', mode='compare')
        prompt = str(gen.call_args)
        self.assertIn('[ERROR] [payments] pool exhausted', prompt)


class ReanalyseModePrimaryTest(_BatchFixture):
    """New mode — promotes result to primary AND creates Issues."""

    def test_primary_updates_analysis_text_and_creates_issues(self):
        # Seed a prior compare-mode entry so we can verify it gets demoted.
        self.batch.analysis_history = [{
            'model_name': 'gemini',
            'analyzed_at': '2026-09-19T00:00:00Z',
            'analysis_result': _analysis('old compare narrative'),
            'is_primary': False,
            'mode': 'compare',
        }]
        self.batch.save()

        payload = (
            '{"correlated_issues": [{"issue_type":"INFRASTRUCTURE_ERROR",'
            '"scope":"SERVICE","component":"checkout","severity":"CRITICAL",'
            '"error_class":"CONNECTION_REFUSED","error_target":"redis:6379",'
            '"description":"redis down","root_cause":"redis at :6379 unreachable"}]}'
        )
        with _fake_ai_stack(payload):
            reanalyze_batch_with_model.run(
                self.batch.batch_id, 'claude', mode='primary',
            )

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.model_name, 'claude')
        self.assertEqual(
            self.batch.analysis_text, 'redis at :6379 unreachable',
        )
        # One issue created via the dedup helper.
        self.assertEqual(Issue.objects.filter(batch=self.batch).count(), 1)
        # New entry is primary, old is demoted.
        self.assertEqual(len(self.batch.analysis_history), 2)
        entries_by_model = {e['model_name']: e for e in self.batch.analysis_history}
        self.assertTrue(entries_by_model['claude']['is_primary'])
        self.assertFalse(entries_by_model['gemini']['is_primary'])
        self.assertEqual(entries_by_model['claude']['mode'], 'primary')


class PromoteHistoryEntryTest(_BatchFixture):
    """`promote_history_entry_to_primary` — fast path, no AI call."""

    def test_promote_uses_history_entry_as_new_primary(self):
        # Seed: two history entries, gemini currently primary
        self.batch.analysis_text = 'PRIMARY: gemini narrative'
        self.batch.model_name = 'gemini'
        self.batch.analysis_history = [
            {
                'model_name': 'gemini',
                'analyzed_at': '2026-09-19T00:00:00Z',
                'analysis_result': _analysis('gemini said redis'),
                'is_primary': True,
                'mode': 'primary',
            },
            {
                'model_name': 'claude',
                'analyzed_at': '2026-09-19T01:00:00Z',
                'analysis_result': _analysis('claude said redis, more precise'),
                'is_primary': False,
                'mode': 'compare',
            },
        ]
        self.batch.save()

        summary = promote_history_entry_to_primary(
            self.batch, '2026-09-19T01:00:00Z',
        )
        self.batch.refresh_from_db()

        self.assertEqual(summary['issues_created'], 1)
        self.assertEqual(self.batch.analysis_text, 'claude said redis, more precise')
        self.assertEqual(self.batch.model_name, 'claude')
        # is_primary flipped
        by_model = {e['model_name']: e for e in self.batch.analysis_history}
        self.assertFalse(by_model['gemini']['is_primary'])
        self.assertTrue(by_model['claude']['is_primary'])

    def test_promote_unknown_analyzed_at_raises(self):
        self.batch.analysis_history = [{
            'model_name': 'gemini',
            'analyzed_at': '2026-09-19T00:00:00Z',
            'analysis_result': _analysis('x'),
            'is_primary': True,
        }]
        self.batch.save()

        with self.assertRaises(ValueError):
            promote_history_entry_to_primary(
                self.batch, '2099-01-01T00:00:00Z',
            )
