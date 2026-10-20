"""
Tests for Past-Incident Memory (Data/memory.py).

Coverage:
  1. Empty when no resolved issues exist
  2. Empty when IssueSettings.memory_enabled = False
  3. Multi-tenancy: org A's resolved issues never returned for org B
  4. Quality filter: root_cause shorter than MIN_ROOT_CAUSE_LENGTH excluded
  5. Window respected: issue older than memory_window_days excluded
  6. Tier 1 saturation: limit exact-env hits prevents tier 2 query
  7. Tier 2 fallback: missing exact-env hits are filled from other envs
  8. format_memories_for_prompt: cross-env tagged honestly
  9. format_memories_for_prompt: empty input returns empty string
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from Organisations.models import Organisations
from Projects.models import Project
from Data.models import AIAnalyzedBatch, Issue
from Data.memory import (
    MIN_ROOT_CAUSE_LENGTH,
    find_past_memories,
    format_memories_for_prompt,
)
from org_settings.models import IssueSettings


def _make_resolved_issue(*, project, organisation, batch, environment,
                        resolved_days_ago=10, issue_type='CONNECTION_TIMEOUT',
                        component='backend', root_cause=None,
                        recommendation='Bump connection pool size', status='RESOLVED'):
    """Create a resolved issue with a sensible default root_cause length."""
    if root_cause is None:
        root_cause = 'Database connection pool was undersized after the v2.3.1 deploy'
    resolved_at = timezone.now() - timedelta(days=resolved_days_ago)
    # Need a unique fingerprint per issue to satisfy the unique constraint.
    fingerprint = f'test-fp-{Issue.objects.count() + 1:04d}'
    return Issue.objects.create(
        batch=batch,
        project=project,
        organisation=organisation,
        environment=environment,
        issue_type=issue_type,
        component=component,
        severity='CRITICAL',
        description='Sample failure',
        root_cause=root_cause,
        recommendation=recommendation,
        fingerprint=fingerprint,
        status=status,
        resolved_at=resolved_at if status == 'RESOLVED' else None,
    )


class PastMemoryTestBase(TestCase):
    """Shared fixtures: one org with a project + batch, plus a second org for isolation tests."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Memory Org')
        self.other_org = Organisations.objects.create(name='Other Memory Org')

        self.project = Project.objects.create(name='memory-project', organisation=self.org)
        self.other_project = Project.objects.create(
            name='other-memory-project', organisation=self.other_org,
        )

        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='mem-batch-001',
            project=self.project,
            organisation=self.org,
            timestamp=timezone.now(),
            data={'logs': []},
        )
        self.other_batch = AIAnalyzedBatch.objects.create(
            batch_id='mem-batch-other-001',
            project=self.other_project,
            organisation=self.other_org,
            timestamp=timezone.now(),
            data={'logs': []},
        )


class TestEmptyAndOptOut(PastMemoryTestBase):
    """Cases 1 and 2 — empty input and the memory_enabled toggle."""

    def test_no_resolved_issues_returns_empty(self):
        memories = find_past_memories(
            project=self.project,
            environment='production',
            organisation=self.org,
        )
        self.assertEqual(memories, [])

    def test_memory_disabled_returns_empty(self):
        IssueSettings.objects.create(organisation=self.org, memory_enabled=False)
        _make_resolved_issue(
            project=self.project, organisation=self.org, batch=self.batch,
            environment='production',
        )
        memories = find_past_memories(
            project=self.project,
            environment='production',
            organisation=self.org,
        )
        self.assertEqual(memories, [])

    def test_missing_project_or_org_returns_empty(self):
        # Missing project is a hard precondition.
        self.assertEqual(
            find_past_memories(project=None, environment='production', organisation=self.org),
            [],
        )
        # Missing organisation is a hard precondition.
        self.assertEqual(
            find_past_memories(project=self.project, environment='production', organisation=None),
            [],
        )


class TestMultiTenancy(PastMemoryTestBase):
    """Case 3 — memories never cross organisation boundaries."""

    def test_other_org_memories_never_returned(self):
        # Resolved issue in org B's project.
        _make_resolved_issue(
            project=self.other_project, organisation=self.other_org, batch=self.other_batch,
            environment='production',
        )
        # Query from org A — must see nothing even though same env.
        memories = find_past_memories(
            project=self.project,
            environment='production',
            organisation=self.org,
        )
        self.assertEqual(memories, [])


