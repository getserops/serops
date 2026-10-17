"""
Tests for Issue views: IssueBulkActionsView and IssueListView sorting.
"""

import uuid
from django.test import TestCase
from django.core.cache import cache
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from django.utils import timezone
from datetime import timedelta

from Data.models import Issue, AIAnalyzedBatch
from Projects.models import Project
from Organisations.models import Organisations

User = get_user_model()


class IssueViewTestBase(TestCase):
    """Shared setup for issue view tests."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()

        # Org A
        self.org_a = Organisations.objects.create(name="org-a")
        self.user_a = User.objects.create_user(
            username="usera", email="a@example.com", password="pass123"
        )
        self.user_a.organisation = self.org_a
        self.user_a.role = 'user'
        self.user_a.save()

        self.project_a = Project.objects.create(
            name="project-a", organisation=self.org_a
        )
        self.batch_a = AIAnalyzedBatch.objects.create(
            batch_id="batch-a-001",
            project=self.project_a,
            organisation=self.org_a,
            timestamp=timezone.now(),
        )

        # Org B (for cross-org tests)
        self.org_b = Organisations.objects.create(name="org-b")
        self.user_b = User.objects.create_user(
            username="userb", email="b@example.com", password="pass123"
        )
        self.user_b.organisation = self.org_b
        self.user_b.role = 'user'
        self.user_b.save()

        self.project_b = Project.objects.create(
            name="project-b", organisation=self.org_b
        )
        self.batch_b = AIAnalyzedBatch.objects.create(
            batch_id="batch-b-001",
            project=self.project_b,
            organisation=self.org_b,
            timestamp=timezone.now(),
        )

    def _create_issue(self, batch, org, project=None, **kwargs):
        defaults = {
            'severity': 'WARNING',
            'description': 'Test issue',
            'status': 'OPEN',
            'issue_type': 'OTHER',
            'scope': 'SERVICE',
            'fingerprint': f'test:{uuid.uuid4().hex[:32]}',
        }
        defaults.update(kwargs)
        return Issue.objects.create(
            batch=batch,
            organisation=org,
            project=project or batch.project,
            **defaults,
        )


class TestIssueBulkActionsView(IssueViewTestBase):
    """Tests for POST /api/data/issues/bulk-action/"""

    url = '/api/data/issues/bulk-action/'

    def test_bulk_resolve(self):
        """Bulk resolve sets status to RESOLVED."""
        i1 = self._create_issue(self.batch_a, self.org_a)
        i2 = self._create_issue(self.batch_a, self.org_a)
        self.client.force_authenticate(user=self.user_a)

        resp = self.client.post(self.url, {
            'issue_ids': [i1.id, i2.id],
            'action': 'resolve',
        }, format='json')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['updated'], 2)
        i1.refresh_from_db()
        i2.refresh_from_db()
        self.assertEqual(i1.status, 'RESOLVED')
        self.assertEqual(i2.status, 'RESOLVED')

    def test_bulk_mute_with_days(self):
        """Bulk mute sets status to MUTED and sets muted_until."""
        i1 = self._create_issue(self.batch_a, self.org_a)
        self.client.force_authenticate(user=self.user_a)

        resp = self.client.post(self.url, {
            'issue_ids': [i1.id],
            'action': 'mute',
            'days': 14,
        }, format='json')

        self.assertEqual(resp.status_code, 200)
        i1.refresh_from_db()
        self.assertEqual(i1.status, 'MUTED')
        self.assertIsNotNone(i1.muted_until)
        # Should be approximately 14 days from now
        expected = timezone.now() + timedelta(days=14)
        self.assertAlmostEqual(
            i1.muted_until.timestamp(), expected.timestamp(), delta=60
        )

    def test_bulk_mute_forever(self):
        """Bulk mute with days=0 sets muted_until to None (forever)."""
        i1 = self._create_issue(self.batch_a, self.org_a)
        self.client.force_authenticate(user=self.user_a)

        resp = self.client.post(self.url, {
            'issue_ids': [i1.id],
            'action': 'mute',
            'days': 0,
        }, format='json')

        self.assertEqual(resp.status_code, 200)
        i1.refresh_from_db()
        self.assertEqual(i1.status, 'MUTED')
        self.assertIsNone(i1.muted_until)

    def test_bulk_reopen(self):
        """Bulk reopen sets status to OPEN and clears muted_until."""
        i1 = self._create_issue(
            self.batch_a, self.org_a,
            status='RESOLVED',
        )
        i2 = self._create_issue(
            self.batch_a, self.org_a,
            status='MUTED',
            muted_until=timezone.now() + timedelta(days=7),
        )
        self.client.force_authenticate(user=self.user_a)

        resp = self.client.post(self.url, {
            'issue_ids': [i1.id, i2.id],
            'action': 'reopen',
        }, format='json')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['updated'], 2)
        i1.refresh_from_db()
        i2.refresh_from_db()
        self.assertEqual(i1.status, 'OPEN')
        self.assertEqual(i2.status, 'OPEN')
        self.assertIsNone(i2.muted_until)

    def test_empty_issue_ids_rejected(self):
        """Empty issue_ids list returns 400."""
        self.client.force_authenticate(user=self.user_a)
        resp = self.client.post(self.url, {
            'issue_ids': [],
            'action': 'resolve',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_invalid_action_rejected(self):
        """Invalid action returns 400."""
        i1 = self._create_issue(self.batch_a, self.org_a)
        self.client.force_authenticate(user=self.user_a)
        resp = self.client.post(self.url, {
            'issue_ids': [i1.id],
            'action': 'delete',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_cross_org_rejection(self):
        """User cannot bulk-action issues from another org."""
        i_other = self._create_issue(self.batch_b, self.org_b)
        self.client.force_authenticate(user=self.user_a)

        resp = self.client.post(self.url, {
            'issue_ids': [i_other.id],
            'action': 'resolve',
        }, format='json')

        self.assertEqual(resp.status_code, 400)
        self.assertIn('not found or not accessible', resp.data['error'])
        # Issue should remain unchanged
        i_other.refresh_from_db()
        self.assertEqual(i_other.status, 'OPEN')

    def test_mixed_org_ids_rejected(self):
        """Mix of own and other org IDs is rejected."""
        i_own = self._create_issue(self.batch_a, self.org_a)
        i_other = self._create_issue(self.batch_b, self.org_b)
        self.client.force_authenticate(user=self.user_a)

        resp = self.client.post(self.url, {
            'issue_ids': [i_own.id, i_other.id],
            'action': 'resolve',
        }, format='json')

        self.assertEqual(resp.status_code, 400)
        # Neither should be changed
        i_own.refresh_from_db()
        self.assertEqual(i_own.status, 'OPEN')

    def test_unauthenticated_rejected(self):
        """Unauthenticated request returns 401/403."""
        resp = self.client.post(self.url, {
            'issue_ids': [1],
            'action': 'resolve',
        }, format='json')
        self.assertIn(resp.status_code, [401, 403])


class TestIssueListSorting(IssueViewTestBase):
    """Tests for IssueListView sorting capabilities."""

    url = '/api/data/issues/'

    def test_sort_by_created_at_asc(self):
        """Issues sorted by created_at ascending."""
        i1 = self._create_issue(self.batch_a, self.org_a, description='Older issue')
        i2 = self._create_issue(self.batch_a, self.org_a, description='Newer issue')
        self.client.force_authenticate(user=self.user_a)

        resp = self.client.get(self.url, {
            'sort_by': 'created_at',
            'sort_dir': 'asc',
        })

        self.assertEqual(resp.status_code, 200)
        results = resp.data['results']
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['id'], i1.id)
        self.assertEqual(results[1]['id'], i2.id)

    def test_sort_by_created_at_desc(self):
        """Issues sorted by created_at descending."""
        i1 = self._create_issue(self.batch_a, self.org_a, description='Older issue')
        i2 = self._create_issue(self.batch_a, self.org_a, description='Newer issue')
        self.client.force_authenticate(user=self.user_a)

        resp = self.client.get(self.url, {
            'sort_by': 'created_at',
            'sort_dir': 'desc',
        })

        self.assertEqual(resp.status_code, 200)
        results = resp.data['results']
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['id'], i2.id)
        self.assertEqual(results[1]['id'], i1.id)

    def test_sort_by_last_seen_at(self):
        """Issues sorted by last_seen_at."""
        i1 = self._create_issue(self.batch_a, self.org_a, description='Issue A')
        i2 = self._create_issue(self.batch_a, self.org_a, description='Issue B')
        # Touch i1 to update its last_seen_at
        i1.occurrence_count = 5
        i1.save(update_fields=['occurrence_count', 'last_seen_at'])

        self.client.force_authenticate(user=self.user_a)

        resp = self.client.get(self.url, {
            'sort_by': 'last_seen_at',
            'sort_dir': 'desc',
        })

        self.assertEqual(resp.status_code, 200)
        results = resp.data['results']
        self.assertEqual(len(results), 2)
        # i1 was updated more recently
        self.assertEqual(results[0]['id'], i1.id)

    def test_sort_by_severity_default(self):
        """Default sort is by severity descending (CRITICAL first)."""
        i_warn = self._create_issue(
            self.batch_a, self.org_a, severity='WARNING', description='Warning'
        )
        i_crit = self._create_issue(
            self.batch_a, self.org_a, severity='CRITICAL', description='Critical'
        )
        self.client.force_authenticate(user=self.user_a)

        resp = self.client.get(self.url)

        self.assertEqual(resp.status_code, 200)
        results = resp.data['results']
        self.assertEqual(results[0]['severity'], 'CRITICAL')
        self.assertEqual(results[1]['severity'], 'WARNING')


class TestIssueListFilters(IssueViewTestBase):
    """Project / environment / service filters and the fields the issue panel reads."""

    url = '/api/data/issues/'

    def setUp(self):
        super().setUp()
        from Projects.models import Project
        self.project_a2 = Project.objects.create(name="project-a2", organisation=self.org_a)
        self.batch_a2 = AIAnalyzedBatch.objects.create(
            batch_id='filters-a2', project=self.project_a2, organisation=self.org_a, data={})
        self.i1 = self._create_issue(self.batch_a, self.org_a, description='checkout down')
        self.i1.component, self.i1.environment = 'checkout', 'production'
        self.i1.save(update_fields=['component', 'environment'])
        self.i2 = self._create_issue(self.batch_a2, self.org_a, description='cache cold')
        self.i2.component, self.i2.environment = 'redis', 'staging'
        self.i2.save(update_fields=['component', 'environment'])
        self.client.force_authenticate(user=self.user_a)

    def ids(self, **params):
        resp = self.client.get(self.url, params)
        self.assertEqual(resp.status_code, 200, resp.data)
        return [r['id'] for r in resp.data['results']]

    def test_filter_by_project(self):
        self.assertEqual(self.ids(project=self.project_a2.id), [self.i2.id])

    def test_filter_by_environment_and_service(self):
        self.assertEqual(self.ids(environment='Production'), [self.i1.id])
        self.assertEqual(self.ids(component='REDIS'), [self.i2.id])

    def test_total_reflects_filters(self):
        resp = self.client.get(self.url, {'project': self.project_a.id})
        self.assertEqual(resp.data['pagination']['total_issues'], 1)

    def test_project_must_be_a_number(self):
        self.assertEqual(self.client.get(self.url, {'project': 'x'}).status_code, 400)

    def test_another_organisations_project_returns_nothing(self):
        self.assertEqual(self.ids(project=self.project_b.id), [])

    def test_panel_fields(self):
        row = next(r for r in self.client.get(self.url).data['results'] if r['id'] == self.i1.id)
        self.assertEqual((row['project'], row['project_name']), (self.project_a.id, 'project-a'))
        self.assertIn('acknowledged_at', row)

    def test_since_hours_filters_on_last_seen(self):
        old = timezone.now() - timedelta(days=10)
        Issue.objects.filter(id=self.i1.id).update(created_at=old, last_seen_at=timezone.now() - timedelta(hours=2))
        Issue.objects.filter(id=self.i2.id).update(created_at=old, last_seen_at=old)
        self.assertEqual(self.ids(since_hours=24), [self.i1.id])
        self.assertEqual(sorted(self.ids(since_hours=24 * 30)), sorted([self.i1.id, self.i2.id]))

    def test_since_hours_is_validated(self):
        for bad in ('0', 'x', '9000'):
            self.assertEqual(self.client.get(self.url, {'since_hours': bad}).status_code, 400)
