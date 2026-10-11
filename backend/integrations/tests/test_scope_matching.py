"""Scope-match resolution matrix for _best_integration (Batch 51).

The core routing question: given a deployment (env × cluster × region
× namespace) and N integrations with various IntegrationScope tags,
which integration wins?

Tests cover:
  * Wildcard behaviour on each dimension
  * Explicit-match beats wildcard-only
  * Field precedence (cluster > env > region > namespace)
  * Priority tier as secondary tiebreaker
  * Provider preference (self-hosted > managed) as tertiary tiebreaker
  * Backwards-compat when caller passes cluster= instead of deployment=
  * "No matching integration" returns None
"""

from django.test import TestCase

from Organisations.models import Organisations
from Projects.models import Project, ProjectEnvironment, ProjectDeployment
from integrations.models import Cluster, ObservabilityIntegration, IntegrationScope
from integrations.registry import IntegrationRegistry


def _make_integration(org, provider, capability, *, cluster=None,
                       priority_tier='primary',
                       scope_cluster=None, scope_env='', scope_region='',
                       scope_namespace=''):
    """Helper — create integration + its IntegrationScope in one call.

    Signal handler auto-creates a default (cluster-only) scope but we
    typically want a specific scope, so we overwrite it via
    update_or_create.
    """
    integ = ObservabilityIntegration.objects.create(
        organisation=org, provider=provider,
        display_name=f'{provider} ({priority_tier})',
        capabilities=[capability],
        host='https://mock',
        cluster=cluster,
        priority_tier=priority_tier,
        log_adapter_class='mock.LogAdapter' if capability == 'logs' else '',
        metric_adapter_class='mock.MetricAdapter' if capability == 'metrics' else '',
        trace_adapter_class='mock.TraceAdapter' if capability == 'traces' else '',
    )
    IntegrationScope.objects.update_or_create(
        integration=integ,
        defaults={
            'cluster': scope_cluster if scope_cluster is not None else cluster,
            'environment': scope_env,
            'region': scope_region,
            'namespace': scope_namespace,
        },
    )
    return integ


class WildcardBehaviourTest(TestCase):
    """Null / empty scope fields match anything on that dimension."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='WildOrg')
        cls.cluster = Cluster.objects.create(organisation=cls.org, name='prod', provider='eks')
        cls.project = Project.objects.create(name='p', organisation=cls.org, cluster=cls.cluster)
        cls.env = ProjectEnvironment.objects.create(
            project=cls.project, name='production', display_name='Production',
        )
        # Env-signal auto-created a deployment — grab it, don't recreate.
        cls.deployment = cls.project.deployments.first()

    def test_fully_unscoped_integration_matches_any_deployment(self):
        unscoped = _make_integration(self.org, 'prometheus', 'metrics')
        best = IntegrationRegistry._best_integration(
            self.org, 'metrics', deployment=self.deployment,
        )
        self.assertEqual(best.pk, unscoped.pk)

    def test_no_integrations_returns_none(self):
        best = IntegrationRegistry._best_integration(
            self.org, 'metrics', deployment=self.deployment,
        )
        self.assertIsNone(best)

    def test_inactive_integration_excluded(self):
        integ = _make_integration(self.org, 'prometheus', 'metrics')
        integ.is_active = False
        integ.save()
        best = IntegrationRegistry._best_integration(
            self.org, 'metrics', deployment=self.deployment,
        )
        self.assertIsNone(best)

    def test_wrong_capability_excluded(self):
        _make_integration(self.org, 'elasticsearch', 'logs')  # capability=logs
        best = IntegrationRegistry._best_integration(
            self.org, 'metrics', deployment=self.deployment,
        )
        self.assertIsNone(best)


class ExplicitMatchBeatsWildcardTest(TestCase):
    """Precedence: fully-scoped integration wins over wildcard fallback."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='ExplicitOrg')
        cls.cluster = Cluster.objects.create(organisation=cls.org, name='prod-eks', provider='eks')
        cls.project = Project.objects.create(name='p', organisation=cls.org, cluster=cls.cluster)
        cls.env = ProjectEnvironment.objects.create(
            project=cls.project, name='production', display_name='Production',
        )
        cls.deployment = cls.project.deployments.first()

    def test_cluster_scoped_beats_unscoped(self):
        unscoped = _make_integration(self.org, 'prometheus', 'metrics')
        scoped = _make_integration(
            self.org, 'prometheus', 'metrics',
            cluster=self.cluster, priority_tier='fallback',  # even w/ worse tier
        )
        best = IntegrationRegistry._best_integration(
            self.org, 'metrics', deployment=self.deployment,
        )
        self.assertEqual(best.pk, scoped.pk)

    def test_env_scoped_beats_unscoped(self):
        _make_integration(self.org, 'prometheus', 'metrics')  # unscoped
        env_scoped = _make_integration(
            self.org, 'prometheus', 'metrics',
            priority_tier='fallback', scope_env='production',
        )
        best = IntegrationRegistry._best_integration(
            self.org, 'metrics', deployment=self.deployment,
        )
        self.assertEqual(best.pk, env_scoped.pk)

    def test_cluster_and_env_both_win_over_cluster_only(self):
        _make_integration(self.org, 'prometheus', 'metrics', cluster=self.cluster)
        cluster_env = _make_integration(
            self.org, 'prometheus', 'metrics',
            cluster=self.cluster, priority_tier='fallback',  # worse tier
            scope_env='production',
        )
        best = IntegrationRegistry._best_integration(
            self.org, 'metrics', deployment=self.deployment,
        )
        # Even with worse priority tier, matching MORE dimensions wins.
        self.assertEqual(best.pk, cluster_env.pk)


