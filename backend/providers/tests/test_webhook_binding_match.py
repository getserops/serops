"""A signed webhook is applied only to the repository or job of its binding.

Phase 3 review, SC-17: the signature proves the request is the binding's
webhook, not that the repository in the body is the binding's. With a GitHub
organisation webhook, one Jenkins notifier for many jobs or a Bitbucket
workspace hook, every other repository's runs and commits were filed under
the bound service and fed into its root-cause analyses.
"""
import hashlib
import hmac
import json
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from Organisations.models import Organisations
from Projects.models import CICDBinding, Project, ProjectService, SCMBinding
from providers.models import CodeChange, Pipeline, ProviderIntegration
from providers.payload_identity import (
    azure_pipeline_identifiers, jenkins_job_matches, matches, repository_identifiers,
)
from providers.webhook_service import WebhookService


def _binding(provider_type, pipeline_id, secret='s3cret'):
    org = Organisations.objects.create(name=f'Org-{provider_type}')
    project = Project.objects.create(name='shop', organisation=org)
    service = ProjectService.objects.create(project=project, name='api', service_type='application')
    integration = ProviderIntegration.objects.create(
        organisation=org, provider_type=provider_type, name=provider_type)
    return CICDBinding.objects.create(
        project_service=service, integration=integration, pipeline_id=pipeline_id,
        is_active=True, webhook_secret=secret)


class GitHubRunForAnotherRepositoryTest(TestCase):

    def setUp(self):
        self.binding = _binding('github', 'acme/shop', secret='gh-secret')

    def _post(self, full_name):
        body = json.dumps({
            'action': 'completed',
            'workflow_run': {'id': 77, 'name': 'deploy', 'conclusion': 'success',
                             'head_branch': 'main', 'head_sha': 'abc123def456'},
            'repository': {'id': 42, 'full_name': full_name},
        }).encode()
        signature = 'sha256=' + hmac.new(b'gh-secret', body, hashlib.sha256).hexdigest()
        with patch('providers.utils.store_cicd_logs_generic'):
            return APIClient().post(
                f'/api/webhooks/github/{self.binding.pk}/', data=body, content_type='application/json',
                HTTP_X_HUB_SIGNATURE_256=signature, HTTP_X_GITHUB_EVENT='workflow_run')

    def test_a_run_of_another_repository_is_ignored(self):
        response = self._post('acme/billing')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['ignored'])
        self.assertFalse(Pipeline.objects.exists())

    def test_a_run_of_the_bound_repository_is_recorded(self):
        response = self._post('Acme/Shop')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn('ignored', response.json())
        self.assertEqual(Pipeline.objects.count(), 1)


class JenkinsBuildOfAnotherJobTest(TestCase):

    def setUp(self):
        self.binding = _binding('jenkins', 'shop/payments', secret='jk-secret')

    def _post(self, url):
        with patch('providers.utils.store_cicd_logs_generic'):
            return APIClient().post(
                f'/api/webhooks/jenkins/{self.binding.pk}/', format='json', HTTP_X_JENKINS_TOKEN='jk-secret',
                data={'name': 'payments', 'url': url,
                      'build': {'number': 12, 'phase': 'COMPLETED', 'status': 'SUCCESS',
                                'scm': {'branch': 'main', 'commit': 'abc123'}}})

    def test_a_build_of_a_job_with_the_same_name_in_another_folder_is_ignored(self):
        response = self._post('job/billing/job/payments/')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['ignored'])
        self.assertFalse(Pipeline.objects.exists())

    def test_a_build_of_the_bound_job_is_recorded(self):
        response = self._post('job/shop/job/payments/')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Pipeline.objects.count(), 1)


class SCMPushForAnotherRepositoryTest(TestCase):

    def setUp(self):
        org = Organisations.objects.create(name='SCM Org')
        project = Project.objects.create(name='shop', organisation=org)
        service = ProjectService.objects.create(project=project, name='api')
        integration = ProviderIntegration.objects.create(organisation=org, name='gh', provider_type='github')
        self.binding = SCMBinding.objects.create(
            project_service=service, integration=integration,
            repository_id='acme/shop', repository_name='shop')

    def _push(self, full_name):
        return WebhookService.process_scm_payload(self.binding, {
            'ref': 'refs/heads/main',
            'repository': {'id': 9, 'full_name': full_name},
            'commits': [{'id': 'f' * 40, 'message': 'feat: x', 'timestamp': '2026-11-16T10:00:00Z',
                         'author': {'name': 'bob', 'email': 'bob@example.com'}, 'url': 'https://x'}],
        }, 'push')

    def test_commits_of_another_repository_are_not_saved_as_the_bindings(self):
        result = self._push('acme/billing')

        self.assertTrue(result['ignored'])
        self.assertFalse(CodeChange.objects.exists())

    def test_commits_of_the_bound_repository_are_processed(self):
        result = self._push('acme/shop')

        self.assertNotIn('ignored', result)


class PayloadIdentityTest(SimpleTestCase):

    def test_repository_identifiers_cover_each_provider(self):
        self.assertIn('acme/shop', repository_identifiers({'repository': {'full_name': 'Acme/Shop'}}))
        self.assertIn('42', repository_identifiers({'project': {'id': 42}}))
        self.assertIn('ws/repo', repository_identifiers({'repository': {'full_name': 'ws/repo',
                                                                        'uuid': '{a-b}'}}))
        self.assertIn('a-b', repository_identifiers({'repository': {'uuid': '{a-b}'}}))
        self.assertIn('proj/repo', repository_identifiers(
            {'resource': {'repository': {'id': 'g1', 'name': 'repo', 'project': {'name': 'Proj'}}}}))

    def test_a_binding_or_payload_naming_nothing_is_let_through(self):
        self.assertTrue(matches('', {'acme/shop'}))
        self.assertTrue(matches('acme/shop', set()))
        self.assertFalse(matches('acme/shop', {'acme/billing'}))

    def test_azure_pipeline_identifiers(self):
        payload = {'resource': {'run': {'id': 3, 'pipeline': {'id': 7, 'name': 'payments-ci'}},
                                'repositories': [{'repository': {'fullName': 'org/payments'}}]}}
        ids = azure_pipeline_identifiers(payload)
        self.assertTrue({'7', 'payments-ci', 'org/payments'} <= ids)
        self.assertFalse(matches('billing-ci', ids))

    def test_jenkins_job_paths(self):
        self.assertTrue(jenkins_job_matches('shop/payments', {'url': 'job/shop/job/payments/'}))
        self.assertTrue(jenkins_job_matches('job/shop/job/payments', {'url': 'job/shop/job/payments/job/main/'}))
        self.assertFalse(jenkins_job_matches('shop/payments', {'url': 'job/billing/job/payments/'}))
        # Only the short name: accepted when it is the job's last segment.
        self.assertTrue(jenkins_job_matches('shop/payments', {'name': 'payments'}))
        self.assertFalse(jenkins_job_matches('shop/payments', {'name': 'billing'}))
