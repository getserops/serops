from celery import shared_task
import requests
import re
from datetime import datetime, timezone

from providers.utils import gitlab_retrieve_job_logs, get_gitlab_api_base
from .models import GitlabProject

def filter_error_warning_lines(log_text):
    """
    Remove ANSI escape sequences and filter lines containing error/warning keywords.
    Returns a list of individual log entries with cleaned messages.
    """
    # Remove both types of ANSI escape codes
    ansi_escape = re.compile(r'(\x1B|\u001b)\[[0-?]*[ -/]*[@-~]')
    clean_log = ansi_escape.sub('', log_text)
    
    # Also remove common section markers and header patterns
    clean_log = re.sub(r'section_(start|end):[0-9]+:[a-z_]+', '', clean_log)
    
    # Define error and warning patterns
    keywords = [
        "error", "warning", "failed", "fatal", "exception", 
        "exit code", "not found", "denied", "cannot", "could not",
        "timeout", "unable to", "invalid", "failure", "forbidden"
    ]
    
    # Filter out progress indicators and routine messages
    exclude_patterns = [
        r"Downloading \[\=+\>",
        r"Extracting \[\=+\>",
        r"Already exists",
        r"Pull complete",
        r"Verifying Checksum",
        r"Download complete",
        r"Pulling fs layer",
        r"Waiting",
        r"Starting service",
        r"Preparing environment",
        r"^OK:",
        r"pid \d+"
    ]
    
    filtered_entries = []
    for line in clean_log.splitlines():
        line = line.strip()
        
        # Skip empty lines
        if not line:
            continue
            
        # Skip lines matching exclude patterns
        if any(re.search(pattern, line) for pattern in exclude_patterns):
            continue
        
        # Include lines with keywords
        if any(keyword in line.lower() for keyword in keywords):
            # Clean the message to extract only the actual content
            cleaned_message = clean_log_message(line)
            if cleaned_message:
                filtered_entries.append(cleaned_message)
    
    return filtered_entries

def clean_log_message(log_line):
    """
    Extract the actual message content from log lines, removing timestamps and level prefixes.
    """
    # Pattern to match log formats like: time="..." level=... msg="actual message"
    msg_pattern = r'msg="([^"]*)"'
    msg_match = re.search(msg_pattern, log_line)
    if msg_match:
        return msg_match.group(1)
    
    # Pattern to match formats like: [timestamp] [level] actual message
    bracket_pattern = r'^\[.*?\]\s*\[.*?\]\s*(.+)$'
    bracket_match = re.search(bracket_pattern, log_line)
    if bracket_match:
        return bracket_match.group(1)
    
    # Pattern to match formats like: timestamp level: actual message
    timestamp_level_pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*?(ERROR|WARNING|INFO|FATAL|DEBUG)[:]\s*(.+)$'
    timestamp_match = re.search(timestamp_level_pattern, log_line, re.IGNORECASE)
    if timestamp_match:
        return timestamp_match.group(2)
    
    # Pattern to match Docker/GitLab CI format: time="..." level=... msg content
    docker_pattern = r'time="[^"]*"\s+level=\w+\s+(.+)$'
    docker_match = re.search(docker_pattern, log_line)
    if docker_match:
        message_part = docker_match.group(1)
        # If it still has msg="...", extract that
        if 'msg="' in message_part:
            msg_match = re.search(r'msg="([^"]*)"', message_part)
            if msg_match:
                return msg_match.group(1)
        return message_part
    
    # If no pattern matches, return the original line (it might already be clean)
    return log_line

