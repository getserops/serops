import logging
import secrets
from typing import Dict, Any, Optional

from django.conf import settings
from django.utils import timezone

from Projects.models import SCMBinding, CICDBinding
from .code_change_service import CodeChangeService
from .scm_providers import SCMProviderError

logger = logging.getLogger(__name__)

class WebhookService:
    """
    Service for managing SCM and CI/CD webhooks.
    Handles setup, validation, and processing of webhook events.
    """
    
    @staticmethod
    def generate_secret() -> str:
        """Generate a secure random secret for webhooks."""
        return secrets.token_hex(32)
    
    @staticmethod
    def setup_scm_webhook(binding: SCMBinding, host_url: str) -> Dict[str, Any]:
        """
        Configure webhook on the SCM provider.
        
        Args:
            binding: SCMBinding instance
            host_url: Base URL of the SerOps instance (e.g., https://api.serops.com)
            
        Returns:
            Dict with success status and details
        """
        try:
            provider = binding.get_provider()
            
            # Generate secret if not exists
            if not binding.webhook_secret:
                binding.webhook_secret = WebhookService.generate_secret()
                binding.save(update_fields=['webhook_secret'])
            
            # Construct webhook URL
            # Endpoint: POST /api/webhooks/scm/{binding_id}/
            webhook_path = f"/api/webhooks/scm/{binding.id}/"
            webhook_url = f"{host_url.rstrip('/')}{webhook_path}"
            
            # Call provider API
            # Note: create_webhook must be implemented on the provider
            if not hasattr(provider, 'create_webhook'):
                return {
                    'success': False,
                    'error': f"Provider {binding.provider_type} does not support webhook creation"
                }
            
            result = provider.create_webhook(
                webhook_url=webhook_url,
                secret=binding.webhook_secret
            )
            
            if 'error' in result:
                return {'success': False, 'error': result['error']}
            
            # Update binding status
            binding.webhook_configured = True
            binding.webhook_id = str(result.get('id', ''))
            binding.save(update_fields=['webhook_configured', 'webhook_id'])
            
            return {
                'success': True,
                'message': f"Webhook configured successfully for {binding.repository_name}",
                'webhook_url': webhook_url
            }
            
        except Exception as e:
            logger.exception(f"Failed to setup webhook for binding {binding.id}: {e}")
            return {'success': False, 'error': str(e)}

    # URL slug mapping: provider_type → webhook URL segment
    CICD_URL_SLUGS = {
        'gitlab': 'gitlab',
        'github': 'github',                # platform name (ProviderIntegration)
        'github_actions': 'github',         # CI/CD name (Pipeline)
        'jenkins': 'jenkins',
        'bitbucket': 'bitbucket',           # platform name (ProviderIntegration)
        'bitbucket_pipelines': 'bitbucket', # CI/CD name (Pipeline)
        'azure_devops': 'azure-devops',
    }

    # GitOps controllers post to the deployment webhooks (providers/urls.py).
    GITOPS_URL_SLUGS = {
        'argocd': 'argocd',
        'flux': 'flux',
    }

    # Provider-specific webhook events
    CICD_WEBHOOK_EVENTS = {
        'gitlab': {
            'pipeline_events': True,
            'job_events': True,
            'push_events': True,
        },
        'github_actions': ['workflow_run'],
        'bitbucket_pipelines': ['repo:commit_status_created'],
    }

    @staticmethod
    def setup_cicd_webhook(binding: 'CICDBinding', host_url: str) -> Dict[str, Any]:
        """
        Configure webhook on the CI/CD provider.

        Args:
            binding: CICDBinding instance
            host_url: Base URL of the SerOps instance (e.g., https://api.serops.com)

        Returns:
            Dict with success status and details
        """
        try:
            # Generate secret if not exists
            if not binding.webhook_secret:
                binding.webhook_secret = WebhookService.generate_secret()
                binding.save(update_fields=['webhook_secret'])

            # Determine URL slug for provider
            provider_type = binding.integration.provider_type
            if provider_type in WebhookService.GITOPS_URL_SLUGS:
                # Argo CD / Flux: configured by hand on the controller.
                binding.webhook_configured = True
                binding.save(update_fields=['webhook_configured', 'webhook_secret'])
                slug = WebhookService.GITOPS_URL_SLUGS[provider_type]
                return {
                    'success': True,
                    'message': f"Point {binding.integration.get_provider_type_display()} at this URL",
                    'webhook_url': f"{host_url.rstrip('/')}/api/providers/webhook/{slug}/{binding.id}/",
                    'manual_setup': True,
                    'webhook_secret': binding.webhook_secret,
                }
            url_slug = WebhookService.CICD_URL_SLUGS.get(provider_type)
            if not url_slug:
                return {
                    'success': False,
                    'error': f"Unknown provider type: {provider_type}",
                }

            # Construct webhook URL
            webhook_path = f"/api/webhooks/{url_slug}/{binding.id}/"
            webhook_url = f"{host_url.rstrip('/')}{webhook_path}"

            # Providers with create_webhook API (GitLab, GitHub, Bitbucket)
            provider = binding.get_provider()
            if hasattr(provider, 'create_webhook'):
                events = WebhookService.CICD_WEBHOOK_EVENTS.get(provider_type, {})
                result = provider.create_webhook(
                    webhook_url=webhook_url,
                    secret=binding.webhook_secret,
                    events=events,
                )

                if 'error' in result:
                    return {'success': False, 'error': result['error']}

                binding.webhook_id = str(result.get('id', ''))
            else:
                # Jenkins/Azure DevOps: no API — return URL for manual config
                pass

            binding.webhook_configured = True
            binding.save(update_fields=['webhook_configured', 'webhook_id', 'webhook_secret'])

            manual = not hasattr(provider, 'create_webhook')
            result = {
                'success': True,
                'message': f"Webhook configured for {binding.pipeline_name or binding.pipeline_id}",
                'webhook_url': webhook_url,
                'manual_setup': manual,
            }
            if manual:
                # Jenkins / Azure DevOps (and Argo CD / Flux on the same binding)
                # are configured by hand, so the person needs the secret. It was
                # only ever returned by the create call, which the UI did not show.
                result['webhook_secret'] = binding.webhook_secret
            return result

        except Exception as e:
            logger.exception(f"Failed to setup CI/CD webhook for binding {binding.id}: {e}")
            return {'success': False, 'error': str(e)}

    @staticmethod
    def process_scm_payload(binding: SCMBinding, payload: Dict[str, Any], event_type: str = 'push') -> Dict[str, Any]:
        """
        Process incoming SCM webhook payload.
        
        Args:
            binding: SCMBinding instance
            payload: Webhook payload
            event_type: Type of event (push, pull_request, etc.)
            
        Returns:
            Dict with processing results
        """
        try:
            provider = binding.get_provider()
            
            if event_type == 'push':
                # Parse commits
                commits = provider.parse_webhook_payload(payload)
                
                if not commits:
                    return {'success': True, 'message': 'No commits found in payload'}
                
                # Save using CodeChangeService
                # We map SCMBinding's integration to CodeChange model
                # Note: CodeChange model in providers/models.py uses 'provider' and 'project_id'
                saved_changes = CodeChangeService.save_commits_from_webhook(
                    provider=binding.provider_type,
                    project_id=binding.repository_id,
                    commits=commits,
                    gitlab_project=None  # We use generic fields now
                )
                
                # Update binding sync status
                binding.last_sync_at = timezone.now()
                binding.save(update_fields=['last_sync_at'])
                
                return {
                    'success': True,
                    'commits_processed': len(saved_changes),
                    'message': f"Processed {len(saved_changes)} commits"
                }
            
            return {'success': True, 'message': f"Event {event_type} ignored"}
            
        except Exception as e:
            logger.exception(f"Error processing webhook for binding {binding.id}: {e}")
            return {'success': False, 'error': str(e)}
