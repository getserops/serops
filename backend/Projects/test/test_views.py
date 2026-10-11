"""
Tests for Projects app views: Project CRUD, ProjectService CRUD,
SCMBindingViewSet, CICDBindingViewSet, and SCMWebhookReceiverView.

Covers all view-level gaps — previously 0 view tests existed.
"""

import hmac
import hashlib
from unittest.mock import patch, MagicMock

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from Organisations.models import Organisations
from Users.models import User
from Projects.models import (
    Project, ProjectService, ProjectEnvironment,
    SCMBinding, CICDBinding,
)
from providers.models import ProviderIntegration


class ProjectViewTestBase(APITestCase):
    """Shared setUp for Project view tests."""

    def setUp(self):
        self.org = Organisations.objects.create(
            name='Proj Org', website='https://proj.com',
        )
        self.other_org = Organisations.objects.create(
            name='Other Org', website='https://other.com',
        )
        self.admin = User.objects.create_user(
            username='projadmin', email='pa@test.com',
            password='Test123!', organisation=self.org,
            role='admin', is_active=True,
        )
        self.viewer = User.objects.create_user(
            username='projviewer', email='pv@test.com',
            password='Test123!', organisation=self.org,
            role='viewer', is_active=True,
        )
        self.other_admin = User.objects.create_user(
            username='otheradmin', email='oa@test.com',
            password='Test123!', organisation=self.other_org,
            role='admin', is_active=True,
        )

        self.project = Project.objects.create(
            name='test-project', organisation=self.org,
        )
        self.other_project = Project.objects.create(
            name='other-project', organisation=self.other_org,
        )
        ProjectEnvironment.objects.create(
            project=self.project, name='production', display_name='Production',
        )

        self.integration = ProviderIntegration.objects.create(
            name='Org GitLab', provider_type='gitlab',
            category='devops', organisation=self.org,
        )
        self.other_integration = ProviderIntegration.objects.create(
            name='Other GitLab', provider_type='gitlab',
            category='devops', organisation=self.other_org,
        )

    def _auth(self, user):
        self.client.force_authenticate(user=user)


# ---------------------------------------------------------------------------
# Project CRUD
# ---------------------------------------------------------------------------

