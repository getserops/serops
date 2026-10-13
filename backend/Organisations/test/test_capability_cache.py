"""Tests for the capability-registry cache layer (Q2.3).

The registry itself is well-covered by ``test_capability_registry.py``
(correctness of each detector, cross-org isolation, all-known
enumeration). This file exercises what changes with caching:

* Second call short-circuits the detector queries.
* Signals on the four driver models invalidate the entry on the
  next lookup.
* Cross-org isolation survives the cache (org A's cached answer
  never leaks into org B's).
* Cache backend failure falls open — a Redis outage must not
  break capability lookups.
"""

from __future__ import annotations

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from Organisations import capability_registry as reg
from Organisations.capability_registry import (
    enabled_capabilities_for,
    enabled_capabilities_for_org,
    invalidate_org,
    invalidate_project,
)
from Organisations.models import Organisations


def _make_observability(org, provider, capabilities):
    from integrations.models import ObservabilityIntegration
    return ObservabilityIntegration.objects.create(
        organisation=org,
        provider=provider,
        display_name=f'{provider}-int',
        capabilities=capabilities,
        is_active=True,
        host='http://example',
    )


class CapabilityCacheHitTest(TestCase):
    """Cached wrappers return the same value as the uncached path,
    but skip the underlying queries on the second call."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='CacheOrg')
        from Projects.models import Project
        cls.project = Project.objects.create(organisation=cls.org, name='cache-proj')

    def setUp(self):
        # Test isolation — Django doesn't roll back the cache between
        # tests. Clear only the keys we own.
        reg.clear_all()

    def test_second_lookup_bypasses_detector_queries(self):
        _make_observability(self.org, 'elasticsearch', ['logs'])
        # Warm the cache.
        first = enabled_capabilities_for_org(self.org)
        self.assertEqual(first, frozenset({'logs'}))
        # If the second call still hit ``_has_logs`` (etc.), the patch
        # below would record a call. It must record none.
        with patch.object(reg, '_has_logs', wraps=reg._has_logs) as h_logs, \
             patch.object(reg, '_has_metrics', wraps=reg._has_metrics) as h_m, \
             patch.object(reg, '_has_traces', wraps=reg._has_traces) as h_t:
            second = enabled_capabilities_for_org(self.org)
        self.assertEqual(first, second)
        self.assertEqual(h_logs.call_count, 0)
        self.assertEqual(h_m.call_count, 0)
        self.assertEqual(h_t.call_count, 0)

    def test_project_lookup_second_hit_bypasses_detectors(self):
        _make_observability(self.org, 'elasticsearch', ['logs'])
        first = enabled_capabilities_for(self.project)
        self.assertEqual(first, frozenset({'logs'}))
        with patch.object(reg, '_has_logs', wraps=reg._has_logs) as h_logs, \
             patch.object(reg, '_has_code', wraps=reg._has_code) as h_code:
            second = enabled_capabilities_for(self.project)
        self.assertEqual(first, second)
        self.assertEqual(h_logs.call_count, 0)
        self.assertEqual(h_code.call_count, 0)

    def test_org_cache_isolated_between_orgs(self):
        """Warming org A's cache must not leak to org B."""
        other = Organisations.objects.create(name='CacheOrgOther')
        _make_observability(self.org, 'elasticsearch', ['logs'])
        _make_observability(other, 'prometheus', ['metrics'])
        self.assertEqual(
            enabled_capabilities_for_org(self.org), frozenset({'logs'}),
        )
        self.assertEqual(
            enabled_capabilities_for_org(other), frozenset({'metrics'}),
        )


class CapabilitySignalInvalidationTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='InvalOrg')
        from Projects.models import Project, ProjectService
        cls.project = Project.objects.create(organisation=cls.org, name='inval-proj')
        cls.service = ProjectService.objects.create(
            project=cls.project, name='inval-service',
        )

    def setUp(self):
        reg.clear_all()

    def test_observability_integration_save_invalidates_org_cache(self):
        # Warm empty cache first.
        self.assertEqual(enabled_capabilities_for_org(self.org), frozenset())
        # Adding an integration must flip the answer, not return the
        # stale empty set.
        _make_observability(self.org, 'elasticsearch', ['logs'])
        self.assertEqual(
            enabled_capabilities_for_org(self.org), frozenset({'logs'}),
        )

    def test_observability_integration_delete_invalidates(self):
        integration = _make_observability(self.org, 'elasticsearch', ['logs'])
        self.assertEqual(
            enabled_capabilities_for_org(self.org), frozenset({'logs'}),
        )
        integration.delete()
        self.assertEqual(enabled_capabilities_for_org(self.org), frozenset())

    def test_ingest_key_save_invalidates(self):
        """OTLP ingest-key creation must flip traces on immediately."""
        from traces.models import IngestKey
        self.assertEqual(enabled_capabilities_for_org(self.org), frozenset())
        key = IngestKey(
            organisation=self.org, name='inval-key', is_active=True,
        )
        key.set_key('serops_otlp_invalidation_test_key_xxx')
        key.save()
        self.assertEqual(
            enabled_capabilities_for_org(self.org), frozenset({'traces'}),
        )

    def test_scm_binding_save_invalidates_org_and_project(self):
        """Adding an SCMBinding must flip code on for BOTH the project
        it's attached to and the parent org's union view."""
        from Projects.models import SCMBinding
        from providers.models import ProviderIntegration

        integration = ProviderIntegration.objects.create(
            organisation=self.org,
            name='cache-github',
            provider_type='github',
            category='devops',
        )
        # Warm both caches empty first.
        self.assertEqual(enabled_capabilities_for(self.project), frozenset())
        self.assertEqual(enabled_capabilities_for_org(self.org), frozenset())

        SCMBinding.objects.create(
            project_service=self.service,
            integration=integration,
            repository_id='42',
        )
        self.assertEqual(
            enabled_capabilities_for(self.project), frozenset({'code'}),
        )
        self.assertEqual(
            enabled_capabilities_for_org(self.org), frozenset({'code'}),
        )

    def test_cicd_binding_save_invalidates(self):
        from Projects.models import CICDBinding
        from providers.models import ProviderIntegration
        integration = ProviderIntegration.objects.create(
            organisation=self.org,
            name='cache-jenkins',
            provider_type='jenkins',
            category='cicd',
        )
        self.assertEqual(enabled_capabilities_for(self.project), frozenset())
        CICDBinding.objects.create(
            project_service=self.service,
            integration=integration,
            binding_type='deploy',
            pipeline_id='job-1',
            pipeline_name='deploy-checkout',
        )
        self.assertEqual(
            enabled_capabilities_for(self.project), frozenset({'cicd'}),
        )


class CapabilityCacheFailOpenTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='FailOpenOrg')
        from Projects.models import Project
        cls.project = Project.objects.create(organisation=cls.org, name='fo-proj')

    def setUp(self):
        reg.clear_all()

    def test_cache_get_error_falls_back_to_detectors(self):
        _make_observability(self.org, 'elasticsearch', ['logs'])
        with patch.object(cache, 'get', side_effect=RuntimeError('redis is down')):
            result = enabled_capabilities_for_org(self.org)
        self.assertEqual(result, frozenset({'logs'}))

    def test_cache_set_error_never_raises(self):
        """A failed write must be swallowed; the caller still gets
        the freshly computed answer for this request."""
        _make_observability(self.org, 'elasticsearch', ['logs'])
        with patch.object(cache, 'set', side_effect=RuntimeError('redis is down')):
            result = enabled_capabilities_for_org(self.org)
        self.assertEqual(result, frozenset({'logs'}))

    def test_invalidate_swallows_cache_backend_error(self):
        """A dead cache backend must not turn a save() into a 500."""
        # Warm cache first.
        _make_observability(self.org, 'elasticsearch', ['logs'])
        self.assertEqual(
            enabled_capabilities_for_org(self.org), frozenset({'logs'}),
        )
        # Now the invalidate path must survive a broken backend.
        with patch.object(
            cache, 'delete_many', side_effect=RuntimeError('redis is down'),
        ):
            # Must not raise.
            invalidate_org(self.org.id)


class CapabilityCacheHelperTest(TestCase):
    """Direct tests of the invalidation helpers, so the signal
    handlers stay one-liners that just call into them."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='HelperOrg')
        from Projects.models import Project
        cls.project = Project.objects.create(organisation=cls.org, name='helper-proj')

    def setUp(self):
        reg.clear_all()

    def test_invalidate_project_targets_both_project_and_org(self):
        _make_observability(self.org, 'elasticsearch', ['logs'])
        # Warm both caches so we can prove both got dropped.
        self.assertEqual(
            enabled_capabilities_for(self.project), frozenset({'logs'}),
        )
        self.assertEqual(
            enabled_capabilities_for_org(self.org), frozenset({'logs'}),
        )
        invalidate_project(self.project.id, org_id=self.org.id)
        # Add a metrics integration; without the org invalidation the
        # org lookup would return the stale {'logs'} answer.
        _make_observability(self.org, 'prometheus', ['metrics'])
        # SIDE NOTE: the ObservabilityIntegration signal itself
        # invalidates, so this test is a belt-and-braces on the
        # helper's behaviour rather than the signal chain.
        # Force reads.
        self.assertEqual(
            enabled_capabilities_for(self.project),
            frozenset({'logs', 'metrics'}),
        )
        self.assertEqual(
            enabled_capabilities_for_org(self.org),
            frozenset({'logs', 'metrics'}),
        )

    def test_none_ids_are_safe_noops(self):
        # No exceptions, no cache calls that could fail.
        invalidate_org(None)
        invalidate_project(None)
