"""
Argo CD and Flux are integration types of their own (journey suite, B22).

GitOps webhooks need a CI/CD binding, and a binding hung off a GitLab,
GitHub, Bitbucket, Azure DevOps or Jenkins integration: a team deploying with
Argo CD or Flux but building elsewhere could not set it up. The new types are
receive-only: no credentials, nothing to verify against.
"""

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from Organisations.models import Organisations
from Projects.models import CICDBinding, Project, ProjectService
from providers.models import Deployment, ProviderIntegration


class GitOpsIntegrationTest(APITestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='GitOps Org')
        self.admin = get_user_model().objects.create_user(
            username='gitops-admin', email='go@test.com', password='Test123!',
            organisation=self.org, role='admin', is_active=True)
        self.project = Project.objects.create(name='shop', organisation=self.org)
        self.service = ProjectService.objects.create(
            project=self.project, name='payments', service_type='application')
        self.client.force_authenticate(self.admin)

    def add(self, provider_type):
        response = self.client.post('/api/providers/integrations/', {
            'provider_type': provider_type, 'name': f'{provider_type} prod'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return ProviderIntegration.objects.get(pk=response.data['id'])

    def test_argocd_is_offered(self):
        codes = [t['code'] for t in self.client.get('/api/providers/integrations/provider-types/').data]
        self.assertIn('argocd', codes)
        self.assertIn('flux', codes)

    def test_added_without_credentials_and_verified(self):
        integration = self.add('argocd')
        self.assertEqual(integration.category, 'gitops')
        self.assertTrue(integration.is_verified)
        response = self.client.post(f'/api/providers/integrations/{integration.id}/verify/')
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post(f'/api/providers/integrations/{integration.id}/health-check/')
        self.assertEqual(response.status_code, 200, response.data)

    def test_binding_gives_the_argocd_webhook_url_and_secret(self):
        integration = self.add('argocd')
        response = self.client.post('/api/projects/cicd-bindings/', {
            'project_service': self.service.id, 'integration': integration.id,
            'binding_type': 'deploy', 'pipeline_id': 'payments'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        binding_id = response.data['id']
        setup = self.client.post(f'/api/projects/cicd-bindings/{binding_id}/setup-webhook/')
        self.assertEqual(setup.status_code, 200, setup.data)
        self.assertTrue(setup.data['webhook_url'].endswith(f'/api/providers/webhook/argocd/{binding_id}/'))
        self.assertTrue(setup.data['webhook_secret'])

        # Argo CD's notification, sent with the documented Bearer header.
        hook = APIClient()
        response = hook.post(
            f'/api/providers/webhook/argocd/{binding_id}/',
            {'app': {'metadata': {'name': 'payments', 'namespace': 'argocd'},
                     'spec': {'destination': {'namespace': 'production'}},
                     'status': {'sync': {'revision': 'a1b2c3d4e5f6a7b8'},
                                'operationState': {'phase': 'Succeeded'}}},
             'context': {}},
            format='json', HTTP_AUTHORIZATION=f"Bearer {setup.data['webhook_secret']}")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Deployment.objects.get().project_service, self.service)

    def test_nothing_to_sync(self):
        binding = CICDBinding.objects.create(
            project_service=self.service, integration=self.add('flux'), binding_type='deploy')
        response = self.client.post(f'/api/projects/cicd-bindings/{binding.id}/sync/')
        self.assertEqual(response.status_code, 400)
        self.assertIn('nothing to sync', response.data['error'])
