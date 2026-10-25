"""E2E: ArgoCD notification webhook → Deployment + CodeChange stub.

Exercises the GitOps deploy-event seam (Item #15) end-to-end: ArgoCD's
own default notification payload posted to the org's per-binding
webhook URL translates to a canonical
``{commit_sha, environment, ...}`` deploy record without the user
having to author a custom notification template.

Runs the full chain for real: binding resolution, optional HMAC
verification, sync-status filtering, environment resolution (annotation
> namespace > default), stub CodeChange creation for a commit we
haven't seen yet, and Deployment persistence via
``DeploymentService.create_deployment``. Nothing is mocked.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from django.utils import timezone

from providers.models import CodeChange, Deployment, ProviderIntegration
from Projects.models import CICDBinding

from .base import E2ETestCase


class ArgoCDWebhookE2ETest(E2ETestCase):

    def setUp(self):
        super().setUp()

        # ArgoCD is GitOps — this org runs GitHub Actions for the app
        # itself and ArgoCD for the deploys, so a github integration is
        # the realistic binding target. The webhook handler doesn't
        # care about the provider type; it only needs an active binding.
        self.integration = ProviderIntegration.objects.create(
            organisation=self.org,
            name='e2e-github',
            provider_type='github',
            category='devops',
        )
        self.binding = CICDBinding.objects.create(
            project_service=self.service,
            integration=self.integration,
            binding_type='deploy',
            pipeline_id='argo-checkout',
            pipeline_name='checkout',
            is_active=True,
            webhook_secret='e2e-argocd-shared-secret',
        )

    def _as_argocd(self):
        """Anonymous, like Argo CD: no user, the binding secret as a bearer
        token (Argo CD templates cannot compute an HMAC). force_authenticate
        (user=None) also clears credentials, so the token is set after it."""
        self.client.force_authenticate(user=None)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.binding.webhook_secret}')

    # ------------------------------------------------------------------
    # Payload + URL helpers
    # ------------------------------------------------------------------

    _COMMIT_SHA = 'deadbeefcafefeed01234567890abcdefdeadbee'

    def _payload(
        self,
        *,
        commit_sha: str = _COMMIT_SHA,
        sync_status: str = 'Synced',
        phase: str = 'Succeeded',
        namespace: str = 'production',
        env_annotation: str | None = None,
    ) -> dict:
        """ArgoCD notifications-controller v1.x default payload shape.

        See argocd_webhook.py's docstring for the exact grammar. Only
        the fields the parser reads are populated; the rest of the
        payload is intentionally sparse so a parser regression on a
        missing branch shows up here first.
        """
        metadata: dict = {
            'name': 'checkout',
            'namespace': namespace,
        }
        if env_annotation is not None:
            metadata['annotations'] = {'serops.io/environment': env_annotation}

        return {
            'app': {
                'metadata': metadata,
                'spec': {
                    'source': {'targetRevision': 'HEAD'},
                },
                'status': {
                    'sync': {
                        'status': sync_status,
                        'revision': commit_sha,
                    },
                    'health': {'status': 'Healthy'},
                    'operationState': {
                        'phase': phase,
                        'finishedAt': '2026-09-19T10:00:00Z',
                        'operation': {'initiatedBy': {'username': 'gitops-bot'}},
                    },
                },
            },
            'context': {'argocdUrl': 'https://argocd.local'},
        }

    def _url(self, binding_id: int | None = None) -> str:
        return f'/api/providers/webhook/argocd/{binding_id or self.binding.pk}/'

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_successful_sync_creates_deployment_and_stub_code_change(self):
        self._as_argocd()

        resp = self.client.post(
            self._url(),
            data=self._payload(),
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['message'], 'deployment recorded')
        self.assertEqual(resp.data['environment'], 'production')
        self.assertTrue(resp.data['code_change_created'])

        # DB assertions — one CodeChange stub + one Deployment, both
        # scoped to the primary org.
        code_changes = CodeChange.objects.filter(commit_sha=self._COMMIT_SHA)
        self.assertEqual(code_changes.count(), 1)
        cc = code_changes.get()
        self.assertEqual(cc.organisation, self.org)
        # provider stub uses the binding's integration provider_type
        # (github here), not GitLab default — verifying the fallback
        # chain in _get_or_create_code_change.
        self.assertEqual(cc.provider, 'github')

        deployments = Deployment.objects.filter(code_change=cc)
        self.assertEqual(deployments.count(), 1)
        d = deployments.get()
        self.assertEqual(d.environment, 'production')
        self.assertEqual(d.status, 'success')
        self.assertEqual(d.deployed_by, 'gitops-bot')
        self.assertIn('argocd-app=checkout', d.notes or '')

    def test_environment_annotation_overrides_namespace(self):
        self._as_argocd()

        resp = self.client.post(
            self._url(),
            data=self._payload(
                namespace='monitoring',        # not a valid env alias
                env_annotation='staging',      # annotation wins
            ),
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['environment'], 'staging')

    def test_out_of_sync_is_rejected_no_deployment(self):
        """ArgoCD fires notifications on health-changes too. Without a
        succeeded operation, an OutOfSync app is not a deployment. (With
        one, it is: the app can read OutOfSync right after its sync.)"""
        self._as_argocd()

        payload = self._payload(sync_status='OutOfSync')
        payload['app']['status'].pop('operationState', None)
        resp = self.client.post(self._url(), data=payload, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(Deployment.objects.count(), 0)
        self.assertEqual(CodeChange.objects.count(), 0)

    def test_failed_phase_is_rejected_no_deployment(self):
        self._as_argocd()

        resp = self.client.post(
            self._url(),
            data=self._payload(phase='Failed'),
            format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(Deployment.objects.count(), 0)

    def test_unknown_binding_is_403(self):
        self._as_argocd()

        resp = self.client.post(
            self._url(binding_id=9999999),
            data=self._payload(),
            format='json',
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Deployment.objects.count(), 0)

    def test_hmac_signature_required_when_binding_has_secret(self):
        """When the operator sets a webhook_secret, the handler must
        reject any request without a matching X-SerOps-Signature."""
        self.client.force_authenticate(user=None)   # no bearer token: HMAC path only

        # 1. No signature → 403.
        resp = self.client.post(
            self._url(), data=self._payload(), format='json',
        )
        self.assertEqual(resp.status_code, 403)

        # 2. Wrong signature → 403.
        payload = self._payload()
        raw = json.dumps(payload).encode('utf-8')
        wrong = hmac.new(b'a-different-secret', raw, hashlib.sha256).hexdigest()
        resp = self.client.post(
            self._url(),
            data=raw,
            content_type='application/json',
            HTTP_X_SEROPS_SIGNATURE=f'sha256={wrong}',
        )
        self.assertEqual(resp.status_code, 403)

        # 3. Correct signature → 200 (and the deploy is recorded).
        correct = hmac.new(
            self.binding.webhook_secret.encode('utf-8'), raw, hashlib.sha256,
        ).hexdigest()
        resp = self.client.post(
            self._url(),
            data=raw,
            content_type='application/json',
            HTTP_X_SEROPS_SIGNATURE=f'sha256={correct}',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(Deployment.objects.count(), 1)

    def test_inactive_binding_cannot_receive_webhook(self):
        """Disabling a binding must stop deployments from being recorded
        against it — otherwise a decommissioned pipeline keeps posting
        rows into the org's dashboard."""
        self.client.force_authenticate(user=None)
        self.binding.is_active = False
        self.binding.save(update_fields=['is_active'])

        resp = self.client.post(
            self._url(), data=self._payload(), format='json',
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Deployment.objects.count(), 0)
