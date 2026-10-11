"""
Code Change Processing Service

Handles the storage and processing of code changes (commits) from SCM webhooks.
Provides a clean interface for saving commits and fetching diffs asynchronously.
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from dateutil import parser as date_parser
from django.utils import timezone
from django.db import transaction

from .models import CodeChange, GitlabProject
from .scm_providers import get_provider, SCMProviderError

logger = logging.getLogger(__name__)


class CodeChangeService:
    """
    Service class for managing code changes.
    
    Provides methods for:
    - Saving commits from webhook payloads
    - Fetching and updating diffs
    - Querying code changes for batch processing
    """
    
    @staticmethod
    def save_commit_from_webhook(
        provider: str,
        project_id: str,
        commit_data: Dict[str, Any],
        gitlab_project: Optional[GitlabProject] = None
    ) -> Optional[CodeChange]:
        """
        Save a single commit from webhook data.
        
        Args:
            provider: SCM provider name ('gitlab', 'github', etc.)
            project_id: SCM project ID
            commit_data: Standardized commit dictionary from provider
            gitlab_project: Optional GitLabProject instance for linking
            
        Returns:
            CodeChange instance or None if save failed
        """
        try:
            # Parse timestamp
            timestamp = commit_data.get('timestamp')
            if isinstance(timestamp, str):
                timestamp = date_parser.parse(timestamp)
            if timestamp and not timezone.is_aware(timestamp):
                timestamp = timezone.make_aware(timestamp)
            
            # Calculate basic stats from file lists
            files_modified = commit_data.get('files_modified', [])
            files_added = commit_data.get('files_added', [])
            files_removed = commit_data.get('files_removed', [])
            files_changed = len(files_modified) + len(files_added) + len(files_removed)
            
            # Build initial diff summary from webhook data
            diff_summary = {
                "files": [
                    {"path": f, "is_new": False, "is_deleted": False} for f in files_modified
                ] + [
                    {"path": f, "is_new": True, "is_deleted": False} for f in files_added
                ] + [
                    {"path": f, "is_new": False, "is_deleted": True} for f in files_removed
                ],
                "total_additions": 0,  # Will be updated when full diff is fetched
                "total_deletions": 0,
            }
            
            # Use update_or_create to handle duplicate commits gracefully
            # Get organisation from gitlab_project for multi-tenancy isolation
            organisation = gitlab_project.organisation if gitlab_project else None
            
            code_change, created = CodeChange.objects.update_or_create(
                provider=provider,
                project_id=str(project_id),
                commit_sha=commit_data.get('sha'),
                defaults={
                    'organisation': organisation,  # Multi-tenancy isolation
                    'gitlab_project': gitlab_project,
                    'commit_message': commit_data.get('message', '')[:2000],  # Limit message length
                    'author_name': commit_data.get('author_name', 'Unknown'),
                    'author_email': commit_data.get('author_email'),
                    'timestamp': timestamp or timezone.now(),
                    'branch': commit_data.get('branch', 'unknown'),
                    'files_changed': files_changed,
                    'diff_summary': diff_summary,
                }
            )
            
            action = "Created" if created else "Updated"
            logger.info(f"{action} CodeChange for commit {commit_data.get('sha', 'N/A')[:8]}")
            return code_change
            
        except Exception as e:
            logger.error(f"Error saving commit: {str(e)}")
            return None
    
    @staticmethod
    def save_commits_from_webhook(
        provider: str,
        project_id: str,
        commits: List[Dict[str, Any]],
        gitlab_project: Optional[GitlabProject] = None
    ) -> List[CodeChange]:
        """
        Save multiple commits from webhook payload.
        
        Args:
            provider: SCM provider name
            project_id: SCM project ID
            commits: List of standardized commit dictionaries
            gitlab_project: Optional GitLabProject instance
            
        Returns:
            List of saved CodeChange instances
        """
        saved = []
        for commit_data in commits:
            code_change = CodeChangeService.save_commit_from_webhook(
                provider=provider,
                project_id=project_id,
                commit_data=commit_data,
                gitlab_project=gitlab_project
            )
            if code_change:
                saved.append(code_change)
        
        logger.info(f"Saved {len(saved)}/{len(commits)} commits for project {project_id}")
        return saved
    
    @staticmethod
    def fetch_and_update_diff(code_change: CodeChange, access_token: str) -> bool:
        """
        Fetch full diff from SCM and update the CodeChange record.
        
        Args:
            code_change: CodeChange instance to update
            access_token: API access token for the provider
            
        Returns:
            True if successful, False otherwise
        """
        if code_change.diff_fetched:
            logger.debug(f"Diff already fetched for {code_change.commit_sha[:8]}")
            return True
        
        try:
            # Get appropriate provider
            base_url = None
            if code_change.gitlab_project:
                base_url = code_change.gitlab_project.gitlab_url
            
            provider = get_provider(
                provider_name=code_change.provider,
                project_id=code_change.project_id,
                access_token=access_token,
                base_url=base_url
            )
            
            # Fetch diff
            diff_summary = provider.get_commit_diff(code_change.commit_sha)
            
            # Update record
            code_change.diff_summary = diff_summary
            code_change.additions = diff_summary.get('total_additions', 0)
            code_change.deletions = diff_summary.get('total_deletions', 0)
            code_change.files_changed = len(diff_summary.get('files', []))
            code_change.diff_fetched = True
            code_change.save()
            
            logger.info(f"Updated diff for commit {code_change.commit_sha[:8]}: "
                       f"+{code_change.additions}/-{code_change.deletions}")
            return True
            
        except SCMProviderError as e:
            logger.warning(f"Failed to fetch diff for {code_change.commit_sha[:8]}: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Error fetching diff: {str(e)}")
            return False
    
    @staticmethod
    def get_changes_for_time_window(
        project_id: str,
        start_time: datetime,
        end_time: datetime,
        provider: str = 'gitlab',
        limit: int = 50
    ) -> List[CodeChange]:
        """
        Get code changes within a time window for batch processing.
        
        Args:
            project_id: SCM project ID
            start_time: Start of time window
            end_time: End of time window
            provider: SCM provider name
            limit: Maximum number of changes to return
            
        Returns:
            List of CodeChange instances
        """
        return list(
            CodeChange.objects.filter(
                provider=provider,
                project_id=project_id,
                timestamp__gte=start_time,
                timestamp__lte=end_time
            ).order_by('-timestamp')[:limit]
        )
    
    @staticmethod
    def get_changes_for_project_name(
        project_name: str,
        start_time: datetime,
        end_time: datetime,
        limit: int = 50
    ) -> List[CodeChange]:
        """
        Get code changes for a SerOps project by name.

        Provider-agnostic: resolves SCM project IDs from SCMBinding.

        Args:
            project_name: SerOps project name
            start_time: Start of time window
            end_time: End of time window
            limit: Maximum number of changes to return

        Returns:
            List of CodeChange instances
        """
        from Projects.models import ProjectService

        services = ProjectService.objects.filter(
            project__name__iexact=project_name,
        )

        scm_project_ids = set()
        for svc in services:
            if svc.scm_binding:
                scm_project_ids.add(str(svc.scm_binding.repository_id))

        if not scm_project_ids:
            return []

        return list(
            CodeChange.objects.filter(
                project_id__in=list(scm_project_ids),
                timestamp__gte=start_time,
                timestamp__lte=end_time
            ).order_by('-timestamp')[:limit]
        )
    
    @staticmethod
    def prepare_changes_for_ai(changes: List[CodeChange]) -> List[Dict[str, Any]]:
        """
        Prepare code changes for AI analysis prompt.
        
        Args:
            changes: List of CodeChange instances
            
        Returns:
            List of compact summaries suitable for AI consumption
        """
        return [change.get_summary_for_ai() for change in changes]
