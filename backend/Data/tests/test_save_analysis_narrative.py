"""Regression tests for ``AIAnalyzedBatch.save_analysis``.

Prior to the 2026-09-20 RCA-audit follow-up, ``save_analysis`` assigned
the raw ``analysis_result`` dict directly to the ``analysis_text``
``TextField``. Django coerced the dict to its Python ``repr()``, so
Batch Detail's hero card rendered walls of ``{'summary': {...`` text
with single-quoted keys — the shape the frontend now defensively
rejects. This test pins the fix: ``analysis_text`` must only ever
carry the human-readable narrative extracted from the first
correlated issue (or a bare string when the AI returned prose).
"""

from __future__ import annotations

from django.test import TestCase

from Data.models import AIAnalyzedBatch


class SaveAnalysisNarrativeTest(TestCase):

    def _make_batch(self, batch_id: str = 'save-analysis-test') -> AIAnalyzedBatch:
        return AIAnalyzedBatch.objects.create(batch_id=batch_id)

    def test_dict_result_stores_narrative_not_repr(self):
        batch = self._make_batch()
        analysis = {
            'summary': {'total_entries': 7, 'critical': 3},
            'correlated_issues': [
                {
                    'root_cause': (
                        'Redis service at redis:6379 is unreachable, '
                        'causing checkout cache operations to fail.'
                    ),
                    'severity': 'CRITICAL',
                },
            ],
        }
        batch.save_analysis(analysis, model_name='claude-sonnet-4-5')
        batch.refresh_from_db()

        self.assertIsNotNone(batch.analysis_text)
        # Narrative made it through.
        self.assertIn('Redis service at redis:6379', batch.analysis_text)
        # And the dict-repr signature did NOT leak into the field.
        self.assertNotIn("{'summary':", batch.analysis_text)
        self.assertNotIn("'correlated_issues':", batch.analysis_text)
        self.assertNotIn("'root_cause':", batch.analysis_text)

    def test_full_dict_still_stored_under_data_and_history(self):
        batch = self._make_batch('save-analysis-history')
        analysis = {
            'summary': {'total_entries': 4},
            'correlated_issues': [
                {'root_cause': 'Disk I/O saturated on db-primary.'},
            ],
        }
        batch.save_analysis(analysis, model_name='claude-sonnet-4-5')
        batch.refresh_from_db()

        # History keeps the full JSON — nothing lost.
        self.assertEqual(len(batch.analysis_history), 1)
        entry = batch.analysis_history[-1]
        self.assertEqual(entry['is_primary'], True)
        self.assertEqual(entry['model_name'], 'claude-sonnet-4-5')
        self.assertEqual(
            entry['analysis_result']['correlated_issues'][0]['root_cause'],
            'Disk I/O saturated on db-primary.',
        )

    def test_string_result_stored_capped(self):
        batch = self._make_batch('save-analysis-string')
        prose = 'A' * 5000
        batch.save_analysis(prose, model_name='legacy-adapter')
        batch.refresh_from_db()
        self.assertEqual(len(batch.analysis_text), 4000)

    def test_no_correlated_issues_stores_none(self):
        batch = self._make_batch('save-analysis-empty')
        batch.save_analysis({'summary': {'total_entries': 0}, 'correlated_issues': []})
        batch.refresh_from_db()
        self.assertIsNone(batch.analysis_text)

    def test_nested_dict_root_cause_flattened(self):
        # A legacy prompt output where root_cause was itself a nested dict.
        batch = self._make_batch('save-analysis-nested')
        analysis = {
            'correlated_issues': [
                {
                    'root_cause': {
                        'description': 'Connection pool exhausted on api-gateway.',
                        'confidence': 0.87,
                    },
                },
            ],
        }
        batch.save_analysis(analysis)
        batch.refresh_from_db()
        self.assertEqual(
            batch.analysis_text,
            'Connection pool exhausted on api-gateway.',
        )

    def test_narrative_capped_at_4000_chars(self):
        batch = self._make_batch('save-analysis-cap')
        analysis = {
            'correlated_issues': [{'root_cause': 'B' * 6000}],
        }
        batch.save_analysis(analysis)
        batch.refresh_from_db()
        self.assertEqual(len(batch.analysis_text), 4000)

    def test_none_result_stores_none(self):
        batch = self._make_batch('save-analysis-none')
        batch.save_analysis(None)
        batch.refresh_from_db()
        self.assertIsNone(batch.analysis_text)
