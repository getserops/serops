"""Tests for the Cluster model + CRUD API + registry cluster-awareness (Item #17)."""

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from rest_framework.test import APIClient

from integrations.models import Cluster, ObservabilityIntegration
from integrations.registry import IntegrationRegistry
from Organisations.models import Organisations

User = get_user_model()


def _make_integration(org, provider, capabilities, cluster=None):
    return ObservabilityIntegration.objects.create(
        organisation=org,
        provider=provider,
        display_name=f'{provider}-int',
        capabilities=capabilities,
        cluster=cluster,
        is_active=True,
        host='http://example',
    )


class ClusterModelTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='ClusterOrg')

    def test_create_cluster(self):
        c = Cluster.objects.create(
            organisation=self.org, name='prod-eks', provider='eks',
            region='us-west-2',
        )
        self.assertEqual(str(c), 'prod-eks (AWS EKS)')

    def test_name_unique_per_org(self):
        Cluster.objects.create(organisation=self.org, name='dup', provider='eks')
        with self.assertRaises(IntegrityError):
            Cluster.objects.create(organisation=self.org, name='dup', provider='gke')

    def test_same_name_different_org_allowed(self):
        other = Organisations.objects.create(name='OtherOrg')
        Cluster.objects.create(organisation=self.org, name='prod', provider='eks')
        # Different org — no collision.
        Cluster.objects.create(organisation=other, name='prod', provider='eks')

    def test_cluster_delete_setnulls_integration_cluster(self):
        c = Cluster.objects.create(organisation=self.org, name='to-delete', provider='eks')
        integ = _make_integration(self.org, 'prometheus', ['metrics'], cluster=c)
        c.delete()
        integ.refresh_from_db()
        self.assertIsNone(integ.cluster)


class ObservabilityIntegrationClusterConstraintTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='ConstraintOrg')
        cls.c1 = Cluster.objects.create(organisation=cls.org, name='c1', provider='eks')
        cls.c2 = Cluster.objects.create(organisation=cls.org, name='c2', provider='gke')

    def test_two_prometheus_on_two_clusters_allowed(self):
        _make_integration(self.org, 'prometheus', ['metrics'], cluster=self.c1)
        _make_integration(self.org, 'prometheus', ['metrics'], cluster=self.c2)
        # No IntegrityError — both scoped uniquely per cluster.
        self.assertEqual(
            ObservabilityIntegration.objects.filter(provider='prometheus').count(), 2,
        )

    def test_duplicate_scoped_prometheus_rejected(self):
        _make_integration(self.org, 'prometheus', ['metrics'], cluster=self.c1)
        with self.assertRaises(IntegrityError):
            _make_integration(self.org, 'prometheus', ['metrics'], cluster=self.c1)

    def test_duplicate_unscoped_prometheus_rejected(self):
        _make_integration(self.org, 'prometheus', ['metrics'], cluster=None)
        with self.assertRaises(IntegrityError):
            _make_integration(self.org, 'prometheus', ['metrics'], cluster=None)

    def test_one_scoped_plus_one_unscoped_allowed(self):
        _make_integration(self.org, 'prometheus', ['metrics'], cluster=self.c1)
        _make_integration(self.org, 'prometheus', ['metrics'], cluster=None)
        # Both — cluster-scoped for c1, unscoped fallback for everything else.
        self.assertEqual(ObservabilityIntegration.objects.count(), 2)


class RegistryClusterAwareTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='RegistryOrg')
        cls.c1 = Cluster.objects.create(organisation=cls.org, name='c1', provider='eks')
        cls.c2 = Cluster.objects.create(organisation=cls.org, name='c2', provider='gke')

    def setUp(self):
        # Adapter cache is module-level; wipe between tests to isolate.
        IntegrationRegistry.clear_cache()

    def test_cluster_scoped_wins(self):
        scoped = _make_integration(self.org, 'prometheus', ['metrics'], cluster=self.c1)
        unscoped = _make_integration(self.org, 'prometheus', ['metrics'], cluster=None)
        result = IntegrationRegistry._best_integration(self.org, 'metrics', cluster=self.c1)
        self.assertEqual(result.pk, scoped.pk)

    def test_falls_back_to_unscoped_when_no_cluster_match(self):
        unscoped = _make_integration(self.org, 'prometheus', ['metrics'], cluster=None)
        # Ask for c2 — no c2-scoped exists, fall through to unscoped.
        result = IntegrationRegistry._best_integration(self.org, 'metrics', cluster=self.c2)
        self.assertEqual(result.pk, unscoped.pk)

    def test_no_cluster_prefers_unscoped(self):
        scoped = _make_integration(self.org, 'prometheus', ['metrics'], cluster=self.c1)
        unscoped = _make_integration(self.org, 'prometheus', ['metrics'], cluster=None)
        # No cluster asked for — historical behavior: unscoped wins.
        result = IntegrationRegistry._best_integration(self.org, 'metrics')
        self.assertEqual(result.pk, unscoped.pk)

    def test_returns_none_when_nothing_matches(self):
        result = IntegrationRegistry._best_integration(self.org, 'metrics', cluster=self.c1)
        self.assertIsNone(result)


class ClusterEndpointTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='EndpointOrg')
        self.other_org = Organisations.objects.create(name='ForeignOrg')
        self.admin = User.objects.create_user(
            username='admin1', email='a@t.com', password='p',
            organisation=self.org, role='admin', is_active=True,
        )
        self.user = User.objects.create_user(
            username='user1', email='u@t.com', password='p',
            organisation=self.org, role='user', is_active=True,
        )
        self.client = APIClient()
        self.url = '/api/integrations/clusters/'

    def test_list_requires_auth(self):
        self.assertIn(self.client.get(self.url).status_code, (401, 403))

    def test_authenticated_user_can_list(self):
        Cluster.objects.create(organisation=self.org, name='mine', provider='eks')
        Cluster.objects.create(organisation=self.other_org, name='foreign', provider='eks')
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        # DRF ViewSet returns either a bare list or a paginated {results:[...]}.
        body = response.json()
        rows = body['results'] if isinstance(body, dict) else body
        names = [c['name'] for c in rows]
        self.assertEqual(names, ['mine'])

    def test_non_admin_cannot_create(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.url, {'name': 'c1', 'provider': 'eks'}, format='json')
        self.assertIn(response.status_code, (401, 403))

    def test_admin_can_create(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            self.url,
            {'name': 'prod-eks', 'provider': 'eks', 'region': 'us-west-2'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Cluster.objects.count(), 1)
        c = Cluster.objects.get()
        self.assertEqual(c.organisation, self.org)
        self.assertEqual(c.name, 'prod-eks')

    def test_duplicate_name_400(self):
        Cluster.objects.create(organisation=self.org, name='dup', provider='eks')
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            self.url, {'name': 'dup', 'provider': 'gke'}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_cross_org_delete_404(self):
        foreign = Cluster.objects.create(organisation=self.other_org, name='foreign', provider='eks')
        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(f'{self.url}{foreign.pk}/')
        self.assertEqual(response.status_code, 404)
        # Foreign cluster untouched.
        self.assertTrue(Cluster.objects.filter(pk=foreign.pk).exists())
