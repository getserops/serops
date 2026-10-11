"""
Deployment Service - Handles deployment tracking and queries.

Provides methods for:
- Creating deployment records from CI/CD webhooks
- Querying deployments for batch creation
- Managing deployment status
"""

import logging
from datetime import datetime
from typing import List, Optional
from django.utils import timezone
from django.db.models import Q

from .models import CodeChange, Deployment, Pipeline

logger = logging.getLogger(__name__)


class DeploymentService:
    """Service layer for deployment operations"""
    
    @staticmethod
    def create_deployment(
        code_change: CodeChange,
        environment: str,
        deployed_at: Optional[datetime] = None,
        pipeline: Optional[Pipeline] = None,
        status: str = 'success',
        deployed_by: str = 'CI/CD',
        notes: str = ''
    ) -> Deployment:
        """
        Create a deployment record.
        
        This is the PRIMARY method for recording deployments.
        Called from:
        - GitLab webhook handlers (automatic)
        - Manual deployment API (manual)
        - Backfill scripts (migration)
        
        Args:
            code_change: CodeChange instance
            environment: 'development', 'staging', or 'production'
            deployed_at: Deployment timestamp (defaults to now)
            pipeline: Optional pipeline that deployed the code
            status: Deployment status (default: 'success')
            deployed_by: Who deployed (default: 'CI/CD')
            notes: Optional notes about deployment
        
        Returns:
            Deployment instance (created or existing)
        
        Example:
            >>> code_change = CodeChange.objects.get(commit_sha='abc123')
            >>> deployment = DeploymentService.create_deployment(
            ...     code_change=code_change,
            ...     environment='production',
            ...     pipeline=pipeline
            ... )
        """
        if not deployed_at:
            deployed_at = timezone.now()
        
        # Validate environment
        valid_envs = ['development', 'staging', 'production']
        if environment not in valid_envs:
            raise ValueError(
                f"Invalid environment: {environment}. "
                f"Must be one of {valid_envs}"
            )
        
        # Create or get existing deployment
        deployment, created = Deployment.objects.get_or_create(
            code_change=code_change,
            environment=environment,
            deployed_at=deployed_at,
            defaults={
                'pipeline': pipeline,
                'status': status,
                'deployed_by': deployed_by,
                'notes': notes,
            }
        )
        
        if created:
            logger.info(
                f"✅ Created deployment: {code_change.commit_sha[:8]} → "
                f"{environment} @ {deployed_at.strftime('%Y-%m-%d %H:%M')} "
                f"(status: {status})"
            )
        else:
            logger.debug(f"Deployment already exists: {deployment}")
        
        return deployment
    
    @staticmethod
    def get_deployments_for_batch(
        environment: str,
        start_time: datetime,
        end_time: datetime,
        project_id: Optional[str] = None,
        organisation_id: Optional[int] = None,
        only_successful: bool = True
    ) -> List[CodeChange]:
        """
        Get code changes deployed to an environment within a time window.
        
        THIS IS THE KEY METHOD FOR BATCH CREATION!
        
        Returns code changes that were DEPLOYED in the time window,
        regardless of when they were originally committed.
        
        Args:
            environment: Target environment ('development', 'staging', 'production')
            start_time: Start of batch time window
            end_time: End of batch time window
            project_id: Optional filter by GitLab project ID
            organisation_id: Optional filter by Organisation ID (for multi-tenancy isolation)
            only_successful: Only include successful deployments (default: True)
        
        Returns:
            List of unique CodeChange instances deployed in this window
        
        Example:
            >>> # Get code changes for production batch from 10:00-11:00
            >>> changes = DeploymentService.get_deployments_for_batch(
            ...     environment='production',
            ...     start_time=datetime(2025, 12, 28, 10, 0),
            ...     end_time=datetime(2025, 12, 28, 11, 0),
            ...     organisation_id=1  # Ensure org isolation
            ... )
            >>> # Batch now includes correct code changes!
            >>> batch.data['code_changes'] = [c.get_summary_for_ai() for c in changes]
        """
        query = Deployment.objects.filter(
            environment=environment,
            deployed_at__gte=start_time,
            deployed_at__lte=end_time
        )
        
        # Filter by status if needed
        if only_successful:
            query = query.filter(status='success')
        
        # Filter by organisation (MULTI-TENANCY ISOLATION)
        # Uses direct CodeChange.organisation FK (provider-agnostic)
        if organisation_id:
            query = query.filter(
                code_change__organisation_id=organisation_id
            )
            logger.debug(f"Filtering deployments by organisation_id={organisation_id}")
        
        # Filter by project if specified
        if project_id:
            query = query.filter(code_change__project_id=project_id)
        
        # Get related code changes
        query = query.select_related('code_change').order_by('deployed_at')
        
        # Extract unique code changes (avoid duplicates)
        code_changes = []
        seen_shas = set()
        
        for deployment in query:
            sha = deployment.code_change.commit_sha
            if sha not in seen_shas:
                code_changes.append(deployment.code_change)
                seen_shas.add(sha)
        
        logger.info(
            f"Found {len(code_changes)} unique code changes deployed to "
            f"{environment} between {start_time.strftime('%H:%M')} and "
            f"{end_time.strftime('%H:%M')}"
            + (f" (org_id={organisation_id})" if organisation_id else "")
        )
        
        return code_changes
    
    @staticmethod
    def create_deployments_from_pipeline(
        pipeline: Pipeline,
        commit_shas: List[str],
        environment: str,
        status: str = 'success'
    ) -> List[Deployment]:
        """
        Create deployment records when a pipeline completes.
        
        Called from GitLab webhook handler for pipeline events.
        Records ALL statuses (success, failed, canceled) for root cause analysis.
        
        Args:
            pipeline: The pipeline that ran
            commit_shas: List of commit SHAs in this deployment
            environment: Target environment (detected from pipeline)
            status: Pipeline status ('success', 'failed', 'canceled', etc.)
        
        Returns:
            List of created Deployment instances
        
        Example:
            >>> # In webhook handler for any pipeline status
            >>> deployments = DeploymentService.create_deployments_from_pipeline(
            ...     pipeline=pipeline,
            ...     commit_shas=['abc123', 'def456'],
            ...     environment='production',
            ...     status='failed'  # For root cause analysis
            ... )
        """
        # Track all pipeline events, not just success
        # This enables AI to correlate failed deployments with issues
        
        deployments = []
        deployed_at = timezone.now()
        
        for commit_sha in commit_shas:
            try:
                # Find the code change via provider-agnostic project_id
                if not pipeline.external_project_id:
                    logger.warning(
                        f"Pipeline {pipeline.pipeline_id} has no external_project_id, "
                        f"cannot look up CodeChange for SHA: {commit_sha}"
                    )
                    continue

                code_change = CodeChange.objects.filter(
                    commit_sha=commit_sha,
                    project_id=str(pipeline.external_project_id),
                ).first()
                if not code_change:
                    logger.warning(
                        f"CodeChange not found for SHA: {commit_sha} "
                        f"(pipeline: {pipeline.pipeline_id})"
                    )
                    continue

                # Create deployment with actual pipeline status
                deployment = DeploymentService.create_deployment(
                    code_change=code_change,
                    environment=environment,
                    deployed_at=deployed_at,
                    pipeline=pipeline,
                    status=status,
                    deployed_by='CI/CD'
                )

                deployments.append(deployment)

            except Exception as e:
                logger.error(
                    f"Error creating deployment for {commit_sha}: {e}"
                )
                continue
        
        logger.info(
            f"✅ Created {len(deployments)} deployment records from pipeline "
            f"{pipeline.pipeline_id} → {environment}"
        )
        
        return deployments
