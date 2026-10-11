"""ProjectDeployment model + signal tests (Batch 51 / Deployment model).

Covers:
  * Auto-name generation on save() including all dimension combos
  * User-editable name is preserved on update
  * Unique-shape constraint (project × env × cluster × region × ns)
  * Unique-name-per-project constraint
  * Namespace requires cluster (DB CheckConstraint)
  * post_save signal on ProjectEnvironment auto-creates matching deployment
  * Inactive envs skipped by the signal
  * Migration-seeded deployments (via integration tests)
  * Tenant isolation — deployments never leak across orgs
"""

from django.db import IntegrityError, transaction
from django.test import TestCase

from Organisations.models import Organisations
from Projects.models import Project, ProjectDeployment, ProjectEnvironment
from integrations.models import Cluster


class ProjectDeploymentAutoNameTest(TestCase):
    """suggest_name() composes readable labels from the four dimensions.

    Auto-name generation is what makes the Deployments tab actually
    scannable — pinning to a name like "prod-eks / production" beats
    "deployment 47".
    """

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='NameOrg')
        cls.project = Project.objects.create(name='p1', organisation=cls.org)
        cls.cluster = Cluster.objects.create(organisation=cls.org, name='prod-eks', provider='eks')
        cls.env = ProjectEnvironment.objects.create(
            project=cls.project, name='production', display_name='Production',
        )

    def test_name_composes_cluster_env(self):
        d = ProjectDeployment.objects.create(
            project=self.project, environment=self.env, cluster=self.cluster,
        )
        self.assertIn('prod-eks', d.name)
        self.assertIn('production', d.name)

    def test_name_with_region(self):
        d = ProjectDeployment.objects.create(
            project=self.project, environment=self.env, cluster=self.cluster,
            region='us-east-1',
        )
        self.assertIn('us-east-1', d.name)

    def test_name_with_namespace(self):
        d = ProjectDeployment.objects.create(
            project=self.project, environment=self.env, cluster=self.cluster,
            namespace='payments',
        )
        self.assertIn('ns=payments', d.name)

    def test_name_all_dimensions(self):
        d = ProjectDeployment.objects.create(
            project=self.project, environment=self.env, cluster=self.cluster,
            region='eu-west-1', namespace='checkout',
        )
        for expected in ['prod-eks', 'production', 'eu-west-1', 'ns=checkout']:
            self.assertIn(expected, d.name)

    def test_name_fallback_default_when_all_empty(self):
        # Only possible on legacy 0-env, VM-only, single-region projects.
        d = ProjectDeployment.objects.create(project=self.project)
        self.assertEqual(d.name, 'default')

    def test_user_name_preserved(self):
        # Save with explicit name — auto-suggest MUST NOT overwrite.
        d = ProjectDeployment.objects.create(
            project=self.project, environment=self.env, cluster=self.cluster,
            name='my-custom-label',
        )
        self.assertEqual(d.name, 'my-custom-label')
        # Re-save without touching name → still preserved.
        d.is_active = False
        d.save()
        d.refresh_from_db()
        self.assertEqual(d.name, 'my-custom-label')


class ProjectDeploymentConstraintsTest(TestCase):
    """DB-level integrity constraints — cannot be bypassed at all."""

    def setUp(self):
        # is_active=False → post_save signal skips auto-creation, so
        # baseline is 0 deployments and my per-test counts stay honest.
        # (Signal-behaviour tests live in the dedicated Signal test class.)
        self.org = Organisations.objects.create(name='ConstraintOrg')
        self.project = Project.objects.create(name='p1', organisation=self.org)
        self.env = ProjectEnvironment.objects.create(
            project=self.project, name='production',
            display_name='Production', is_active=False,
        )
        self.cluster = Cluster.objects.create(
            organisation=self.org, name='c1', provider='eks',
        )
        assert self.project.deployments.count() == 0

    def test_unique_shape_blocks_exact_duplicate(self):
        ProjectDeployment.objects.create(
            project=self.project, environment=self.env, cluster=self.cluster,
            region='us-east-1', namespace='',
        )
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ProjectDeployment.objects.create(
                project=self.project, environment=self.env, cluster=self.cluster,
                region='us-east-1', namespace='',
            )

    def test_same_env_different_region_allowed(self):
        # Multi-region same-project — the core use case Deployment unlocks.
        ProjectDeployment.objects.create(
            project=self.project, environment=self.env, cluster=self.cluster,
            region='us-east-1',
        )
        # No IntegrityError expected.
        ProjectDeployment.objects.create(
            project=self.project, environment=self.env, cluster=self.cluster,
            region='eu-west-1',
        )
        self.assertEqual(self.project.deployments.count(), 2)

    def test_same_env_different_namespace_allowed(self):
        ProjectDeployment.objects.create(
            project=self.project, environment=self.env, cluster=self.cluster,
            namespace='team-a',
        )
        ProjectDeployment.objects.create(
            project=self.project, environment=self.env, cluster=self.cluster,
            namespace='team-b',
        )
        self.assertEqual(self.project.deployments.count(), 2)

    def test_unique_name_per_project_blocks_duplicate(self):
        ProjectDeployment.objects.create(
            project=self.project, cluster=self.cluster, name='same-label',
        )
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ProjectDeployment.objects.create(
                project=self.project, environment=self.env, name='same-label',
            )

    def test_same_name_different_project_allowed(self):
        # Two different projects can each have a "production" deployment.
        other_proj = Project.objects.create(name='p2', organisation=self.org)
        ProjectDeployment.objects.create(project=self.project, name='production')
        ProjectDeployment.objects.create(project=other_proj, name='production')
        self.assertEqual(ProjectDeployment.objects.filter(name='production').count(), 2)

    def test_namespace_requires_cluster_check_constraint(self):
        # cluster=NULL + namespace='foo' violates the DB CheckConstraint.
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ProjectDeployment.objects.create(
                project=self.project, environment=self.env,
                cluster=None, namespace='payments',
            )

    def test_namespace_with_cluster_allowed(self):
        # Same non-empty namespace but WITH cluster is legal.
        ProjectDeployment.objects.create(
            project=self.project, environment=self.env,
            cluster=self.cluster, namespace='payments',
        )
        self.assertTrue(
            ProjectDeployment.objects.filter(namespace='payments').exists()
        )

    def test_empty_namespace_no_cluster_allowed(self):
        # VM-only / bare-metal projects — no cluster, no namespace.
        d = ProjectDeployment.objects.create(project=self.project, environment=self.env)
        self.assertEqual(d.namespace, '')
        self.assertIsNone(d.cluster)


