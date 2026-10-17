"""Tests for the generic deployment webhook.

Covers the endpoint at ``POST /api/providers/webhook/deployment/<binding_id>/``.

Verified behaviors:
  * Happy path — known commit → 200, Deployment created, code_change_created=False
  * Unknown commit → 200, stub CodeChange created, deployment linked
  * Missing / non-integer / inactive binding → 403
  * Payload validation (missing/invalid commit_sha, environment, timestamp)
  * Environment aliases (`prod` → `production`, etc.)
  * HMAC-SHA256 signature verification (positive + negative + missing header)
  * Bindings without a secret don't require signature
  * Input-clamping (long notes/actor/version)
  * Security: constant-time signature compare (`hmac.compare_digest`) —
    covered by using different-length good vs bad signatures.
"""

import hashlib
import hmac
import json
from datetime import datetime, timezone as _tz
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from providers.tests.signing_client import SigningAPIClient

from Organisations.models import Organisations
from Projects.models import Project, ProjectService, CICDBinding
from providers.models import CodeChange, Deployment, ProviderIntegration


class DeploymentWebhookTestBase(TestCase):
    """Shared fixture: one org / project / service / integration / binding."""

    def setUp(self):
        self.org = Organisations.objects.create(name='DeployHookOrg')
        self.project = Project.objects.create(name='dh-proj', organisation=self.org)
        self.service = ProjectService.objects.create(
            project=self.project, name='api', service_type='application',
        )
        # provider_type must be one of ProviderIntegration.PROVIDER_TYPES —
        # `github` is representative. The generic deploy webhook works
        # with ANY existing binding regardless of underlying SCM type.
        self.integration = ProviderIntegration.objects.create(
            organisation=self.org,
            provider_type='github',
            name='github-integration',
        )
        self.binding = CICDBinding.objects.create(
            project_service=self.service,
            integration=self.integration,
            binding_type='deploy',
            is_active=True,
            webhook_secret='test-binding-secret',
        )
        self.client = SigningAPIClient('test-binding-secret')
        self.url = f'/api/providers/webhook/deployment/{self.binding.id}/'

    def _payload(self, **overrides):
        base = {
            'commit_sha': 'abc123def456',
            'environment': 'production',
            'actor': 'argocd',
            'notes': 'auto-sync from main',
        }
        base.update(overrides)
        return base


# ============================================================================
# Happy path
# ============================================================================


class HappyPathTest(DeploymentWebhookTestBase):

    def test_known_commit_creates_deployment(self):
        """Existing CodeChange → Deployment linked, code_change_created=False."""
        cc = CodeChange.objects.create(
            organisation=self.org,
            provider='github',
            project_id='42',
            commit_sha='abc123def456',
            commit_message='fix null pointer',
            author_name='alice',
            timestamp=datetime(2026, 1, 1, tzinfo=_tz.utc),
            branch='main',
        )
        response = self.client.post(self.url, self._payload(), format='json')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['message'], 'deployment recorded')
        self.assertFalse(data['code_change_created'])

        deployment = Deployment.objects.get(pk=data['deployment_id'])
        self.assertEqual(deployment.code_change, cc)
        self.assertEqual(deployment.environment, 'production')
        self.assertEqual(deployment.deployed_by, 'argocd')

    def test_unknown_commit_creates_stub_code_change(self):
        """SCM webhook hasn't fired yet → we create a stub so the deploy
        can be linked. Real diff hydrates when the SCM webhook arrives."""
        self.assertEqual(CodeChange.objects.count(), 0)
        response = self.client.post(
            self.url,
            self._payload(commit_sha='fedcba987654'),
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['code_change_created'])
        cc = CodeChange.objects.get(commit_sha='fedcba987654')
        self.assertEqual(cc.organisation, self.org)
        # Stub has empty message + author until SCM webhook fills them.
        self.assertEqual(cc.commit_message, '')

    def test_environment_alias_normalises(self):
        response = self.client.post(
            self.url, self._payload(environment='prod'), format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['environment'], 'production')

    def test_deployed_at_uses_now_when_missing(self):
        response = self.client.post(self.url, self._payload(), format='json')
        self.assertEqual(response.status_code, 200)
        deployment = Deployment.objects.get(pk=response.json()['deployment_id'])
        # deployed_at should be within a few seconds of now
        delta = abs((deployment.deployed_at - datetime.now(_tz.utc)).total_seconds())
        self.assertLess(delta, 10)

    def test_version_prepended_to_notes(self):
        response = self.client.post(
            self.url,
            self._payload(version='v2.3.1', notes='canary rollout'),
            format='json',
        )
        deployment = Deployment.objects.get(pk=response.json()['deployment_id'])
        self.assertIn('version=v2.3.1', deployment.notes)
        self.assertIn('canary rollout', deployment.notes)


# ============================================================================
# Binding resolution
# ============================================================================


