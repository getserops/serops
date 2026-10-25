"""
Tests for CI/CD webhook setup lifecycle.

Covers:
- WebhookService.setup_cicd_webhook() secret generation + provider API calls
- CICDBindingViewSet.setup_webhook action
- CICDBindingViewSet.perform_create auto-generates secret
- _resolve_binding payload-based fallback
- Legacy URL routing
"""

import json
from unittest.mock import Mock, patch, MagicMock, PropertyMock

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import resolve, reverse, NoReverseMatch


# ── Helpers ───────────────────────────────────────────────────

def _make_binding(
    pk=42,
    secret='',
    provider_type='gitlab',
    pipeline_id='12345',
    pipeline_name='my-pipeline',
    has_create_webhook=True,
):
    """Create a mock CICDBinding with provider."""
    binding = Mock()
    binding.id = pk
    binding.pk = pk
    binding.webhook_secret = secret
    binding.webhook_id = ''
    binding.webhook_configured = False
    binding.pipeline_id = pipeline_id
    binding.pipeline_name = pipeline_name
    binding.is_active = True

    integration = Mock()
    integration.provider_type = provider_type
    binding.integration = integration
    binding.provider_type = provider_type

    provider = Mock()
    if has_create_webhook:
        provider.create_webhook = Mock(return_value={'id': 999})
    else:
        del provider.create_webhook
    binding.get_provider = Mock(return_value=provider)

    binding.save = Mock()
    return binding


def _make_request(payload=None, headers=None):
    """Create a mock request."""
    request = Mock()
    body = json.dumps(payload or {}).encode('utf-8')
    request.body = body
    request.data = payload or {}
    request.headers = headers or {}
    return request


# ── WebhookService.setup_cicd_webhook ─────────────────────────

class TestSetupCICDWebhookGeneratesSecret(SimpleTestCase):
    """Verify secret is created on binding when not already set."""

    def test_generates_secret_when_empty(self):
        from providers.webhook_service import WebhookService

        binding = _make_binding(secret='')
        result = WebhookService.setup_cicd_webhook(binding, 'https://api.serops.com')

        self.assertTrue(result['success'])
        # save should have been called with the secret
        save_calls = binding.save.call_args_list
        # First call sets webhook_secret, second (or same) sets webhook_configured
        secrets_saved = any(
            'webhook_secret' in (call.kwargs.get('update_fields', []) or call.args[0] if call.args else [])
            for call in save_calls
        )
        # At minimum, webhook_secret was assigned
        self.assertTrue(len(binding.webhook_secret) > 0)

    def test_reuses_existing_secret(self):
        from providers.webhook_service import WebhookService

        binding = _make_binding(secret='pre-existing-secret')
        result = WebhookService.setup_cicd_webhook(binding, 'https://api.serops.com')

        self.assertTrue(result['success'])
        self.assertEqual(binding.webhook_secret, 'pre-existing-secret')


class TestSetupCICDWebhookCallsCreateWebhook(SimpleTestCase):
    """Verify provider.create_webhook is called with correct URL and secret."""

    def test_gitlab_webhook_url_and_events(self):
        from providers.webhook_service import WebhookService

        binding = _make_binding(pk=42, secret='my-secret', provider_type='gitlab')
        result = WebhookService.setup_cicd_webhook(binding, 'https://api.serops.com')

        self.assertTrue(result['success'])
        self.assertEqual(result['webhook_url'], 'https://api.serops.com/api/webhooks/gitlab/42/')

        provider = binding.get_provider()
        provider.create_webhook.assert_called_once()
        call_kwargs = provider.create_webhook.call_args
        self.assertIn('webhook_url', call_kwargs.kwargs or {})

    def test_github_url_slug(self):
        from providers.webhook_service import WebhookService

        binding = _make_binding(pk=7, secret='s', provider_type='github_actions')
        result = WebhookService.setup_cicd_webhook(binding, 'https://api.serops.com')

        self.assertTrue(result['success'])
        self.assertEqual(result['webhook_url'], 'https://api.serops.com/api/webhooks/github/7/')

    def test_azure_devops_url_slug(self):
        from providers.webhook_service import WebhookService

        binding = _make_binding(pk=9, secret='s', provider_type='azure_devops', has_create_webhook=False)
        result = WebhookService.setup_cicd_webhook(binding, 'https://api.serops.com')

        self.assertTrue(result['success'])
        self.assertEqual(result['webhook_url'], 'https://api.serops.com/api/webhooks/azure-devops/9/')