@shared_task
def fetch_failed_job_logs_for_project(project_id):
    project = GitlabProject.objects.filter(pk=project_id).first()
    if not project:
        return
    access_token = project.get_access_token()
    gitlab_project_id = project.project_id

    gitlab_base = get_gitlab_api_base(project=project)
    pipelines_url = f"{gitlab_base}/api/v4/projects/{gitlab_project_id}/pipelines"
    headers = {"PRIVATE-TOKEN": access_token}
    pipelines_resp = requests.get(pipelines_url, headers=headers)
    if pipelines_resp.status_code != 200:
        return
    
    pipelines = pipelines_resp.json()[:5]  # Get the 5 most recent pipelines
    for pipeline in pipelines:
        pipeline_id = pipeline['id']
        pipeline_branch = pipeline.get('ref', '')
        
        # Get all jobs for this pipeline (all job types)
        jobs_url = f"{gitlab_base}/api/v4/projects/{gitlab_project_id}/pipelines/{pipeline_id}/jobs"
        jobs_resp = requests.get(jobs_url, headers=headers)
        if jobs_resp.status_code != 200:
            continue
            
        jobs = jobs_resp.json()
        for job in jobs:
            if job['status'] == 'failed':
                job_id = job['id']
                job_name = job['name']
                job_time = job.get('duration')
                job_owner = job.get('user', {}).get('username', 'unknown')
                
                # Process all job types, not just builds
                gitlab_retrieve_job_logs(
                    gitlab_project_id, 
                    pipeline_id,
                    pipeline_branch, 
                    job_id, 
                    job_name, 
                    'failed',
                    job_time, 
                    job_owner
                )

@shared_task
def fetch_failed_job_logs_for_all_projects():
    for project in GitlabProject.objects.all():
        fetch_failed_job_logs_for_project.delay(project.pk)

@shared_task
def process_push_event(
    project_id: str,
    commits_data: list,
    branch: str
):
    """
    Process a push event from GitLab webhook.
    
    Saves commits to the database and triggers async diff fetching.
    
    Args:
        project_id: GitLab project ID
        commits_data: List of commit dicts from webhook payload
        branch: Branch name
    """
    from .code_change_service import CodeChangeService
    from .scm_providers import GitLabProvider
    from .models import CodeChange
    
    logger = __import__('logging').getLogger(__name__)
    
    try:
        # Get GitLab project
        gitlab_project = GitlabProject.objects.filter(project_id=project_id).first()
        if not gitlab_project:
            logger.warning(f"GitLab project {project_id} not found, skipping push event")
            return {"status": "skipped", "reason": "project_not_found"}
        
        # Parse commits using provider
        provider = GitLabProvider(
            project_id=project_id,
            access_token=gitlab_project.get_access_token(),
            base_url=gitlab_project.gitlab_url or None
        )

        # Standardize commits from webhook payload
        standardized_commits = []
        for commit in commits_data:
            standardized_commits.append({
                'sha': commit.get("id"),
                'message': commit.get("message", ""),
                'author_name': commit.get("author", {}).get("name", "Unknown"),
                'author_email': commit.get("author", {}).get("email"),
                'timestamp': commit.get("timestamp"),
                'branch': branch,
                'files_modified': commit.get("modified", []),
                'files_added': commit.get("added", []),
                'files_removed': commit.get("removed", []),
            })
        
        # Save commits using service
        saved = CodeChangeService.save_commits_from_webhook(
            provider='gitlab',
            project_id=project_id,
            commits=standardized_commits,
            gitlab_project=gitlab_project
        )
        
        # Trigger async diff fetching for each saved commit
        for code_change in saved:
            fetch_commit_diff.delay(code_change.id)
        
        logger.info(f"Processed push event for project {project_id}: "
                   f"{len(saved)} commits saved, diffs queued")
        
        return {
            "status": "success",
            "commits_saved": len(saved),
            "project_id": project_id
        }
        
    except Exception as e:
        logger.error(f"Error processing push event for project {project_id}: {str(e)}")
        return {"status": "error", "error": str(e)}


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,)
)
def fetch_commit_diff(self, code_change_id: int):
    """
    Fetch the full diff for a commit and update the CodeChange record.
    
    This task has automatic retry with exponential backoff.
    
    Args:
        code_change_id: ID of the CodeChange record to update
    """
    from .code_change_service import CodeChangeService
    from .models import CodeChange
    
    logger = __import__('logging').getLogger(__name__)
    
    try:
        code_change = CodeChange.objects.select_related('gitlab_project').get(id=code_change_id)
        
        if code_change.diff_fetched:
            logger.debug(f"Diff already fetched for commit {code_change.commit_sha[:8]}")
            return {"status": "skipped", "reason": "already_fetched"}
        
        # Get access token
        access_token = None
        if code_change.gitlab_project:
            access_token = code_change.gitlab_project.get_access_token()
        else:
            # Try to find project by project_id
            gitlab_project = GitlabProject.objects.filter(
                project_id=code_change.project_id
            ).first()
            if gitlab_project:
                access_token = gitlab_project.get_access_token()
        
        if not access_token:
            logger.warning(f"No access token for commit {code_change.commit_sha[:8]}")
            return {"status": "failed", "reason": "no_access_token"}
        
        # Fetch and update diff
        success = CodeChangeService.fetch_and_update_diff(code_change, access_token)
        
        if success:
            return {
                "status": "success",
                "commit_sha": code_change.commit_sha[:8],
                "additions": code_change.additions,
                "deletions": code_change.deletions
            }
        else:
            return {"status": "failed", "reason": "fetch_failed"}
            
    except CodeChange.DoesNotExist:
        logger.error(f"CodeChange {code_change_id} not found")
        return {"status": "failed", "reason": "not_found"}
    except Exception as e:
        logger.error(f"Error fetching diff for CodeChange {code_change_id}: {str(e)}")
        raise  # Will trigger retry


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,)
)
def retrieve_gitlab_job_logs(self, project_id, pipeline_id, pipeline_branch,
                              job_id, job_name, job_status, job_time, job_owner):
    """
    Async Celery task to retrieve GitLab job logs.

    Delegates to the existing gitlab_retrieve_job_logs() utility function.
    Called from GitLab build webhook handler instead of blocking the request thread.
    """
    return gitlab_retrieve_job_logs(
        project_id, pipeline_id, pipeline_branch,
        job_id, job_name, job_status, job_time, job_owner,
    )


