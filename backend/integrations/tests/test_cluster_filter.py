"""Tests for the cluster picker filter path (Item #19).

Verifies:
* Batches list filters by ?cluster=<id> via Project.cluster.
* Issues list filters by ?cluster=<id>.
* Malformed cluster id is silently ignored, not 500.
* Clusters/<id>/workloads/ returns projects + services and enforces
  org scoping.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from Data.models import AIAnalyzedBatch, Issue
from integrations.models import Cluster
from Organisations.models import Organisations
from Projects.models import Project, ProjectService

User = get_user_model()


class ClusterFilterTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='FilterOrg')
        cls.user = User.objects.create_user(
            username='fu', email='fu@t.com', password='p',
            organisation=cls.org, role='user', is_active=True,
        )
        cls.c1 = Cluster.objects.create(organisation=cls.org, name='prod-eks', provider='eks')
        cls.c2 = Cluster.objects.create(organisation=cls.org, name='staging-gke', provider='gke')

        cls.proj_a = Project.objects.create(
            organisation=cls.org, name='proj-a', cluster=cls.c1,
        )
        cls.proj_b = Project.objects.create(
            organisation=cls.org, name='proj-b', cluster=cls.c2,
        )
        cls.proj_c = Project.objects.create(
            organisation=cls.org, name='proj-c',   # no cluster
        )

        cls.batch_a = AIAnalyzedBatch.objects.create(
            batch_id='b_a', organisation=cls.org, project=cls.proj_a,
        )
        cls.batch_b = AIAnalyzedBatch.objects.create(
            batch_id='b_b', organisation=cls.org, project=cls.proj_b,
        )
        cls.batch_c = AIAnalyzedBatch.objects.create(
            batch_id='b_c', organisation=cls.org, project=cls.proj_c,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_batches_no_filter_returns_all(self):
        response = self.client.get('/api/data/batches')
        self.assertEqual(response.status_code, 200)
        ids = {b['batch_id'] for b in response.json()['results']}
        self.assertEqual(ids, {'b_a', 'b_b', 'b_c'})

    def test_batches_cluster_filter(self):
        response = self.client.get(f'/api/data/batches?cluster={self.c1.pk}')
        self.assertEqual(response.status_code, 200)
        ids = {b['batch_id'] for b in response.json()['results']}
        self.assertEqual(ids, {'b_a'})

    def test_batches_other_cluster(self):
        response = self.client.get(f'/api/data/batches?cluster={self.c2.pk}')
        ids = {b['batch_id'] for b in response.json()['results']}
        self.assertEqual(ids, {'b_b'})

    def test_batches_bad_cluster_id_ignored(self):
        response = self.client.get('/api/data/batches?cluster=not-a-number')
        self.assertEqual(response.status_code, 200)
        # Silent-drop the bad filter — returns all instead of 500.
        ids = {b['batch_id'] for b in response.json()['results']}
        self.assertEqual(ids, {'b_a', 'b_b', 'b_c'})

    def test_batches_unknown_cluster_id_returns_empty(self):
        response = self.client.get('/api/data/batches?cluster=99999')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'], [])

    def test_issues_cluster_filter(self):
        # Two issues in different clusters — filter picks the right one.
        Issue.objects.create(
            batch=self.batch_a, organisation=self.org, severity='high',
            description='in-a', component='api', issue_type='error', fingerprint='fp-a',
        )
        Issue.objects.create(
            batch=self.batch_b, organisation=self.org, severity='high',
            description='in-b', component='api', issue_type='error', fingerprint='fp-b',
        )
        response = self.client.get(f'/api/data/issues/?cluster={self.c1.pk}')
        self.assertEqual(response.status_code, 200)
        descriptions = {i['description'] for i in response.json().get('results', [])}
        self.assertEqual(descriptions, {'in-a'})


class ClusterWorkloadsEndpointTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='WorkOrg')
        self.other_org = Organisations.objects.create(name='ForeignOrg')
        self.user = User.objects.create_user(
            username='wu', email='w@t.com', password='p',
            organisation=self.org, role='user', is_active=True,
        )
        self.cluster = Cluster.objects.create(
            organisation=self.org, name='w-eks', provider='eks',
        )
        self.foreign_cluster = Cluster.objects.create(
            organisation=self.other_org, name='foreign-eks', provider='eks',
        )
        self.proj = Project.objects.create(
            organisation=self.org, name='billing', cluster=self.cluster,
        )
        ProjectService.objects.create(
            project=self.proj, name='billing-api', service_type='application',
        )
        ProjectService.objects.create(
            project=self.proj, name='billing-db', service_type='infrastructure',
            subtype='database',
        )
        self.client = APIClient()

    def test_requires_auth(self):
        response = self.client.get(f'/api/integrations/clusters/{self.cluster.pk}/workloads/')
        self.assertIn(response.status_code, (401, 403))

    def test_returns_projects_and_services(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/integrations/clusters/{self.cluster.pk}/workloads/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['cluster']['id'], self.cluster.pk)
        self.assertEqual(len(body['projects']), 1)
        proj = body['projects'][0]
        self.assertEqual(proj['name'], 'billing')
        service_names = sorted(s['name'] for s in proj['services'])
        self.assertEqual(service_names, ['billing-api', 'billing-db'])

    def test_cross_org_404(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/integrations/clusters/{self.foreign_cluster.pk}/workloads/')
        self.assertEqual(response.status_code, 404)

    def test_empty_cluster_returns_empty_projects_list(self):
        empty = Cluster.objects.create(organisation=self.org, name='empty', provider='eks')
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/integrations/clusters/{empty.pk}/workloads/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['projects'], [])