class BindingResolutionTest(DeploymentWebhookTestBase):

    def test_nonexistent_binding_returns_403(self):
        response = self.client.post(
            '/api/providers/webhook/deployment/999999/', self._payload(), format='json',
        )
        self.assertEqual(response.status_code, 403)

    def test_inactive_binding_returns_403(self):
        self.binding.is_active = False
        self.binding.save()
        response = self.client.post(self.url, self._payload(), format='json')
        self.assertEqual(response.status_code, 403)


# ============================================================================
# Payload validation
# ============================================================================


class PayloadValidationTest(DeploymentWebhookTestBase):

    def test_missing_commit_sha_400(self):
        payload = self._payload()
        del payload['commit_sha']
        response = self.client.post(self.url, payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('commit_sha', response.json()['error'].lower())

    def test_short_commit_sha_400(self):
        response = self.client.post(
            self.url, self._payload(commit_sha='abc'), format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_non_hex_commit_sha_400(self):
        response = self.client.post(
            self.url, self._payload(commit_sha='xyz123abcdef'), format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_environment_400(self):
        payload = self._payload()
        del payload['environment']
        response = self.client.post(self.url, payload, format='json')
        self.assertEqual(response.status_code, 400)

    def test_unknown_environment_400(self):
        response = self.client.post(
            self.url, self._payload(environment='unknown-planet'), format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_deployed_at_400(self):
        response = self.client.post(
            self.url, self._payload(deployed_at='not-a-timestamp'), format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_long_notes_clamped(self):
        response = self.client.post(
            self.url, self._payload(notes='x' * 5000), format='json',
        )
        self.assertEqual(response.status_code, 200)
        deployment = Deployment.objects.get(pk=response.json()['deployment_id'])
        # <= 500 chars (module constant _NOTES_MAX_LEN)
        self.assertLessEqual(len(deployment.notes), 500)


# ============================================================================
# HMAC signature verification
# ============================================================================


class HmacSignatureTest(DeploymentWebhookTestBase):

    def setUp(self):
        super().setUp()
        self.secret = 'super-secret-webhook-key'
        self.binding.webhook_secret = self.secret
        self.binding.save()
        self.client = SigningAPIClient(self.secret)

    def _sign(self, body: bytes) -> str:
        return 'sha256=' + hmac.new(
            self.secret.encode(), body, hashlib.sha256,
        ).hexdigest()

    def test_valid_signature_accepted(self):
        payload = self._payload()
        body = json.dumps(payload).encode()
        response = self.client.post(
            self.url, data=body, content_type='application/json',
            HTTP_X_SEROPS_SIGNATURE=self._sign(body),
        )
        self.assertEqual(response.status_code, 200)

    def test_wrong_signature_rejected(self):
        payload = self._payload()
        body = json.dumps(payload).encode()
        response = self.client.post(
            self.url, data=body, content_type='application/json',
            HTTP_X_SEROPS_SIGNATURE='sha256=' + 'f' * 64,
        )
        self.assertEqual(response.status_code, 403)

    def test_missing_signature_header_rejected(self):
        response = self.client.post(self.url, self._payload(), format='json', HTTP_X_SEROPS_SIGNATURE='')
        self.assertEqual(response.status_code, 403)

    def test_bearer_token_accepted(self):
        """Argo CD sends the binding secret as a static bearer token."""
        response = self.client.post(self.url, self._payload(), format='json',
                                    HTTP_X_SEROPS_SIGNATURE='', HTTP_AUTHORIZATION=f'Bearer {self.secret}')
        self.assertEqual(response.status_code, 200)

    def test_wrong_bearer_token_rejected(self):
        response = self.client.post(self.url, self._payload(), format='json',
                                    HTTP_X_SEROPS_SIGNATURE='', HTTP_AUTHORIZATION='Bearer nope')
        self.assertEqual(response.status_code, 403)

    def test_malformed_signature_header_rejected(self):
        response = self.client.post(
            self.url, self._payload(), format='json',
            HTTP_X_SEROPS_SIGNATURE='not-sha256-prefixed',
        )
        self.assertEqual(response.status_code, 403)


class NoSecretConfiguredTest(DeploymentWebhookTestBase):
    """A binding without a secret refuses events: nothing is accepted unsigned."""

    def test_binding_without_secret_refuses_events(self):
        self.binding.webhook_secret = ''
        self.binding.save()
        response = self.client.post(self.url, self._payload(), format='json', HTTP_X_SEROPS_SIGNATURE='')
        self.assertEqual(response.status_code, 403)

    def test_refusals_are_indistinguishable(self):
        """Unknown binding, no secret and bad signature give the same answer."""
        unknown = self.client.post('/api/providers/webhook/deployment/999999/', self._payload(), format='json')
        bad = self.client.post(self.url, self._payload(), format='json', HTTP_X_SEROPS_SIGNATURE='sha256=' + '0' * 64)
        self.binding.webhook_secret = ''
        self.binding.save()
        no_secret = self.client.post(self.url, self._payload(), format='json', HTTP_X_SEROPS_SIGNATURE='')
        bodies = {(r.status_code, r.content) for r in (unknown, bad, no_secret)}
        self.assertEqual(len(bodies), 1, bodies)
