"""
Azure DevOps Webhook Handler

Handles webhooks from Azure DevOps Pipelines for CI/CD deployment status updates.
CI/CD only - no SCM integration (per user requirements).

Webhook Events Supported:
- ms.azure-devops-release.deployment-completed-event: Release deployment completed
- ms.vss-pipelines.run-state-changed-event: Pipeline run state changed
"""

import base64
import hmac
import logging
from datetime import datetime

from .webhook_base import BaseCICDWebhookHandler, detect_environment_generic

logger = logging.getLogger(__name__)


class AzureDevOpsWebhookHandler(BaseCICDWebhookHandler):
    """
    Webhook handler for Azure DevOps Pipelines.
    
    Azure DevOps sends deployment and pipeline events via service hooks.
    
    Payload Structure (deployment-completed):
        {
            "eventType": "ms.azure-devops-release.deployment-completed-event",
            "resource": {
                "id": 123,
                "result": "succeeded",
                "project": { "id": "...", "name": "..." },
                "release": { "id": 1, "name": "Release-1" },
                "environment": { "id": 1, "name": "Production" },
                "deployment": {
                    "id": 1,
                    "status": "succeeded"
                }
            },
            "resourceVersion": "1.0",
            "resourceContainers": { ... },
            "message": { "text": "...", "html": "...", "markdown": "..." }
        }
    
    Payload Structure (run-state-changed):
        {
            "eventType": "ms.vss-pipelines.run-state-changed-event",
            "resource": {
                "run": {
                    "id": 123,
                    "name": "20231201.1",
                    "state": "completed",
                    "result": "succeeded",
                    "pipeline": { "id": 1, "name": "my-pipeline" },
                    "createdDate": "2023-12-01T10:00:00Z",
                    "finishedDate": "2023-12-01T10:15:00Z"
                },
                "repositories": [
                    { "type": "GitHub", "repository": { "fullName": "org/repo" } }
                ]
            }
        }
    """
    
    provider_name = "azure_devops"
    
    # Status mapping from Azure DevOps to normalized format
    STATUS_MAP = {
        'succeeded': 'success',
        'partiallysucceeded': 'warning',
        'failed': 'failed',
        'canceled': 'cancelled',
        'inprogress': 'pending',
        'notstarted': 'pending',
    }
    
    # Supported event types
    SUPPORTED_EVENTS = [
        'ms.azure-devops-release.deployment-completed-event',
        'ms.vss-pipelines.run-state-changed-event',
        'ms.vss-pipelines.run-completed-event',
    ]
    
    def validate_request(self, request, binding=None) -> bool:
        """
        Validate Azure DevOps webhook request.

        Azure DevOps service hooks use HTTP Basic authentication.
        The password is the webhook secret (username is empty or ignored).
        Header format: Authorization: Basic base64(:<secret>)
        """
        if not binding or not binding.webhook_secret:
            logger.warning("[azure_devops] No binding or webhook_secret — rejecting")
            return False

        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Basic '):
            logger.warning("[azure_devops] Missing or malformed Authorization header")
            return False

        try:
            decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
            # Azure DevOps sends :<password> or username:password
            password = decoded.split(':', 1)[-1]
        except Exception:
            logger.warning("[azure_devops] Failed to decode Basic auth header")
            return False

        return hmac.compare_digest(password, binding.webhook_secret)
    
    def parse_pipeline_event(self, payload: dict) -> dict:
        """
        Parse Azure DevOps pipeline/deployment event payload.

        Returns normalized pipeline data dictionary, or {'status': 'skip'}
        for unsupported event types.
        """
        event_type = payload.get('eventType', '')
        resource = payload.get('resource', {})

        # Unsupported event types → skip
        if not any(kw in event_type for kw in ['deployment', 'run-state', 'run-completed']):
            return {'status': 'skip'}

        # Handle different event types
        if 'deployment-completed' in event_type:
            return self._parse_deployment_event(resource, payload)
        elif 'run-state-changed' in event_type or 'run-completed' in event_type:
            return self._parse_run_event(resource, payload)
        else:
            return self._parse_generic_event(resource, payload)
    
    def _parse_deployment_event(self, resource: dict, payload: dict) -> dict:
        """Parse release deployment completed event."""
        deployment = resource.get('deployment', resource)
        release = resource.get('release', {})
        environment = resource.get('environment', {})
        project = resource.get('project', {})
        
        # Get result/status
        result = (
            deployment.get('operationStatus') or
            deployment.get('status') or
            resource.get('result', 'unknown')
        )
        
        # Build pipeline ID
        release_id = release.get('id', resource.get('id'))
        deployment_id = deployment.get('id', 0)
        pipeline_id = f"azdo-release-{release_id}-{deployment_id}"
        
        # Determine environment
        env_name = environment.get('name', '')
        normalized_env = self._detect_environment(env_name)
        
        # Parse timestamps
        completed_on = (
            deployment.get('completedOn') or
            resource.get('completedDate') or
            resource.get('completedOn')
        )
        finished_at = None
        if completed_on:
            try:
                from dateutil import parser as date_parser
                finished_at = date_parser.parse(completed_on)
            except Exception:
                finished_at = datetime.utcnow()
        
        return {
            'pipeline_id': pipeline_id,
            'status': self._normalize_status(result),
            'branch': release.get('artifacts', [{}])[0].get('definitionReference', {}).get('branch', {}).get('name', ''),
            'commit_shas': [],
            'project_name': project.get('name', ''),
            'environment': normalized_env,
            'finished_at': finished_at,
            'provider_metadata': {
                'event_type': 'deployment-completed',
                'release_id': release_id,
                'release_name': release.get('name'),
                'deployment_id': deployment_id,
                'environment_name': env_name,
                'project_id': project.get('id'),
            }
        }
    
    def _parse_run_event(self, resource: dict, payload: dict) -> dict:
        """Parse pipeline run state changed event."""
        run = resource.get('run', resource)
        pipeline = run.get('pipeline', {})
        repositories = resource.get('repositories', [])
        
        # Get result/state
        result = run.get('result', run.get('state', 'unknown'))
        
        # Build pipeline ID
        run_id = run.get('id')
        pipeline_id = f"azdo-run-{run_id}"
        
        # Get commit info from repositories
        commit_shas = []
        repo_name = ''
        for repo in repositories:
            repo_info = repo.get('repository', {})
            repo_name = repo_info.get('fullName', repo_info.get('name', ''))
            # Note: Azure DevOps may include commit info in different places
        
        # Detect environment from pipeline name
        pipeline_name = pipeline.get('name', run.get('name', ''))
        environment = detect_environment_generic(
            branch='',
            job_name=pipeline_name,
            project_id=repo_name or pipeline_name,
        )
        
        # Parse timestamps
        finished_date = run.get('finishedDate')
        finished_at = None
        if finished_date:
            try:
                from dateutil import parser as date_parser
                finished_at = date_parser.parse(finished_date)
            except Exception:
                finished_at = datetime.utcnow()
        
        return {
            'pipeline_id': pipeline_id,
            'status': self._normalize_status(result),
            'branch': run.get('resources', {}).get('repositories', {}).get('self', {}).get('refName', '').replace('refs/heads/', ''),
            'commit_shas': commit_shas,
            'project_name': repo_name or pipeline.get('name', ''),
            'environment': environment,
            'finished_at': finished_at,
            'provider_metadata': {
                'event_type': 'run-state-changed',
                'run_id': run_id,
                'run_name': run.get('name'),
                'pipeline_id': pipeline.get('id'),
                'pipeline_name': pipeline.get('name'),
                'state': run.get('state'),
            }
        }
    
    def _parse_generic_event(self, resource: dict, payload: dict) -> dict:
        """Parse generic Azure DevOps event as fallback."""
        return {
            'pipeline_id': f"azdo-{resource.get('id', 'unknown')}",
            'status': self._normalize_status(resource.get('status', 'unknown')),
            'branch': '',
            'commit_shas': [],
            'project_name': resource.get('project', {}).get('name', ''),
            'environment': 'unknown',
            'finished_at': datetime.utcnow(),
            'provider_metadata': {
                'event_type': payload.get('eventType'),
                'resource': resource,
            }
        }
    
    def _normalize_status(self, azure_status: str) -> str:
        """Convert Azure DevOps status to normalized format."""
        return self.STATUS_MAP.get(str(azure_status).lower(), 'unknown')
    
    def _detect_environment(self, env_name: str) -> str:
        """Detect normalized environment from Azure DevOps environment name."""
        env_lower = env_name.lower()

        if any(kw in env_lower for kw in ['prod', 'production', 'live']):
            return 'production'
        elif any(kw in env_lower for kw in ['stag', 'staging', 'uat', 'pre-prod']):
            return 'staging'
        elif any(kw in env_lower for kw in ['dev', 'develop', 'development']):
            return 'development'
        elif any(kw in env_lower for kw in ['test', 'qa', 'quality']):
            return 'testing'
        else:
            return env_name or 'unknown'