@shared_task
def backfill_code_changes(project_id: str, days: int = 7):
    """
    Backfill code changes for a project from the last N days.
    
    Useful when adding code changes to an existing project.
    
    Args:
        project_id: GitLab project ID
        days: Number of days to look back
    """
    from datetime import timedelta
    from django.utils import timezone
    from .code_change_service import CodeChangeService
    from .scm_providers import GitLabProvider
    from .models import CodeChange
    
    logger = __import__('logging').getLogger(__name__)
    
    try:
        gitlab_project = GitlabProject.objects.get(project_id=project_id)

        provider = GitLabProvider(
            project_id=project_id,
            access_token=gitlab_project.get_access_token(),
            base_url=gitlab_project.gitlab_url or None
        )

        since = timezone.now() - timedelta(days=days)
        commits = provider.get_commits(since=since, limit=100)
        
        saved_count = 0
        for commit_data in commits:
            # Check if already exists
            if CodeChange.objects.filter(
                provider='gitlab',
                project_id=project_id,
                commit_sha=commit_data['sha']
            ).exists():
                continue
            
            commit_data['branch'] = 'unknown'  # Branch not available from commits API
            commit_data['files_modified'] = []
            commit_data['files_added'] = []
            commit_data['files_removed'] = []
            
            code_change = CodeChangeService.save_commit_from_webhook(
                provider='gitlab',
                project_id=project_id,
                commit_data=commit_data,
                gitlab_project=gitlab_project
            )
            
            if code_change:
                saved_count += 1
                fetch_commit_diff.delay(code_change.id)
        
        logger.info(f"Backfilled {saved_count} commits for project {project_id}")
        return {"status": "success", "commits_backfilled": saved_count}
        
    except GitlabProject.DoesNotExist:
        logger.error(f"GitLab project {project_id} not found")
        return {"status": "failed", "reason": "project_not_found"}
    except Exception as e:
        logger.error(f"Error backfilling commits: {str(e)}")
        return {"status": "error", "error": str(e)}


