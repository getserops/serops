import re
import requests
from urllib.parse import urlparse
from .models import GitlabProject, Pipeline, Job
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def get_gitlab_api_base(project=None, project_id=None, url_hint=None):
    """
    Get the GitLab base URL for API calls. Supports self-hosted GitLab.

    Resolution order:
    1. url_hint — extracts scheme+host from full URLs (e.g. request data)
    2. project.gitlab_url — from a GitlabProject instance
    3. DB lookup by project_id
    4. Fallback to https://gitlab.com
    """
    DEFAULT = 'https://gitlab.com'

    if url_hint:
        parsed = urlparse(url_hint)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}".rstrip('/')

    if project and getattr(project, 'gitlab_url', None):
        return project.gitlab_url.rstrip('/')

    if project_id:
        try:
            gp = GitlabProject.objects.filter(
                project_id=str(project_id)
            ).only('gitlab_url').first()
            if gp and gp.gitlab_url:
                return gp.gitlab_url.rstrip('/')
        except Exception:
            pass

    return DEFAULT


def _resolve_log_provider(organisation):
    """Resolve the LogProvider for an organisation, with graceful fallback."""
    try:
        from integrations.registry import IntegrationRegistry
        return IntegrationRegistry.get_log_provider_for_org(organisation)
    except Exception as e:
        logger.warning(f"Could not resolve LogProvider for org {organisation}: {e}")
        return None


def _resolve_environment(project, branch):
    """Resolve environment name from project's environment patterns."""
    from providers.webhook_base import detect_environment_generic
    return detect_environment_generic(branch=branch)


def _build_cicd_event_doc(
    org, project, service_name, environment,
    pipeline_id, pipeline_ref, pipeline_status, pipeline_url,
    job_id, job_name, job_stage, job_status, job_duration,
    commit_sha='', error_lines=None, scm_provider='gitlab',
    extra_fields=None,
):
    """Build a standardised CI/CD enriched event document with serops_meta namespace."""
    doc = {
        # Flat canonical fields (for unified querying across all providers)
        'organisation_name': getattr(org, 'slug', '') if org else '',
        'project_name': project.name if project else '',
        'service_name': service_name or '',
        'environment': environment or '',
        'log_level': 'ERROR' if job_status in ('failed', 'error', 'failure') else 'INFO',
        # Keep serops_meta for backward compat
        'serops_meta': {
            'org_id': str(org.id) if org else '',
            'org_slug': getattr(org, 'slug', '') if org else '',
            'project_id': str(project.id) if project else '',
            'project_name': project.name if project else '',
            'service_name': service_name or '',
            'environment': environment or '',
            'scm_provider': scm_provider,
        },
        'pipeline': {
            'id': pipeline_id,
            'ref': pipeline_ref or '',
            'status': pipeline_status or '',
            'url': pipeline_url or '',
        },
        'job': {
            'id': job_id,
            'name': job_name or '',
            'stage': job_stage or '',
            'status': job_status or '',
            'duration_seconds': job_duration,
        },
        'event_type': 'cicd_job_failure' if job_status in ('failed', 'error', 'failure') else 'cicd_job_event',
        '@timestamp': datetime.now(timezone.utc).isoformat(),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'commit_sha': commit_sha or '',
        'error_lines': (error_lines or [])[:20],  # Cap at 20 lines
    }
    if extra_fields:
        doc.update(extra_fields)
    return doc