class TestQualityFilter(PastMemoryTestBase):
    """Case 4 — junk root_cause values are excluded."""

    def test_short_root_cause_excluded(self):
        _make_resolved_issue(
            project=self.project, organisation=self.org, batch=self.batch,
            environment='production', root_cause='fixed',  # length 5, below MIN
        )
        memories = find_past_memories(
            project=self.project, environment='production', organisation=self.org,
        )
        self.assertEqual(memories, [])

    def test_root_cause_at_threshold_included(self):
        rc = 'x' * MIN_ROOT_CAUSE_LENGTH
        _make_resolved_issue(
            project=self.project, organisation=self.org, batch=self.batch,
            environment='production', root_cause=rc,
        )
        memories = find_past_memories(
            project=self.project, environment='production', organisation=self.org,
        )
        self.assertEqual(len(memories), 1)

    def test_null_root_cause_excluded(self):
        # Create an issue first, then null the field — bypass _make_resolved_issue's default.
        Issue.objects.create(
            batch=self.batch, project=self.project, organisation=self.org,
            environment='production', issue_type='OTHER', component='backend',
            severity='WARNING', description='no root cause',
            root_cause=None, status='RESOLVED',
            resolved_at=timezone.now() - timedelta(days=5),
            fingerprint='test-fp-null-rc',
        )
        memories = find_past_memories(
            project=self.project, environment='production', organisation=self.org,
        )
        self.assertEqual(memories, [])


class TestWindow(PastMemoryTestBase):
    """Case 5 — resolved_at outside the window is excluded."""

    def test_issue_older_than_window_excluded(self):
        IssueSettings.objects.create(organisation=self.org, memory_window_days=30)
        _make_resolved_issue(
            project=self.project, organisation=self.org, batch=self.batch,
            environment='production', resolved_days_ago=60,
        )
        memories = find_past_memories(
            project=self.project, environment='production', organisation=self.org,
        )
        self.assertEqual(memories, [])

    def test_issue_inside_window_included(self):
        IssueSettings.objects.create(organisation=self.org, memory_window_days=30)
        _make_resolved_issue(
            project=self.project, organisation=self.org, batch=self.batch,
            environment='production', resolved_days_ago=10,
        )
        memories = find_past_memories(
            project=self.project, environment='production', organisation=self.org,
        )
        self.assertEqual(len(memories), 1)


class TestTiering(PastMemoryTestBase):
    """Cases 6 and 7 — tier 1 saturation prevents tier 2; partial fill triggers fallback."""

    def test_tier_1_saturation_returns_only_exact(self):
        for i in range(3):
            _make_resolved_issue(
                project=self.project, organisation=self.org, batch=self.batch,
                environment='production', component=f'svc-{i}', resolved_days_ago=i + 1,
            )
        # One staging issue that should NOT be returned because tier 1 is full.
        _make_resolved_issue(
            project=self.project, organisation=self.org, batch=self.batch,
            environment='staging', component='svc-staging', resolved_days_ago=2,
        )

        memories = find_past_memories(
            project=self.project, environment='production', organisation=self.org,
        )
        self.assertEqual(len(memories), 3)
        self.assertTrue(all(tier == 'exact' for _, tier in memories))

    def test_tier_2_fallback_fills_remaining_slots(self):
        # One production memory, two staging memories — limit 3 should pull all.
        _make_resolved_issue(
            project=self.project, organisation=self.org, batch=self.batch,
            environment='production', component='prod-svc', resolved_days_ago=1,
        )
        _make_resolved_issue(
            project=self.project, organisation=self.org, batch=self.batch,
            environment='staging', component='stg-svc-a', resolved_days_ago=2,
        )
        _make_resolved_issue(
            project=self.project, organisation=self.org, batch=self.batch,
            environment='staging', component='stg-svc-b', resolved_days_ago=3,
        )

        memories = find_past_memories(
            project=self.project, environment='production', organisation=self.org,
        )
        self.assertEqual(len(memories), 3)
        tiers = [tier for _, tier in memories]
        self.assertEqual(tiers.count('exact'), 1)
        self.assertEqual(tiers.count('broader'), 2)


class TestFormatter(TestCase):
    """Cases 8 and 9 — formatter behaviour."""

    def test_empty_input_returns_empty_string(self):
        self.assertEqual(format_memories_for_prompt([]), '')
        self.assertEqual(format_memories_for_prompt(None), '')

    def test_cross_env_memory_is_tagged(self):
        org = Organisations.objects.create(name='Fmt Org')
        project = Project.objects.create(name='fmt-project', organisation=org)
        batch = AIAnalyzedBatch.objects.create(
            batch_id='fmt-batch', project=project, organisation=org,
            timestamp=timezone.now(), data={},
        )
        issue = _make_resolved_issue(
            project=project, organisation=org, batch=batch,
            environment='staging', component='auth',
        )
        rendered = format_memories_for_prompt([(issue, 'broader')])
        self.assertIn('Past Incident Memory', rendered)
        self.assertIn('[different env: staging]', rendered)
        self.assertIn('CONNECTION_TIMEOUT', rendered)
        self.assertIn('Root cause (AI, not confirmed):', rendered)
        self.assertIn('Fix:', rendered)

    def test_exact_tier_has_no_env_tag(self):
        org = Organisations.objects.create(name='Fmt Org 2')
        project = Project.objects.create(name='fmt-project-2', organisation=org)
        batch = AIAnalyzedBatch.objects.create(
            batch_id='fmt-batch-2', project=project, organisation=org,
            timestamp=timezone.now(), data={},
        )
        issue = _make_resolved_issue(
            project=project, organisation=org, batch=batch,
            environment='production', component='api',
        )
        rendered = format_memories_for_prompt([(issue, 'exact')])
        self.assertNotIn('[different env', rendered)