def sync_stuck_pipelines():
    """
    Sync pipelines stuck in 'running' status by querying GitLab for actual status.
    
    Called before batch creation to ensure code changes from recently completed
    pipelines are included. Handles the case where webhook was missed during
    service restart.
    
    Returns:
        dict: Summary of synced pipelines and created deployments
    """
    from .models import Pipeline, CodeChange, Deployment
    from .deployment_service import DeploymentService
    from .utils import detect_environment_from_pipeline
    from django.utils import timezone
    
    logger = __import__('logging').getLogger(__name__)
    
    synced_count = 0
    deployments_created = 0
    
    try:
        # Find pipelines stuck in 'running' status
        stuck_pipelines = Pipeline.objects.filter(status='running').select_related('project')
        
        if not stuck_pipelines.exists():
            logger.debug("No stuck pipelines to sync")
            return {"synced": 0, "deployments_created": 0}
        
        logger.info(f"Syncing {stuck_pipelines.count()} pipelines with 'running' status")
        
        for pipeline in stuck_pipelines:
            if not pipeline.project or not pipeline.project.access_token:
                continue

            try:
                # Query GitLab for actual pipeline status
                gitlab_base = get_gitlab_api_base(project=pipeline.project)
                url = f"{gitlab_base}/api/v4/projects/{pipeline.project.project_id}/pipelines/{pipeline.pipeline_id}"
                headers = {"PRIVATE-TOKEN": pipeline.project.get_access_token()}
                response = requests.get(url, headers=headers, timeout=10)
                
                if response.status_code != 200:
                    logger.warning(f"Failed to get pipeline {pipeline.pipeline_id} from GitLab: {response.status_code}")
                    continue
                
                data = response.json()
                actual_status = data.get("status")
                
                # Only process if status changed to terminal state
                if actual_status in ("success", "failed", "canceled") and pipeline.status != actual_status:
                    logger.info(f"Pipeline {pipeline.pipeline_id}: {pipeline.status} → {actual_status}")
                    
                    # Update pipeline status
                    pipeline.status = actual_status
                    pipeline.save(update_fields=["status"])
                    synced_count += 1
                    
                    # Get branch for environment detection
                    branch = data.get("ref", "")
                    
                    # Detect environment using ProjectEnvironment branch patterns
                    environment = "production"  # Default fallback
                    try:
                        from Projects.models import ProjectService, ProjectEnvironment
                        # Find the Project linked to this GitLab project
                        service = ProjectService.objects.filter(gitlab_project=pipeline.project).first()
                        if service:
                            # Check which environment matches this branch
                            for env in ProjectEnvironment.objects.filter(project=service.project, is_active=True):
                                if env.matches_branch(branch):
                                    environment = env.name
                                    logger.debug(f"Branch '{branch}' matched environment '{environment}'")
                                    break
                    except Exception as e:
                        logger.debug(f"Could not detect environment from ProjectEnvironment: {e}")
                    
                    # Find unlinked CodeChanges for this project/branch
                    code_changes = CodeChange.objects.filter(
                        gitlab_project=pipeline.project,
                        pipeline__isnull=True,
                        branch=branch
                    ).order_by('-timestamp')[:10]
                    
                    # Link and create deployments
                    for cc in code_changes:
                        cc.pipeline = pipeline
                        cc.save(update_fields=["pipeline"])
                        
                        # Create deployment
                        deployment, created = Deployment.objects.get_or_create(
                            code_change=cc,
                            environment=environment,
                            defaults={
                                "status": actual_status,
                                "pipeline": pipeline,
                                "deployed_at": timezone.now()
                            }
                        )
                        if created:
                            deployments_created += 1
                            logger.debug(f"Created deployment for {cc.commit_sha[:8]}")
                    
            except Exception as e:
                logger.error(f"Error syncing pipeline {pipeline.pipeline_id}: {e}")
                continue
        
        logger.info(f"Pipeline sync complete: {synced_count} synced, {deployments_created} deployments created")
        return {"synced": synced_count, "deployments_created": deployments_created}
        
    except Exception as e:
        logger.error(f"Error in sync_stuck_pipelines: {e}")
        return {"synced": 0, "deployments_created": 0, "error": str(e)}


