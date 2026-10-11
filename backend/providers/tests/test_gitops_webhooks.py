"""Tests for ArgoCD + Flux native webhook translators (Items #15 + #16).

Both handlers subclass ``GenericDeploymentWebhookHandler`` so the
auth / HMAC / rate-limit / persistence paths are already covered by
``test_deployment_webhook.py``. These tests focus on the payload
translation layer that turns vendor-native shapes into the canonical
``{commit_sha, environment, ...}`` dict.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from Organisations.models import Organisations
from Projects.models import CICDBinding, Project, ProjectService
from providers.models import Deployment, ProviderIntegration


class GitopsWebhookBase(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='GitopsOrg')
        self.project = Project.objects.create(name='gops-proj', organisation=self.org)
        self.service = ProjectService.objects.create(
            project=self.project, name='api', service_type='application',
        )
        self.integration = ProviderIntegration.objects.create(
            organisation=self.org, provider_type='github', name='gh-int',
        )
        self.binding = CICDBinding.objects.create(
            project_service=self.service, integration=self.integration,
            binding_type='deploy', is_active=True,
        )
        self.client = APIClient()


# ============================================================================
# ArgoCD
# ============================================================================


class ArgoCDWebhookTest(GitopsWebhookBase):

    def _url(self):
        return f'/api/providers/webhook/argocd/{self.binding.id}/'

    def _payload(self, **overrides):
        base = {
            'app': {
                'metadata': {
                    'name': 'checkout',
                    'namespace': 'production',
                },
                'spec': {'source': {'targetRevision': 'main'}},
                'status': {
                    'sync': {
                        'status': 'Synced',
                        'revision': 'abc123def456789',
                    },
                    'health': {'status': 'Healthy'},
                    'operationState': {
                        'phase': 'Succeeded',
                        'finishedAt': '2026-10-25T14:25:00Z',
                        'operation': {'initiatedBy': {'username': 'gitops-bot'}},
                    },
                },
            },
        }
        # Deep-merge overrides.
        for k, v in overrides.items():
            base[k] = v
        return base

    def test_successful_sync_creates_deployment(self):
        response = self.client.post(self._url(), self._payload(), format='json')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['commit_sha'], 'abc123def456789')
        self.assertEqual(body['environment'], 'production')
        self.assertEqual(Deployment.objects.count(), 1)
        dep = Deployment.objects.get()
        self.assertEqual(dep.deployed_by, 'gitops-bot')
        # Notes surface the argocd app name so the AI prompt has context.
        self.assertIn('argocd-app=checkout', dep.notes)

    def test_failed_operation_is_ignored(self):
        payload = self._payload()
        payload['app']['status']['operationState']['phase'] = 'Failed'
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Deployment.objects.count(), 0)

    def test_out_of_sync_is_ignored(self):
        payload = self._payload()
        payload['app']['status']['sync']['status'] = 'OutOfSync'
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Deployment.objects.count(), 0)

    def test_missing_revision_400(self):
        payload = self._payload()
        payload['app']['status']['sync']['revision'] = ''
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.status_code, 400)

    def test_missing_app_object_400(self):
        response = self.client.post(self._url(), {'foo': 'bar'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_env_from_annotation_wins_over_namespace(self):
        payload = self._payload()
        payload['app']['metadata']['annotations'] = {
            'serops.io/environment': 'staging',
        }
        payload['app']['metadata']['namespace'] = 'production'   # would win otherwise
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.json()['environment'], 'staging')

    def test_env_alias_prod_maps_to_production(self):
        payload = self._payload()
        payload['app']['metadata']['namespace'] = 'prod'
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.json()['environment'], 'production')

    def test_env_unknown_namespace_falls_back_to_production(self):
        payload = self._payload()
        payload['app']['metadata']['namespace'] = 'weird-team-namespace'
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.json()['environment'], 'production')

    def test_no_operation_state_still_records(self):
        """Some ArgoCD event templates omit operationState (health-only
        transitions). If sync is Synced and no phase is set, accept it."""
        payload = self._payload()
        payload['app']['status'].pop('operationState')
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.status_code, 200)

    def test_actor_defaults_to_argocd(self):
        payload = self._payload()
        payload['app']['status']['operationState']['operation'] = {}
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Deployment.objects.get().deployed_by, 'argocd')


# ============================================================================
# Flux
# ============================================================================


class FluxWebhookTest(GitopsWebhookBase):

    def _url(self):
        return f'/api/providers/webhook/flux/{self.binding.id}/'

    def _payload(self, **overrides):
        base = {
            'involvedObject': {
                'kind': 'Kustomization',
                'name': 'checkout',
                'namespace': 'production',
            },
            'severity': 'info',
            'reason': 'ReconciliationSucceeded',
            'message': 'Reconciliation finished in 2.1s',
            'metadata': {'revision': 'main@sha1:abc123def456789'},
            'timestamp': '2026-10-25T14:25:00Z',
            'reportingController': 'kustomize-controller',
        }
        base.update(overrides)
        return base

    def test_successful_reconciliation_creates_deployment(self):
        response = self.client.post(self._url(), self._payload(), format='json')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['commit_sha'], 'abc123def456789')
        self.assertEqual(body['environment'], 'production')
        dep = Deployment.objects.get()
        self.assertEqual(dep.deployed_by, 'kustomize-controller')
        self.assertIn('flux-kustomization=checkout', dep.notes)

    def test_error_severity_ignored(self):
        response = self.client.post(
            self._url(), self._payload(severity='error'), format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Deployment.objects.count(), 0)

    def test_non_success_reason_ignored(self):
        response = self.client.post(
            self._url(),
            self._payload(reason='ReconciliationFailed'),
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_revision_without_sha_400(self):
        response = self.client.post(
            self._url(),
            self._payload(metadata={'revision': 'main@sha1:'}),
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_revision_with_sha256_algo(self):
        """Newer Flux builds use sha256 prefix — must still parse."""
        response = self.client.post(
            self._url(),
            self._payload(metadata={'revision': 'main@sha256:abc123def456789'}),
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['commit_sha'], 'abc123def456789')

    def test_env_from_namespace(self):
        response = self.client.post(
            self._url(),
            self._payload(involvedObject={
                'kind': 'Kustomization', 'name': 'x', 'namespace': 'staging',
            }),
            format='json',
        )
        self.assertEqual(response.json()['environment'], 'staging')

    def test_env_alias_dev_maps_to_development(self):
        response = self.client.post(
            self._url(),
            self._payload(involvedObject={
                'kind': 'Kustomization', 'name': 'x', 'namespace': 'dev',
            }),
            format='json',
        )
        self.assertEqual(response.json()['environment'], 'development')

    def test_missing_metadata_400(self):
        response = self.client.post(
            self._url(),
            self._payload(metadata={}),
            format='json',
        )
        self.assertEqual(response.status_code, 400)