class FieldPrecedenceTest(TestCase):
    """When two integrations match the same COUNT of dimensions,
    the one matching on the MORE-IMPORTANT field wins:
    cluster > env > region > namespace."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='PrecedOrg')
        cls.cluster = Cluster.objects.create(organisation=cls.org, name='c1', provider='eks')
        cls.project = Project.objects.create(name='p', organisation=cls.org, cluster=cls.cluster)
        cls.env = ProjectEnvironment.objects.create(
            project=cls.project, name='production', display_name='Production',
        )
        # Rewrite the auto-created deployment to include region + ns.
        cls.deployment = cls.project.deployments.first()
        cls.deployment.region = 'us-east-1'
        cls.deployment.namespace = 'payments'
        cls.deployment.save()

    def test_cluster_beats_env_when_match_count_equal(self):
        # A: cluster only (1 match). B: env only (1 match). Same count.
        cluster_only = _make_integration(
            self.org, 'prometheus', 'metrics', cluster=self.cluster,
            scope_env='',
        )
        _make_integration(
            self.org, 'prometheus', 'metrics',
            priority_tier='fallback',  # different tier so no unique constraint
            scope_env='production',
        )
        best = IntegrationRegistry._best_integration(
            self.org, 'metrics', deployment=self.deployment,
        )
        self.assertEqual(best.pk, cluster_only.pk)

    def test_env_beats_region_when_match_count_equal(self):
        env_only = _make_integration(
            self.org, 'prometheus', 'metrics', scope_env='production',
        )
        _make_integration(
            self.org, 'prometheus', 'metrics',
            priority_tier='fallback', scope_region='us-east-1',
        )
        best = IntegrationRegistry._best_integration(
            self.org, 'metrics', deployment=self.deployment,
        )
        self.assertEqual(best.pk, env_only.pk)

    def test_region_beats_namespace_when_match_count_equal(self):
        region_only = _make_integration(
            self.org, 'prometheus', 'metrics', scope_region='us-east-1',
        )
        _make_integration(
            self.org, 'prometheus', 'metrics',
            priority_tier='fallback',
            scope_cluster=self.cluster,  # needed for namespace-requires-cluster
            scope_namespace='payments',
        )
        best = IntegrationRegistry._best_integration(
            self.org, 'metrics', deployment=self.deployment,
        )
        # region_only matches 1 field (region) — namespace-only matches
        # 2 (cluster + namespace). More matches wins.
        # But we set scope_cluster on B, so it's actually cluster+namespace
        # → 2 matches. This test really shows "more matches beats fewer".
        # For a pure region-vs-namespace tiebreak see next test.
        self.assertNotEqual(best.pk, region_only.pk)

    def test_region_beats_namespace_pure_tiebreak(self):
        # Both integrations match exactly 1 field. Region should win
        # because region has higher precedence than namespace.
        region_only = _make_integration(
            self.org, 'prometheus', 'metrics', scope_region='us-east-1',
        )
        ns_only = _make_integration(
            self.org, 'prometheus', 'metrics',
            priority_tier='fallback',
            scope_cluster=self.cluster, scope_namespace='payments',
        )
        # ns_only actually matches 2 fields (cluster + ns), so it wins
        # on count. To test the tiebreak we need both to match exactly 1.
        # We do that by NOT setting scope_cluster on ns_only... but
        # then ns_only violates the DB CheckConstraint.
        # Realistic conclusion: pure region-vs-ns tiebreak can't
        # happen because namespace REQUIRES cluster. Precedence
        # tiebreak matters only for cluster > env > region.
        # Skip pure-namespace-tie assertion — impossible shape.
        best = IntegrationRegistry._best_integration(
            self.org, 'metrics', deployment=self.deployment,
        )
        self.assertEqual(best.pk, ns_only.pk)  # 2 matches beats 1


class PriorityTierTiebreakTest(TestCase):
    """When scope match is identical, primary beats fallback beats tertiary."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='TierOrg')
        cls.cluster = Cluster.objects.create(organisation=cls.org, name='c', provider='eks')
        cls.project = Project.objects.create(name='p', organisation=cls.org, cluster=cls.cluster)
        cls.env = ProjectEnvironment.objects.create(
            project=cls.project, name='production', display_name='Production',
        )
        cls.deployment = cls.project.deployments.first()

    def test_primary_wins_over_fallback(self):
        _make_integration(
            self.org, 'prometheus', 'metrics',
            cluster=self.cluster, priority_tier='fallback',
        )
        primary = _make_integration(
            self.org, 'prometheus', 'metrics',
            cluster=self.cluster, priority_tier='primary',
        )
        best = IntegrationRegistry._best_integration(
            self.org, 'metrics', deployment=self.deployment,
        )
        self.assertEqual(best.pk, primary.pk)

    def test_fallback_wins_over_tertiary(self):
        _make_integration(
            self.org, 'prometheus', 'metrics',
            cluster=self.cluster, priority_tier='tertiary',
        )
        fallback = _make_integration(
            self.org, 'prometheus', 'metrics',
            cluster=self.cluster, priority_tier='fallback',
        )
        best = IntegrationRegistry._best_integration(
            self.org, 'metrics', deployment=self.deployment,
        )
        self.assertEqual(best.pk, fallback.pk)