@shared_task
def sync_recent_deployments(hours: int = 2):
    """
    Sync recent deployments by querying GitLab API directly.
    
    This is a ROBUST sync that doesn't rely on webhooks being received.
    It queries GitLab for recent pipelines and ensures:
    1. Pipeline records exist in DB
    2. CodeChange records exist (creates from commit if missing)
    3. Deployment records exist for completed pipelines
    
    Called:
    - Before batch creation (ensure fresh data)
    - Periodically via Celery beat (every 10 min)
    
    Args:
        hours: Sync pipelines from the last N hours (default: 2)
    
    Returns:
        dict: Summary with counts of synced/created records
    """
    from .models import GitlabProject, Pipeline, CodeChange, Deployment
    from .code_change_service import CodeChangeService
    from .scm_providers import GitLabProvider
    from django.utils import timezone
    from datetime import timedelta
    
    logger = __import__('logging').getLogger(__name__)
    
    stats = {
        "projects_processed": 0,
        "pipelines_synced": 0,
        "code_changes_created": 0,
        "deployments_created": 0,
        "errors": []
    }
    
    try:
        # Get all GitLab projects with access tokens configured
        gitlab_projects = GitlabProject.objects.exclude(access_token__isnull=True).exclude(access_token='')

        if not gitlab_projects.exists():
            logger.info("No GitLab projects with webhooks found")
        else:
            logger.info(f"Syncing deployments for {gitlab_projects.count()} GitLab projects (last {hours}h)")
        
        for gitlab_project in gitlab_projects:
            if not gitlab_project.access_token:
                continue
                
            stats["projects_processed"] += 1
            
            try:
                # Query GitLab API for recent pipelines
                provider = GitLabProvider(
                    project_id=gitlab_project.project_id,
                    access_token=gitlab_project.get_access_token(),
                    base_url=gitlab_project.gitlab_url or None
                )
                
                # Get pipelines from last N hours
                url = f"{provider.base_url}/api/v4/projects/{gitlab_project.project_id}/pipelines"
                headers = provider._get_headers()
                params = {
                    "per_page": 20,
                    "order_by": "updated_at",
                    "sort": "desc"
                }
                
                response = requests.get(url, headers=headers, params=params, timeout=15)
                
                if response.status_code != 200:
                    logger.warning(f"Failed to fetch pipelines for {gitlab_project.name}: {response.status_code}")
                    continue
                
                pipelines_data = response.json()
                cutoff_time = timezone.now() - timedelta(hours=hours)
                
                for p_data in pipelines_data:
                    pipeline_id = str(p_data['id'])
                    status = p_data['status']
                    branch = p_data['ref']
                    sha = p_data['sha']
                    updated_at = p_data.get('updated_at')
                    
                    # Skip if updated before cutoff
                    if updated_at:
                        try:
                            from dateutil import parser as date_parser
                            updated_dt = date_parser.parse(updated_at)
                            if updated_dt < cutoff_time:
                                continue
                        except Exception:
                            pass
                    
                    # Skip non-terminal pipelines
                    if status not in ('success', 'failed', 'canceled'):
                        continue
                    
                    # Ensure Pipeline record exists
                    pipeline, pipeline_created = Pipeline.objects.get_or_create(
                        organisation=gitlab_project.organisation,  # Multi-tenancy isolation
                        pipeline_id=pipeline_id,
                        defaults={
                            'project': gitlab_project,
                            'status': status,
                            'branch': branch,
                        }
                    )
                    
                    if pipeline_created or pipeline.status != status:
                        pipeline.status = status
                        pipeline.branch = branch
                        pipeline.save()
                        stats["pipelines_synced"] += 1
                    
                    # Ensure CodeChange record exists for this commit
                    code_change = CodeChange.objects.filter(
                        gitlab_project=gitlab_project,
                        commit_sha=sha
                    ).first()
                    
                    if not code_change:
                        # Fetch commit details from GitLab
                        commit_url = f"{provider.base_url}/api/v4/projects/{gitlab_project.project_id}/repository/commits/{sha}"
                        commit_resp = requests.get(commit_url, headers=headers, timeout=10)
                        
                        if commit_resp.status_code == 200:
                            commit_data = commit_resp.json()
                            
                            code_change = CodeChange.objects.create(
                                provider='gitlab',
                                project_id=gitlab_project.project_id,
                                organisation=gitlab_project.organisation,  # Multi-tenancy isolation
                                gitlab_project=gitlab_project,
                                commit_sha=sha,
                                commit_message=commit_data.get('message', '')[:500],
                                author_name=commit_data.get('author_name', 'Unknown'),
                                author_email=commit_data.get('author_email', ''),
                                branch=branch,
                                timestamp=commit_data.get('committed_date'),
                                pipeline=pipeline
                            )
                            stats["code_changes_created"] += 1
                            logger.debug(f"Created CodeChange for {sha[:8]}")
                        else:
                            logger.warning(f"Could not fetch commit {sha[:8]} from GitLab")
                            continue
                    else:
                        # Link existing CodeChange to pipeline if not linked
                        if not code_change.pipeline:
                            code_change.pipeline = pipeline
                            code_change.save(update_fields=['pipeline'])
                    
                    # Detect environment from branch (unified detection)
                    from providers.webhook_base import detect_environment_generic
                    environment = detect_environment_generic(
                        branch=branch,
                        project_id=gitlab_project.project_id,
                    )
                    
                    # Ensure Deployment record exists
                    deployment, dep_created = Deployment.objects.get_or_create(
                        code_change=code_change,
                        environment=environment,
                        defaults={
                            'pipeline': pipeline,
                            'status': status,
                            'deployed_by': 'GitLabSync',
                            'deployed_at': timezone.now()
                        }
                    )
                    
                    if dep_created:
                        stats["deployments_created"] += 1
                        logger.debug(f"Created Deployment for {sha[:8]} → {environment}")
                        
            except Exception as e:
                error_msg = f"Error syncing {gitlab_project.name}: {str(e)}"
                logger.error(error_msg)
                stats["errors"].append(error_msg)
                continue
        
        # === Sync non-GitLab CI/CD providers via CICDBinding ===
        try:
            from Projects.models import CICDBinding
            from providers.webhook_base import detect_environment_generic

            bindings = CICDBinding.objects.filter(
                is_active=True,
                integration__is_active=True,
            ).exclude(
                integration__provider_type='gitlab'
            ).select_related('integration', 'project_service', 'project_service__project')

            for binding in bindings:
                try:
                    provider = binding.get_provider()
                    recent_pipelines = provider.list_recent_pipelines(hours)

                    if not recent_pipelines:
                        continue

                    for p_data in recent_pipelines:
                        p_id = str(p_data['id'])
                        p_status = p_data['status']
                        p_branch = p_data.get('ref', '')
                        p_sha = p_data.get('sha', '')

                        if p_status not in ('success', 'failed', 'canceled'):
                            continue

                        # Ensure Pipeline record
                        pipeline, pipeline_created = Pipeline.objects.get_or_create(
                            organisation=binding.project_service.project.organisation,
                            pipeline_id=p_id,
                            cicd_provider=binding.provider_type,
                            defaults={
                                'status': p_status,
                                'branch': p_branch,
                                'external_project_id': binding.pipeline_id,
                            }
                        )

                        if pipeline_created or pipeline.status != p_status:
                            pipeline.status = p_status
                            pipeline.branch = p_branch
                            pipeline.save()
                            stats["pipelines_synced"] += 1

                        # Ensure CodeChange if SHA available
                        if p_sha:
                            code_change = CodeChange.objects.filter(
                                commit_sha=p_sha
                            ).first()

                            if not code_change:
                                org = getattr(binding.project_service.project, 'organisation', None)
                                code_change = CodeChange.objects.create(
                                    provider=binding.provider_type,
                                    project_id=binding.pipeline_id,
                                    organisation=org,
                                    commit_sha=p_sha,
                                    branch=p_branch,
                                    pipeline=pipeline,
                                )
                                stats["code_changes_created"] += 1
                            elif not code_change.pipeline:
                                code_change.pipeline = pipeline
                                code_change.save(update_fields=['pipeline'])

                            # Detect environment
                            environment = detect_environment_generic(
                                branch=p_branch,
                                project_id=binding.pipeline_id,
                            )

                            # Ensure Deployment record
                            deployment, dep_created = Deployment.objects.get_or_create(
                                code_change=code_change,
                                environment=environment,
                                defaults={
                                    'pipeline': pipeline,
                                    'status': p_status,
                                    'deployed_by': f'{binding.provider_type}Sync',
                                    'deployed_at': timezone.now(),
                                }
                            )
                            if dep_created:
                                stats["deployments_created"] += 1

                    # Update sync timestamp
                    binding.last_sync_at = timezone.now()
                    binding.save(update_fields=['last_sync_at'])

                except Exception as e:
                    error_msg = f"Error syncing {binding.provider_type} binding {binding.pipeline_id}: {str(e)}"
                    logger.error(error_msg)
                    stats["errors"].append(error_msg)
                    continue

        except Exception as e:
            logger.warning(f"Could not sync non-GitLab providers: {e}")

        logger.info(
            f"Deployment sync complete: {stats['pipelines_synced']} pipelines, "
            f"{stats['code_changes_created']} code changes, "
            f"{stats['deployments_created']} deployments created"
        )
        return stats

    except Exception as e:
        logger.error(f"Error in sync_recent_deployments: {e}")
        stats["errors"].append(str(e))
        return stats


