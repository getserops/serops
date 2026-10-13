"""
GitHub Actions Webhook Handler

Processes workflow_run events from GitHub Actions to:
- Track deployments per environment
- Store CI/CD logs to Elasticsearch
- Create pipeline records

Setup in GitHub:
1. Go to repo Settings → Webhooks → Add webhook
2. Payload URL: https://your-backend.com/webhooks/github/
3. Content type: application/json
4. Events: Select "Workflow runs"
"""

import hashlib
import hmac
import logging

from .webhook_base import BaseCICDWebhookHandler, detect_environment_generic

logger = logging.getLogger(__name__)


class GitHubActionsWebhookHandler(BaseCICDWebhookHandler):
    """
    GitHub Actions webhook handler.
    
    Processes workflow_run events when GitHub Actions workflows complete.
    
    Expected event: workflow_run
    Trigger: When a workflow run completes (completed, success, failure)
    
    Payload structure:
    {
        "action": "completed",
        "workflow_run": {
            "id": 12345,
            "name": "Deploy to Production",
            "head_branch": "main",
            "head_sha": "abc123...",
            "status": "completed",
            "conclusion": "success",  # success, failure, cancelled
            "environment": "production",  # May be present
            ...
        },
        "repository": {
            "id": 67890,
            "full_name": "owner/repo",
            ...
        }
    }
    """
    
    provider_name = 'github_actions'
    integration_provider_type = 'github'
    
    def validate_request(self, request, binding=None) -> bool:
        """
        Validate GitHub webhook request.

        Verifies X-Hub-Signature-256 header using HMAC-SHA256 of the
        request body against binding.webhook_secret.
        """
        if not binding or not binding.webhook_secret:
            logger.warning("[github_actions] No binding or webhook_secret — rejecting")
            return False

        signature_header = request.headers.get('X-Hub-Signature-256', '')
        if not signature_header or not signature_header.startswith('sha256='):
            logger.warning("[github_actions] Missing or malformed X-Hub-Signature-256 header")
            return False

        expected_sig = hmac.new(
            binding.webhook_secret.encode('utf-8'),
            request.body,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(
            signature_header,
            f'sha256={expected_sig}',
        )
    
    def parse_pipeline_event(self, payload: dict) -> dict:
        """
        Parse GitHub Actions workflow_run event to normalized format.
        
        Maps GitHub's workflow structure to our standard pipeline format.
        """
        action = payload.get('action', '')
        
        # Only process completed workflow runs
        if action != 'completed':
            logger.info(f"[github_actions] Ignoring action '{action}' (only processing 'completed')")
            return {
                'pipeline_id': 'skip',
                'status': 'skip',
                'branch': '',
                'commit_shas': [],
                'environment': 'development',
                'jobs': [],
                'project_id': '',
            }
        
        workflow_run = payload.get('workflow_run', {})
        repository = payload.get('repository', {})
        
        # Extract data
        workflow_id = workflow_run.get('id')
        workflow_name = workflow_run.get('name', 'Unknown Workflow')
        conclusion = workflow_run.get('conclusion', 'unknown')  # success, failure, cancelled
        head_branch = workflow_run.get('head_branch', '')
        head_sha = workflow_run.get('head_sha', '')
        
        # Repository info
        repo_full_name = repository.get('full_name', '')  # owner/repo
        repo_id = repository.get('id', '')
        
        # Detect environment
        explicit_env = workflow_run.get('environment')  # GitHub may set this
        environment = detect_environment_generic(
            branch=head_branch,
            job_name=workflow_name,
            explicit_env=explicit_env,
            project_id=repo_full_name or str(repo_id),
        )
        
        # Normalize status
        status = self._normalize_status(conclusion)
        
        # Build jobs list from workflow_run info
        # Note: For full job details, you'd need to call GitHub API
        jobs = [{
            'id': str(workflow_id),
            'name': workflow_name,
            'status': status,
            'duration': self._calculate_duration(workflow_run),
        }]
        
        normalized = {
            'pipeline_id': str(workflow_id),
            'status': status,
            'branch': head_branch,
            'commit_shas': [head_sha] if head_sha else [],
            'environment': environment,
            'jobs': jobs,
            'project_id': repo_full_name or str(repo_id),
            'metadata': {
                'workflow_name': workflow_name,
                'run_number': workflow_run.get('run_number'),
                'run_attempt': workflow_run.get('run_attempt'),
                'html_url': workflow_run.get('html_url'),
                'actor': workflow_run.get('actor', {}).get('login'),
                'triggering_actor': workflow_run.get('triggering_actor', {}).get('login'),
                'event': workflow_run.get('event'),  # push, pull_request, etc.
            }
        }
        
        logger.info(
            f"[github_actions] Parsed workflow {workflow_id}: "
            f"{workflow_name} → {status} on {head_branch} ({environment})"
        )
        
        return normalized
    
    def _normalize_status(self, github_conclusion: str) -> str:
        """Map GitHub conclusion to our standard status."""
        status_map = {
            'success': 'success',
            'failure': 'failed',
            'cancelled': 'cancelled',
            'skipped': 'skipped',
            'timed_out': 'failed',
            'action_required': 'pending',
            'neutral': 'success',  # Neutral is considered success
        }
        return status_map.get(github_conclusion, 'unknown')
    
    def _calculate_duration(self, workflow_run: dict) -> int:
        """Calculate workflow duration in seconds."""
        try:
            from dateutil import parser as date_parser
            
            started = workflow_run.get('run_started_at')
            updated = workflow_run.get('updated_at')
            
            if started and updated:
                start_dt = date_parser.parse(started)
                end_dt = date_parser.parse(updated)
                return int((end_dt - start_dt).total_seconds())
        except Exception:
            pass
        
        return 0
