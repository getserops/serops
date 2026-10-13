"""Dashboard cluster scoping.

The cluster picker is a global filter: pick a cluster and every page
should agree about which one you are looking at. Batches and Issues
already honoured it; the dashboard analytics endpoints are covered
here.

Two things are asserted:

1. Passing ``?cluster=<id>`` narrows the numbers to that cluster.
2. A *stale* cluster id — one the picker persisted in localStorage but
   which no longer exists, or is simply garbage — degrades to "all
   clusters" rather than erroring. The user cannot see the stale value
   to clear it, so a 500 there is unrecoverable without devtools.
"""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from Data.models import AIAnalyzedBatch
from Organisations.models import Organisations
from Projects.models import Project
from Users.models import User
from integrations.models import Cluster


class DashboardClusterFilterTest(APITestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='Cluster Filter Org')
        self.admin = User.objects.create_user(
            username='cfadmin', email='cf@test.com', password='Test123!',
            organisation=self.org, role='admin', is_active=True,
        )

        self.cluster_a = Cluster.objects.create(
            organisation=self.org, name='prod-eks',
        )
        self.cluster_b = Cluster.objects.create(
            organisation=self.org, name='prod-gke',
        )

        self.project_a = Project.objects.create(
            organisation=self.org, name='proj-a', cluster=self.cluster_a,
        )
        self.project_b = Project.objects.create(
            organisation=self.org, name='proj-b', cluster=self.cluster_b,
        )

        now = timezone.now()
        # 3 batches on cluster A, 1 on cluster B.
        for i in range(3):
            AIAnalyzedBatch.objects.create(
                batch_id=f'cf-a-{i}', organisation=self.org,
                project=self.project_a, timestamp=now - timedelta(hours=1),
                environment='production', sentinel_decision='alert',
            )
        AIAnalyzedBatch.objects.create(
            batch_id='cf-b-0', organisation=self.org,
            project=self.project_b, timestamp=now - timedelta(hours=1),
            environment='production', sentinel_decision='alert',
        )

        self.client.force_authenticate(user=self.admin)
        self.url = reverse('sentinel-stats')

    # -- scoping ----------------------------------------------------

    def test_unfiltered_counts_every_cluster(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['total_batches'], 4)

    def test_cluster_filter_narrows_counts(self):
        r = self.client.get(self.url, {'cluster': self.cluster_a.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['total_batches'], 3)

        r = self.client.get(self.url, {'cluster': self.cluster_b.id})
        self.assertEqual(r.data['total_batches'], 1)

    def test_cluster_all_is_treated_as_unfiltered(self):
        r = self.client.get(self.url, {'cluster': 'all'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['total_batches'], 4)

    # -- graceful degradation ---------------------------------------

    def test_unparseable_cluster_does_not_error(self):
        """A garbage value falls back to unfiltered instead of 500."""
        r = self.client.get(self.url, {'cluster': 'not-a-number'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['total_batches'], 4)

    def test_stale_cluster_id_returns_empty_not_error(self):
        """An id for a cluster that no longer exists is a real case —
        the picker persists the selection in localStorage, so it can
        outlive the cluster. Expect an honest zero, not a crash."""
        ghost_id = self.cluster_b.id + 9999
        r = self.client.get(self.url, {'cluster': ghost_id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['total_batches'], 0)

    # -- isolation ---------------------------------------------------

    def test_cluster_filter_cannot_cross_orgs(self):
        """Filtering by another org's cluster must not leak its data."""
        other_org = Organisations.objects.create(name='Other CF Org')
        other_cluster = Cluster.objects.create(
            organisation=other_org, name='their-eks',
        )
        other_project = Project.objects.create(
            organisation=other_org, name='their-proj', cluster=other_cluster,
        )
        AIAnalyzedBatch.objects.create(
            batch_id='cf-other-0', organisation=other_org,
            project=other_project, timestamp=timezone.now(),
            environment='production', sentinel_decision='alert',
        )

        r = self.client.get(self.url, {'cluster': other_cluster.id})
        self.assertEqual(r.status_code, 200)
        # Org filter applies first, so their cluster yields nothing here.
        self.assertEqual(r.data['total_batches'], 0)


class ClusterIdParsingTest(APITestCase):
    """Direct coverage of the shared helper, independent of any view."""

    def _parse(self, raw):
        from types import SimpleNamespace
        from Data.mixins import OrgFilterMixin
        params = {} if raw is None else {'cluster': raw}
        return OrgFilterMixin._get_cluster_id(SimpleNamespace(query_params=params))

    def test_valid_int(self):
        self.assertEqual(self._parse('42'), 42)

    def test_missing_is_none(self):
        self.assertIsNone(self._parse(None))

    def test_empty_is_none(self):
        self.assertIsNone(self._parse(''))

    def test_all_is_none(self):
        self.assertIsNone(self._parse('all'))
        self.assertIsNone(self._parse('ALL'))

    def test_garbage_is_none(self):
        self.assertIsNone(self._parse('not-a-number'))
        self.assertIsNone(self._parse('12abc'))
