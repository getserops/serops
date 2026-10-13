"""ObservabilityIntegrationSerializer priority_tier + scope tests (Batch 53).

Covers the new fields exposed on ObservabilityIntegrationSerializer:

  * ``priority_tier`` — read + write, defaults to 'primary'
  * ``scope`` nested serializer — env / region / namespace read + write
  * Tier-sliced uniqueness — same (org, provider, cluster) with different
    tier succeeds; same tier fails with a readable error
  * Namespace-requires-cluster invariant enforced at the serializer level
  * ``to_representation`` never returns ``scope=None``

These tests target the serializer directly (bypass DRF view routing)
so they run fast and don't need the auth stack.
"""

from django.test import TestCase, RequestFactory

from Organisations.models import Organisations
from Users.models import User
from integrations.models import Cluster, IntegrationScope, ObservabilityIntegration
from integrations.serializers import ObservabilityIntegrationSerializer


def _ctx(user):
    """Build the minimum request context the serializer expects."""
    req = RequestFactory().post('/')
    req.user = user
    return {'request': req}


class SerializerTierFieldTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='TierOrg')
        cls.user = User.objects.create(
            email='tier@example.com', organisation=cls.org,
        )

    def test_default_tier_is_primary_on_create(self):
        s = ObservabilityIntegrationSerializer(
            data={
                'provider': 'elasticsearch',
                'display_name': 'Elasticsearch',
                'capabilities': ['logs'],
                'host': 'http://es:9200',
            },
            context=_ctx(self.user),
        )
        self.assertTrue(s.is_valid(), s.errors)
        instance = s.save(organisation=self.org)
        self.assertEqual(instance.priority_tier, 'primary')

    def test_explicit_tier_writes(self):
        s = ObservabilityIntegrationSerializer(
            data={
                'provider': 'elasticsearch',
                'display_name': 'ES-fallback',
                'capabilities': ['logs'],
                'host': 'http://es-fb:9200',
                'priority_tier': 'fallback',
            },
            context=_ctx(self.user),
        )
        self.assertTrue(s.is_valid(), s.errors)
        instance = s.save(organisation=self.org)
        self.assertEqual(instance.priority_tier, 'fallback')

    def test_representation_includes_tier_and_display(self):
        i = ObservabilityIntegration.objects.create(
            organisation=self.org, provider='loki', capabilities=['logs'],
            host='http://loki:3100', priority_tier='tertiary',
        )
        data = ObservabilityIntegrationSerializer(i).data
        self.assertEqual(data['priority_tier'], 'tertiary')
        self.assertEqual(data['priority_tier_display'], 'Tertiary')


class SerializerScopeFieldTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='ScopeOrg')
        cls.user = User.objects.create(
            email='scope@example.com', organisation=cls.org,
        )
        cls.cluster = Cluster.objects.create(
            organisation=cls.org, name='prod-eks', provider='eks',
        )

    def test_scope_writes_env_region(self):
        s = ObservabilityIntegrationSerializer(
            data={
                'provider': 'prometheus',
                'display_name': 'Prom',
                'capabilities': ['metrics'],
                'host': 'http://prom:9090',
                'scope': {'environment': 'production', 'region': 'us-east-1'},
            },
            context=_ctx(self.user),
        )
        self.assertTrue(s.is_valid(), s.errors)
        instance = s.save(organisation=self.org)
        instance.refresh_from_db()
        self.assertEqual(instance.scope.environment, 'production')
        self.assertEqual(instance.scope.region, 'us-east-1')

    def test_scope_namespace_requires_cluster(self):
        # No cluster on the parent → scope.namespace='foo' rejected.
        s = ObservabilityIntegrationSerializer(
            data={
                'provider': 'loki',
                'display_name': 'Loki',
                'capabilities': ['logs'],
                'host': 'http://loki:3100',
                'scope': {'namespace': 'payments'},
            },
            context=_ctx(self.user),
        )
        self.assertFalse(s.is_valid())
        self.assertIn('scope', s.errors)

    def test_scope_namespace_with_cluster_succeeds(self):
        s = ObservabilityIntegrationSerializer(
            data={
                'provider': 'loki',
                'display_name': 'Loki-team-a',
                'capabilities': ['logs'],
                'host': 'http://loki:3100',
                'cluster': self.cluster.id,
                'scope': {'namespace': 'team-a', 'environment': 'production'},
            },
            context=_ctx(self.user),
        )
        self.assertTrue(s.is_valid(), s.errors)
        instance = s.save(organisation=self.org)
        instance.refresh_from_db()
        self.assertEqual(instance.scope.namespace, 'team-a')
        self.assertEqual(instance.scope.cluster_id, self.cluster.id)

    def test_scope_never_null_in_response(self):
        # Even for an integration without a scope row somehow, the
        # response must have a stable {environment,region,namespace} shape.
        i = ObservabilityIntegration.objects.create(
            organisation=self.org, provider='datadog',
            capabilities=['logs', 'metrics'], host='datadoghq.com',
        )
        # Delete the auto-created scope to force the None branch.
        IntegrationScope.objects.filter(integration=i).delete()
        i.refresh_from_db()
        data = ObservabilityIntegrationSerializer(i).data
        self.assertIsNotNone(data.get('scope'))
        self.assertEqual(
            data['scope'],
            {'environment': '', 'region': '', 'namespace': ''},
        )

    def test_partial_update_preserves_scope(self):
        i = ObservabilityIntegration.objects.create(
            organisation=self.org, provider='prometheus',
            capabilities=['metrics'], host='http://prom:9090',
        )
        i.scope.environment = 'production'
        i.scope.region = 'us-east-1'
        i.scope.save()

        # PATCH without scope key should leave scope intact.
        s = ObservabilityIntegrationSerializer(
            i, data={'display_name': 'Prom-renamed'},
            partial=True, context=_ctx(self.user),
        )
        self.assertTrue(s.is_valid(), s.errors)
        s.save()
        i.refresh_from_db()
        self.assertEqual(i.scope.environment, 'production')
        self.assertEqual(i.scope.region, 'us-east-1')


class SerializerTierUniquenessTest(TestCase):
    """(org, provider, cluster, tier) uniqueness — Batch 48 slicing."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='UniqOrg')
        cls.user = User.objects.create(
            email='uniq@example.com', organisation=cls.org,
        )
        cls.cluster = Cluster.objects.create(
            organisation=cls.org, name='prod-eks', provider='eks',
        )

    def test_same_provider_same_tier_blocked(self):
        ObservabilityIntegration.objects.create(
            organisation=self.org, provider='loki',
            capabilities=['logs'], host='http://loki1:3100',
            priority_tier='primary',
        )
        s = ObservabilityIntegrationSerializer(
            data={
                'provider': 'loki',
                'display_name': 'Loki-2',
                'capabilities': ['logs'],
                'host': 'http://loki2:3100',
                'priority_tier': 'primary',
            },
            context=_ctx(self.user),
        )
        self.assertFalse(s.is_valid())
        self.assertIn('provider', s.errors)
        self.assertIn('already exists', str(s.errors['provider'][0]))

    def test_same_provider_different_tier_allowed(self):
        ObservabilityIntegration.objects.create(
            organisation=self.org, provider='loki',
            capabilities=['logs'], host='http://loki1:3100',
            priority_tier='primary',
        )
        s = ObservabilityIntegrationSerializer(
            data={
                'provider': 'loki',
                'display_name': 'Loki-fb',
                'capabilities': ['logs'],
                'host': 'http://loki2:3100',
                'priority_tier': 'fallback',
            },
            context=_ctx(self.user),
        )
        self.assertTrue(s.is_valid(), s.errors)
        instance = s.save(organisation=self.org)
        self.assertEqual(instance.priority_tier, 'fallback')

    def test_same_tier_different_cluster_allowed(self):
        cluster2 = Cluster.objects.create(
            organisation=self.org, name='staging-eks', provider='eks',
        )
        ObservabilityIntegration.objects.create(
            organisation=self.org, provider='prometheus',
            capabilities=['metrics'], host='http://prom1:9090',
            cluster=self.cluster, priority_tier='primary',
        )
        s = ObservabilityIntegrationSerializer(
            data={
                'provider': 'prometheus',
                'display_name': 'Prom-staging',
                'capabilities': ['metrics'],
                'host': 'http://prom2:9090',
                'cluster': cluster2.id,
                'priority_tier': 'primary',
            },
            context=_ctx(self.user),
        )
        self.assertTrue(s.is_valid(), s.errors)