def gitlab_retrieve_job_logs(project_id, pipeline_id, pipeline_branch, job_id, job_name, job_status, job_time, job_owner):
    """
    Retrieve job logs from GitLab API and save to file only (no direct Elasticsearch indexing)
    """
    logger = logging.getLogger(__name__)

    if not job_id:
        return "Missing job ID"
        
    project_instance = GitlabProject.objects.filter(project_id=project_id).first()
    if not project_instance:
        return f"Project with ID {project_id} not found"
    
    # Get project name and service name with better error handling
    project_name = 'unknown'  # Default fallback
    service_name = 'unknown'  # Default fallback
    try:
        from Projects.models import ProjectService
        if project_instance:
            project_service = ProjectService.objects.filter(gitlab_project=project_instance).first()
            if project_service and project_service.project:
                project_name = project_service.project.name.lower().replace(' ', '_').replace('-', '_')
                project_name = ''.join(c for c in project_name if c.isalnum() or c == '_')
                if not project_name:
                    project_name = 'unknown'

            service_name = project_instance.name or 'unknown'
    except Exception as e:
        logger.error(f"Error getting project name: {e}")
        project_name = 'unknown'
        service_name = 'unknown'
        
    access_token = project_instance.get_access_token()
    gitlab_url = get_gitlab_api_base(project=project_instance)
    job_logs_url = f'{gitlab_url}/api/v4/projects/{project_id}/jobs/{job_id}/trace'
    headers = {'PRIVATE-TOKEN': access_token}

    response = requests.get(job_logs_url, headers=headers, timeout=30)

    if response.status_code == 200:
        job_logs_data = response.text
        
        # Save full logs to database
        project = project_instance
        pipeline, created = Pipeline.objects.get_or_create(
            project=project, 
            pipeline_id=pipeline_id, 
            defaults={
                'branch': pipeline_branch,
                'status': 'unknown',
                'organisation': project.organisation  # Multi-tenancy isolation
            }
        ) 

        job_instance, created = Job.objects.get_or_create(
            pipeline=pipeline, 
            job_id=job_id, 
            defaults={'name': job_name}
        )
        
        # Use correct field names from Job model
        job_instance.logs = job_logs_data  # Fixed: was 'log', model has 'logs'
        job_instance.status = job_status
        job_instance.save()
        
        # === Store enriched event doc via LogProvider for FAILED jobs ===
        if job_status == 'failed':
            try:
                from integrations.schemas import LogStream
                from providers.tasks import filter_error_warning_lines

                org = project_instance.organisation
                project_obj = project_service.project if project_service else None
                environment = _resolve_environment(project_obj, pipeline_branch) if project_obj else 'development'

                error_lines = filter_error_warning_lines(job_logs_data)

                # Store error_summary on Job model (replaces full logs storage)
                job_instance.error_summary = '\n'.join(error_lines[:20])
                job_instance.save(update_fields=['error_summary'])

                event_doc = _build_cicd_event_doc(
                    org=org,
                    project=project_obj,
                    service_name=service_name,
                    environment=environment,
                    pipeline_id=pipeline_id,
                    pipeline_ref=pipeline_branch,
                    pipeline_status='failed',
                    pipeline_url='',
                    job_id=job_id,
                    job_name=job_name,
                    job_stage='',
                    job_status=job_status,
                    job_duration=job_time,
                    error_lines=error_lines,
                    scm_provider='gitlab',
                )

                provider = _resolve_log_provider(org)
                if provider:
                    stream = LogStream(
                        category='cicd',
                        org_slug=getattr(org, 'slug', 'default'),
                        project=project_name,
                        service=service_name,
                        environment=environment,
                    )
                    provider.index([event_doc], stream=stream)
                    logger.info(f"✅ Indexed CI/CD event doc via LogProvider: {job_name}")
                else:
                    logger.warning(f"No LogProvider found, skipping event doc indexing for {job_name}")
            except Exception as e:
                logger.error(f"Failed to index CI/CD event doc: {e}", exc_info=True)
        # === END event doc indexing ===

        return "Logs processed and indexed via LogProvider"

    else:
        logger.error(f"Failed to retrieve logs for job {job_id}: {response.status_code} - {response.reason}")
        return f'Error retrieving logs for job {job_id}: {response.status_code} - {response.text}'

def gitlab_update_pipeline_status(project_id, pipeline_id,status):

    project= GitlabProject.objects.filter(project_id=project_id).first()
    pipeline = Pipeline.objects.filter(project=project, pipeline_id=pipeline_id).first()
    pipeline.status=status
    pipeline.save()
    return f'pipeline status with id {pipeline_id} on project {project_id} updated'

def extract_error_lines(log_string):

    error_keywords = ["error", "warning", "exception","fatal","failed","exit","not found"]
    error_lines = []
    
    for line in log_string.splitlines():
        for keyword in error_keywords:
            if keyword.lower() in line.lower() and line not in error_lines:
                #error_lines.append(line)
                
                # Get three lines after the error line
                for i in range(3):
                    next_line = log_string.splitlines(keepends=False)[log_string.splitlines(keepends=False).index(line) + i-1]
                    if next_line and next_line not in error_lines:         
                        #print(next_line in error_lines, "line",line)
                        error_lines.append(next_line)

    
    return "\n".join(error_lines) if error_lines else ""


def extract_gitlab_info(url):
    try:
        url_parts = url.split('/')
        username = url_parts[3]
        repository = url_parts[4]
        return username, repository
    except IndexError:
        return '', ''

def trigger_pipeline_run( project_id,access_token,pipeline_id):
    gitlab_base = get_gitlab_api_base(project_id=project_id)
    url = f"{gitlab_base}/api/v4/projects/{project_id}/pipelines/{pipeline_id}/retry"
    headers = {
        "PRIVATE-TOKEN": access_token
    }


    response = requests.post(url, headers=headers, json={}, timeout=30)
    if response.status_code not in [200,201] :
        return False
    logger.debug(f"Response status: {response.status_code}")
    return True


