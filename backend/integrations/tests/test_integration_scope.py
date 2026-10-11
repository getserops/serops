"""IntegrationScope model + signal + tenant-isolation tests (Batch 51)."""

from django.db import IntegrityError, transaction
from django.test import TestCase

from Organisations.models import Organisations
from integrations.models import (
    Cluster, ObservabilityIntegration, IntegrationScope,
)


class IntegrationScopeSignalTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='ScopeOrg')

    def test_creating_integration_auto_creates_scope(self):
        integ = ObservabilityIntegration.objects.create(
            organisation=self.org, provider='prometheus',
            display_name='Prom', capabilities=['metrics'],
            host='https://mock',
        )
        # Signal fired → scope row exists with default (all wildcards).
        scope = IntegrationScope.objects.get(integration=integ)
        self.assertEqual(scope.cluster, None)
        self.assertEqual(scope.environment, '')
        self.assertEqual(scope.region, '')
        self.assertEqual(scope.namespace, '')

    def test_signal_mirrors_cluster_from_integration(self):
        cluster = Cluster.objects.create(organisation=self.org, name='c', provider='eks')
        integ = ObservabilityIntegration.objects.create(
            organisation=self.org, provider='prometheus',
            display_name='Prom', capabilities=['metrics'],
            host='https://mock', cluster=cluster,
        )
        scope = IntegrationScope.objects.get(integration=integ)
        self.assertEqual(scope.cluster, cluster)

    def test_updating_integration_does_not_recreate_scope(self):
        integ = ObservabilityIntegration.objects.create(
            organisation=self.org, provider='prometheus',
            display_name='Prom', capabilities=['metrics'],
            host='https://mock',
        )
        scope_pk = integ.scope.pk
        integ.host = 'https://other'
        integ.save()
        # Same scope row — signal only fires on create.
        integ.refresh_from_db()
        self.assertEqual(integ.scope.pk, scope_pk)


class IntegrationScopeConstraintTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='ScopeConstraintOrg')
        cls.integ = ObservabilityIntegration.objects.create(
            organisation=cls.org, provider='prometheus',
            display_name='Prom', capabilities=['metrics'], host='https://mock',
        )

    def test_namespace_requires_cluster(self):
        # DB CheckConstraint enforces: namespace non-empty → cluster required.
        scope = self.integ.scope
        scope.cluster = None
        scope.namespace = 'payments'
        with transaction.atomic(), self.assertRaises(IntegrityError):
            scope.save()


class ObservabilityIntegrationTierConstraintTest(TestCase):
    """Uniqueness sliced by priority_tier — same-cluster same-provider
    integration allowed once per tier. Batch 48 shipped this."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='TierConstraintOrg')
        cls.cluster = Cluster.objects.create(organisation=cls.org, name='c', provider='eks')

    def test_same_scope_different_tiers_allowed(self):
        # Prom @ prod-eks primary + Prom @ prod-eks fallback = OK.
        ObservabilityIntegration.objects.create(
            organisation=self.org, provider='prometheus',
            display_name='p1', capabilities=['metrics'], host='https://m',
            cluster=self.cluster, priority_tier='primary',
        )
        ObservabilityIntegration.objects.create(
            organisation=self.org, provider='prometheus',
            display_name='p2', capabilities=['metrics'], host='https://m',
            cluster=self.cluster, priority_tier='fallback',
        )
        self.assertEqual(
            ObservabilityIntegration.objects.filter(cluster=self.cluster).count(),
            2,
        )

    def test_same_scope_same_tier_blocked(self):
        ObservabilityIntegration.objects.create(
            organisation=self.org, provider='prometheus',
            display_name='p1', capabilities=['metrics'], host='https://m',
            cluster=self.cluster, priority_tier='primary',
        )
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ObservabilityIntegration.objects.create(
                organisation=self.org, provider='prometheus',
                display_name='p2', capabilities=['metrics'], host='https://m',
                cluster=self.cluster, priority_tier='primary',
            )

    def test_unscoped_different_tiers_allowed(self):
        # Same shape but cluster=NULL. Uniqueness slices by tier here too.
        ObservabilityIntegration.objects.create(
            organisation=self.org, provider='datadog',
            display_name='dd1', capabilities=['metrics'], host='https://m',
            cluster=None, priority_tier='primary',
        )
        ObservabilityIntegration.objects.create(
            organisation=self.org, provider='datadog',
            display_name='dd2', capabilities=['metrics'], host='https://m',
            cluster=None, priority_tier='fallback',
        )
        self.assertEqual(
            ObservabilityIntegration.objects.filter(
                cluster__isnull=True, provider='datadog',
            ).count(),
            2,
        )


class IntegrationScopeTenantIsolationTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organisations.objects.create(name='OrgA')
        cls.org_b = Organisations.objects.create(name='OrgB')
        cls.integ_a = ObservabilityIntegration.objects.create(
            organisation=cls.org_a, provider='prometheus',
            display_name='pa', capabilities=['metrics'], host='https://a',
        )
        cls.integ_b = ObservabilityIntegration.objects.create(
            organisation=cls.org_b, provider='prometheus',
            display_name='pb', capabilities=['metrics'], host='https://b',
        )

    def test_scope_scoped_by_org_via_integration(self):
        # Filter by org via the integration FK.
        a_scopes = IntegrationScope.objects.filter(
            integration__organisation=self.org_a,
        )
        b_scopes = IntegrationScope.objects.filter(
            integration__organisation=self.org_b,
        )
        self.assertEqual(a_scopes.count(), 1)
        self.assertEqual(b_scopes.count(), 1)
        self.assertEqual(a_scopes.first().integration, self.integ_a)
        self.assertEqual(b_scopes.first().integration, self.integ_b)
