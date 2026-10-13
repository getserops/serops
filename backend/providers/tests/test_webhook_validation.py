"""
Tests for webhook validation across all CI/CD providers.

Verifies that:
- Valid secrets are accepted
- Invalid secrets are rejected
- Missing secrets are rejected
- Missing bindings are rejected
"""

import base64
import hashlib
import hmac
import json
from unittest.mock import Mock, patch, MagicMock

from django.test import SimpleTestCase


def _make_request(payload=None, headers=None, query_params=None):
    """Create a mock request with optional payload, headers, and query params."""
    request = Mock()
    body = json.dumps(payload or {}).encode('utf-8')
    request.body = body
    request.data = payload or {}

    _headers = headers or {}
    request.headers = _headers
    request.query_params = query_params or {}
    return request


def _make_binding(secret='test-secret', provider_type='gitlab'):
    """Create a mock CICDBinding."""
    binding = Mock()
    binding.webhook_secret = secret
    integration = Mock()
    integration.provider_type = provider_type
    binding.integration = integration
    binding.is_active = True
    return binding


# ── GitLab ─────────────────────────────────────────────────────

class TestGitLabWebhookValidation(SimpleTestCase):

    def test_valid_token_accepted(self):
        from providers.gitlab_webhook import GitLabCICDWebhookHandler

        handler = GitLabCICDWebhookHandler()
        binding = _make_binding(secret='my-gitlab-secret', provider_type='gitlab')
        request = _make_request(headers={'X-Gitlab-Token': 'my-gitlab-secret'})

        self.assertTrue(handler.validate_request(request, binding=binding))

    def test_invalid_token_rejected(self):
        from providers.gitlab_webhook import GitLabCICDWebhookHandler

        handler = GitLabCICDWebhookHandler()
        binding = _make_binding(secret='real-secret', provider_type='gitlab')
        request = _make_request(headers={'X-Gitlab-Token': 'wrong-secret'})

        self.assertFalse(handler.validate_request(request, binding=binding))

    def test_missing_token_rejected(self):
        from providers.gitlab_webhook import GitLabCICDWebhookHandler

        handler = GitLabCICDWebhookHandler()
        binding = _make_binding(secret='real-secret', provider_type='gitlab')
        request = _make_request(headers={})

        self.assertFalse(handler.validate_request(request, binding=binding))

    def test_missing_binding_rejected(self):
        from providers.gitlab_webhook import GitLabCICDWebhookHandler

        handler = GitLabCICDWebhookHandler()
        request = _make_request(headers={'X-Gitlab-Token': 'anything'})

        self.assertFalse(handler.validate_request(request, binding=None))


# ── GitHub ─────────────────────────────────────────────────────

class TestGitHubWebhookValidation(SimpleTestCase):

    def _sign(self, body: bytes, secret: str) -> str:
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return f'sha256={sig}'

    def test_valid_signature_accepted(self):
        from providers.github_webhook import GitHubActionsWebhookHandler

        handler = GitHubActionsWebhookHandler()
        binding = _make_binding(secret='gh-secret', provider_type='github_actions')
        payload = {'action': 'completed'}
        body = json.dumps(payload).encode()
        sig = self._sign(body, 'gh-secret')
        request = _make_request(payload=payload, headers={'X-Hub-Signature-256': sig})
        request.body = body

        self.assertTrue(handler.validate_request(request, binding=binding))

    def test_invalid_signature_rejected(self):
        from providers.github_webhook import GitHubActionsWebhookHandler

        handler = GitHubActionsWebhookHandler()
        binding = _make_binding(secret='gh-secret', provider_type='github_actions')
        request = _make_request(
            payload={},
            headers={'X-Hub-Signature-256': 'sha256=0000000000000000'},
        )

        self.assertFalse(handler.validate_request(request, binding=binding))

    def test_missing_signature_rejected(self):
        from providers.github_webhook import GitHubActionsWebhookHandler

        handler = GitHubActionsWebhookHandler()
        binding = _make_binding(secret='gh-secret', provider_type='github_actions')
        request = _make_request(headers={})

        self.assertFalse(handler.validate_request(request, binding=binding))

    def test_missing_binding_rejected(self):
        from providers.github_webhook import GitHubActionsWebhookHandler

        handler = GitHubActionsWebhookHandler()
        request = _make_request(headers={'X-Hub-Signature-256': 'sha256=abc'})

        self.assertFalse(handler.validate_request(request, binding=None))


# ── Jenkins ────────────────────────────────────────────────────