@shared_task
def fetch_jenkins_builds_for_binding(binding_id: int):
    """
    Poll Jenkins for recent builds via a CICDBinding and create Pipeline records.

    Used as a fallback when webhooks are not configured. Can be called
    periodically via Celery beat or triggered manually.

    Args:
        binding_id: PK of CICDBinding linked to a Jenkins ProviderIntegration
    """
    from Projects.models import CICDBinding
    from .models import Pipeline
    from django.utils import timezone

    logger = __import__('logging').getLogger(__name__)

    try:
        binding = CICDBinding.objects.select_related(
            'integration', 'project_service', 'project_service__project'
        ).get(pk=binding_id, integration__provider_type='jenkins', is_active=True)
    except CICDBinding.DoesNotExist:
        logger.warning(f"Jenkins CICDBinding {binding_id} not found or inactive")
        return {"status": "skipped", "reason": "binding_not_found"}

    try:
        provider = binding.get_provider()
    except Exception as e:
        logger.error(f"Could not get Jenkins provider for binding {binding_id}: {e}")
        return {"status": "error", "error": str(e)}

    job_name = binding.pipeline_id  # pipeline_id stores the Jenkins job name
    if not job_name:
        return {"status": "skipped", "reason": "no_job_name"}

    builds = provider.list_recent_builds(job_name, count=10)
    created_count = 0

    for build in builds:
        if build.get('building'):
            continue

        result = build.get('result')
        if not result:
            continue

        status_map = {
            'SUCCESS': 'success',
            'FAILURE': 'failed',
            'UNSTABLE': 'failed',
            'ABORTED': 'cancelled',
        }
        status = status_map.get(result, 'unknown')
        pipeline_id = f"{job_name}-{build['number']}"

        _, created = Pipeline.objects.get_or_create(
            organisation=binding.project_service.project.organisation,
            pipeline_id=pipeline_id,
            cicd_provider='jenkins',
            defaults={
                'status': status,
                'branch': '',
                'external_project_id': job_name,
            },
        )
        if created:
            created_count += 1

    # Update sync timestamp
    binding.last_sync_at = timezone.now()
    binding.save(update_fields=['last_sync_at'])

    logger.info(f"Jenkins poll for {job_name}: {created_count} new pipelines from {len(builds)} builds")
    return {"status": "success", "pipelines_created": created_count}


@shared_task
def check_token_expiry_all():
    """
    Periodic task to check token expiry for all active integrations.

    Iterates integrations that have token_expires_at set,
    calls check_token_expiry() to update verification_status and log warnings.
    """
    from .models import ProviderIntegration

    logger = __import__('logging').getLogger(__name__)

    integrations = ProviderIntegration.objects.filter(
        is_active=True,
        token_expires_at__isnull=False,
    )

    expired = 0
    expiring_soon = 0

    for integration in integrations:
        result = integration.check_token_expiry()
        if result == 'expired':
            expired += 1
        elif result == 'expires_soon':
            expiring_soon += 1

    if expired or expiring_soon:
        logger.warning(f"Token expiry check: {expired} expired, {expiring_soon} expiring soon")

    return {"expired": expired, "expiring_soon": expiring_soon}