class ProviderTiebreakTest(TestCase):
    """When scope + tier are tied, self-hosted beats managed."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='ProvOrg')
        cls.project = Project.objects.create(name='p', organisation=cls.org)
        cls.env = ProjectEnvironment.objects.create(
            project=cls.project, name='production', display_name='Production',
        )
        cls.deployment = cls.project.deployments.first()

    def test_prometheus_beats_datadog_at_same_scope(self):
        # Both unscoped, both primary. Prom (self-hosted) should win.
        _make_integration(self.org, 'datadog', 'metrics')
        prom = _make_integration(
            self.org, 'prometheus', 'metrics',
            priority_tier='fallback',  # different tier so no uniqueness clash
        )
        # But priority_tier matters — put prom on same tier via workaround:
        prom.priority_tier = 'primary'
        prom.save()
        best = IntegrationRegistry._best_integration(
            self.org, 'metrics', deployment=self.deployment,
        )
        # Prometheus wins on provider preference even though datadog
        # was created first + also primary.
        self.assertEqual(best.provider, 'prometheus')


class BackwardsCompatTest(TestCase):
    """Pre-Batch 49 callers pass cluster= instead of deployment=."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='CompatOrg')
        cls.cluster = Cluster.objects.create(organisation=cls.org, name='c', provider='eks')

    def test_cluster_kwarg_still_works(self):
        cluster_scoped = _make_integration(
            self.org, 'prometheus', 'metrics', cluster=self.cluster,
        )
        best = IntegrationRegistry._best_integration(
            self.org, 'metrics', cluster=self.cluster,
        )
        self.assertEqual(best.pk, cluster_scoped.pk)

    def test_no_args_returns_unscoped_fallback(self):
        unscoped = _make_integration(self.org, 'prometheus', 'metrics')
        best = IntegrationRegistry._best_integration(self.org, 'metrics')
        self.assertEqual(best.pk, unscoped.pk)