class TestProjectListView(ProjectViewTestBase):
    """Tests for GET/POST /api/projects/"""

    def setUp(self):
        super().setUp()
        self.url = reverse('project-list')

    def test_list_projects(self):
        self._auth(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [p['name'] for p in response.data]
        self.assertIn('test-project', names)

    def test_list_projects_org_isolation(self):
        """Cannot see other org's projects."""
        self._auth(self.admin)
        response = self.client.get(self.url)
        names = [p['name'] for p in response.data]
        self.assertNotIn('other-project', names)

    @patch('Projects.views.threading.Thread')
    def test_create_project(self, mock_thread):
        """Project + default environments created."""
        mock_thread.return_value = MagicMock()
        self._auth(self.admin)
        response = self.client.post(self.url, {
            'name': 'new-project', 'description': 'A new project',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Project.objects.filter(name='new-project', organisation=self.org).exists())

    @patch('Projects.views.threading.Thread')
    def test_create_project_custom_envs(self, mock_thread):
        """Custom environments array respected."""
        mock_thread.return_value = MagicMock()
        self._auth(self.admin)
        response = self.client.post(self.url, {
            'name': 'env-project',
            'environments': [
                {'name': 'dev', 'display_name': 'Development'},
                {'name': 'staging', 'display_name': 'Staging'},
            ],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        proj = Project.objects.get(name='env-project')
        env_names = list(proj.environments.values_list('name', flat=True))
        self.assertIn('dev', env_names)
        self.assertIn('staging', env_names)

    def test_create_project_duplicate_name(self):
        """unique_together (name, org) enforced."""
        self._auth(self.admin)
        response = self.client.post(self.url, {
            'name': 'test-project',
        }, format='json')
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_409_CONFLICT])

    def test_create_project_viewer_denied(self):
        """ReadOnlyForViewer blocks POST."""
        self._auth(self.viewer)
        response = self.client.post(self.url, {'name': 'no-way'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TestProjectDetailView(ProjectViewTestBase):
    """Tests for GET/PUT/DELETE /api/projects/<pk>/"""

    def test_get_project(self):
        self._auth(self.admin)
        url = reverse('project-detail', kwargs={'pk': self.project.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'test-project')

    def test_update_project(self):
        self._auth(self.admin)
        url = reverse('project-detail', kwargs={'pk': self.project.pk})
        response = self.client.put(url, {
            'name': 'updated-project',
            'description': 'Updated desc',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, 'updated-project')

    def test_delete_project(self):
        self._auth(self.admin)
        proj = Project.objects.create(name='to-delete', organisation=self.org)
        url = reverse('project-detail', kwargs={'pk': proj.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Project.objects.filter(pk=proj.pk).exists())

    def test_cross_org_denied(self):
        """Other org's project not accessible."""
        self._auth(self.admin)
        url = reverse('project-detail', kwargs={'pk': self.other_project.pk})
        response = self.client.get(url)
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_viewer_cannot_modify(self):
        """ReadOnlyForViewer blocks PUT."""
        self._auth(self.viewer)
        url = reverse('project-detail', kwargs={'pk': self.project.pk})
        response = self.client.put(url, {'name': 'nope'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_project_not_found(self):
        self._auth(self.admin)
        url = reverse('project-detail', kwargs={'pk': 99999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# Project Services
# ---------------------------------------------------------------------------

class TestProjectServiceView(ProjectViewTestBase):
    """Tests for GET/POST /api/projects/<project_id>/services/"""

    def setUp(self):
        super().setUp()
        self.url = reverse('project-service-create', kwargs={'project_id': self.project.pk})

    def test_list_services(self):
        self._auth(self.admin)
        ProjectService.objects.create(
            project=self.project, name='svc-1', service_type='application',
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_service(self):
        self._auth(self.admin)
        response = self.client.post(self.url, {
            'name': 'new-service', 'service_type': 'application',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch('Projects.views.SCMBinding.objects.create')
    def test_create_service_with_integration(self, mock_scm_create):
        """Integration + repository linked via SCMBinding."""
        mock_scm_create.return_value = MagicMock()
        self._auth(self.admin)
        response = self.client.post(self.url, {
            'name': 'scm-service',
            'service_type': 'application',
            'integration_id': self.integration.id,
            'repository_id': 'repo-123',
            'repository_name': 'my/repo',
            'default_branch': 'main',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_scm_create.assert_called_once()

    def test_create_service_viewer_denied(self):
        self._auth(self.viewer)
        response = self.client.post(self.url, {
            'name': 'nope', 'service_type': 'application',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_project_not_found(self):
        self._auth(self.admin)
        url = reverse('project-service-create', kwargs={'project_id': 99999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cross_org_project_denied(self):
        """Other org's project."""
        self._auth(self.admin)
        url = reverse('project-service-create', kwargs={'project_id': self.other_project.pk})
        response = self.client.get(url)
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])


class TestProjectServiceDetailView(ProjectViewTestBase):
    """Tests for GET/DELETE /api/projects/services/<pk>/"""

    def setUp(self):
        super().setUp()
        self.service = ProjectService.objects.create(
            project=self.project, name='detail-svc', service_type='application',
        )
        # Extra service keeps gitlab_project=None filter alive after deletion
        self.other_service = ProjectService.objects.create(
            project=self.project, name='keep-svc', service_type='application',
        )

    def test_get_service_detail(self):
        self._auth(self.admin)
        url = reverse('project-service-detail', kwargs={'pk': self.service.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_delete_service(self):
        self._auth(self.admin)
        url = reverse('project-service-detail', kwargs={'pk': self.service.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ProjectService.objects.filter(pk=self.service.pk).exists())

    def test_service_not_found(self):
        self._auth(self.admin)
        url = reverse('project-service-detail', kwargs={'pk': 99999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_viewer_cannot_delete(self):
        self._auth(self.viewer)
        url = reverse('project-service-detail', kwargs={'pk': self.service.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# SCMBinding ViewSet
# ---------------------------------------------------------------------------

class TestSCMBindingViewSet(ProjectViewTestBase):
    """Tests for SCMBinding CRUD and custom actions."""

    def setUp(self):
        super().setUp()
        self.service = ProjectService.objects.create(
            project=self.project, name='scm-svc', service_type='application',
        )
        self.binding = SCMBinding.objects.create(
            project_service=self.service, integration=self.integration,
            repository_id='repo-1', repository_name='org/repo',
            default_branch='main', webhook_secret='test-secret',
        )

    def test_list_bindings(self):
        self._auth(self.admin)
        url = reverse('scm-binding-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_binding(self):
        self._auth(self.admin)
        svc2 = ProjectService.objects.create(
            project=self.project, name='scm-svc-2', service_type='application',
        )
        url = reverse('scm-binding-list')
        response = self.client.post(url, {
            'project_service': svc2.pk,
            'integration': self.integration.pk,
            'repository_id': 'repo-2',
            'repository_name': 'org/repo2',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_binding_cross_org_integration(self):
        """Another organisation's integration is rejected.

        This test used to accept 201 *or* 400 and say so in a comment: binding
        a service to another organisation's integration — and with it that
        organisation's SCM credentials — was allowed.
        """
        self._auth(self.admin)
        svc3 = ProjectService.objects.create(
            project=self.project, name='scm-svc-3', service_type='application',
        )
        response = self.client.post(reverse('scm-binding-list'), {
            'project_service': svc3.pk,
            'integration': self.other_integration.pk,
            'repository_id': 'repo-x',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('integration', response.json())
        self.assertFalse(SCMBinding.objects.filter(project_service=svc3).exists())

    def test_update_binding_onto_foreign_integration_is_400(self):
        """PATCH had no organisation check at all."""
        self._auth(self.admin)
        response = self.client.patch(
            reverse('scm-binding-detail', kwargs={'pk': self.binding.pk}),
            {'integration': self.other_integration.pk}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.binding.refresh_from_db()
        self.assertEqual(self.binding.integration_id, self.integration.pk)

    def test_update_binding_onto_foreign_service_is_400(self):
        """Moving a binding onto another organisation's service plants it in
        their tenant; PATCH used to allow it."""
        self._auth(self.admin)
        foreign_svc = ProjectService.objects.create(
            project=self.other_project, name='foreign-target', service_type='application',
        )
        response = self.client.patch(
            reverse('scm-binding-detail', kwargs={'pk': self.binding.pk}),
            {'project_service': foreign_svc.pk}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.binding.refresh_from_db()
        self.assertEqual(self.binding.project_service_id, self.service.pk)

    def test_foreign_ids_get_the_same_error_as_missing_ones(self):
        """No existence oracle: another organisation's integration id fails
        exactly like an id that does not exist anywhere."""
        self._auth(self.admin)
        svc = ProjectService.objects.create(
            project=self.project, name='scm-oracle', service_type='application',
        )
        def attempt(integration_id):
            return self.client.post(reverse('scm-binding-list'), {
                'project_service': svc.pk, 'integration': integration_id,
                'repository_id': 'r',
            }, format='json').json()['integration']
        foreign = attempt(self.other_integration.pk)
        missing = attempt(999999)
        self.assertEqual(
            [m.replace(str(self.other_integration.pk), 'N') for m in foreign],
            [m.replace('999999', 'N') for m in missing],
        )

    def test_create_binding_for_other_orgs_service_is_400(self):
        """A service from another organisation is rejected as a 400.

        perform_create raised serializers.ValidationError without importing
        `serializers`, so this path raised NameError: the write was still
        blocked, but as a 500 with a traceback in the logs.
        """
        self._auth(self.admin)
        foreign_svc = ProjectService.objects.create(
            project=self.other_project, name='foreign-svc', service_type='application',
        )
        response = self.client.post(reverse('scm-binding-list'), {
            'project_service': foreign_svc.pk,
            'integration': self.integration.pk,
            'repository_id': 'repo-foreign',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('project_service', response.json())
        self.assertFalse(SCMBinding.objects.filter(project_service=foreign_svc).exists())

    def test_retrieve_binding(self):
        self._auth(self.admin)
        url = reverse('scm-binding-detail', kwargs={'pk': self.binding.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_update_binding(self):
        self._auth(self.admin)
        url = reverse('scm-binding-detail', kwargs={'pk': self.binding.pk})
        response = self.client.put(url, {
            'project_service': self.service.pk,
            'integration': self.integration.pk,
            'repository_id': 'repo-1',
            'default_branch': 'develop',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.binding.refresh_from_db()
        self.assertEqual(self.binding.default_branch, 'develop')

    def test_delete_binding(self):
        self._auth(self.admin)
        url = reverse('scm-binding-detail', kwargs={'pk': self.binding.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    @patch.object(SCMBinding, 'get_provider')
    def test_sync_action(self, mock_get_provider):
        """Sync fetches commits since last_sync_at."""
        mock_provider = MagicMock()
        mock_provider.get_commits.return_value = []
        mock_get_provider.return_value = mock_provider
        self._auth(self.admin)
        url = reverse('scm-binding-sync', kwargs={'pk': self.binding.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('Projects.views.WebhookService.setup_scm_webhook')
    def test_setup_webhook_action(self, mock_setup):
        """setup-webhook sets webhook_configured=True."""
        mock_setup.return_value = {'success': True, 'webhook_id': 'wh-123'}
        self._auth(self.admin)
        url = reverse('scm-binding-setup-webhook', kwargs={'pk': self.binding.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('providers.services.AutoLinkService')
    def test_auto_link_suggestions(self, mock_auto_link_cls):
        """Returns detected CI/CD pipelines."""
        mock_service = MagicMock()
        mock_service.can_auto_link.return_value = False
        mock_auto_link_cls.return_value = mock_service
        self._auth(self.admin)
        url = reverse('scm-binding-auto-link-suggestions', kwargs={'pk': self.binding.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_cannot_create(self):
        self._auth(self.viewer)
        url = reverse('scm-binding-list')
        response = self.client.post(url, {
            'project_service': self.service.pk,
            'integration': self.integration.pk,
            'repository_id': 'nope',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# CICDBinding ViewSet
# ---------------------------------------------------------------------------

class TestCICDBindingViewSet(ProjectViewTestBase):
    """Tests for CICDBinding CRUD and custom actions."""

    def setUp(self):
        super().setUp()
        self.service = ProjectService.objects.create(
            project=self.project, name='cicd-svc', service_type='application',
        )
        self.jenkins_integration = ProviderIntegration.objects.create(
            name='Org Jenkins', provider_type='jenkins',
            category='cicd', organisation=self.org,
        )
        self.binding = CICDBinding.objects.create(
            project_service=self.service, integration=self.integration,
            binding_type='build', pipeline_id='pipe-1',
            pipeline_name='Main Pipeline',
        )

    def test_list_bindings(self):
        self._auth(self.admin)
        url = reverse('cicd-binding-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_binding(self):
        self._auth(self.admin)
        url = reverse('cicd-binding-list')
        response = self.client.post(url, {
            'project_service': self.service.pk,
            'integration': self.integration.pk,
            'binding_type': 'deploy',
            'pipeline_id': 'pipe-2',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_binding_with_foreign_integration_is_400(self):
        self._auth(self.admin)
        response = self.client.post(reverse('cicd-binding-list'), {
            'project_service': self.service.pk,
            'integration': self.other_integration.pk,
            'binding_type': 'deploy',
            'pipeline_id': 'pipe-foreign-int',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('integration', response.json())
        self.assertFalse(CICDBinding.objects.filter(pipeline_id='pipe-foreign-int').exists())

    def test_update_binding_onto_foreign_integration_or_service_is_400(self):
        self._auth(self.admin)
        url = reverse('cicd-binding-detail', kwargs={'pk': self.binding.pk})
        foreign_svc = ProjectService.objects.create(
            project=self.other_project, name='foreign-cicd-target', service_type='application',
        )
        for payload in ({'integration': self.other_integration.pk},
                        {'project_service': foreign_svc.pk}):
            response = self.client.patch(url, payload, format='json')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, payload)
        self.binding.refresh_from_db()
        self.assertEqual(self.binding.integration_id, self.integration.pk)
        self.assertEqual(self.binding.project_service_id, self.service.pk)

    def test_create_binding_for_other_orgs_service_is_400(self):
        """Same cross-organisation check as SCM bindings, same missing import."""
        self._auth(self.admin)
        foreign_svc = ProjectService.objects.create(
            project=self.other_project, name='foreign-cicd-svc', service_type='application',
        )
        response = self.client.post(reverse('cicd-binding-list'), {
            'project_service': foreign_svc.pk,
            'integration': self.integration.pk,
            'binding_type': 'deploy',
            'pipeline_id': 'pipe-foreign',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('project_service', response.json())
        self.assertFalse(CICDBinding.objects.filter(project_service=foreign_svc).exists())

    @patch('providers.scm_providers.CICD_PROVIDERS', ['jenkins'])
    @patch.object(CICDBinding, 'get_provider')
    def test_sync_action(self, mock_get_provider):
        """Sync fetches builds from Jenkins provider."""
        mock_provider = MagicMock()
        mock_provider.list_projects.return_value = []
        mock_get_provider.return_value = mock_provider
        # Use Jenkins binding for CICD sync (hits CICD_PROVIDERS path)
        jenkins_binding = CICDBinding.objects.create(
            project_service=self.service, integration=self.jenkins_integration,
            binding_type='build', pipeline_id='jenkins-sync',
        )
        self._auth(self.admin)
        url = reverse('cicd-binding-sync', kwargs={'pk': jenkins_binding.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('providers.scm_providers.CICD_PROVIDERS', ['jenkins'])
    @patch.object(CICDBinding, 'get_provider')
    def test_trigger_action_jenkins(self, mock_get_provider):
        """Trigger build for Jenkins binding."""
        jenkins_binding = CICDBinding.objects.create(
            project_service=self.service, integration=self.jenkins_integration,
            binding_type='build', pipeline_id='jenkins-1',
        )
        mock_provider = MagicMock()
        mock_provider.trigger_build.return_value = {'success': True, 'queue_url': '/queue/123'}
        mock_get_provider.return_value = mock_provider
        self._auth(self.admin)
        url = reverse('cicd-binding-trigger', kwargs={'pk': jenkins_binding.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('providers.scm_providers.CICD_PROVIDERS', ['jenkins'])
    def test_trigger_action_non_jenkins(self):
        """Non-Jenkins provider rejected for trigger."""
        self._auth(self.admin)
        url = reverse('cicd-binding-trigger', kwargs={'pk': self.binding.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_filter_by_binding_type(self):
        self._auth(self.admin)
        url = reverse('cicd-binding-list')
        response = self.client.get(url, {'binding_type': 'build'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_cannot_create(self):
        self._auth(self.viewer)
        url = reverse('cicd-binding-list')
        response = self.client.post(url, {
            'project_service': self.service.pk,
            'integration': self.integration.pk,
            'binding_type': 'build',
            'pipeline_id': 'nope',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# SCMWebhookReceiverView
# ---------------------------------------------------------------------------

class TestSCMWebhookReceiverView(ProjectViewTestBase):
    """Tests for POST /api/webhooks/scm/<binding_id>/ (AllowAny)."""

    def setUp(self):
        super().setUp()
        self.service = ProjectService.objects.create(
            project=self.project, name='wh-svc', service_type='application',
        )
        self.binding = SCMBinding.objects.create(
            project_service=self.service, integration=self.integration,
            repository_id='repo-wh', webhook_secret='mysecret',
        )
        self.url = reverse('scm-webhook', kwargs={'binding_id': self.binding.pk})
        # No auth needed — AllowAny
        self.client.force_authenticate(user=None)

    @patch('Projects.views.WebhookService.process_scm_payload')
    def test_gitlab_webhook_valid_token(self, mock_process):
        """X-Gitlab-Token matches webhook_secret."""
        mock_process.return_value = {'success': True, 'commits_processed': 1}
        response = self.client.post(
            self.url, {'ref': 'refs/heads/main', 'commits': []},
            format='json', HTTP_X_GITLAB_TOKEN='mysecret',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_gitlab_webhook_invalid_token(self):
        """Wrong token rejected."""
        response = self.client.post(
            self.url, {'ref': 'refs/heads/main'},
            format='json', HTTP_X_GITLAB_TOKEN='wrongsecret',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch('Projects.views.WebhookService.process_scm_payload')
    def test_github_webhook_valid_signature(self, mock_process):
        """X-Hub-Signature-256 HMAC matches."""
        mock_process.return_value = {'success': True, 'commits_processed': 1}
        body = b'{"ref": "refs/heads/main"}'
        sig = 'sha256=' + hmac.new(
            b'mysecret', body, hashlib.sha256
        ).hexdigest()
        response = self.client.post(
            self.url, body, content_type='application/json',
            HTTP_X_HUB_SIGNATURE_256=sig,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_github_webhook_invalid_signature(self):
        """Wrong HMAC rejected."""
        response = self.client.post(
            self.url, b'{"ref": "refs/heads/main"}',
            content_type='application/json',
            HTTP_X_HUB_SIGNATURE_256='sha256=invalid',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_webhook_binding_not_found(self):
        """Invalid binding_id returns 404."""
        url = reverse('scm-webhook', kwargs={'binding_id': 99999})
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
