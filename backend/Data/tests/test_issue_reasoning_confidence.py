"""
Tests for the AI-evidence-chain (reasoning) and confidence fields on Issue.

The fields are populated from the batch-analysis JSON via
Issue._serialize_reasoning and Issue._normalize_confidence. We cover the
parsing helpers in isolation and the end-to-end flow through
Issue.find_or_create_deduplicated.
"""

from django.test import TestCase
from django.utils import timezone

from Organisations.models import Organisations
from Projects.models import Project
from Data.models import AIAnalyzedBatch, Issue


# ---------------------------------------------------------------------------
# _serialize_reasoning
# ---------------------------------------------------------------------------

class SerializeReasoningTest(TestCase):
    def test_none_returns_none(self):
        self.assertIsNone(Issue._serialize_reasoning(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(Issue._serialize_reasoning(''))
        self.assertIsNone(Issue._serialize_reasoning('   '))

    def test_empty_list_returns_none(self):
        self.assertIsNone(Issue._serialize_reasoning([]))

    def test_list_of_strings_is_numbered(self):
        out = Issue._serialize_reasoning([
            'Saw errors in payment-worker',
            'Checked the latest deploy v2.3.3',
            'Confirmed Redis pool was undersized',
        ])
        self.assertEqual(
            out,
            (
                '1. Saw errors in payment-worker\n'
                '2. Checked the latest deploy v2.3.3\n'
                '3. Confirmed Redis pool was undersized'
            ),
        )

    def test_list_skips_blank_steps(self):
        out = Issue._serialize_reasoning(['a', '   ', '', 'b'])
        self.assertEqual(out, '1. a\n2. b')

    def test_plain_string_is_passed_through(self):
        out = Issue._serialize_reasoning('Single-line legacy reasoning')
        self.assertEqual(out, 'Single-line legacy reasoning')

    def test_unsupported_type_returns_none(self):
        self.assertIsNone(Issue._serialize_reasoning({'not': 'a list'}))


# ---------------------------------------------------------------------------
# _normalize_confidence
# ---------------------------------------------------------------------------

class NormalizeConfidenceTest(TestCase):
    def test_none_becomes_unknown(self):
        self.assertEqual(Issue._normalize_confidence(None), 'UNKNOWN')

    def test_empty_becomes_unknown(self):
        self.assertEqual(Issue._normalize_confidence(''), 'UNKNOWN')

    def test_exact_values_pass_through_uppercased(self):
        for value in ('high', 'Medium', 'LOW', 'unknown'):
            self.assertEqual(
                Issue._normalize_confidence(value),
                value.upper(),
            )

    def test_lenient_prefix_matching(self):
        self.assertEqual(Issue._normalize_confidence('hi'), 'HIGH')
        self.assertEqual(Issue._normalize_confidence('med'), 'MEDIUM')
        self.assertEqual(Issue._normalize_confidence('lo'), 'LOW')

    def test_invalid_value_falls_back_to_unknown(self):
        self.assertEqual(Issue._normalize_confidence('certain'), 'UNKNOWN')


# ---------------------------------------------------------------------------
# End-to-end: AI JSON → Issue record
# ---------------------------------------------------------------------------

class FindOrCreateWithReasoningTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Reasoning Org')
        self.project = Project.objects.create(name='proj', organisation=self.org)
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='b-reasoning-1', project=self.project, organisation=self.org,
            timestamp=timezone.now(), data={},
        )

    def _create(self, **overrides):
        # Disable dedup so the test isn't affected by fingerprint logic.
        from org_settings.models import IssueSettings
        IssueSettings.objects.create(
            organisation=self.org, dedup_enabled=False,
        )

        issue_data = {
            'issue_type': 'CONNECTION_REFUSED',
            'scope': 'SERVICE',
            'component': 'payment-worker',
            'severity': 'CRITICAL',
            'description': 'Redis connection refused',
            'root_cause': 'Redis connection pool was undersized after the v2.3.3 deploy',
            'recommended_action': 'Bump pool size to 50',
            'error_class': 'CONNECTION_REFUSED',
            'error_target': 'redis:6379',
            'reasoning': [
                'Saw repeated `ConnectionRefusedError` in payment-worker',
                'Checked deploys → v2.3.3 reduced pool from 50 to 20',
                'Confirmed pool exhaustion at p95 in Redis metrics',
            ],
            'confidence': 'high',
        }
        issue_data.update(overrides)
        issue, _created = Issue.find_or_create_deduplicated(
            issue_data, self.batch, self.project, 'production',
        )
        return issue

    def test_reasoning_array_is_persisted_as_numbered_list(self):
        issue = self._create()
        self.assertIn('1. Saw repeated', issue.reasoning)
        self.assertIn('2. Checked deploys', issue.reasoning)
        self.assertIn('3. Confirmed pool exhaustion', issue.reasoning)

    def test_confidence_is_normalised_to_uppercase(self):
        issue = self._create(confidence='high')
        self.assertEqual(issue.confidence, 'HIGH')

    def test_missing_reasoning_is_null(self):
        issue = self._create(reasoning=None)
        self.assertIsNone(issue.reasoning)

    def test_missing_confidence_defaults_to_unknown(self):
        issue = self._create(confidence=None)
        self.assertEqual(issue.confidence, 'UNKNOWN')

    def test_lenient_confidence_input_med(self):
        issue = self._create(confidence='med')
        self.assertEqual(issue.confidence, 'MEDIUM')
