"""
Jenkins Webhook Handler

Processes build notifications from Jenkins to:
- Track deployments per environment
- Store CI/CD logs to Elasticsearch
- Create pipeline records

Setup in Jenkins:
1. Install "Notification" or "HTTP Request" plugin
2. Add Post-build Action → HTTP Request
3. URL: https://your-backend.com/webhooks/jenkins/
4. Method: POST
5. Content-Type: application/json
6. Body: Use ${BUILD_STATUS}, ${JOB_NAME}, etc. variables

Example payload (customize based on your Jenkins setup):
{
    "name": "my-job",
    "build": {
        "number": 123,
        "status": "SUCCESS",
        "url": "https://jenkins.example.com/job/my-job/123/",
        "scm": {
            "branch": "main",
            "commit": "abc123..."
        }
    }
}
"""

import hmac
import logging

from .webhook_base import BaseCICDWebhookHandler, detect_environment_generic

logger = logging.getLogger(__name__)


class JenkinsWebhookHandler(BaseCICDWebhookHandler):
    """
    Jenkins webhook handler.

    Processes build notifications from Jenkins.

    Note: Jenkins doesn't have a standard webhook format, so this handler
    supports common patterns. You may need to customize based on your
    Jenkins setup.
    """
    
    provider_name = 'jenkins'
    
    def validate_request(self, request, binding=None) -> bool:
        """
        Validate Jenkins webhook request.

        Checks X-Jenkins-Token header or ?token= query param against
        the CICDBinding.webhook_secret using constant-time comparison.
        If no binding or no secret configured, rejects the request.
        """
        if not binding or not binding.webhook_secret:
            logger.warning("[jenkins] No binding or webhook_secret — rejecting")
            return False

        # Jenkins sends token via header or query parameter
        provided_token = (
            request.headers.get('X-Jenkins-Token', '')
            or request.query_params.get('token', '')
        )
        if not provided_token:
            logger.warning("[jenkins] No token in request header or query param")
            return False

        return hmac.compare_digest(provided_token, binding.webhook_secret)
    
    def parse_pipeline_event(self, payload: dict) -> dict:
        """
        Parse Jenkins build notification to normalized format.
        
        Supports common Jenkins notification formats.
        """
        # Handle different Jenkins payload formats
        build = payload.get('build', {})
        
        # If 'build' key doesn't exist, try flat structure
        if not build:
            build = {
                'number': payload.get('build_number') or payload.get('number'),
                'status': payload.get('build_status') or payload.get('status'),
                'url': payload.get('build_url') or payload.get('url'),
                'scm': {
                    'branch': payload.get('branch') or payload.get('ref', '').replace('refs/heads/', ''),
                    'commit': payload.get('commit') or payload.get('sha'),
                }
            }
        
        # Extract job name
        job_name = payload.get('name') or payload.get('job_name') or 'unknown-job'
        
        # Build number
        build_number = build.get('number', 0)
        
        # Create unique pipeline ID
        pipeline_id = f"{job_name}-{build_number}"
        
        # Status — Jenkins uses 'result' in Notification Plugin, 'status' in others
        jenkins_status = build.get('status') or build.get('result', 'UNKNOWN')
        status = self._normalize_status(jenkins_status)
        
        # Branch and commit
        scm = build.get('scm', {})
        branch = scm.get('branch', '')
        commit = scm.get('commit', '')
        
        # Handle multiple commits
        if isinstance(commit, str):
            commit_shas = [commit] if commit else []
        elif isinstance(commit, list):
            commit_shas = commit
        else:
            commit_shas = []
        
        # Detect environment from job name
        environment = detect_environment_generic(
            branch=branch,
            job_name=job_name,
            explicit_env=payload.get('environment'),
            project_id=job_name,
        )
        
        # Build job entry
        jobs = [{
            'id': str(build_number),
            'name': job_name,
            'status': status,
            'stage': build.get('phase', 'build'),
            'duration': build.get('duration', 0),
        }]
        
        normalized = {
            'pipeline_id': pipeline_id,
            'status': status,
            'branch': branch,
            'commit_shas': commit_shas,
            'environment': environment,
            'jobs': jobs,
            'project_id': job_name,
            'metadata': {
                'build_number': build_number,
                'build_url': build.get('url'),
                'full_url': build.get('full_url') or payload.get('build_url'),
                'phase': build.get('phase'),  # STARTED, COMPLETED, FINALIZED
                'parameters': payload.get('parameters', {}),
            }
        }
        
        logger.info(
            f"[jenkins] Parsed build {pipeline_id}: "
            f"{status} on {branch} ({environment})"
        )
        
        return normalized
    
    def _normalize_status(self, jenkins_status: str) -> str:
        """Map Jenkins build status to our standard status."""
        status_upper = jenkins_status.upper() if jenkins_status else 'UNKNOWN'
        
        status_map = {
            'SUCCESS': 'success',
            'FAILURE': 'failed',
            'FAILED': 'failed',
            'UNSTABLE': 'failed',  # Tests failed but build succeeded
            'ABORTED': 'cancelled',
            'NOT_BUILT': 'skipped',
            'BUILDING': 'running',
            'IN_PROGRESS': 'running',
        }
        return status_map.get(status_upper, 'unknown')