def cancel_pipeline_run(  project_id,access_token,pipeline_id):
    gitlab_base = get_gitlab_api_base(project_id=project_id)
    url = f"{gitlab_base}/api/v4/projects/{project_id}/pipelines/{pipeline_id}/cancel"
    headers = {
        "PRIVATE-TOKEN": access_token
    }

    response = requests.post(url, headers=headers ,json={}, timeout=30)
    if response.status_code not in [200,201] :
        return False
    logger.debug(f"Response status: {response.status_code}")
    return None


def get_project_name_from_pipeline(pipeline_data: dict) -> str:
    """
    Extract and sanitize project name from webhook payload.
    Matches existing index naming convention: ci_cd-logs-{project_name}
    """
    try:
        project_id = pipeline_data.get('project', {}).get('id')
        if not project_id:
            return 'unknown'
        
        from providers.models import GitlabProject
        from Projects.models import ProjectService
        
        gitlab_project = GitlabProject.objects.filter(project_id=str(project_id)).first()
        if gitlab_project:
            project_service = ProjectService.objects.filter(gitlab_project=gitlab_project).first()
            if project_service and project_service.project:
                # Same sanitization as Fluentd logs
                project_name = project_service.project.name.lower().replace(' ', '_').replace('-', '_')
                project_name = ''.join(c for c in project_name if c.isalnum() or c == '_')
                return project_name if project_name else 'unknown'
        
        return 'unknown'
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting project name from pipeline: {e}")
        return 'unknown'