class TestJenkinsWebhookValidation(SimpleTestCase):

    def test_valid_header_token_accepted(self):
        from providers.jenkins_webhook import JenkinsWebhookHandler

        handler = JenkinsWebhookHandler()
        binding = _make_binding(secret='jenkins-tok', provider_type='jenkins')
        request = _make_request(headers={'X-Jenkins-Token': 'jenkins-tok'})

        self.assertTrue(handler.validate_request(request, binding=binding))

    def test_valid_query_param_token_accepted(self):
        from providers.jenkins_webhook import JenkinsWebhookHandler

        handler = JenkinsWebhookHandler()
        binding = _make_binding(secret='jenkins-tok', provider_type='jenkins')
        request = _make_request(
            headers={},
            query_params={'token': 'jenkins-tok'},
        )

        self.assertTrue(handler.validate_request(request, binding=binding))

    def test_invalid_token_rejected(self):
        from providers.jenkins_webhook import JenkinsWebhookHandler

        handler = JenkinsWebhookHandler()
        binding = _make_binding(secret='real-tok', provider_type='jenkins')
        request = _make_request(headers={'X-Jenkins-Token': 'wrong-tok'})

        self.assertFalse(handler.validate_request(request, binding=binding))

    def test_missing_token_rejected(self):
        from providers.jenkins_webhook import JenkinsWebhookHandler

        handler = JenkinsWebhookHandler()
        binding = _make_binding(secret='real-tok', provider_type='jenkins')
        request = _make_request(headers={}, query_params={})

        self.assertFalse(handler.validate_request(request, binding=binding))

    def test_missing_binding_rejected(self):
        from providers.jenkins_webhook import JenkinsWebhookHandler

        handler = JenkinsWebhookHandler()
        request = _make_request(headers={'X-Jenkins-Token': 'anything'})

        self.assertFalse(handler.validate_request(request, binding=None))


# ── Bitbucket ──────────────────────────────────────────────────

class TestBitbucketWebhookValidation(SimpleTestCase):

    def test_valid_secret_accepted(self):
        from providers.bitbucket_webhook import BitbucketWebhookHandler

        handler = BitbucketWebhookHandler()
        binding = _make_binding(secret='bb-secret', provider_type='bitbucket')
        request = _make_request(headers={
            'X-Event-Key': 'repo:commit_status_created',
            'X-Webhook-Secret': 'bb-secret',
        })

        self.assertTrue(handler.validate_request(request, binding=binding))

    def test_invalid_secret_rejected(self):
        from providers.bitbucket_webhook import BitbucketWebhookHandler

        handler = BitbucketWebhookHandler()
        binding = _make_binding(secret='bb-secret', provider_type='bitbucket')
        request = _make_request(headers={
            'X-Event-Key': 'repo:commit_status_created',
            'X-Webhook-Secret': 'wrong-secret',
        })

        self.assertFalse(handler.validate_request(request, binding=binding))

    def test_unsupported_event_rejected(self):
        from providers.bitbucket_webhook import BitbucketWebhookHandler

        handler = BitbucketWebhookHandler()
        binding = _make_binding(secret='bb-secret', provider_type='bitbucket')
        request = _make_request(headers={
            'X-Event-Key': 'repo:push',
            'X-Webhook-Secret': 'bb-secret',
        })

        self.assertFalse(handler.validate_request(request, binding=binding))

    def test_missing_binding_rejected(self):
        from providers.bitbucket_webhook import BitbucketWebhookHandler

        handler = BitbucketWebhookHandler()
        request = _make_request(headers={
            'X-Event-Key': 'repo:commit_status_created',
            'X-Webhook-Secret': 'anything',
        })

        self.assertFalse(handler.validate_request(request, binding=None))


# ── Azure DevOps ───────────────────────────────────────────────

class TestAzureDevOpsWebhookValidation(SimpleTestCase):

    def _make_basic_auth(self, password: str, username: str = '') -> str:
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
        return f"Basic {encoded}"

    def test_valid_basic_auth_accepted(self):
        from providers.azure_devops_webhook import AzureDevOpsWebhookHandler

        handler = AzureDevOpsWebhookHandler()
        binding = _make_binding(secret='azdo-secret', provider_type='azure_devops')
        auth = self._make_basic_auth('azdo-secret')
        request = _make_request(headers={'Authorization': auth})

        self.assertTrue(handler.validate_request(request, binding=binding))

    def test_invalid_password_rejected(self):
        from providers.azure_devops_webhook import AzureDevOpsWebhookHandler

        handler = AzureDevOpsWebhookHandler()
        binding = _make_binding(secret='azdo-secret', provider_type='azure_devops')
        auth = self._make_basic_auth('wrong-password')
        request = _make_request(headers={'Authorization': auth})

        self.assertFalse(handler.validate_request(request, binding=binding))

    def test_missing_auth_header_rejected(self):
        from providers.azure_devops_webhook import AzureDevOpsWebhookHandler

        handler = AzureDevOpsWebhookHandler()
        binding = _make_binding(secret='azdo-secret', provider_type='azure_devops')
        request = _make_request(headers={})

        self.assertFalse(handler.validate_request(request, binding=binding))

    def test_missing_binding_rejected(self):
        from providers.azure_devops_webhook import AzureDevOpsWebhookHandler

        handler = AzureDevOpsWebhookHandler()
        auth = self._make_basic_auth('anything')
        request = _make_request(headers={'Authorization': auth})

        self.assertFalse(handler.validate_request(request, binding=None))
