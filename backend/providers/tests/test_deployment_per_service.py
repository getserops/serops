"""
A deploy that comes through a CI/CD binding belongs to that binding's service.

Before, a deployment reached a project only through code_change -> repository
-> SCM binding, so an Argo CD, Flux or Jenkins deploy of a service without an
SCM binding belonged to no project: Overview's Recent Deployments never listed
it and Investigate's "Since the last deploy" stayed disabled (journey suite,
findings B27/B28).
"""

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from Data.investigation_views import _last_deploy_at
from providers.models import Deployment, Pipeline
from providers.tests.test_deployment_webhook import DeploymentWebhookTestBase


class DeploymentPerServiceTest(DeploymentWebhookTestBase):

    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_user(
            username='dps-admin', email='dps@test.com', password='Test123!',
            organisation=self.org, role='admin', is_active=True)
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def recent(self):
        response = self.api.get('/api/data/analytics/deployments/')
        self.assertEqual(response.status_code, 200)
        return {s['service_name']: s for s in response.data['services']}

    def test_gitops_deploy_is_recorded_for_the_bindings_service(self):
        response = self.client.post(self.url, self._payload(), format='json')
        self.assertEqual(response.status_code, 200, response.data)
        deployment = Deployment.objects.get(pk=response.data['deployment_id'])
        self.assertEqual(deployment.project_service, self.service)

    def test_gitops_deploy_shows_in_recent_deployments(self):
        """The service has no SCM binding, only the deploy binding."""
        self.client.post(self.url, self._payload(), format='json')
        api = self.recent()['api']
        self.assertEqual(api['latest_pipeline']['environment'], 'production')
        self.assertEqual(api['latest_pipeline']['id'], 'abc123de')
        self.assertEqual(api['provider'], 'argocd')

    def test_gitops_deploy_is_the_projects_last_deploy(self):
        self.assertIsNone(_last_deploy_at(self.org, self.project))
        self.client.post(self.url, self._payload(), format='json')
        self.assertIsNotNone(_last_deploy_at(self.org, self.project))

    def test_binding_pipeline_shows_without_scm_binding(self):
        """A Jenkins build reported through the service's binding."""
        Pipeline.objects.create(
            organisation=self.org, cicd_provider='jenkins', pipeline_id='payments-deploy#7',
            status='failed', environment='production',
            provider_metadata={'serops_project_id': self.project.id, 'service_name': 'api'})
        api = self.recent()['api']
        self.assertEqual(api['latest_pipeline']['status'], 'failed')
        self.assertEqual(api['provider'], 'jenkins')
        self.assertIsNotNone(_last_deploy_at(self.org, self.project))