def detect_environment_from_pipeline(pipeline_data: dict) -> str:
    """
    Detects the target environment from a GitLab pipeline webhook payload.
    
    Detection strategies (in priority order):
    1. ProjectEnvironment branch patterns (user-configured)
    2. Environment variables (CI_ENVIRONMENT_NAME, DEPLOY_ENV, ENVIRONMENT)
    3. Job name patterns (deploy-to-production, deploy-staging, etc.)
    4. Branch patterns (main/master -> production, develop -> development)
    5. Git tags (any tag -> production)
    
    Args:
        pipeline_data: GitLab webhook payload dictionary
        
    Returns:
        Environment string: 'development', 'staging', or 'production'
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Get branch/ref info
    ref = pipeline_data.get('object_attributes', {}).get('ref', '').lower()
    project_data = pipeline_data.get('project', {})
    project_id = project_data.get('id')
    
    # Strategy 0: Check ProjectEnvironment branch patterns (user-configured)
    try:
        from .models import GitlabProject
        from Projects.models import ProjectService, ProjectEnvironment
        
        gitlab_project = GitlabProject.objects.filter(project_id=str(project_id)).first()
        if gitlab_project:
            service = ProjectService.objects.filter(gitlab_project=gitlab_project).first()
            if service:
                for env in ProjectEnvironment.objects.filter(project=service.project, is_active=True):
                    if env.matches_branch(ref):
                        logger.debug(f"Branch '{ref}' matched ProjectEnvironment '{env.name}'")
                        return env.name
    except Exception as e:
        logger.debug(f"Could not check ProjectEnvironment patterns: {e}")
    
    # Strategy 1: Check environment variables from CI/CD
    variables = pipeline_data.get('object_attributes', {}).get('variables', [])
    for var in variables:
        if var.get('key') in ['CI_ENVIRONMENT_NAME', 'DEPLOY_ENV', 'ENVIRONMENT']:
            env_value = var.get('value', '').lower()
            
            if env_value in ['production', 'prod']:
                return 'production'
            elif env_value in ['staging', 'stag', 'stage']:
                return 'staging'
            elif env_value in ['development', 'dev', 'develop']:
                return 'development'
    
    # Strategy 2: Check job names for deployment patterns
    builds = pipeline_data.get('builds', [])
    for build in builds:
        job_name = build.get('name', '').lower()
        stage = build.get('stage', '').lower()
        
        # Only check deploy-related jobs
        if 'deploy' in job_name or stage == 'deploy':
            if 'prod' in job_name or 'production' in job_name:
                return 'production'
            elif 'stag' in job_name or 'staging' in job_name:
                return 'staging'
            elif 'dev' in job_name or 'development' in job_name:
                return 'development'
    
    # Strategy 3: Check branch name (hardcoded fallback)
    if ref in ['main', 'master']:
        return 'production'
    elif 'staging' in ref or ref == 'stag':
        return 'staging'
    elif 'develop' in ref or ref == 'dev' or 'feature' in ref:
        return 'development'
    
    # Strategy 4: Check if triggered by tag (tags usually = production releases)
    if pipeline_data.get('object_attributes', {}).get('tag', False):
        return 'production'
    
    # Default: assume development (safer than production)
    logger.warning(
        f"Could not detect environment from pipeline. "
        f"Ref: {ref}, Builds: {[b.get('name') for b in builds]}. "
        f"Defaulting to 'development'"
    )
    return 'development'


def store_cicd_logs_generic(provider_name: str, normalized_data: dict):
    """
    Store CI/CD event documents via LogProvider (provider-agnostic).
    
    Works for any CI/CD provider: GitLab, GitHub Actions, Jenkins, Azure DevOps, etc.
    Uses normalized data format from BaseCICDWebhookHandler.parse_pipeline_event().
    
    Args:
        provider_name: CI/CD provider name ('gitlab', 'github_actions', 'jenkins', etc.)
        normalized_data: Normalized pipeline data dict
    """
    from integrations.schemas import LogStream
    
    try:
        project_id = normalized_data.get('project_id', 'unknown')
        pipeline_id = normalized_data.get('pipeline_id')
        environment = normalized_data.get('environment', 'development')

        # Resolve org context (try binding context first, then GitlabProject fallback)
        org = None
        project_obj = None
        service_name = ''

        # Preferred: use binding context injected by webhook handler
        binding_ctx = normalized_data.get('_binding_context')
        if binding_ctx:
            org = binding_ctx.get('organisation')
            project_obj = binding_ctx.get('project')
            service_name = binding_ctx.get('service_name', '')

        # Fallback: legacy GitlabProject lookup
        if not org:
            try:
                from Projects.models import ProjectService
                gitlab_proj = GitlabProject.objects.filter(project_id=project_id).first()
                if gitlab_proj:
                    org = gitlab_proj.organisation
                    ps = ProjectService.objects.filter(gitlab_project=gitlab_proj).select_related('project').first()
                    if ps:
                        project_obj = ps.project
                        service_name = ps.name or gitlab_proj.name
            except Exception:
                pass

        provider = _resolve_log_provider(org)
        if not provider:
            logger.warning(f"[{provider_name}] No LogProvider for org={org}, skipping CI/CD event indexing")
            return

        # Sanitize project name for stream (prefer project object name over raw project_id)
        raw_project = project_obj.name if project_obj and hasattr(project_obj, 'name') else str(project_id)
        safe_project = raw_project.lower().replace('/', '_').replace(' ', '_')
        safe_project = ''.join(c for c in safe_project if c.isalnum() or c in ('_', '-'))

        stream = LogStream(
            category='cicd',
            org_slug=getattr(org, 'slug', 'default'),
            project=safe_project or 'unknown',
            service=service_name,
            environment=environment,
        )

        # Build event docs
        jobs = normalized_data.get('jobs', [])
        event_docs = []

        # Index per-job docs for failed jobs
        if jobs:
            for job in jobs:
                job_status = job.get('status', normalized_data.get('status', ''))
                if job_status not in ('failed', 'error', 'failure'):
                    continue
                event_docs.append(_build_cicd_event_doc(
                    org=org,
                    project=project_obj,
                    service_name=service_name,
                    environment=environment,
                    pipeline_id=pipeline_id,
                    pipeline_ref=normalized_data.get('branch', ''),
                    pipeline_status=normalized_data.get('status', ''),
                    pipeline_url='',
                    job_id=job.get('id'),
                    job_name=job.get('name'),
                    job_stage=job.get('stage'),
                    job_status=job_status,
                    job_duration=job.get('duration'),
                    commit_sha=','.join(normalized_data.get('commit_shas', [])),
                    scm_provider=provider_name,
                ))

        # Always emit a pipeline-level summary doc for terminal statuses
        pipeline_status = normalized_data.get('status', '')
        if pipeline_status in ('success', 'failed', 'error', 'canceled', 'cancelled'):
            event_docs.append(_build_cicd_event_doc(
                org=org,
                project=project_obj,
                service_name=service_name,
                environment=environment,
                pipeline_id=pipeline_id,
                pipeline_ref=normalized_data.get('branch', ''),
                pipeline_status=pipeline_status,
                pipeline_url='',
                job_id=None,
                job_name='pipeline',
                job_stage='',
                job_status=pipeline_status,
                job_duration=None,
                commit_sha=','.join(normalized_data.get('commit_shas', [])),
                scm_provider=provider_name,
            ))

        if event_docs:
            count = provider.index(event_docs, stream=stream)
            logger.info(
                f"✅ [{provider_name}] Indexed {count} CI/CD event docs via LogProvider "
                f"(env: {environment}, pipeline: {pipeline_id})"
            )
        
    except Exception as e:
        logger.error(f"[{provider_name}] Error storing CI/CD event docs: {e}", exc_info=True)