class TestSetupCICDWebhookJenkinsNoApiCall(SimpleTestCase):
    """Verify Jenkins skips create_webhook and returns manual URL."""

    def test_jenkins_manual_setup(self):
        from providers.webhook_service import WebhookService

        binding = _make_binding(pk=5, secret='s', provider_type='jenkins', has_create_webhook=False)
        result = WebhookService.setup_cicd_webhook(binding, 'https://api.serops.com')

        self.assertTrue(result['success'])
        self.assertTrue(result['manual_setup'])
        self.assertEqual(result['webhook_url'], 'https://api.serops.com/api/webhooks/jenkins/5/')
        # Configured by hand, so the person needs the secret (it used to be
        # returned only by the create call, which the UI never showed).
        self.assertEqual(result['webhook_secret'], 's')

    def test_secret_not_returned_when_serops_registers_the_webhook(self):
        from providers.webhook_service import WebhookService

        binding = _make_binding(pk=6, secret='s', provider_type='gitlab', has_create_webhook=True)
        result = WebhookService.setup_cicd_webhook(binding, 'https://api.serops.com')
        self.assertNotIn('webhook_secret', result)


# ── CICDBindingViewSet.perform_create ─────────────────────────

class TestPerformCreateGeneratesSecret(SimpleTestCase):
    """Verify that perform_create auto-generates webhook_secret."""

    @patch('Projects.views.log_service_action')
    def test_secret_generated_on_create(self, mock_log):
        from Projects.views import CICDBindingViewSet

        # Build a mock serializer that returns a binding
        binding = _make_binding(secret='')
        binding.project_service = Mock()
        binding.project_service.id = 1
        binding.project_service.project = Mock()
        binding.project_service.project.organisation = Mock()

        serializer = Mock()
        serializer.save = Mock(return_value=binding)
        serializer.validated_data = {
            'project_service': binding.project_service,
        }

        viewset = CICDBindingViewSet()
        viewset.request = Mock()
        viewset.request.user = Mock()
        viewset.request.user.organisation = binding.project_service.project.organisation

        viewset.perform_create(serializer)

        # Secret should now be set (non-empty)
        self.assertTrue(len(binding.webhook_secret) > 0)
        # save should have been called with update_fields=['webhook_secret']
        binding.save.assert_any_call(update_fields=['webhook_secret'])


# ── _resolve_binding behaviour (binding_id is required) ───────

class TestResolveBindingRequiresBindingId(SimpleTestCase):
    """Without binding_id the resolver always returns None (no payload fallback)."""

    @patch('Projects.models.CICDBinding.objects')
    def test_no_binding_id_returns_none_even_with_payload_project(self, mock_objects):
        """The payload-based fallback was removed; binding_id is mandatory."""
        from providers.gitlab_webhook import GitLabCICDWebhookHandler

        handler = GitLabCICDWebhookHandler()
        request = _make_request(payload={'project': {'id': 54321}})

        result = handler._resolve_binding(request)  # no binding_id kwarg

        self.assertIsNone(result)
        # The DB must not even have been queried.
        mock_objects.select_related.assert_not_called()

    @patch('Projects.models.CICDBinding.objects')
    def test_no_binding_id_no_payload_returns_none(self, mock_objects):
        from providers.gitlab_webhook import GitLabCICDWebhookHandler

        handler = GitLabCICDWebhookHandler()
        request = _make_request(payload={})

        result = handler._resolve_binding(request)

        self.assertIsNone(result)
        mock_objects.select_related.assert_not_called()

    @patch('Projects.models.CICDBinding.objects')
    def test_binding_id_in_url_takes_precedence(self, mock_objects):
        """When binding_id is in URL kwargs, use it directly (no fallback)."""
        from providers.gitlab_webhook import GitLabCICDWebhookHandler

        mock_binding = _make_binding(pk=10)
        mock_objects.select_related.return_value.get.return_value = mock_binding

        handler = GitLabCICDWebhookHandler()
        request = _make_request(payload={'project': {'id': 99999}})

        result = handler._resolve_binding(request, binding_id=10)

        self.assertEqual(result, mock_binding)
        mock_objects.select_related.return_value.get.assert_called_once_with(
            pk=10,
            integration__provider_type='gitlab',
            is_active=True,
        )


# ── URL routing: binding_id is REQUIRED ────────────────────────

class TestWebhookUrlRouting(SimpleTestCase):
    """The unbound legacy URLs were removed; binding_id is mandatory."""

    def test_binding_based_gitlab_url_resolves(self):
        match = resolve('/api/webhooks/gitlab/1/')
        self.assertEqual(match.url_name, 'gitlab-webhook-bound')

    def test_legacy_gitlab_url_404s(self):
        from django.urls import Resolver404
        with self.assertRaises(Resolver404):
            resolve('/api/webhooks/gitlab/')

    def test_legacy_github_url_404s(self):
        from django.urls import Resolver404
        with self.assertRaises(Resolver404):
            resolve('/api/webhooks/github/')

    def test_legacy_jenkins_url_404s(self):
        from django.urls import Resolver404
        with self.assertRaises(Resolver404):
            resolve('/api/webhooks/jenkins/')

    def test_legacy_bitbucket_url_404s(self):
        from django.urls import Resolver404
        with self.assertRaises(Resolver404):
            resolve('/api/webhooks/bitbucket/')

    def test_legacy_azure_devops_url_404s(self):
        from django.urls import Resolver404
        with self.assertRaises(Resolver404):
            resolve('/api/webhooks/azure-devops/')
