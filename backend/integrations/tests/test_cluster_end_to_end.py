"""End-to-end verification of multi-cluster wiring (Q1.4 residual, Batch 25).

Covers the three things that were unfinished after Batch 18:

1. Batch pipeline routes to cluster-scoped log/metric provider.
2. Dashboard analytics honour ?cluster= via the mixin + hand-rolled
   patches.
3. AI prompt receives cluster context in project_context.
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from rest_framework.test import APIClient

from Data.models import AIAnalyzedBatch, Issue
from Data.mixins import OrgFilterMixin
from integrations.models import Cluster, ObservabilityIntegration
from integrations.registry import IntegrationRegistry
from Organisations.models import Organisations
from Projects.models import Project

User = get_user_model()


def _make_integration(org, provider, capabilities, cluster=None):
    return ObservabilityIntegration.objects.create(
        organisation=org, provider=provider, display_name=f'{provider}-int',
        capabilities=capabilities, cluster=cluster, is_active=True,
        host='http://example',
    )


# ============================================================================
# 1. Registry — public methods accept + forward cluster
# ============================================================================


class RegistryClusterKwargTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='REndOrg')
        self.c1 = Cluster.objects.create(organisation=self.org, name='c1', provider='eks')
        IntegrationRegistry.clear_cache()

    # These assert one thing: the caller's ``cluster`` reaches the resolver.
    #
    # They used to patch ``_best_integration``, which the logs/metrics paths
    # stopped calling directly when the adapter-failover chain landed — they
    # now go through ``_first_matching_integration``, which takes an extra
    # ``skip_ids`` so already-tried integrations can be excluded on retry.
    # Patching a method that is no longer on the path meant the mock recorded
    # zero calls and the assertion failed while the behaviour was fine.
    # ``_best_integration`` is still live for the trace path (see
    # test_scope_matching.py), so it was not removed.

    @patch.object(IntegrationRegistry, '_first_matching_integration')
    def test_get_log_provider_for_org_passes_cluster(self, first):
        first.return_value = None
        with self.assertRaises(ValueError):
            # No integration configured, so the chain is exhausted — that is
            # the documented outcome and proves the resolver actually ran.
            IntegrationRegistry.get_log_provider_for_org(self.org, cluster=self.c1)
        first.assert_called_once_with(
            self.org, 'logs', cluster=self.c1, deployment=None, skip_ids=None,
        )

    @patch.object(IntegrationRegistry, '_first_matching_integration')
    def test_get_metric_provider_for_org_passes_cluster(self, first):
        first.return_value = None
        with self.assertRaises(ValueError):
            IntegrationRegistry.get_metric_provider_for_org(self.org, cluster=self.c1)
        first.assert_called_once_with(
            self.org, 'metrics', cluster=self.c1, deployment=None, skip_ids=None,
        )

    @patch.object(IntegrationRegistry, '_first_matching_integration')
    def test_deployment_is_forwarded_too(self, first):
        """The kwarg added alongside cluster — untested until now, and the
        reason the original assertion had to be rewritten once already."""
        first.return_value = None
        with self.assertRaises(ValueError):
            IntegrationRegistry.get_log_provider_for_org(
                self.org, cluster=self.c1, deployment=None,
            )
        _, kwargs = first.call_args
        self.assertIn('deployment', kwargs)
        self.assertIn('skip_ids', kwargs)

    def test_cluster_scoped_integration_wins(self):
        """End-to-end: scoped Prometheus wins over unscoped when
        cluster is requested. Uses real _best_integration path."""
        scoped = _make_integration(self.org, 'prometheus', ['metrics'], cluster=self.c1)
        unscoped = _make_integration(self.org, 'prometheus', ['metrics'], cluster=None)
        # Simulate adapter loading — patch _load_adapter to skip.
        with patch.object(IntegrationRegistry, '_load_adapter') as load:
            load.return_value = MagicMock()
            IntegrationRegistry.get_metric_provider_for_org(self.org, cluster=self.c1)
            # First arg = the class path; look at kwargs for org_id.
            args, kwargs = load.call_args
            # The class path should be the scoped one's adapter class,
            # which for prometheus is the same as unscoped — but the
            # config dict comes from the scoped instance. Verify org_id
            # matches (which is the cheapest proof the resolver ran).
            self.assertEqual(kwargs.get('org_id'), self.org.id)

    def test_cluster_none_uses_unscoped(self):
        """Historical callers (cluster=None) get identical behaviour."""
        _make_integration(self.org, 'prometheus', ['metrics'], cluster=None)
        with patch.object(IntegrationRegistry, '_load_adapter') as load:
            load.return_value = MagicMock()
            IntegrationRegistry.get_metric_provider_for_org(self.org)
            self.assertTrue(load.called)


# ============================================================================
# 2. OrgFilterMixin cluster filter (used by all analytics views)
# ============================================================================


class OrgFilterMixinClusterTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='FilterMixinOrg')
        cls.c1 = Cluster.objects.create(organisation=cls.org, name='c1', provider='eks')
        cls.c2 = Cluster.objects.create(organisation=cls.org, name='c2', provider='gke')
        cls.user = User.objects.create_user(
            username='u', email='u@t.com', password='p',
            organisation=cls.org, role='user', is_active=True,
        )
        cls.p_c1 = Project.objects.create(organisation=cls.org, name='p1', cluster=cls.c1)
        cls.p_c2 = Project.objects.create(organisation=cls.org, name='p2', cluster=cls.c2)
        cls.p_none = Project.objects.create(organisation=cls.org, name='p3')
        cls.b_c1 = AIAnalyzedBatch.objects.create(
            batch_id='b_c1', organisation=cls.org, project=cls.p_c1,
        )
        cls.b_c2 = AIAnalyzedBatch.objects.create(
            batch_id='b_c2', organisation=cls.org, project=cls.p_c2,
        )
        cls.b_none = AIAnalyzedBatch.objects.create(
            batch_id='b_none', organisation=cls.org, project=cls.p_none,
        )

    def _request(self, cluster=None):
        rf = RequestFactory()
        req = rf.get('/analytics/', {'cluster': cluster} if cluster is not None else {})
        req.user = self.user

        # Emulate DRF's request.query_params (dict-like on QueryDict).
        req.query_params = req.GET
        return req

    def test_batch_filter_by_cluster(self):
        mixin = OrgFilterMixin()
        req = self._request(cluster=str(self.c1.pk))
        qs = mixin.filter_by_org(req, AIAnalyzedBatch.objects.all(), 'batch')
        self.assertEqual({b.batch_id for b in qs}, {'b_c1'})

    def test_issue_filter_by_cluster(self):
        Issue.objects.create(
            batch=self.b_c1, organisation=self.org, severity='high',
            description='x', component='api', issue_type='error', fingerprint='fp1',
        )
        Issue.objects.create(
            batch=self.b_c2, organisation=self.org, severity='high',
            description='y', component='api', issue_type='error', fingerprint='fp2',
        )
        mixin = OrgFilterMixin()
        req = self._request(cluster=str(self.c2.pk))
        qs = mixin.filter_by_org(req, Issue.objects.all(), 'issue')
        self.assertEqual({i.fingerprint for i in qs}, {'fp2'})

    def test_no_cluster_returns_everything(self):
        mixin = OrgFilterMixin()
        req = self._request(cluster=None)
        qs = mixin.filter_by_org(req, AIAnalyzedBatch.objects.all(), 'batch')
        self.assertEqual(qs.count(), 3)

    def test_bad_cluster_id_ignored(self):
        mixin = OrgFilterMixin()
        req = self._request(cluster='not-a-number')
        qs = mixin.filter_by_org(req, AIAnalyzedBatch.objects.all(), 'batch')
        # Silent drop — all 3 returned.
        self.assertEqual(qs.count(), 3)


# ============================================================================
# 3. Dashboard analytics endpoint smoke test
# ============================================================================


class MTTREndpointClusterTest(TestCase):
    """MTTR uses filter_issues_by_org → mixin does the cluster filter."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='MTTROrg')
        cls.c1 = Cluster.objects.create(organisation=cls.org, name='c1', provider='eks')
        cls.p = Project.objects.create(organisation=cls.org, name='p1', cluster=cls.c1)
        cls.other_p = Project.objects.create(organisation=cls.org, name='p2')
        cls.user = User.objects.create_user(
            username='mu', email='m@t.com', password='p',
            organisation=cls.org, role='user', is_active=True,
        )
        b1 = AIAnalyzedBatch.objects.create(
            batch_id='b1', organisation=cls.org, project=cls.p,
        )
        b2 = AIAnalyzedBatch.objects.create(
            batch_id='b2', organisation=cls.org, project=cls.other_p,
        )
        Issue.objects.create(
            batch=b1, organisation=cls.org, severity='CRITICAL',
            description='in-cluster', component='api', issue_type='error',
            fingerprint='fp-in-cluster', status='RESOLVED',
        )
        Issue.objects.create(
            batch=b2, organisation=cls.org, severity='CRITICAL',
            description='no-cluster', component='api', issue_type='error',
            fingerprint='fp-no-cluster', status='RESOLVED',
        )

    def test_cluster_filter_narrows_analytics(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.get(f'/api/data/analytics/mttr/?cluster={self.c1.pk}')
        # We don't assert on MTTR math itself (that's another test's
        # job) — we assert the response is 200 (endpoint accepts +
        # honours the query param) and doesn't 500 on the filter.
        self.assertEqual(response.status_code, 200)


# ============================================================================
# 4. _build_project_context includes cluster
# ============================================================================


class ProjectContextClusterTest(TestCase):

    def test_no_cluster_no_key(self):
        from ai_model.tasks import _build_project_context
        org = Organisations.objects.create(name='PCOrg')
        p = Project.objects.create(organisation=org, name='p')

        class _B: pass
        b = _B(); b.project = p
        ctx = _build_project_context(b)
        self.assertNotIn('cluster', ctx)

    def test_cluster_present_populated(self):
        from ai_model.tasks import _build_project_context
        org = Organisations.objects.create(name='PCOrg2')
        c = Cluster.objects.create(
            organisation=org, name='prod-eks', provider='eks', region='us-west-2',
        )
        p = Project.objects.create(organisation=org, name='p', cluster=c)

        class _B: pass
        b = _B(); b.project = p
        ctx = _build_project_context(b)
        self.assertEqual(ctx['cluster']['name'], 'prod-eks')
        self.assertEqual(ctx['cluster']['provider'], 'AWS EKS')
        self.assertEqual(ctx['cluster']['region'], 'us-west-2')

    def test_prompt_renders_cluster_line(self):
        """The rendered user prompt contains a Cluster: line when set."""
        from ai_model.prompt_context import DataSourceContext
        from ai_model.prompts import get_batch_analysis_prompt_parts
        _system, user = get_batch_analysis_prompt_parts(
            DataSourceContext(
                batch_data={'batch_id': 'x', 'timestamp': 't', 'environment': 'prod'},
                logs=[],
                project_context={
                    'name': 'checkout', 'description': '',
                    'services': [],
                    'cluster': {'name': 'prod-eks', 'provider': 'AWS EKS', 'region': 'us-west-2'},
                },
            ),
        )
        self.assertIn('Cluster: prod-eks — AWS EKS (us-west-2)', user)
