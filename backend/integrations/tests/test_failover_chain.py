"""iter_integrations_for_failover — priority-tier failover chain (Batch 51).

Yields up to 3 unique integrations in match-score order. Callers wrap
their query call in try/except and continue to the next integration
on adapter error. Chain is bounded to 3 attempts by default so a
whole-provider outage doesn't triple batch latency.
"""

from django.test import TestCase

from Organisations.models import Organisations
from Projects.models import Project, ProjectEnvironment
from integrations.models import Cluster, ObservabilityIntegration, IntegrationScope
from integrations.registry import IntegrationRegistry


def _make_integration(org, provider, capability, *, cluster=None,
                       priority_tier='primary', scope_cluster=None):
    integ = ObservabilityIntegration.objects.create(
        organisation=org, provider=provider,
        display_name=f'{provider} ({priority_tier})',
        capabilities=[capability], host='https://mock',
        cluster=cluster, priority_tier=priority_tier,
        metric_adapter_class='mock.MetricAdapter' if capability == 'metrics' else '',
    )
    IntegrationScope.objects.update_or_create(
        integration=integ,
        defaults={
            'cluster': scope_cluster if scope_cluster is not None else cluster,
            'environment': '', 'region': '', 'namespace': '',
        },
    )
    return integ


class FailoverOrderingTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='FailoverOrg')
        cls.cluster = Cluster.objects.create(organisation=cls.org, name='c', provider='eks')
        cls.project = Project.objects.create(name='p', organisation=cls.org, cluster=cls.cluster)
        cls.env = ProjectEnvironment.objects.create(
            project=cls.project, name='production', display_name='Production',
        )
        cls.deployment = cls.project.deployments.first()

    def test_yields_primary_then_fallback_then_tertiary(self):
        primary = _make_integration(self.org, 'prometheus', 'metrics',
                                     cluster=self.cluster, priority_tier='primary')
        fallback = _make_integration(self.org, 'prometheus', 'metrics',
                                      cluster=self.cluster, priority_tier='fallback')
        tertiary = _make_integration(self.org, 'prometheus', 'metrics',
                                      cluster=self.cluster, priority_tier='tertiary')
        chain = list(IntegrationRegistry.iter_integrations_for_failover(
            self.org, 'metrics', deployment=self.deployment,
        ))
        self.assertEqual(len(chain), 3)
        self.assertEqual([i.priority_tier for i in chain],
                          ['primary', 'fallback', 'tertiary'])

    def test_yields_only_available_tiers(self):
        # Only primary + tertiary configured — no fallback. Chain
        # should yield the 2 that exist, in match order.
        _make_integration(self.org, 'prometheus', 'metrics',
                          cluster=self.cluster, priority_tier='primary')
        _make_integration(self.org, 'prometheus', 'metrics',
                          cluster=self.cluster, priority_tier='tertiary')
        chain = list(IntegrationRegistry.iter_integrations_for_failover(
            self.org, 'metrics', deployment=self.deployment,
        ))
        self.assertEqual(len(chain), 2)

    def test_max_tries_caps_chain_length(self):
        # Even if 3 tiers configured, cap at 1 (extreme case, tests bound).
        _make_integration(self.org, 'prometheus', 'metrics',
                          cluster=self.cluster, priority_tier='primary')
        _make_integration(self.org, 'prometheus', 'metrics',
                          cluster=self.cluster, priority_tier='fallback')
        _make_integration(self.org, 'prometheus', 'metrics',
                          cluster=self.cluster, priority_tier='tertiary')
        chain = list(IntegrationRegistry.iter_integrations_for_failover(
            self.org, 'metrics', deployment=self.deployment, max_tries=1,
        ))
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0].priority_tier, 'primary')

    def test_zero_integrations_yields_empty(self):
        chain = list(IntegrationRegistry.iter_integrations_for_failover(
            self.org, 'metrics', deployment=self.deployment,
        ))
        self.assertEqual(chain, [])

    def test_skip_ids_excludes_already_tried(self):
        # This tests the internal skip_ids semantics (used by the
        # iter_ helper to avoid re-yielding the same integration).
        p = _make_integration(self.org, 'prometheus', 'metrics',
                              cluster=self.cluster, priority_tier='primary')
        f = _make_integration(self.org, 'prometheus', 'metrics',
                              cluster=self.cluster, priority_tier='fallback')
        # If we skip primary, first-match should be fallback.
        remaining = IntegrationRegistry._first_matching_integration(
            self.org, 'metrics', deployment=self.deployment,
            skip_ids={p.pk},
        )
        self.assertEqual(remaining.pk, f.pk)


class FailoverAcrossProvidersTest(TestCase):
    """When primary is one provider and fallback is another,
    the chain should still enumerate them."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='CrossOrg')
        cls.project = Project.objects.create(name='p', organisation=cls.org)
        cls.env = ProjectEnvironment.objects.create(
            project=cls.project, name='production', display_name='Production',
        )
        cls.deployment = cls.project.deployments.first()

    def test_prom_primary_datadog_fallback(self):
        prom = _make_integration(self.org, 'prometheus', 'metrics',
                                  priority_tier='primary')
        dd = _make_integration(self.org, 'datadog', 'metrics',
                                priority_tier='fallback')
        chain = list(IntegrationRegistry.iter_integrations_for_failover(
            self.org, 'metrics', deployment=self.deployment,
        ))
        self.assertEqual(len(chain), 2)
        self.assertEqual(chain[0].pk, prom.pk)   # primary tier wins
        self.assertEqual(chain[1].pk, dd.pk)     # fallback next