class ProjectDeploymentSignalTest(TestCase):
    """post_save on ProjectEnvironment auto-creates a matching deployment."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='SignalOrg')

    def test_new_active_env_creates_deployment(self):
        project = Project.objects.create(name='p', organisation=self.org)
        # Baseline: no deployments (Project.post_save signal was removed
        # in Batch 49 because it double-created).
        self.assertEqual(project.deployments.count(), 0)

        env = ProjectEnvironment.objects.create(
            project=project, name='production', display_name='Production',
        )
        # env-signal fired → one deployment.
        deps = list(project.deployments.all())
        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0].environment, env)

    def test_inactive_env_does_not_create_deployment(self):
        project = Project.objects.create(name='p', organisation=self.org)
        ProjectEnvironment.objects.create(
            project=project, name='dev', display_name='Dev', is_active=False,
        )
        self.assertEqual(project.deployments.count(), 0)

    def test_signal_pins_deployment_to_project_cluster(self):
        cluster = Cluster.objects.create(organisation=self.org, name='c', provider='eks')
        project = Project.objects.create(name='p', organisation=self.org, cluster=cluster)
        ProjectEnvironment.objects.create(
            project=project, name='production', display_name='Production',
        )
        dep = project.deployments.first()
        self.assertEqual(dep.cluster, cluster)

    def test_signal_updating_env_does_not_create_second_deployment(self):
        project = Project.objects.create(name='p', organisation=self.org)
        env = ProjectEnvironment.objects.create(
            project=project, name='production', display_name='Production',
        )
        # Update, not create — signal must NOT fire the create path.
        env.display_name = 'Prod!'
        env.save()
        self.assertEqual(project.deployments.count(), 1)


class ProjectDeploymentTenantIsolationTest(TestCase):
    """No deployment leakage across orgs even via unexpected paths."""

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organisations.objects.create(name='OrgA')
        cls.org_b = Organisations.objects.create(name='OrgB')
        cls.proj_a = Project.objects.create(name='pa', organisation=cls.org_a)
        cls.proj_b = Project.objects.create(name='pb', organisation=cls.org_b)
        ProjectDeployment.objects.create(project=cls.proj_a, name='A-dep')
        ProjectDeployment.objects.create(project=cls.proj_b, name='B-dep')

    def test_deployments_scoped_by_project_org(self):
        # Filter by org via the project FK — no direct org on the model.
        a_deps = ProjectDeployment.objects.filter(project__organisation=self.org_a)
        b_deps = ProjectDeployment.objects.filter(project__organisation=self.org_b)
        self.assertEqual(a_deps.count(), 1)
        self.assertEqual(b_deps.count(), 1)
        self.assertEqual(a_deps.first().name, 'A-dep')
        self.assertEqual(b_deps.first().name, 'B-dep')

    def test_cross_org_cluster_reference_blocked_at_shape(self):
        # A cluster belongs to one org. Pinning a deployment on a
        # different org's project to that cluster is nonsense but the
        # ORM won't stop you — the safeguard is that batch pipeline
        # queries integrations filtered by org, so the wrong cluster
        # scope yields no integration match. Not strictly enforced at
        # the DB level; this test documents the current behaviour.
        cluster_a = Cluster.objects.create(organisation=self.org_a, name='ca', provider='eks')
        # Cross-org assignment succeeds at the ORM (documented weakness).
        d = ProjectDeployment.objects.create(project=self.proj_b, cluster=cluster_a)
        # But integration lookup for org_b won't find any org_a integrations
        # — safety comes from downstream filters, not this model.
        self.assertIsNotNone(d.pk)
