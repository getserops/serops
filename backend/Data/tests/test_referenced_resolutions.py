"""
Tests for Recent Resolutions Context surfacing:
  - _build_past_memories returns the IDs of the resolved issues it found
  - IssueSerializer.informed_by exposes a compact digest of those issues
  - empty / no-context cases produce {'count': 0, 'items': []} so the
    frontend can render conditionally without a follow-up request
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from Organisations.models import Organisations
from Projects.models import Project
from Data.models import AIAnalyzedBatch, Issue
from Data.serializers import IssueSerializer

from ai_model.tasks import _build_past_memories


def _seed_resolved(project, organisation, batch, environment='production',
                   issue_type='CONNECTION_TIMEOUT', component='backend',
                   resolved_days_ago=1, fingerprint_suffix='1'):
    """Helper: a resolved issue with a substantive root cause."""
    return Issue.objects.create(
        batch=batch,
        project=project,
        organisation=organisation,
        environment=environment,
        issue_type=issue_type,
        component=component,
        severity='WARNING',
        description='Example',
        root_cause=(
            'Connection pool was undersized for production load after '
            'the v2.3.3 deploy.'
        ),
        recommendation='Bump pool size',
        fingerprint=f'fp-{fingerprint_suffix}',
        status='RESOLVED',
        resolved_at=timezone.now() - timedelta(days=resolved_days_ago),
    )


class BuildPastMemoriesReturnsIdsTest(TestCase):
    """The helper returns (text, ids) — the IDs must point at the same
    rows the text described."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Mem Ids Org')
        self.project = Project.objects.create(name='proj', organisation=self.org)
        self.seed_batch = AIAnalyzedBatch.objects.create(
            batch_id='seed-batch', project=self.project, organisation=self.org,
            timestamp=timezone.now(), data={},
        )

    def test_returns_empty_when_no_resolved_issues(self):
        new_batch = AIAnalyzedBatch.objects.create(
            batch_id='new-batch', project=self.project, organisation=self.org,
            timestamp=timezone.now(), environment='production', data={},
        )
        text, ids = _build_past_memories(new_batch)
        self.assertEqual(text, '')
        self.assertEqual(ids, [])

    def test_returns_ids_when_resolved_issues_exist(self):
        issue1 = _seed_resolved(
            self.project, self.org, self.seed_batch,
            fingerprint_suffix='a', resolved_days_ago=1,
        )
        issue2 = _seed_resolved(
            self.project, self.org, self.seed_batch,
            fingerprint_suffix='b', resolved_days_ago=2,
            component='payment-worker',
        )

        new_batch = AIAnalyzedBatch.objects.create(
            batch_id='new-batch-2', project=self.project, organisation=self.org,
            timestamp=timezone.now(), environment='production', data={},
        )
        text, ids = _build_past_memories(new_batch)
        self.assertNotEqual(text, '')
        self.assertCountEqual(ids, [issue1.id, issue2.id])


class IssueSerializerInformedByTest(TestCase):
    """The serializer surfaces a small digest of past resolutions referenced
    by the issue's batch."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Informed Org')
        self.project = Project.objects.create(name='proj', organisation=self.org)
        self.seed_batch = AIAnalyzedBatch.objects.create(
            batch_id='seed-batch', project=self.project, organisation=self.org,
            timestamp=timezone.now(), data={},
        )

    def _make_issue(self, batch):
        return Issue.objects.create(
            batch=batch, project=self.project, organisation=self.org,
            environment='production',
            issue_type='CONNECTION_TIMEOUT',
            component='backend',
            severity='WARNING',
            description='Live issue',
            root_cause='',
            fingerprint='live-fp',
            status='OPEN',
        )

    def test_informed_by_empty_when_batch_has_no_references(self):
        batch = AIAnalyzedBatch.objects.create(
            batch_id='no-refs', project=self.project, organisation=self.org,
            timestamp=timezone.now(), environment='production', data={},
        )
        issue = self._make_issue(batch)
        data = IssueSerializer(issue).data
        self.assertEqual(data['informed_by'], {'count': 0, 'items': []})

    def test_informed_by_includes_referenced_resolutions(self):
        ref1 = _seed_resolved(
            self.project, self.org, self.seed_batch,
            fingerprint_suffix='ref1', resolved_days_ago=3,
        )
        ref2 = _seed_resolved(
            self.project, self.org, self.seed_batch,
            fingerprint_suffix='ref2', resolved_days_ago=1,
            component='payment-worker',
        )

        live_batch = AIAnalyzedBatch.objects.create(
            batch_id='live-batch', project=self.project, organisation=self.org,
            timestamp=timezone.now(), environment='production', data={},
            referenced_resolution_ids=[ref1.id, ref2.id],
        )
        issue = self._make_issue(live_batch)
        data = IssueSerializer(issue).data

        self.assertEqual(data['informed_by']['count'], 2)
        # Most-recently resolved first.
        item_ids = [item['id'] for item in data['informed_by']['items']]
        self.assertEqual(item_ids, [ref2.id, ref1.id])
        for item in data['informed_by']['items']:
            self.assertIn(item['issue_type'], ('CONNECTION_TIMEOUT',))
            self.assertIsNotNone(item['resolved_at'])
            self.assertIn(item['component'], ('backend', 'payment-worker'))
