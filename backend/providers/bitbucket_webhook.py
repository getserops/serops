"""
Bitbucket Pipelines Webhook Handler

Handles webhooks from Bitbucket Pipelines for CI/CD pipeline status updates.

Webhook Events Supported:
- repo:commit_status_created: Pipeline status updates
- repo:commit_status_updated: Pipeline status changes
"""

import hmac
import logging
from datetime import datetime

from .webhook_base import BaseCICDWebhookHandler, detect_environment_generic

logger = logging.getLogger(__name__)


class BitbucketWebhookHandler(BaseCICDWebhookHandler):
    """
    Webhook handler for Bitbucket Pipelines.
    
    Bitbucket sends pipeline status via commit_status events.
    
    Headers:
        X-Event-Key: Event type (repo:commit_status_created, etc.)
        X-Hook-UUID: Webhook identifier
        X-Request-UUID: Request identifier
    
    Payload Structure (commit_status_created):
        {
            "commit_status": {
                "key": "pipeline-id",
                "type": "build",
                "state": "SUCCESSFUL",
                "name": "Pipeline #123",
                "description": "Build completed",
                "url": "https://bitbucket.org/...",
                "commit": { "hash": "abc123..." }
            },
            "repository": {
                "full_name": "workspace/repo",
                "uuid": "{...}",
                "name": "repo"
            },
            "actor": {
                "display_name": "User",
                "uuid": "{...}"
            }
        }
    """
    
    provider_name = "bitbucket"
    
    # Status mapping from Bitbucket to normalized format
    STATUS_MAP = {
        'INPROGRESS': 'pending',
        'SUCCESSFUL': 'success',
        'FAILED': 'failed',
        'STOPPED': 'cancelled',
    }
    
    # Supported event types
    SUPPORTED_EVENTS = [
        'repo:commit_status_created',
        'repo:commit_status_updated',
    ]
    
    def validate_request(self, request, binding=None) -> bool:
        """
        Validate the Bitbucket webhook request.

        Checks event type is supported AND validates X-Webhook-Secret
        header against binding.webhook_secret using constant-time comparison.
        """
        event_key = request.headers.get('X-Event-Key', '')
        if event_key not in self.SUPPORTED_EVENTS:
            logger.warning(f"Bitbucket: Unsupported event type: {event_key}")
            return False

        if not binding or not binding.webhook_secret:
            logger.warning("[bitbucket] No binding or webhook_secret — rejecting")
            return False

        provided_secret = request.headers.get('X-Webhook-Secret', '')
        if not provided_secret:
            logger.warning("[bitbucket] Missing X-Webhook-Secret header")
            return False

        return hmac.compare_digest(provided_secret, binding.webhook_secret)
    
    def parse_pipeline_event(self, payload: dict) -> dict:
        """
        Parse Bitbucket pipeline event payload.
        
        Returns normalized pipeline data dictionary.
        """
        commit_status = payload.get('commit_status', {})
        repository = payload.get('repository', {})
        
        # Extract key fields
        pipeline_key = commit_status.get('key', '')
        state = commit_status.get('state', 'UNKNOWN')
        commit_hash = commit_status.get('commit', {}).get('hash', '')
        pipeline_name = commit_status.get('name', '')
        repo_full_name = repository.get('full_name', '')
        
        # Determine branch from refname if available
        refname = commit_status.get('refname', '')
        branch = refname.replace('refs/heads/', '') if refname else ''
        
        # Detect environment
        environment = detect_environment_generic(
            branch=branch,
            job_name=pipeline_name,
            explicit_env=commit_status.get('environment'),
            project_id=repo_full_name,
        )
        
        # Normalize status
        normalized_status = self._normalize_status(state)
        
        # Parse timestamp
        updated_on = commit_status.get('updated_on', '')
        finished_at = None
        if updated_on:
            try:
                from dateutil import parser as date_parser
                finished_at = date_parser.parse(updated_on)
            except Exception:
                finished_at = datetime.utcnow()
        
        return {
            'pipeline_id': f"bb-{pipeline_key}" if pipeline_key else f"bb-{commit_hash[:8]}",
            'status': normalized_status,
            'branch': branch,
            'commit_shas': [commit_hash] if commit_hash else [],
            'project_name': repo_full_name,
            'environment': environment,
            'finished_at': finished_at,
            'provider_metadata': {
                'key': pipeline_key,
                'name': pipeline_name,
                'type': commit_status.get('type'),
                'url': commit_status.get('url'),
                'description': commit_status.get('description'),
                'repo_uuid': repository.get('uuid'),
            }
        }
    
    def _normalize_status(self, bitbucket_status: str) -> str:
        """Convert Bitbucket status to normalized format."""
        return self.STATUS_MAP.get(bitbucket_status.upper(), 'unknown')
