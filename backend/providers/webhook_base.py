"""
Base CI/CD Webhook Handler - Abstract base for multi-provider support.

Provides:
- Common webhook validation
- Normalized pipeline data format
- Deployment creation
- CI/CD log storage

Usage:
    class GitHubActionsWebhookHandler(BaseCICDWebhookHandler):
        provider_name = 'github_actions'
        
        def validate_request(self, request) -> bool:
            # GitHub-specific validation
            ...
        
        def parse_pipeline_event(self, payload) -> dict:
            # Return normalized data
            ...
"""

from abc import ABC, abstractmethod
import hmac
import hashlib

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.utils import timezone
import logging
import json

logger = logging.getLogger(__name__)


class BaseCICDWebhookHandler(APIView, ABC):
    """
    Abstract base class for CI/CD webhook handlers.
    
    Inherit from this to add new CI/CD providers (GitHub Actions, Jenkins, etc.).
    The existing GitLab handler continues working unchanged - this is for NEW providers.
    
    Subclasses must implement:
    - provider_name: str - Unique provider identifier
    - validate_request(request) -> bool - Validate webhook signature/token
    - parse_pipeline_event(payload) -> dict - Normalize pipeline data
    """
    
    permission_classes = [AllowAny]  # Webhooks don't use JWT auth
    
    # Override in subclass
    provider_name: str = None
    # Override when the ProviderIntegration.provider_type differs from
    # provider_name (e.g. GitHub: provider_name='github_actions' but
    # ProviderIntegration uses provider_type='github').
    integration_provider_type: str = None
    
    @abstractmethod
    def validate_request(self, request, binding=None) -> bool:
        """
        Validate the incoming webhook request.

        Implement provider-specific validation:
        - GitHub: Verify X-Hub-Signature-256 using HMAC-SHA256
        - GitLab: Verify X-Gitlab-Token header
        - Jenkins: Check X-Jenkins-Token header or ?token= query param
        - Bitbucket: Verify X-Webhook-Secret header
        - Azure DevOps: Verify Authorization: Basic header

        Args:
            request: The incoming HTTP request
            binding: Optional CICDBinding with webhook_secret

        Returns:
            True if request is valid, False otherwise
        """
        pass
    
    @abstractmethod
    def parse_pipeline_event(self, payload: dict) -> dict:
        """
        Parse provider-specific webhook payload into normalized format.
        
        Args:
            payload: Raw webhook payload (already JSON decoded)
        
        Returns:
            Normalized dict with:
            {
                'pipeline_id': str,           # Unique pipeline/workflow ID
                'status': str,                # 'success', 'failed', 'running', 'cancelled'
                'branch': str,                # Branch name
                'commit_shas': List[str],     # Commit SHAs in this pipeline
                'environment': str,           # 'development', 'staging', 'production'
                'jobs': List[dict],           # Job details (optional)
                'project_id': str,            # External project/repo ID
                'metadata': dict,             # Provider-specific extra data
            }
        """
        pass
    
    def _resolve_binding(self, request, **kwargs):
        """Look up the CICDBinding for this webhook by its binding_id.

        The binding_id is required (the unbound legacy URLs were
        removed). Returns None if the binding is missing, inactive, or
        belongs to a different provider — the caller treats None as an
        immediate rejection.
        """
        from Projects.models import CICDBinding

        binding_id = kwargs.get('binding_id')
        if not binding_id:
            return None

        lookup_type = self.integration_provider_type or self.provider_name
        try:
            return CICDBinding.objects.select_related('integration').get(
                pk=binding_id,
                integration__provider_type=lookup_type,
                is_active=True,
            )
        except CICDBinding.DoesNotExist:
            logger.warning(
                f"[{self.provider_name}] CICDBinding {binding_id} not found"
            )
            return None

    def post(self, request, **kwargs):
        """
        Main webhook handler - common for all providers.

        Flow:
        1. Resolve binding from URL (if binding_id present)
        2. Validate request (provider-specific)
        3. Parse payload (provider-specific)
        4. Create pipeline record
        5. Create deployments (if successful)
        6. Store CI/CD logs
        """
        try:
            # 1. Resolve binding — must succeed before we look at the payload
            binding = self._resolve_binding(request, **kwargs)
            if binding is None:
                logger.warning(
                    f"[{self.provider_name}] Rejecting webhook with no matching binding"
                )
                return Response(
                    {'error': 'Unknown or inactive binding'},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # 2. Validate request (HMAC / shared-secret check) using the binding
            if not self.validate_request(request, binding=binding):
                logger.warning(f"[{self.provider_name}] Invalid webhook request rejected")
                return Response(
                    {'error': 'Invalid webhook signature or token'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # 2. Parse payload
            try:
                if isinstance(request.data, dict):
                    payload = request.data
                else:
                    payload = json.loads(request.body)
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"[{self.provider_name}] Invalid JSON payload: {e}")
                return Response(
                    {'error': 'Invalid JSON payload'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 3. Normalize to standard format
            try:
                normalized = self.parse_pipeline_event(payload)
            except Exception as e:
                logger.error(f"[{self.provider_name}] Failed to parse payload: {e}")
                return Response(
                    {'error': f'Failed to parse webhook: {str(e)}'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Skip events that don't need processing (e.g. non-completed workflows)
            if normalized.get('status') == 'skip':
                return Response({
                    'message': f'{self.provider_name} event acknowledged (no action needed)',
                })

            # Log for debugging
            logger.info(
                f"[{self.provider_name}] Pipeline {normalized.get('pipeline_id')} - "
                f"Status: {normalized.get('status')}, Env: {normalized.get('environment')}"
            )
            
            # 4. Create pipeline record, owned by the binding's organisation and
            # project. Without this the row had neither, so nothing that
            # filters by them (analyses, deploy panels) ever found the build.
            pipeline = self._create_pipeline_record(normalized, binding=binding)
            
            # 5. Create deployments if successful
            deployments_created = 0
            if normalized.get('status') == 'success':
                deployments_created = self._create_deployments(normalized, pipeline, binding=binding)
            
            # 6. Store CI/CD logs for all terminal statuses
            if normalized.get('status') in ('success', 'failed', 'error', 'canceled', 'cancelled'):
                # Inject binding context for org/project resolution fallback
                if binding:
                    try:
                        svc = binding.project_service
                        normalized['_binding_context'] = {
                            'organisation': svc.project.organisation,
                            'project': svc.project,
                            'service_name': svc.name,
                        }
                    except Exception:
                        pass
                self._store_cicd_logs(normalized)
            
            return Response({
                'message': f'{self.provider_name} webhook processed',
                'pipeline_id': normalized.get('pipeline_id'),
                'status': normalized.get('status'),
                'environment': normalized.get('environment'),
                'deployments_created': deployments_created,
            })
            
        except Exception as e:
            logger.exception(f"[{self.provider_name}] Webhook processing error: {e}")
            return Response(
                {'error': f'Internal error: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _create_pipeline_record(self, normalized: dict, binding=None):
        """Create or update Pipeline record in database."""
        from .models import Pipeline

        metadata = dict(normalized.get('metadata') or {})
        env_source = normalized.get('environment_source')
        if env_source:
            metadata['environment_source'] = env_source
        owner = {}
        if binding is not None:
            try:
                svc = binding.project_service
                # Pipeline.project is the legacy GitlabProject link, so the
                # SerOps project goes in the metadata.
                owner = {'organisation': svc.project.organisation}
                metadata.setdefault('serops_project_id', svc.project.id)
                metadata.setdefault('service_name', svc.name)
                metadata.setdefault('binding_type', binding.binding_type)
            except Exception:
                owner = {}

        pipeline, created = Pipeline.objects.update_or_create(
            organisation=owner.pop('organisation', None),
            pipeline_id=str(normalized['pipeline_id']),
            cicd_provider=self.provider_name,
            defaults={
                'status': normalized.get('status', 'unknown'),
                'branch': normalized.get('branch', ''),
                'external_project_id': normalized.get('project_id'),
                'environment': normalized.get('environment'),
                'provider_metadata': metadata,
                **owner,
            }
        )
        
        action = "Created" if created else "Updated"
        logger.info(f"[{self.provider_name}] {action} pipeline record: {pipeline.pipeline_id}")
        
        return pipeline
    
    def _create_deployments(self, normalized: dict, pipeline, binding=None) -> int:
        """Create deployment records for commits in this pipeline."""
        from .deployment_service import DeploymentService
        from .models import CodeChange

        project_service = getattr(binding, 'project_service', None)
        
        commit_shas = normalized.get('commit_shas', [])
        environment = normalized.get('environment', 'development')
        deployments_created = 0
        
        for sha in commit_shas:
            try:
                # Look up code change (provider-agnostic)
                code_change = CodeChange.objects.filter(commit_sha=sha).first()
                
                if code_change:
                    # Link commit to this pipeline (Commit-to-Build Correlation)
                    if not code_change.pipeline:
                        code_change.pipeline = pipeline
                        code_change.save(update_fields=['pipeline'])
                    
                    DeploymentService.create_deployment(
                        code_change=code_change,
                        environment=environment,
                        deployed_at=timezone.now(),
                        pipeline=pipeline,
                        status='success',
                        deployed_by='CI/CD',
                        project_service=project_service,
                    )
                    deployments_created += 1
                else:
                    logger.debug(f"[{self.provider_name}] CodeChange not found for SHA: {sha[:8]}")
                    
            except Exception as e:
                logger.warning(f"[{self.provider_name}] Failed to process commit {sha[:8]}: {e}")
        
        if deployments_created:
            logger.info(
                f"[{self.provider_name}] Created {deployments_created} deployments → {environment}"
            )
        
        return deployments_created
    
    def _store_cicd_logs(self, normalized: dict):
        """Store CI/CD logs to Elasticsearch."""
        from .utils import store_cicd_logs_generic
        
        try:
            store_cicd_logs_generic(self.provider_name, normalized)
        except Exception as e:
            logger.error(f"[{self.provider_name}] Failed to store CI/CD logs: {e}")


# Helper function to detect environment from common patterns
def detect_environment_generic(
    branch: str = None, job_name: str = None,
    explicit_env: str = None, project_id: str = None,
) -> str:
    """Detect environment from common patterns; returns the env name only.

    Kept as a thin wrapper for callers that don't need the detection
    provenance. New code should call ``detect_environment_with_source``.
    """
    env, _ = detect_environment_with_source(
        branch=branch, job_name=job_name,
        explicit_env=explicit_env, project_id=project_id,
    )
    return env


def detect_environment_with_source(
    branch: str = None, job_name: str = None,
    explicit_env: str = None, project_id: str = None,
) -> tuple:
    """Detect environment + return which strategy matched.

    Returns ``(env_name, source)`` where ``source`` is one of:
    ``db_pattern``, ``explicit``, ``job_name``, ``branch``, ``default``.

    Surfacing the source lets the pipeline handler log/store *why* an
    environment was picked (E27 debuggability). Users regularly ask
    "why did SerOps tag this deploy as production?" — the answer is
    now first-class metadata instead of an opaque default.

    Priority:
    0. ProjectEnvironment DB patterns (if project_id provided)
    1. Explicit environment (if set in CI/CD config)
    2. Job/workflow name patterns
    3. Branch patterns
    4. Default to development
    """
    # 0. ProjectEnvironment DB lookup (if project_id provided and branch available)
    if project_id and branch:
        try:
            from Projects.models import SCMBinding, ProjectEnvironment, ProjectService
            from providers.models import GitlabProject

            project = None

            # Try SCMBinding first (works for all providers)
            scm_binding = SCMBinding.objects.filter(
                repository_id=project_id
            ).select_related('project_service__project').first()
            if scm_binding:
                project = scm_binding.project_service.project

            # Fallback: GitlabProject legacy lookup
            if not project:
                gp = GitlabProject.objects.filter(project_id=project_id).first()
                if gp:
                    ps = ProjectService.objects.filter(
                        gitlab_project=gp
                    ).select_related('project').first()
                    if ps:
                        project = ps.project

            if project:
                for env in ProjectEnvironment.objects.filter(project=project, is_active=True):
                    if env.matches_branch(branch):
                        return env.name, 'db_pattern'
        except Exception:
            pass

    # 1. Explicit environment
    if explicit_env:
        env_lower = explicit_env.lower()
        if env_lower in ['production', 'prod']:
            return 'production', 'explicit'
        elif env_lower in ['staging', 'stage', 'stag']:
            return 'staging', 'explicit'
        elif env_lower in ['development', 'dev', 'develop']:
            return 'development', 'explicit'

    # 2. Job name patterns
    if job_name:
        job_lower = job_name.lower()
        if 'prod' in job_lower or 'production' in job_lower:
            return 'production', 'job_name'
        elif 'stag' in job_lower or 'staging' in job_lower:
            return 'staging', 'job_name'
        elif 'dev' in job_lower or 'development' in job_lower:
            return 'development', 'job_name'

    # 3. Branch patterns
    if branch:
        branch_lower = branch.lower()
        if branch_lower in ['main', 'master']:
            return 'production', 'branch'
        elif 'staging' in branch_lower or 'stage' in branch_lower:
            return 'staging', 'branch'
        elif 'develop' in branch_lower or 'dev' in branch_lower:
            return 'development', 'branch'

    # 4. Default
    return 'development', 'default'
