"""
GitLab CI/CD Webhook Handler

Processes GitLab webhook events (push, pipeline, build) using the
BaseCICDWebhookHandler abstraction.

Setup in GitLab:
1. Go to project Settings → Webhooks
2. URL: https://your-backend.com/api/webhooks/gitlab/<binding_id>/
3. Triggers: Push events, Pipeline events, Job events
"""

import hmac
import json
import logging

from rest_framework.response import Response

from .webhook_base import BaseCICDWebhookHandler, detect_environment_with_source

logger = logging.getLogger(__name__)


class GitLabCICDWebhookHandler(BaseCICDWebhookHandler):
    """
    GitLab webhook handler.

    Handles three event types:
    - push: Code changes → dispatches Celery task
    - pipeline: Pipeline status → creates records + deployments + logs
    - build: Job events → retrieves detailed job logs
    """

    provider_name = 'gitlab'

    def validate_request(self, request, binding=None) -> bool:
        """
        Validate GitLab webhook request.

        Checks X-Gitlab-Token header against binding.webhook_secret
        using constant-time comparison.
        """
        if not binding or not binding.webhook_secret:
            logger.warning("[gitlab] No binding or webhook_secret — rejecting")
            return False

        token = request.headers.get('X-Gitlab-Token', '')
        if not token:
            logger.warning("[gitlab] Missing X-Gitlab-Token header")
            return False

        return hmac.compare_digest(token, binding.webhook_secret)

    def parse_pipeline_event(self, payload: dict) -> dict:
        """
        Parse GitLab pipeline webhook payload into normalized format.

        Maps GitLab's pipeline structure to our standard format:
        - object_attributes.id → pipeline_id
        - object_attributes.status → status
        - object_attributes.ref → branch
        - object_attributes.sha → commit_shas[0]
        - detect_environment_from_pipeline() → environment (5 strategies)
        - builds[] → jobs[]
        - project.id → project_id
        """
        object_attributes = payload.get('object_attributes', {})
        project_data = payload.get('project', {})
        ref = object_attributes.get('ref', '')
        project_id = str(project_data.get('id', ''))

        # Extract deploy job name for environment heuristic
        deploy_job_name = ''
        jobs = []
        for build in payload.get('builds', []):
            name = build.get('name', '')
            stage = build.get('stage', '')
            if 'deploy' in name.lower() or stage.lower() == 'deploy':
                deploy_job_name = name
            jobs.append({
                'id': str(build.get('id', '')),
                'name': name,
                'stage': stage,
                'status': build.get('status', ''),
                'duration': build.get('duration'),
            })

        environment, env_source = detect_environment_with_source(
            branch=ref,
            job_name=deploy_job_name,
            project_id=project_id,
            organisation=self._binding_organisation(),
        )

        head_sha = object_attributes.get('sha', '')

        return {
            'pipeline_id': str(object_attributes.get('id', '')),
            'status': object_attributes.get('status', 'unknown'),
            'branch': ref,
            'commit_shas': [head_sha] if head_sha else [],
            'environment': environment,
            'environment_source': env_source,
            'jobs': jobs,
            'project_id': project_id,
            'metadata': {
                'source': object_attributes.get('source'),
                'tag': object_attributes.get('tag', False),
                'url': object_attributes.get('url', ''),
            },
        }

    def post(self, request, **kwargs):
        """
        Route GitLab webhook by event type.

        GitLab sends different event types via object_kind:
        - push: Code pushed to repository
        - pipeline: Pipeline status change
        - build: Job/build status change
        """
        try:
            binding = self._resolve_binding(request, **kwargs)
            if not self.validate_request(request, binding=binding):
                logger.warning("[gitlab] Invalid webhook request rejected")
                return Response(
                    {'error': 'Invalid webhook signature or token'},
                    status=403,
                )
            self.binding = binding

            try:
                payload = json.loads(request.body)
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"[gitlab] Invalid JSON payload: {e}")
                return Response({'error': 'Invalid JSON payload'}, status=400)
            if not isinstance(payload, dict):
                return Response({'error': 'Invalid JSON payload'}, status=400)

            # The token proves the request comes from this binding's webhook,
            # not that the project named in the body is the binding's: a
            # tenant holding its own token could name another organisation's
            # GitLab project and write to its pipelines and code changes
            # (security review 2026-11, finding 2).
            if not self._payload_matches_binding(payload, binding):
                logger.warning(
                    "[gitlab] Payload project does not match binding %s — rejected", binding.pk,
                )
                return Response(
                    {'error': "Payload project does not match this webhook's binding"},
                    status=403,
                )

            logger.debug(f'Webhook payload: {payload}')
            object_kind = payload.get('object_kind')

            if object_kind == 'push':
                return self._handle_push_event(payload)
            elif object_kind == 'build':
                return self._handle_build_event(payload)
            elif object_kind == 'pipeline':
                return self._handle_pipeline_event(payload, binding=binding)
            else:
                return Response({
                    'message': 'Webhook received, but not for a handled event type.'
                })

        except Exception as e:
            import traceback
            logger.error(f"Error: {str(e)}")
            traceback.print_exc()
            logger.error(f"GitLab webhook processing failed: {str(e)}")
            return Response(
                {'error': 'Webhook processing failed', 'details': str(e)},
                status=500,
            )

    @staticmethod
    def _payload_project(payload):
        """(id, path_with_namespace) of the GitLab project the payload names.

        Push and pipeline events carry a ``project`` object; job (build)
        events carry ``project_id`` at the top level.
        """
        project = payload.get('project') if isinstance(payload.get('project'), dict) else {}
        project_id = project.get('id') or payload.get('project_id')
        path = project.get('path_with_namespace') or ''
        return (str(project_id) if project_id not in (None, '') else ''), str(path)

    def _payload_matches_binding(self, payload, binding):
        """True when the payload's project is the binding's GitLab project.

        ``CICDBinding.pipeline_id`` holds the GitLab project id (or its
        ``group/project`` path) for GitLab bindings. Only a binding with no
        project recorded is checked by organisation alone, through the
        organisation-scoped lookups below.
        """
        expected = str(binding.pipeline_id or '').strip()
        if not expected:
            return True
        project_id, path = self._payload_project(payload)
        if not project_id and not path:
            # Nothing to act on (e.g. a GitLab test event without a project);
            # the handlers below find no project and do nothing.
            return True
        return expected == project_id or (bool(path) and expected.lower() == path.lower())

    def _binding_gitlab_project(self, project_id):
        """The organisation's legacy GitlabProject row for ``project_id``.

        Scoped to the binding's organisation: ``project_id`` comes from the
        payload (security review 2026-11, finding 2).
        """
        from .models import GitlabProject

        organisation = self._binding_organisation()
        if organisation is None or not project_id:
            return None
        return GitlabProject.objects.filter(
            project_id=str(project_id), organisation=organisation,
        ).first()

    def _handle_push_event(self, payload):
        """Handle push events by dispatching Celery task for code change tracking."""
        from .tasks import process_push_event

        project_data = payload.get('project') or {}
        project_id = project_data.get('id')
        commits = payload.get('commits', [])
        branch = payload.get('ref', '').replace('refs/heads/', '')

        organisation = self._binding_organisation()
        if project_id and commits and organisation is not None:
            process_push_event.delay(
                project_id=str(project_id),
                commits_data=commits,
                branch=branch,
                organisation_id=organisation.id,
            )
            logger.info(f"Push event received: {len(commits)} commits for project {project_id}")
            return Response({
                'message': f'Processing {len(commits)} commits from push event',
                'project_id': project_id,
                'branch': branch,
            })

        return Response({'message': 'Push event received but no commits found'})

    def _handle_build_event(self, payload):
        """Handle build/job events by dispatching async log retrieval."""
        job_status = payload.get('build_status')
        if job_status in ('pending', 'running', 'created'):
            return Response({'message': 'Webhook received, but not for a handled event type.'})

        project_id = payload.get('project_id')
        job_id = payload.get('build_id')
        job_name = payload.get('build_name')
        pipeline_id = payload.get('pipeline_id')
        pipeline_branch = payload.get('ref')
        job_time = payload.get('build_duration')
        job_owner = (payload.get('user') or {}).get('username')

        logger.debug(f"Processing: job_id={job_id}, pipeline_id={pipeline_id}, project_id={project_id}")

        gitlab_project = self._binding_gitlab_project(project_id)
        if gitlab_project is None:
            logger.warning(f"[gitlab] Job event for project {project_id} not registered in the binding's organisation")
            return Response({'message': 'Webhook received, but no matching project.'})

        from .tasks import retrieve_gitlab_job_logs
        retrieve_gitlab_job_logs.delay(
            project_id, pipeline_id, pipeline_branch,
            job_id, job_name, job_status, job_time, job_owner,
            organisation_id=gitlab_project.organisation_id,
        )

        # Log URL for observability
        from .utils import get_gitlab_api_base
        gitlab_base_url = get_gitlab_api_base(project=gitlab_project)

        job_url = f"{gitlab_base_url}/-/jobs/{job_id}"
        if job_status == 'failed':
            logger.error(
                f"GitLab job failed - project_id: {project_id}, job_id: {job_id}, "
                f"job_name: {job_name}, status: {job_status}, url: {job_url}"
            )
        else:
            logger.info(
                f"GitLab job finished - project_id: {project_id}, job_id: {job_id}, "
                f"job_name: {job_name}, status: {job_status}, url: {job_url}"
            )

        return Response({'message': 'Logs retrieval initiated for job.'})

    def _handle_pipeline_event(self, payload, binding=None):
        """Handle pipeline events: create records, deployments, and store logs."""
        normalized = self.parse_pipeline_event(payload)

        logger.info(
            f"Pipeline {normalized['pipeline_id']} detected environment: "
            f"{normalized['environment']} (source={normalized.get('environment_source', 'unknown')}) "
            f"status: {normalized['status']}"
        )

        # Create/update pipeline record
        pipeline = self._create_pipeline_record(normalized, binding=binding)

        # Inject binding context for CI/CD log storage (org/project resolution)
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

        # Store CI/CD logs (indexes only failed jobs internally)
        try:
            self._store_cicd_logs(normalized)
        except Exception as e:
            logger.error(f"Error storing CI/CD logs: {e}")

        # Create deployments for ALL terminal statuses (for root cause analysis)
        pipeline_status = normalized.get('status')
        if pipeline_status in ('success', 'failed', 'canceled'):
            try:
                self._create_deployments(normalized, pipeline, binding=binding)
            except Exception as e:
                logger.error(f"Error creating deployments: {e}", exc_info=True)

        return Response({'message': 'pipeline processed'})

    def _create_pipeline_record(self, normalized, binding=None):
        """
        Create pipeline record with GitLab-specific legacy fields.

        Sets standard fields via super() (cicd_provider, external_project_id,
        the binding's organisation) plus the legacy project FK (GitlabProject)
        when the organisation has that project.
        """
        pipeline = super()._create_pipeline_record(normalized, binding=binding)

        # Set legacy GitLab-specific fields
        project_id = normalized.get('project_id')
        gitlab_project = self._binding_gitlab_project(project_id)

        if gitlab_project:
            pipeline.project = gitlab_project
            pipeline.save(update_fields=['project'])
        else:
            logger.warning(f"Received pipeline event for unknown project {project_id}")

        return pipeline

    def _create_deployments(self, normalized, pipeline, binding=None):
        """
        Create deployments with GitLab-specific bidirectional CodeChange linking.

        Differences from base handler:
        - Creates deployments for ALL terminal statuses (not just success)
        - Links CodeChanges to Pipeline (SHA match + branch fallback)
        - Uses DeploymentService.create_deployments_from_pipeline()
        """
        from .deployment_service import DeploymentService
        from .models import CodeChange

        environment = normalized.get('environment', 'development')
        pipeline_status = normalized.get('status')
        head_sha = normalized['commit_shas'][0] if normalized.get('commit_shas') else None
        branch = normalized.get('branch', '')
        project_id = normalized.get('project_id')

        gitlab_project = self._binding_gitlab_project(project_id)
        if not gitlab_project or not head_sha:
            logger.warning(f"No head SHA or project for pipeline {normalized['pipeline_id']}")
            return 0

        # Strategy 1: Exact SHA match
        code_changes = CodeChange.objects.filter(
            gitlab_project=gitlab_project,
            commit_sha=head_sha,
        )

        # Strategy 2: Branch + unlinked fallback
        if not code_changes.exists():
            code_changes = CodeChange.objects.filter(
                gitlab_project=gitlab_project,
                branch=branch,
                pipeline__isnull=True,
            ).order_by('-timestamp')[:10]

        # Link CodeChanges to Pipeline and create deployments
        code_changes_to_deploy = []
        for cc in code_changes:
            if not cc.pipeline:
                cc.pipeline = pipeline
                cc.save(update_fields=['pipeline'])
                logger.debug(f"Linked CodeChange {cc.commit_sha[:8]} to pipeline {normalized['pipeline_id']}")
            code_changes_to_deploy.append(cc)

        if code_changes_to_deploy:
            commit_shas = [cc.commit_sha for cc in code_changes_to_deploy]
            deployments = DeploymentService.create_deployments_from_pipeline(
                pipeline=pipeline,
                commit_shas=commit_shas,
                environment=environment,
                status=pipeline_status,
            )
            logger.info(
                f"Created {len(deployments)} deployment records for "
                f"pipeline {normalized['pipeline_id']} → {environment} (status: {pipeline_status})"
            )
            return len(deployments)
        else:
            logger.info(f"No CodeChanges found to deploy for pipeline {normalized['pipeline_id']}")
            return 0
