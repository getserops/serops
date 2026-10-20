"""
One shared cause is one issue: the component where the cause lives, plus the
other services that show its symptoms in ``affected_services``.
"""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from Organisations.models import Organisations
from Projects.models import Project
from Data.models import AIAnalyzedBatch, Issue
from Users.models import User


def redis_issue(**overrides):
    data = {
        'issue_type': 'CONNECTION_REFUSED',
        'scope': 'SERVICE',
        'component': 'redis-cache',
        'affected_services': ['checkout-api', 'cart-api'],
        'severity': 'CRITICAL',
        'description': 'Redis refuses connections: maxclients reached',
        'root_cause': 'maxclients was lowered to 50 in the Helm values',
        'recommended_action': 'Restore maxclients to 10000',
        'error_class': 'CONNECTION_REFUSED',
        'error_target': 'redis:6379',
    }
    data.update(overrides)
    return data


class NormalizeAffectedServicesTest(TestCase):
    def test_list_is_sorted_and_deduplicated(self):
        self.assertEqual(
            Issue.normalize_affected_services(['web', 'cart-api', 'web', ' ']),
            ['cart-api', 'web'])

    def test_component_is_dropped(self):
        self.assertEqual(
            Issue.normalize_affected_services(['redis-cache', 'web'], 'redis-cache'), ['web'])

    def test_comma_separated_string(self):
        self.assertEqual(Issue.normalize_affected_services('web, cart-api'), ['cart-api', 'web'])

    def test_garbage_is_empty(self):
        self.assertEqual(Issue.normalize_affected_services(None), [])
        self.assertEqual(Issue.normalize_affected_services({'a': 1}), [])
        self.assertEqual(Issue.normalize_affected_services([{'name': 'x'}, None]), [])


class AffectedServicesDedupTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Shared Cause Org')
        self.project = Project.objects.create(name='shop', organisation=self.org)

    def _batch(self, n):
        return AIAnalyzedBatch.objects.create(
            batch_id=f'b-shared-{n}', project=self.project, organisation=self.org,
            timestamp=timezone.now(), data={})

    def test_stored_on_create(self):
        issue, created = Issue.find_or_create_deduplicated(
            redis_issue(), self._batch(1), self.project, 'production')
        self.assertTrue(created)
        self.assertEqual(issue.affected_services, ['cart-api', 'checkout-api'])

    def test_recurrence_merges_services(self):
        first, _ = Issue.find_or_create_deduplicated(
            redis_issue(), self._batch(1), self.project, 'production')
        again, created = Issue.find_or_create_deduplicated(
            redis_issue(affected_services=['sessions', 'cart-api']), self._batch(2),
            self.project, 'production')
        self.assertFalse(created)
        self.assertEqual(again.pk, first.pk)
        again.refresh_from_db()
        self.assertEqual(again.affected_services, ['cart-api', 'checkout-api', 'sessions'])

    def test_missing_field_is_empty(self):
        data = redis_issue()
        del data['affected_services']
        issue, _ = Issue.find_or_create_deduplicated(data, self._batch(1), self.project, 'production')
        self.assertEqual(issue.affected_services, [])

    def test_dedup_disabled_still_stores(self):
        from org_settings.models import IssueSettings
        IssueSettings.objects.create(organisation=self.org, dedup_enabled=False)
        issue, _ = Issue.find_or_create_deduplicated(
            redis_issue(), self._batch(1), self.project, 'production')
        self.assertEqual(issue.affected_services, ['cart-api', 'checkout-api'])


class ServiceFilterTest(TestCase):
    """Filtering issues by a service also finds causes elsewhere that affect it."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Filter Org')
        self.project = Project.objects.create(name='shop', organisation=self.org)
        batch = AIAnalyzedBatch.objects.create(
            batch_id='b-filter', project=self.project, organisation=self.org,
            timestamp=timezone.now(), data={})
        Issue.find_or_create_deduplicated(redis_issue(), batch, self.project, 'production')
        Issue.find_or_create_deduplicated(
            redis_issue(component='billing', affected_services=[], error_target='invoice'),
            batch, self.project, 'production')
        user = User.objects.create_user(
            username='f', email='filter@example.com', password='x', organisation=self.org, role='admin')
        self.client = APIClient()
        self.client.force_authenticate(user=user)

    def test_filter_matches_component_and_affected(self):
        url = reverse('issues-list')
        names = lambda r: sorted(i['component'] for i in (r.data.get('results') or r.data.get('issues') or []))
        self.assertEqual(names(self.client.get(url, {'component': 'cart-api'})), ['redis-cache'])
        self.assertEqual(names(self.client.get(url, {'component': 'billing'})), ['billing'])
