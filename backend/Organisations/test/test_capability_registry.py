"""Tests for Organisations.capability_registry.

Verifies each of the 5 capabilities is correctly detected from live
config, and that cross-org isolation holds (org A's integrations
never leak into org B's capability set).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from Organisations.capability_registry import (
    ALL_CAPABILITIES,
    enabled_capabilities_for,
    enabled_capabilities_for_org,
)
from Organisations.models import Organisations

User = get_user_model()


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


class CapabilityRegistryTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='CapOrg')
        cls.other_org = Organisations.objects.create(name='OtherCapOrg')
        from Projects.models import Project
        cls.project = Project.objects.create(organisation=cls.org, name='cap-project')
        cls.other_project = Project.objects.create(
            organisation=cls.other_org, name='other-cap-project',
        )

    def test_all_known_covers_five_sources(self):
        self.assertEqual(
            ALL_CAPABILITIES,
            frozenset({'logs', 'metrics', 'code', 'cicd', 'traces'}),
        )

    def test_bare_org_has_none(self):
        self.assertEqual(enabled_capabilities_for(self.project), frozenset())

    def test_none_project_returns_empty(self):
        self.assertEqual(enabled_capabilities_for(None), frozenset())

    def test_logs_detected(self):
        _make_observability(self.org, 'elasticsearch', ['logs'])
        self.assertEqual(enabled_capabilities_for(self.project), frozenset({'logs'}))

    def test_metrics_detected(self):
        _make_observability(self.org, 'prometheus', ['metrics'])
        self.assertEqual(enabled_capabilities_for(self.project), frozenset({'metrics'}))

    def test_dual_capability(self):
        _make_observability(self.org, 'datadog', ['logs', 'metrics'])
        self.assertEqual(
            enabled_capabilities_for(self.project),
            frozenset({'logs', 'metrics'}),
        )

    def test_traces_via_ingest_key(self):
        from traces.models import IngestKey
        key = IngestKey(organisation=self.org, name='k')
        key.set_key(IngestKey.generate_key())
        key.save()
        self.assertEqual(enabled_capabilities_for(self.project), frozenset({'traces'}))

    def test_traces_via_external_adapter(self):
        _make_observability(self.org, 'jaeger', ['traces'])
        self.assertEqual(enabled_capabilities_for(self.project), frozenset({'traces'}))

    def test_traces_ignores_inactive_ingest_key(self):
        from traces.models import IngestKey
        key = IngestKey(organisation=self.org, name='revoked')
        key.set_key(IngestKey.generate_key())
        key.is_active = False
        key.save()
        self.assertEqual(enabled_capabilities_for(self.project), frozenset())

    def test_inactive_observability_ignored(self):
        _make_observability(self.org, 'loki', ['logs'])
        from integrations.models import ObservabilityIntegration
        ObservabilityIntegration.objects.filter(organisation=self.org).update(is_active=False)
        self.assertEqual(enabled_capabilities_for(self.project), frozenset())

    def test_cross_org_isolation(self):
        # OTHER org configures everything; caller org still has nothing.
        _make_observability(self.other_org, 'elasticsearch', ['logs'])
        _make_observability(self.other_org, 'prometheus', ['metrics'])
        self.assertEqual(enabled_capabilities_for(self.project), frozenset())

    def test_full_stack(self):
        from Projects.models import ProjectService, SCMBinding, CICDBinding
        from providers.models import ProviderIntegration
        _make_observability(self.org, 'elasticsearch', ['logs'])
        _make_observability(self.org, 'prometheus', ['metrics'])
        _make_observability(self.org, 'jaeger', ['traces'])
        svc = ProjectService.objects.create(
            project=self.project, name='api', service_type='application',
        )
        # SCMBinding requires an integration; create a bare provider.
        integ = ProviderIntegration.objects.create(
            organisation=self.org,
            provider_type='gitlab',
            name='gitlab-int',
        )
        SCMBinding.objects.create(
            project_service=svc, integration=integ,
            repository_id='42', repository_name='api',
        )
        CICDBinding.objects.create(
            project_service=svc, integration=integ,
            binding_type='build',
        )
        self.assertEqual(
            enabled_capabilities_for(self.project),
            frozenset({'logs', 'metrics', 'code', 'cicd', 'traces'}),
        )


class CapabilityEndpointTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='EndOrg')
        self.user = User.objects.create_user(
            username='endpoint', email='e@t.com', password='p',
            organisation=self.org, role='user', is_active=True,
        )
        self.client = APIClient()

    def test_requires_auth(self):
        response = self.client.get('/api/organisation/capabilities/')
        self.assertIn(response.status_code, (401, 403))

    def test_returns_all_known(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/organisation/capabilities/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            set(data['all_known']),
            {'logs', 'metrics', 'code', 'cicd', 'traces'},
        )
        # No integrations yet.
        self.assertEqual(data['capabilities'], [])

    def test_reflects_live_config(self):
        _make_observability(self.org, 'loki', ['logs'])
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/organisation/capabilities/')
        self.assertEqual(response.json()['capabilities'], ['logs'])
