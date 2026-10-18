"""
SCM Provider Abstraction Layer

Provides a unified interface for interacting with different Source Code Management
platforms (GitLab, GitHub, Bitbucket). This allows the application to work with
multiple SCM providers using a single, consistent API.

Usage:
    from providers.scm_providers import get_provider
    
    provider = get_provider('gitlab', project_id='123', access_token='xxx')
    commits = provider.get_commits(since=datetime)
    diff = provider.get_commit_diff(commit_sha='abc123')
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, List, Dict, Any
import requests
import logging
from dateutil import parser as date_parser

logger = logging.getLogger(__name__)

# Characters of each file's diff kept on the CodeChange. The prompt picks
# hunks out of this (ai_model.diff_selection), so it needs the whole
# change for typical commits, not the first screenful.
DIFF_PREVIEW_CHARS = 16_000


def split_unified_diff(text: str) -> Dict[str, str]:
    """Split a whole-commit ``git diff`` into ``{path: hunks}``.

    Keeps each file's text from its first ``@@`` hunk header, which is what
    the prompt reads (ai_model.diff_selection); ``diff --git``/``index``/
    ``---``/``+++`` lines carry nothing the file list doesn't.
    """
    files: Dict[str, str] = {}
    path, body, in_hunks = None, [], False

    def flush():
        if path and body:
            files[path] = '\n'.join(body)

    for line in (text or '').splitlines():
        if line.startswith('diff --git '):
            flush()
            # diff --git a/old/path b/new/path
            parts = line.split(' b/', 1)
            path = parts[1] if len(parts) == 2 else None
            body, in_hunks = [], False
        elif line.startswith('+++ ') and not in_hunks:
            target = line[4:].strip()
            if target.startswith('b/'):
                path = target[2:]
        elif line.startswith('@@'):
            in_hunks = True
            body.append(line)
        elif in_hunks:
            body.append(line)
    flush()
    return files


def unified_diff_text(old: str, new: str, context: int = 3) -> str:
    """Hunks (no file header) between two versions of a file."""
    import difflib
    lines = difflib.unified_diff(
        (old or '').splitlines(), (new or '').splitlines(), lineterm='', n=context,
    )
    return '\n'.join(line for line in lines if not line.startswith(('--- ', '+++ ')))


class SCMProviderError(Exception):
    """Base exception for SCM provider errors."""
    pass


class AuthenticationError(SCMProviderError):
    """Raised when authentication fails."""
    pass


class RateLimitError(SCMProviderError):
    """Raised when rate limit is exceeded."""
    pass


class BaseProvider(ABC):
    """
    Abstract base class for SCM providers.
    
    Subclass this to add support for new SCM platforms (GitHub, Bitbucket, etc.)
    """
    
    def __init__(self, project_id: str, access_token: str, base_url: Optional[str] = None):
        self.project_id = project_id
        self.access_token = access_token
        self.base_url = base_url
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (e.g., 'gitlab', 'github')."""
        pass
    
    @abstractmethod
    def get_commits(
        self, 
        since: Optional[datetime] = None, 
        until: Optional[datetime] = None,
        branch: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get commits from the repository.
        
        Args:
            since: Only return commits after this date
            until: Only return commits before this date
            branch: Filter by branch name
            limit: Maximum number of commits to return
            
        Returns:
            List of commit dictionaries with standardized fields
        """
        pass
    
    @abstractmethod
    def get_commit_diff(self, commit_sha: str) -> Dict[str, Any]:
        """
        Get the diff for a specific commit.
        
        Args:
            commit_sha: The commit SHA/hash
            
        Returns:
            Dictionary with diff summary and file changes
        """
        pass
    
    @abstractmethod
    def parse_webhook_payload(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Parse incoming webhook payload to extract commit information.
        
        Args:
            payload: Raw webhook payload from SCM
            
        Returns:
            List of standardized commit dictionaries
        """
        pass
    
    def verify_connection(self) -> Dict[str, Any]:
        """
        Verify the connection to the provider.
        
        Tests that the access token is valid and has necessary permissions.
        
        Returns:
            Dictionary with user/org info on success
            
        Raises:
            SCMProviderError: If verification fails
        """
        raise NotImplementedError("Subclass must implement verify_connection")
    
    def list_projects(
        self, 
        page: int = 1, 
        per_page: int = 20, 
        search: str = ''
    ) -> List[Dict[str, Any]]:
        """
        List available projects/repositories from the provider.
        
        Args:
            page: Page number for pagination
            per_page: Number of items per page
            search: Optional search term
            
        Returns:
            List of project dictionaries with id, name, url, etc.
            
        Raises:
            SCMProviderError: If listing fails
        """
        raise NotImplementedError("Subclass must implement list_projects")
    
    def list_recent_pipelines(self, hours: int = 2) -> List[Dict[str, Any]]:
        """
        List recent terminal pipeline runs. Override in subclasses.

        Returns:
            List of dicts with keys: id, status, ref, sha, updated_at
        """
        return []

    def _make_request(
        self, 
        method: str, 
        url: str, 
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
        json: Optional[Dict] = None,
        data: Optional[Any] = None,
        timeout: int = 30
    ) -> requests.Response:
        """Make an HTTP request with error handling."""
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json,
                data=data,
                timeout=timeout
            )
            
            if response.status_code == 401:
                raise AuthenticationError(f"Authentication failed for {self.provider_name}")
            elif response.status_code == 429:
                raise RateLimitError(f"Rate limit exceeded for {self.provider_name}")
            
            return response
            
        except requests.exceptions.Timeout:
            raise SCMProviderError(f"Request timeout for {self.provider_name}")
        except requests.exceptions.RequestException as e:
            raise SCMProviderError(f"Request failed: {str(e)}")



class GitLabProvider(BaseProvider):
    """
    GitLab SCM provider implementation.
    
    Supports GitLab.com and self-hosted GitLab instances.
    """
    
    DEFAULT_BASE_URL = "https://gitlab.com"
    
    def __init__(self, project_id: str, access_token: str, base_url: Optional[str] = None):
        super().__init__(project_id, access_token, base_url or self.DEFAULT_BASE_URL)
    
    @property
    def provider_name(self) -> str:
        return 'gitlab'
    
    def _get_headers(self) -> Dict[str, str]:
        return {"PRIVATE-TOKEN": self.access_token}
    
    def get_commits(
        self, 
        since: Optional[datetime] = None, 
        until: Optional[datetime] = None,
        branch: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get commits from GitLab repository."""
        url = f"{self.base_url}/api/v4/projects/{self.project_id}/repository/commits"
        
        params = {"per_page": min(limit, 100)}
        if since:
            params["since"] = since.isoformat()
        if until:
            params["until"] = until.isoformat()
        if branch:
            params["ref_name"] = branch
        
        response = self._make_request("GET", url, headers=self._get_headers(), params=params)
        
        if response.status_code != 200:
            logger.error(f"GitLab commits API error: {response.status_code} - {response.text[:200]}")
            return []
        
        commits = response.json()
        return [self._normalize_commit(c) for c in commits]
    
    def get_commit_diff(self, commit_sha: str) -> Dict[str, Any]:
        """Get diff for a specific commit from GitLab."""
        url = f"{self.base_url}/api/v4/projects/{self.project_id}/repository/commits/{commit_sha}/diff"
        
        response = self._make_request("GET", url, headers=self._get_headers())
        
        if response.status_code != 200:
            logger.error(f"GitLab diff API error: {response.status_code} - {response.text[:200]}")
            return {"files": [], "total_additions": 0, "total_deletions": 0}
        
        diffs = response.json()
        return self._summarize_diff(diffs)
    
    def parse_webhook_payload(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse GitLab push webhook payload."""
        commits = payload.get("commits", [])
        branch = payload.get("ref", "").replace("refs/heads/", "")
        
        standardized = []
        for commit in commits:
            standardized.append({
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
        
        return standardized
    
    def create_webhook(self, webhook_url: str, secret: str, events: List[str] = None) -> Dict[str, Any]:
        """
        Create a webhook in the GitLab project.
        
        Args:
            webhook_url: URL to receive webhook payloads
            secret: Secret token for verification
            events: List of events (default: push_events, pipeline_events, merge_requests_events)
            
        Returns:
            Created webhook data or error
        """
        url = f"{self.base_url}/api/v4/projects/{self.project_id}/hooks"
        
        if events is None:
            events = ["push_events", "pipeline_events", "merge_requests_events"]
        
        # specific mapping for GitLab event names if generic names were passed
        # but here we assume caller knows or we map generic ones
        payload = {
            "url": webhook_url,
            "token": secret,
            "enable_ssl_verification": True,
            # Enable all requested events
            **{event: True for event in events}
        }
        
        try:
            response = self._make_request("POST", url, headers=self._get_headers(), json=payload)
            
            if response.status_code in [200, 201]:
                logger.info(f"Created GitLab webhook for {self.project_id}")
                return response.json()
            else:
                logger.error(f"Failed to create GitLab webhook: {response.status_code} - {response.text}")
                return {"error": response.text, "status_code": response.status_code}
                
        except Exception as e:
            logger.error(f"Error creating GitLab webhook: {e}")
            return {"error": str(e)}
    
    def _normalize_commit(self, commit: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize GitLab API commit response to standard format."""
        return {
            'sha': commit.get("id"),
            'message': commit.get("message", ""),
            'author_name': commit.get("author_name", "Unknown"),
            'author_email': commit.get("author_email"),
            'timestamp': commit.get("committed_date"),
            'branch': None,  # Not available in commits list
        }
    
    def _summarize_diff(self, diffs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create a compact summary of diffs for AI consumption."""
        summary = {
            "files": [],
            "total_additions": 0,
            "total_deletions": 0,
            "total_files": len(diffs)
        }
        
        for diff in diffs:
            # Count additions/deletions from diff content
            diff_content = diff.get("diff", "")
            additions = len([l for l in diff_content.split('\n') if l.startswith('+')])
            deletions = len([l for l in diff_content.split('\n') if l.startswith('-')])
            
            file_summary = {
                "path": diff.get("new_path"),
                "old_path": diff.get("old_path"),
                "is_new": diff.get("new_file", False),
                "is_deleted": diff.get("deleted_file", False),
                "is_renamed": diff.get("renamed_file", False),
                "additions": additions,
                "deletions": deletions,
                "diff_preview": diff_content[:DIFF_PREVIEW_CHARS] if diff_content else ""
            }
            
            summary["files"].append(file_summary)
            summary["total_additions"] += additions
            summary["total_deletions"] += deletions
        
        return summary
    
    def verify_connection(self) -> Dict[str, Any]:
        """
        Verify connection to GitLab by checking the current user.
        
        Returns:
            Dictionary with user info on success
            
        Raises:
            SCMProviderError: If verification fails
        """
        url = f"{self.base_url}/api/v4/user"
        
        try:
            response = self._make_request("GET", url, headers=self._get_headers())
            
            if response.status_code == 200:
                user_data = response.json()
                return {
                    'username': user_data.get('username'),
                    'name': user_data.get('name'),
                    'email': user_data.get('email'),
                    'avatar_url': user_data.get('avatar_url'),
                    'is_admin': user_data.get('is_admin', False),
                }
            else:
                error_msg = response.json().get('message', response.text[:200])
                raise SCMProviderError(f"GitLab verification failed: {error_msg}")
                
        except AuthenticationError:
            raise SCMProviderError("Invalid GitLab access token")
        except Exception as e:
            if isinstance(e, SCMProviderError):
                raise
            raise SCMProviderError(f"Failed to verify GitLab connection: {str(e)}")
    
    def list_projects(
        self, 
        page: int = 1, 
        per_page: int = 20, 
        search: str = ''
    ) -> List[Dict[str, Any]]:
        """
        List GitLab projects accessible to the user.
        
        Args:
            page: Page number for pagination
            per_page: Number of items per page
            search: Optional search term
            
        Returns:
            List of project dictionaries
        """
        url = f"{self.base_url}/api/v4/projects"
        
        params = {
            'membership': 'true',  # Only projects user is member of
            'page': page,
            'per_page': min(per_page, 100),
            'order_by': 'last_activity_at',
            'sort': 'desc',
        }
        
        if search:
            params['search'] = search
        
        try:
            response = self._make_request("GET", url, headers=self._get_headers(), params=params)
            
            if response.status_code != 200:
                logger.error(f"GitLab projects API error: {response.status_code}")
                return []
            
            projects = response.json()
            
            return [
                {
                    'id': str(project.get('id')),
                    'name': project.get('name'),
                    'full_name': project.get('path_with_namespace'),
                    'description': project.get('description'),
                    'url': project.get('web_url'),
                    'default_branch': project.get('default_branch', 'main'),
                    'is_private': project.get('visibility') == 'private',
                    'last_activity_at': project.get('last_activity_at'),
                }
                for project in projects
            ]
            
        except Exception as e:
            logger.exception(f"Failed to list GitLab projects: {e}")
            raise SCMProviderError(f"Failed to list projects: {str(e)}")


class GitHubProvider(BaseProvider):
    """
    GitHub SCM provider implementation.
    
    Supports GitHub.com and GitHub Enterprise.
    
    Usage:
        provider = GitHubProvider(
            project_id='owner/repo',
            access_token='ghp_xxx...',
            base_url='https://api.github.com'  # or GitHub Enterprise URL
        )
        commits = provider.get_commits(since=datetime(...))
    """
    
    DEFAULT_BASE_URL = "https://api.github.com"
    
    def __init__(self, project_id: str, access_token: str, base_url: Optional[str] = None):
        """
        Initialize GitHub provider.
        
        Args:
            project_id: Repository in 'owner/repo' format
            access_token: GitHub Personal Access Token or GitHub App token
            base_url: API base URL (default: https://api.github.com)
        """
        super().__init__(project_id, access_token, base_url or self.DEFAULT_BASE_URL)
    
    @property
    def provider_name(self) -> str:
        return 'github'
    
    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
    
    def get_commits(
        self, 
        since: Optional[datetime] = None, 
        until: Optional[datetime] = None,
        branch: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get commits from GitHub repository.
        
        Args:
            since: Only return commits after this date
            until: Only return commits before this date
            branch: Filter by branch name (SHA or branch name)
            limit: Maximum number of commits to return
        
        Returns:
            List of normalized commit dictionaries
        """
        # GitHub API: GET /repos/{owner}/{repo}/commits
        url = f"{self.base_url}/repos/{self.project_id}/commits"
        
        params = {"per_page": min(limit, 100)}
        if since:
            params["since"] = since.isoformat()
        if until:
            params["until"] = until.isoformat()
        if branch:
            params["sha"] = branch  # Can be branch name or SHA
        
        response = self._make_request("GET", url, headers=self._get_headers(), params=params)
        
        if response.status_code != 200:
            logger.error(f"GitHub commits API error: {response.status_code} - {response.text[:200]}")
            return []
        
        commits = response.json()
        return [self._normalize_commit(c) for c in commits]
    
    def get_commit_diff(self, commit_sha: str) -> Dict[str, Any]:
        """
        Get diff for a specific commit from GitHub.
        
        Args:
            commit_sha: The commit SHA
        
        Returns:
            Dictionary with diff summary and file changes
        """
        # GitHub API: GET /repos/{owner}/{repo}/commits/{sha}
        url = f"{self.base_url}/repos/{self.project_id}/commits/{commit_sha}"
        
        response = self._make_request("GET", url, headers=self._get_headers())
        
        if response.status_code != 200:
            logger.error(f"GitHub commit API error: {response.status_code} - {response.text[:200]}")
            return {"files": [], "total_additions": 0, "total_deletions": 0}
        
        data = response.json()
        stats = data.get("stats", {})
        
        return {
            "files": [
                {
                    "path": f.get("filename"),
                    "old_path": f.get("previous_filename"),
                    "is_new": f.get("status") == "added",
                    "is_deleted": f.get("status") == "removed",
                    "is_renamed": f.get("status") == "renamed",
                    "additions": f.get("additions", 0),
                    "deletions": f.get("deletions", 0),
                    # The commit API already returns the unified diff
                    # hunks; keeping them is what lets the AI read the
                    # change, not just its file name.
                    "diff_preview": (f.get("patch") or "")[:DIFF_PREVIEW_CHARS],
                }
                for f in data.get("files", [])
            ],
            "total_additions": stats.get("additions", 0),
            "total_deletions": stats.get("deletions", 0),
            "total_files": len(data.get("files", [])),
        }
    
    def parse_webhook_payload(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Parse GitHub push webhook payload.
        
        GitHub sends push webhooks with this structure:
        {
            "ref": "refs/heads/main",
            "commits": [
                {
                    "id": "abc123...",
                    "message": "Commit message",
                    "author": {"name": "...", "email": "..."},
                    "timestamp": "2025-01-01T00:00:00Z",
                    "added": ["file1.py"],
                    "modified": ["file2.py"],
                    "removed": []
                }
            ]
        }
        """
        commits = payload.get("commits", [])
        ref = payload.get("ref", "")
        branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref
        
        standardized = []
        for commit in commits:
            author = commit.get("author", {})
            
            standardized.append({
                'sha': commit.get("id"),
                'message': commit.get("message", ""),
                'author_name': author.get("name", "Unknown"),
                'author_email': author.get("email"),
                'timestamp': commit.get("timestamp"),
                'branch': branch,
                'files_modified': commit.get("modified", []),
                'files_added': commit.get("added", []),
                'files_removed': commit.get("removed", []),
            })
        
        return standardized
    
    def _normalize_commit(self, commit: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize GitHub API commit response to standard format."""
        commit_data = commit.get("commit", {})
        author = commit_data.get("author", {})
        
        return {
            'sha': commit.get("sha"),
            'message': commit_data.get("message", ""),
            'author_name': author.get("name", "Unknown"),
            'author_email': author.get("email"),
            'timestamp': author.get("date"),
            'branch': None,  # Not available in commits list API
        }
    
    def list_recent_pipelines(self, hours: int = 2) -> List[Dict[str, Any]]:
        """
        List recent completed GitHub Actions workflow runs.

        Uses the GitHub Actions API to fetch recently completed runs,
        filtered by the cutoff time.

        Returns:
            List of dicts with keys: id, status, ref, sha, updated_at
        """
        from datetime import timedelta
        url = f"{self.base_url}/repos/{self.project_id}/actions/runs"
        params = {'per_page': 20, 'status': 'completed'}

        try:
            response = self._make_request("GET", url, headers=self._get_headers(), params=params)
            if response.status_code != 200:
                logger.warning(f"GitHub Actions runs API error: {response.status_code}")
                return []

            data = response.json()
            runs = data.get('workflow_runs', [])

            cutoff = datetime.now(tz=__import__('datetime').timezone.utc) - timedelta(hours=hours)
            status_map = {
                'success': 'success',
                'failure': 'failed',
                'cancelled': 'canceled',
            }

            results = []
            for run in runs:
                updated_at = run.get('updated_at', '')
                if updated_at:
                    try:
                        updated_dt = date_parser.parse(updated_at)
                        if updated_dt < cutoff:
                            continue
                    except Exception:
                        pass

                conclusion = run.get('conclusion', '')
                normalized_status = status_map.get(conclusion, conclusion)

                results.append({
                    'id': str(run.get('id')),
                    'status': normalized_status,
                    'ref': run.get('head_branch', ''),
                    'sha': run.get('head_sha', ''),
                    'updated_at': updated_at,
                })

            return results

        except Exception as e:
            logger.warning(f"Failed to list GitHub Actions runs: {e}")
            return []

    def create_webhook(self, webhook_url: str, secret: str, events: List[str] = None) -> Dict[str, Any]:
        """
        Create a webhook in the GitHub repository.

        Args:
            webhook_url: URL to receive webhook payloads
            secret: Secret for signature verification
            events: List of events to subscribe to (default: push, workflow_run)

        Returns:
            Created webhook data or error dict
        """
        if events is None:
            events = ["push", "workflow_run"]

        url = f"{self.base_url}/repos/{self.project_id}/hooks"
        
        payload = {
            "name": "web",
            "active": True,
            "events": events,
            "config": {
                "url": webhook_url,
                "content_type": "json",
                "secret": secret,
                "insecure_ssl": "0"
            }
        }
        
        try:
            response = requests.post(
                url,
                headers=self._get_headers(),
                json=payload,
                timeout=30
            )
            
            if response.status_code in [200, 201]:
                logger.info(f"Created GitHub webhook for {self.project_id}")
                return response.json()
            else:
                logger.error(f"Failed to create GitHub webhook: {response.status_code} - {response.text}")
                return {"error": response.text, "status_code": response.status_code}
                
        except Exception as e:
            logger.error(f"Error creating GitHub webhook: {e}")
            return {"error": str(e)}
    
    def verify_connection(self) -> Dict[str, Any]:
        """
        Verify connection to GitHub by checking the authenticated user.
        
        Returns:
            Dictionary with user info on success
            
        Raises:
            SCMProviderError: If verification fails
        """
        url = f"{self.base_url}/user"
        
        try:
            response = self._make_request("GET", url, headers=self._get_headers())
            
            if response.status_code == 200:
                user_data = response.json()
                return {
                    'username': user_data.get('login'),
                    'name': user_data.get('name'),
                    'email': user_data.get('email'),
                    'avatar_url': user_data.get('avatar_url'),
                    'html_url': user_data.get('html_url'),
                    'type': user_data.get('type'),  # 'User' or 'Organization'
                }
            elif response.status_code == 401:
                raise SCMProviderError("Invalid GitHub access token")
            else:
                error_msg = response.json().get('message', response.text[:200])
                raise SCMProviderError(f"GitHub verification failed: {error_msg}")
                
        except SCMProviderError:
            raise
        except Exception as e:
            raise SCMProviderError(f"Failed to verify GitHub connection: {str(e)}")
    
    def list_projects(
        self, 
        page: int = 1, 
        per_page: int = 20, 
        search: str = ''
    ) -> List[Dict[str, Any]]:
        """
        List GitHub repositories accessible to the authenticated user.
        
        Args:
            page: Page number for pagination
            per_page: Number of items per page (max 100)
            search: Optional search term to filter repos
            
        Returns:
            List of repository dictionaries
        """
        # If search is provided, use search API
        if search:
            url = f"{self.base_url}/search/repositories"
            params = {
                'q': f'{search} user:@me',
                'page': page,
                'per_page': min(per_page, 100),
                'sort': 'updated',
            }
        else:
            # List authenticated user's repos
            url = f"{self.base_url}/user/repos"
            params = {
                'page': page,
                'per_page': min(per_page, 100),
                'sort': 'updated',
                'affiliation': 'owner,collaborator,organization_member',
            }
        
        try:
            response = self._make_request("GET", url, headers=self._get_headers(), params=params)
            
            if response.status_code != 200:
                logger.error(f"GitHub repos API error: {response.status_code}")
                return []
            
            data = response.json()
            
            # Search API returns {'items': [...]}, direct repo list returns [...]
            repos = data.get('items', data) if isinstance(data, dict) else data
            
            return [
                {
                    'id': str(repo.get('id')),
                    'name': repo.get('name'),
                    'full_name': repo.get('full_name'),
                    'description': repo.get('description'),
                    'url': repo.get('html_url'),
                    'clone_url': repo.get('clone_url'),
                    'default_branch': repo.get('default_branch', 'main'),
                    'is_private': repo.get('private', False),
                    'owner': repo.get('owner', {}).get('login'),
                    'updated_at': repo.get('updated_at'),
                }
                for repo in repos
            ]
            
        except Exception as e:
            logger.exception(f"Failed to list GitHub repos: {e}")
            raise SCMProviderError(f"Failed to list repositories: {str(e)}")


class BitbucketProvider(BaseProvider):
    """
    Bitbucket Cloud SCM provider implementation.
    
    Uses OAuth2 for authentication (more secure than app passwords).
    
    Usage:
        provider = BitbucketProvider(
            project_id='workspace/repo',
            access_token='oauth2_access_token',
            base_url='https://api.bitbucket.org/2.0'
        )
        commits = provider.get_commits(since=datetime(...))
    """
    
    DEFAULT_BASE_URL = "https://api.bitbucket.org/2.0"
    
    def __init__(self, project_id: str, access_token: str, base_url: Optional[str] = None):
        """
        Initialize Bitbucket provider.
        
        Args:
            project_id: Repository in 'workspace/repo' format
            access_token: OAuth2 access token
            base_url: API base URL (default: https://api.bitbucket.org/2.0)
        """
        super().__init__(project_id, access_token, base_url or self.DEFAULT_BASE_URL)
    
    @property
    def provider_name(self) -> str:
        return 'bitbucket'
    
    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
    
    def get_commits(
        self, 
        since: Optional[datetime] = None, 
        until: Optional[datetime] = None,
        branch: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get commits from Bitbucket repository.
        
        Args:
            since: Only return commits after this date
            until: Only return commits before this date
            branch: Filter by branch name
            limit: Maximum number of commits to return
        
        Returns:
            List of normalized commit dictionaries
        """
        # Bitbucket API: GET /repositories/{workspace}/{repo}/commits/{branch}
        if branch:
            url = f"{self.base_url}/repositories/{self.project_id}/commits/{branch}"
        else:
            url = f"{self.base_url}/repositories/{self.project_id}/commits"
        
        params = {"pagelen": min(limit, 100)}
        
        response = self._make_request("GET", url, headers=self._get_headers(), params=params)
        
        if response.status_code != 200:
            logger.error(f"Bitbucket commits API error: {response.status_code} - {response.text[:200]}")
            return []
        
        data = response.json()
        commits = data.get("values", [])
        
        # Filter by date if specified
        normalized = []
        for commit in commits:
            commit_date = commit.get("date")
            if commit_date:
                try:
                    parsed_date = date_parser.parse(commit_date)
                    if since and parsed_date < since:
                        continue
                    if until and parsed_date > until:
                        continue
                except Exception:
                    pass
            
            normalized.append(self._normalize_commit(commit))
        
        return normalized[:limit]
    
    def _fetch_diff_text(self, commit_sha: str) -> Dict[str, str]:
        """``{path: hunks}`` from GET /repositories/{ws}/{repo}/diff/{sha}.
        Empty on any failure: the file list is still useful without it."""
        url = f"{self.base_url}/repositories/{self.project_id}/diff/{commit_sha}"
        headers = {**self._get_headers(), "Accept": "text/plain"}
        try:
            response = self._make_request("GET", url, headers=headers)
        except SCMProviderError as e:
            logger.info(f"Bitbucket diff text unavailable for {commit_sha[:8]}: {e}")
            return {}
        if response.status_code != 200:
            logger.info(f"Bitbucket diff text unavailable for {commit_sha[:8]}: HTTP {response.status_code}")
            return {}
        return split_unified_diff(response.text)

    def get_commit_diff(self, commit_sha: str) -> Dict[str, Any]:
        """
        Get diff for a specific commit from Bitbucket.
        
        Args:
            commit_sha: The commit SHA
        
        Returns:
            Dictionary with diff summary and file changes
        """
        # Bitbucket API: GET /repositories/{workspace}/{repo}/diffstat/{spec}
        url = f"{self.base_url}/repositories/{self.project_id}/diffstat/{commit_sha}"
        
        response = self._make_request("GET", url, headers=self._get_headers())
        
        if response.status_code != 200:
            logger.error(f"Bitbucket diffstat API error: {response.status_code} - {response.text[:200]}")
            return {"files": [], "total_additions": 0, "total_deletions": 0}
        
        data = response.json()
        files_data = data.get("values", [])
        
        files = []
        total_additions = 0
        total_deletions = 0
        
        for f in files_data:
            lines_added = f.get("lines_added", 0)
            lines_removed = f.get("lines_removed", 0)
            total_additions += lines_added
            total_deletions += lines_removed
            
            files.append({
                "path": (f.get("new") or {}).get("path") or (f.get("old") or {}).get("path"),
                "old_path": (f.get("old") or {}).get("path"),
                "is_new": f.get("status") == "added",
                "is_deleted": f.get("status") == "removed",
                "is_renamed": f.get("status") == "renamed",
                "additions": lines_added,
                "deletions": lines_removed,
            })

        # diffstat has no line content; the raw diff endpoint has all of it
        # in one response.
        patches = self._fetch_diff_text(commit_sha)
        for entry in files:
            patch = patches.get(entry["path"]) or patches.get(entry.get("old_path") or "")
            entry["diff_preview"] = (patch or "")[:DIFF_PREVIEW_CHARS]

        return {
            "files": files,
            "total_additions": total_additions,
            "total_deletions": total_deletions,
            "total_files": len(files),
        }
    
    def parse_webhook_payload(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Parse Bitbucket push webhook payload.
        
        Bitbucket sends push webhooks with this structure:
        {
            "push": {
                "changes": [
                    {
                        "new": { "name": "main", "type": "branch" },
                        "commits": [
                            {
                                "hash": "abc123...",
                                "message": "Commit message",
                                "author": {"raw": "User <email>"},
                                "date": "2025-01-01T00:00:00Z"
                            }
                        ]
                    }
                ]
            },
            "repository": { "full_name": "workspace/repo" }
        }
        """
        push = payload.get("push", {})
        changes = push.get("changes", [])
        
        standardized = []
        for change in changes:
            branch_info = change.get("new", {})
            branch = branch_info.get("name", "") if branch_info else ""
            
            commits = change.get("commits", [])
            for commit in commits:
                author_raw = commit.get("author", {}).get("raw", "Unknown")
                # Parse "Name <email>" format
                author_name = author_raw.split("<")[0].strip() if "<" in author_raw else author_raw
                author_email = author_raw.split("<")[1].rstrip(">") if "<" in author_raw else None
                
                standardized.append({
                    'sha': commit.get("hash"),
                    'message': commit.get("message", ""),
                    'author_name': author_name,
                    'author_email': author_email,
                    'timestamp': commit.get("date"),
                    'branch': branch,
                    'files_modified': [],
                    'files_added': [],
                    'files_removed': [],
                })
        
        return standardized
    
    def _normalize_commit(self, commit: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Bitbucket API commit response to standard format."""
        author = commit.get("author", {})
        author_raw = author.get("raw", "Unknown")
        
        # Parse "Name <email>" format
        author_name = author_raw.split("<")[0].strip() if "<" in author_raw else author_raw
        author_email = author_raw.split("<")[1].rstrip(">") if "<" in author_raw else None
        
        return {
            'sha': commit.get("hash"),
            'message': commit.get("message", ""),
            'author_name': author_name,
            'author_email': author_email,
            'timestamp': commit.get("date"),
            'branch': None,  # Not available in commits list API
        }
    
    def verify_repository(self) -> Dict[str, Any]:
        """
        Verify repository exists and token has access.
        
        Returns:
            Repository info or error dict
        """
        url = f"{self.base_url}/repositories/{self.project_id}"
        
        try:
            response = requests.get(
                url,
                headers=self._get_headers(),
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "exists": True,
                    "name": data.get("name"),
                    "full_name": data.get("full_name"),
                    "description": data.get("description"),
                    "is_private": data.get("is_private"),
                    "uuid": data.get("uuid"),
                }
            elif response.status_code == 401:
                return {"exists": False, "error": "Invalid or expired OAuth2 token"}
            elif response.status_code == 404:
                return {"exists": False, "error": f"Repository '{self.project_id}' not found"}
            else:
                return {"exists": False, "error": f"API returned status {response.status_code}"}
                
        except Exception as e:
            return {"exists": False, "error": str(e)}
    
    def verify_connection(self) -> Dict[str, Any]:
        """
        Verify connection to Bitbucket by checking the authenticated user.
        
        Returns:
            Dictionary with user info on success
            
        Raises:
            SCMProviderError: If verification fails
        """
        url = f"{self.base_url}/user"
        
        try:
            response = self._make_request("GET", url, headers=self._get_headers())
            
            if response.status_code == 200:
                user_data = response.json()
                return {
                    'username': user_data.get('username'),
                    'display_name': user_data.get('display_name'),
                    'uuid': user_data.get('uuid'),
                    'account_id': user_data.get('account_id'),
                    'avatar_url': user_data.get('links', {}).get('avatar', {}).get('href'),
                    'type': user_data.get('type'),
                }
            elif response.status_code == 401:
                raise SCMProviderError("Invalid Bitbucket access token")
            else:
                error_msg = response.json().get('error', {}).get('message', response.text[:200])
                raise SCMProviderError(f"Bitbucket verification failed: {error_msg}")
                
        except SCMProviderError:
            raise
        except Exception as e:
            raise SCMProviderError(f"Failed to verify Bitbucket connection: {str(e)}")
    
    def list_projects(
        self, 
        page: int = 1, 
        per_page: int = 20, 
        search: str = ''
    ) -> List[Dict[str, Any]]:
        """
        List Bitbucket repositories accessible to the authenticated user.
        
        Args:
            page: Page number for pagination
            per_page: Number of items per page (max 100)
            search: Optional search term to filter repos
            
        Returns:
            List of repository dictionaries
        """
        # Get user's repositories
        url = f"{self.base_url}/repositories"
        
        params = {
            'role': 'member',  # Repos where user is member
            'pagelen': min(per_page, 100),
            'page': page,
            'sort': '-updated_on',  # Most recently updated first
        }
        
        if search:
            params['q'] = f'name ~ "{search}"'
        
        try:
            response = self._make_request("GET", url, headers=self._get_headers(), params=params)
            
            if response.status_code != 200:
                logger.error(f"Bitbucket repos API error: {response.status_code}")
                return []
            
            data = response.json()
            repos = data.get('values', [])
            
            return [
                {
                    'id': repo.get('uuid'),
                    'name': repo.get('name'),
                    'full_name': repo.get('full_name'),
                    'description': repo.get('description'),
                    'url': repo.get('links', {}).get('html', {}).get('href'),
                    'clone_url': next(
                        (link.get('href') for link in repo.get('links', {}).get('clone', []) 
                         if link.get('name') == 'https'),
                        None
                    ),
                    'default_branch': repo.get('mainbranch', {}).get('name', 'master'),
                    'is_private': repo.get('is_private', True),
                    'owner': repo.get('owner', {}).get('username'),
                    'updated_at': repo.get('updated_on'),
                }
                for repo in repos
            ]
            
        except Exception as e:
            logger.exception(f"Failed to list Bitbucket repos: {e}")
            raise SCMProviderError(f"Failed to list repositories: {str(e)}")
    
    def create_webhook(self, webhook_url: str, secret: str, events: List[str] = None) -> Dict[str, Any]:
        """
        Create a webhook in the Bitbucket repository.
        
        Args:
            webhook_url: URL to receive webhook payloads
            secret: Secret for signature verification
            events: List of events (default: repo:push)
        
        Returns:
            Created webhook data or error dict
        """
        if events is None:
            events = ["repo:push", "pullrequest:created", "pullrequest:updated"]
        
        url = f"{self.base_url}/repositories/{self.project_id}/hooks"
        
        payload = {
            "description": "SerOps Webhook",
            "url": webhook_url,
            "active": True,
            "events": events,
        }
        
        try:
            response = self._make_request(
                "POST", url, 
                headers=self._get_headers(), 
                json=payload
            )
            
            if response.status_code in [200, 201]:
                logger.info(f"Created Bitbucket webhook for {self.project_id}")
                return response.json()
            else:
                logger.error(f"Failed to create Bitbucket webhook: {response.status_code} - {response.text}")
                return {"error": response.text, "status_code": response.status_code}
                
        except Exception as e:
            logger.error(f"Error creating Bitbucket webhook: {e}")
            return {"error": str(e)}


class AzureDevOpsProvider(BaseProvider):
    """
    Azure DevOps SCM and CI/CD provider implementation.
    
    Supports Azure DevOps Services (cloud) and Azure DevOps Server (on-prem).
    
    Usage:
        provider = AzureDevOpsProvider(
            project_id='organization/project',
            access_token='personal_access_token',
            base_url='https://dev.azure.com'
        )
    """
    
    DEFAULT_BASE_URL = "https://dev.azure.com"
    
    def __init__(self, project_id: str, access_token: str, base_url: Optional[str] = None,
                 organization: Optional[str] = None):
        """
        Initialize Azure DevOps provider.

        Args:
            project_id: The repository, as ``organization/project/repository``.
                ``organization/project`` still works and means the repository
                named like its project (Azure's default). With ``organization``
                given, ``project[/repository]`` is enough.
            access_token: Personal Access Token (PAT)
            base_url: API base URL (default: https://dev.azure.com). An
                organization URL (https://dev.azure.com/my-org) also works.
            organization: The integration's organization, used when
                ``project_id`` does not start with it.
        """
        from urllib.parse import urlparse

        org = (organization or '').strip().strip('/')
        parsed = urlparse(base_url or self.DEFAULT_BASE_URL)
        url_org = parsed.path.strip('/').split('/')[0] if parsed.path.strip('/') else ''
        if url_org:
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            org = org or url_org
        super().__init__(project_id, access_token, base_url or self.DEFAULT_BASE_URL)

        parts = [p for p in (self.project_id or '').strip('/').split('/') if p]
        if parts and (not org or parts[0] == org):
            org, parts = parts[0], parts[1:]
        self.organization = org
        self.project = parts[0] if parts else None
        self.repository = parts[1] if len(parts) > 1 else self.project

    @property
    def provider_name(self) -> str:
        return 'azure_devops'
    
    def _get_headers(self) -> Dict[str, str]:
        import base64
        # Azure DevOps uses Basic auth with PAT as password
        auth = base64.b64encode(f":{self.access_token}".encode()).decode()
        return {
            "Authorization": f"Basic {auth}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
    
    def verify_connection(self) -> Dict[str, Any]:
        """
        Verify connection to Azure DevOps by checking the user profile.
        
        Returns:
            Dictionary with user info on success
            
        Raises:
            SCMProviderError: If verification fails
        """
        # Use the connection data API to verify
        url = f"{self.base_url}/{self.organization}/_apis/connectionData?api-version=7.0"
        
        try:
            response = self._make_request("GET", url, headers=self._get_headers())
            
            if response.status_code == 200:
                data = response.json()
                user = data.get('authenticatedUser', {})
                return {
                    'username': user.get('providerDisplayName'),
                    'id': user.get('id'),
                    'descriptor': user.get('descriptor'),
                    'organization': self.organization,
                    'project': self.project,
                }
            elif response.status_code == 401:
                raise SCMProviderError("Invalid Azure DevOps PAT")
            elif response.status_code == 404:
                raise SCMProviderError(f"Organization '{self.organization}' not found")
            else:
                error_msg = response.text[:200]
                raise SCMProviderError(f"Azure DevOps verification failed: {error_msg}")
                
        except SCMProviderError:
            raise
        except Exception as e:
            raise SCMProviderError(f"Failed to verify Azure DevOps connection: {str(e)}")
    
    def list_projects(
        self, 
        page: int = 1, 
        per_page: int = 20, 
        search: str = ''
    ) -> List[Dict[str, Any]]:
        """
        List Azure DevOps projects in the organization.
        
        Args:
            page: Page number for pagination
            per_page: Number of items per page
            search: Optional search term
            
        Returns:
            List of project dictionaries
        """
        # Bindings point at a Git repository, and an Azure project can hold
        # several, named differently from the project. List repositories.
        scope = f"{self.organization}/{self.project}" if self.project else self.organization
        url = f"{self.base_url}/{scope}/_apis/git/repositories?api-version=7.0"

        try:
            response = self._make_request("GET", url, headers=self._get_headers())

            if response.status_code != 200:
                logger.error(f"Azure DevOps repositories API error: {response.status_code}")
                return []

            repos = response.json().get('value', [])
            if search:
                needle = search.lower()
                repos = [
                    r for r in repos
                    if needle in r.get('name', '').lower()
                    or needle in (r.get('project') or {}).get('name', '').lower()
                ]
            repos.sort(key=lambda r: ((r.get('project') or {}).get('name', '').lower(), r.get('name', '').lower()))
            start = (max(page, 1) - 1) * per_page
            repos = repos[start:start + per_page]

            result = []
            for repo in repos:
                project = repo.get('project') or {}
                project_name = project.get('name', '')
                name = repo.get('name', '')
                branch = repo.get('defaultBranch') or 'refs/heads/main'
                result.append({
                    # Self-contained: stored code changes rebuild the
                    # provider from this alone.
                    'id': f"{self.organization}/{project_name}/{name}",
                    'name': name,
                    'full_name': f"{project_name}/{name}",
                    'description': project.get('description'),
                    'url': repo.get('webUrl') or f"{self.base_url}/{self.organization}/{project_name}/_git/{name}",
                    'default_branch': branch.replace('refs/heads/', ''),
                    'is_private': project.get('visibility') != 'public',
                })
            return result

        except Exception as e:
            logger.exception(f"Failed to list Azure DevOps repositories: {e}")
            raise SCMProviderError(f"Failed to list repositories: {str(e)}")

    def get_commits(
        self, 
        since: Optional[datetime] = None, 
        until: Optional[datetime] = None,
        branch: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get commits from Azure DevOps repository.
        """
        if not self.project:
            logger.error("Project name required for Azure DevOps commits")
            return []
        
        url = f"{self._repo_url()}/commits?api-version=7.0"
        
        params = {'$top': min(limit, 100)}
        if since:
            params['searchCriteria.fromDate'] = since.isoformat()
        if until:
            params['searchCriteria.toDate'] = until.isoformat()
        if branch:
            params['searchCriteria.itemVersion.version'] = branch
        
        try:
            response = self._make_request("GET", url, headers=self._get_headers(), params=params)
            
            if response.status_code != 200:
                logger.error(f"Azure DevOps commits API error: {response.status_code}")
                return []
            
            data = response.json()
            commits = data.get('value', [])
            
            return [self._normalize_commit(c) for c in commits]
            
        except Exception as e:
            logger.exception(f"Failed to get Azure DevOps commits: {e}")
            return []
    
    # Azure DevOps has no diff-text API: each file's before/after content is
    # fetched and diffed here. Two requests per file, so only the first few
    # files of a commit, and only text files of a sane size.
    MAX_DIFF_FILES = 10
    MAX_FILE_BYTES = 200_000

    def _repo_url(self) -> str:
        return f"{self.base_url}/{self.organization}/{self.project}/_apis/git/repositories/{self.repository}"

    def _file_at(self, path: str, version: str) -> Optional[str]:
        """Text of ``path`` at commit ``version``; None if missing, binary or too big."""
        params = {
            'path': path,
            'versionDescriptor.version': version,
            'versionDescriptor.versionType': 'commit',
            'includeContent': 'true',
            'api-version': '7.0',
        }
        try:
            response = self._make_request("GET", f"{self._repo_url()}/items", headers=self._get_headers(), params=params)
        except SCMProviderError:
            return None
        if response.status_code != 200:
            return None
        item = response.json()
        meta = item.get('contentMetadata') or {}
        content = item.get('content')
        if meta.get('isBinary') or not isinstance(content, str) or len(content) > self.MAX_FILE_BYTES:
            return None
        return content

    def _parent_sha(self, commit_sha: str) -> Optional[str]:
        try:
            response = self._make_request(
                "GET", f"{self._repo_url()}/commits/{commit_sha}?api-version=7.0", headers=self._get_headers(),
            )
        except SCMProviderError:
            return None
        if response.status_code != 200:
            return None
        parents = response.json().get('parents') or []
        return parents[0] if parents else None

    def get_commit_diff(self, commit_sha: str) -> Dict[str, Any]:
        """Files changed by a commit, with diff hunks for the first few."""
        if not self.project:
            return {"files": [], "total_additions": 0, "total_deletions": 0}

        url = f"{self._repo_url()}/commits/{commit_sha}/changes?api-version=7.0"
        try:
            response = self._make_request("GET", url, headers=self._get_headers())
            if response.status_code != 200:
                return {"files": [], "total_additions": 0, "total_deletions": 0}
            changes = [
                c for c in response.json().get('changes', [])
                if not (c.get('item') or {}).get('isFolder')
                and (c.get('item') or {}).get('gitObjectType', 'blob') == 'blob'
            ]
        except Exception:
            return {"files": [], "total_additions": 0, "total_deletions": 0}

        parent = self._parent_sha(commit_sha)
        files = []
        total_add = total_del = 0
        for index, change in enumerate(changes):
            path = (change.get('item') or {}).get('path')
            change_type = str(change.get('changeType') or '')
            entry = {
                "path": path,
                "is_new": 'add' in change_type,
                "is_deleted": 'delete' in change_type,
                "additions": 0,
                "deletions": 0,
                "diff_preview": "",
            }
            if path and index < self.MAX_DIFF_FILES:
                before = '' if entry["is_new"] or not parent else self._file_at(path, parent)
                after = '' if entry["is_deleted"] else self._file_at(path, commit_sha)
                if before is not None and after is not None:
                    hunks = unified_diff_text(before, after)
                    body = hunks.splitlines()
                    entry["additions"] = sum(1 for l in body if l.startswith('+'))
                    entry["deletions"] = sum(1 for l in body if l.startswith('-'))
                    entry["diff_preview"] = hunks[:DIFF_PREVIEW_CHARS]
            total_add += entry["additions"]
            total_del += entry["deletions"]
            files.append(entry)

        return {
            "files": files,
            "total_additions": total_add,
            "total_deletions": total_del,
            "total_files": len(files),
        }

    def parse_webhook_payload(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse Azure DevOps webhook payload."""
        event_type = payload.get('eventType', '')
        
        if 'git.push' not in event_type:
            return []
        
        resource = payload.get('resource', {})
        commits = resource.get('commits', [])
        ref = resource.get('refUpdates', [{}])[0].get('name', '')
        branch = ref.replace('refs/heads/', '') if ref.startswith('refs/heads/') else ref
        
        return [
            {
                'sha': c.get('commitId'),
                'message': c.get('comment', ''),
                'author_name': c.get('author', {}).get('name'),
                'author_email': c.get('author', {}).get('email'),
                'timestamp': c.get('author', {}).get('date'),
                'branch': branch,
            }
            for c in commits
        ]
    
    def _normalize_commit(self, commit: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Azure DevOps commit to standard format."""
        author = commit.get('author', {})
        return {
            'sha': commit.get('commitId'),
            'message': commit.get('comment', ''),
            'author_name': author.get('name', 'Unknown'),
            'author_email': author.get('email'),
            'timestamp': author.get('date'),
            'branch': None,
        }


class JenkinsProvider:
    """
    Jenkins CI/CD provider implementation.
    
    Note: Jenkins is CI/CD only, not SCM. It does not inherit from BaseProvider
    as it has different methods focused on builds/pipelines rather than commits.
    
    Usage:
        provider = JenkinsProvider(
            base_url='https://jenkins.company.com',
            username='admin',
            api_token='token123'
        )
    """
    
    def __init__(
        self, 
        base_url: str, 
        username: str = '', 
        api_token: str = '',
        job_path: str = ''
    ):
        """
        Initialize Jenkins provider.
        
        Args:
            base_url: Jenkins server URL
            username: Jenkins username
            api_token: Jenkins API token
            job_path: Optional default job path
        """
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.api_token = api_token
        self.job_path = job_path
    
    @property
    def provider_name(self) -> str:
        return 'jenkins'
    
    def _get_auth(self) -> tuple:
        """Get auth tuple for requests."""
        if self.username and self.api_token:
            return (self.username, self.api_token)
        return None
    
    def _get_headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
    
    def verify_connection(self) -> Dict[str, Any]:
        """
        Verify connection to Jenkins by checking the API.
        
        Returns:
            Dictionary with Jenkins info on success
            
        Raises:
            SCMProviderError: If verification fails
        """
        url = f"{self.base_url}/api/json"
        
        try:
            response = requests.get(
                url,
                auth=self._get_auth(),
                headers=self._get_headers(),
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'jenkins_version': response.headers.get('X-Jenkins'),
                    'mode': data.get('mode'),
                    'num_executors': data.get('numExecutors'),
                    'url': data.get('url'),
                    'description': data.get('description'),
                    'jobs_count': len(data.get('jobs', [])),
                }
            elif response.status_code == 401 or response.status_code == 403:
                raise SCMProviderError("Invalid Jenkins credentials")
            else:
                raise SCMProviderError(f"Jenkins verification failed: {response.status_code}")
                
        except SCMProviderError:
            raise
        except requests.exceptions.ConnectionError:
            raise SCMProviderError(f"Cannot connect to Jenkins at {self.base_url}")
        except Exception as e:
            raise SCMProviderError(f"Failed to verify Jenkins connection: {str(e)}")
    
    def list_projects(
        self, 
        page: int = 1, 
        per_page: int = 20, 
        search: str = ''
    ) -> List[Dict[str, Any]]:
        """
        List Jenkins jobs/pipelines.
        
        Args:
            page: Page number (Jenkins doesn't paginate, so this is simulated)
            per_page: Number of items per page
            search: Optional search term
            
        Returns:
            List of job dictionaries
        """
        url = f"{self.base_url}/api/json?tree=jobs[name,url,color,description,buildable,lastBuild[number,result,timestamp]]"
        
        try:
            response = requests.get(
                url,
                auth=self._get_auth(),
                headers=self._get_headers(),
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Jenkins jobs API error: {response.status_code}")
                return []
            
            data = response.json()
            jobs = data.get('jobs', [])
            
            # Filter by search
            if search:
                jobs = [j for j in jobs if search.lower() in j.get('name', '').lower()]
            
            # Simulate pagination
            start = (page - 1) * per_page
            end = start + per_page
            jobs = jobs[start:end]
            
            return [
                {
                    'id': job.get('name'),
                    'name': job.get('name'),
                    'full_name': job.get('name'),
                    'description': job.get('description'),
                    'url': job.get('url'),
                    'color': job.get('color'),  # blue, red, yellow, etc.
                    'buildable': job.get('buildable', True),
                    'last_build': {
                        'number': job.get('lastBuild', {}).get('number'),
                        'result': job.get('lastBuild', {}).get('result'),
                        'timestamp': job.get('lastBuild', {}).get('timestamp'),
                    } if job.get('lastBuild') else None,
                }
                for job in jobs
            ]
            
        except Exception as e:
            logger.exception(f"Failed to list Jenkins jobs: {e}")
            raise SCMProviderError(f"Failed to list jobs: {str(e)}")
    
    def list_recent_pipelines(self, hours: int = 2) -> List[Dict[str, Any]]:
        """
        List recent completed Jenkins builds for the configured job.

        E26-1 fix (2026-09-12): the deploy-sync task (providers/tasks.py
        line 695) calls this on every CI/CD binding's provider. Jenkins
        wasn't a BaseProvider subclass so it inherited nothing → the
        polling task threw AttributeError once per minute per binding.

        Reads builds from ``{job_url}/api/json?tree=builds[...]``, keeps
        only completed ones within the ``hours`` window, and normalises
        each into the ``{id, status, ref, sha, updated_at}`` shape the
        sync task expects (matching BaseProvider signature).

        The Jenkins job path lives on the binding's ``pipeline_id``
        (e.g. ``job/payment-worker/build``). We derive the API URL from
        that instead of hardcoding a single job so multi-binding orgs
        with different jobs work correctly.
        """
        from datetime import timedelta
        job_path = (getattr(self, 'job_name', '') or '').strip('/')
        if not job_path:
            return []

        url = f"{self.base_url}/{job_path}/api/json"
        params = {
            'tree': 'builds[number,result,timestamp,duration,building,'
                    'actions[lastBuiltRevision[SHA1,branch[name]]]]',
        }
        try:
            response = requests.get(
                url, auth=self._get_auth(), headers=self._get_headers(),
                params=params, timeout=30,
            )
            if response.status_code != 200:
                logger.warning(
                    'Jenkins list_recent_pipelines: %s %s',
                    response.status_code, url,
                )
                return []
            data = response.json()
        except Exception as exc:
            logger.warning('Jenkins list_recent_pipelines failed: %s', exc)
            return []

        cutoff = datetime.now(tz=__import__('datetime').timezone.utc) - timedelta(hours=hours)
        status_map = {
            'SUCCESS': 'success',
            'FAILURE': 'failed',
            'UNSTABLE': 'failed',
            'ABORTED': 'canceled',
        }
        results: List[Dict[str, Any]] = []
        for build in data.get('builds', []) or []:
            if build.get('building'):
                continue
            result = build.get('result')
            status = status_map.get(str(result).upper(), '') if result else ''
            if not status:
                continue

            # Jenkins timestamps are milliseconds since epoch.
            ts_ms = build.get('timestamp')
            if ts_ms:
                try:
                    updated_dt = datetime.fromtimestamp(
                        ts_ms / 1000,
                        tz=__import__('datetime').timezone.utc,
                    )
                    if updated_dt < cutoff:
                        continue
                    updated_iso = updated_dt.isoformat()
                except Exception:
                    updated_iso = ''
            else:
                updated_iso = ''

            # Pull SHA + branch from lastBuiltRevision action if present.
            sha, branch = '', ''
            for action in build.get('actions') or []:
                rev = action.get('lastBuiltRevision')
                if rev:
                    sha = rev.get('SHA1', '') or sha
                    branches = rev.get('branch') or []
                    if branches:
                        branch = (branches[0] or {}).get('name', '') or branch
                    if sha:
                        break

            results.append({
                'id': f"{job_path}#{build.get('number')}",
                'status': status,
                'ref': branch,
                'sha': sha,
                'updated_at': updated_iso,
            })
        return results

    def get_build_info(self, job_name: str, build_number: int) -> Dict[str, Any]:
        """
        Get information about a specific build.
        
        Args:
            job_name: Name of the job
            build_number: Build number
            
        Returns:
            Build information dictionary
        """
        url = f"{self.base_url}/job/{job_name}/{build_number}/api/json"
        
        try:
            response = requests.get(
                url,
                auth=self._get_auth(),
                headers=self._get_headers(),
                timeout=30
            )
            
            if response.status_code != 200:
                return {}
            
            data = response.json()
            return {
                'id': data.get('id'),
                'number': data.get('number'),
                'result': data.get('result'),
                'duration': data.get('duration'),
                'timestamp': data.get('timestamp'),
                'url': data.get('url'),
                'building': data.get('building'),
                'display_name': data.get('displayName'),
                'description': data.get('description'),
            }
            
        except Exception as e:
            logger.exception(f"Failed to get Jenkins build info: {e}")
            return {}
    
    def get_build_logs(self, job_name: str, build_number: int) -> str:
        """
        Retrieve console output (logs) for a specific build.

        Args:
            job_name: Name of the Jenkins job
            build_number: Build number

        Returns:
            Build console text, or empty string on failure
        """
        url = f"{self.base_url}/job/{job_name}/{build_number}/consoleText"

        try:
            response = requests.get(
                url,
                auth=self._get_auth(),
                timeout=30,
            )

            if response.status_code == 200:
                return response.text
            else:
                logger.warning(
                    f"Jenkins build logs fetch failed: {job_name}#{build_number} "
                    f"→ {response.status_code}"
                )
                return ''
        except Exception as e:
            logger.error(f"Failed to get Jenkins build logs: {e}")
            return ''

    def list_recent_builds(self, job_name: str, count: int = 10) -> List[Dict[str, Any]]:
        """
        List recent builds for a Jenkins job using the tree API.

        Args:
            job_name: Name of the Jenkins job
            count: Number of recent builds to return (default 10)

        Returns:
            List of build info dicts with id, number, result, timestamp, url, duration
        """
        url = (
            f"{self.base_url}/job/{job_name}/api/json"
            f"?tree=builds[number,result,timestamp,duration,url,building]"
            f"{{0,{count}}}"
        )

        try:
            response = requests.get(
                url,
                auth=self._get_auth(),
                headers=self._get_headers(),
                timeout=30,
            )

            if response.status_code != 200:
                logger.warning(f"Jenkins recent builds fetch failed: {response.status_code}")
                return []

            data = response.json()
            builds = data.get('builds', [])

            return [
                {
                    'id': str(b.get('number', '')),
                    'number': b.get('number'),
                    'result': b.get('result'),
                    'timestamp': b.get('timestamp'),
                    'duration': b.get('duration'),
                    'url': b.get('url'),
                    'building': b.get('building', False),
                }
                for b in builds
            ]
        except Exception as e:
            logger.error(f"Failed to list recent Jenkins builds: {e}")
            return []

    def trigger_build(self, job_name: str, parameters: Dict[str, str] = None) -> Dict[str, Any]:
        """
        Trigger a build for a job.
        
        Args:
            job_name: Name of the job to build
            parameters: Optional build parameters
            
        Returns:
            Trigger response
        """
        if parameters:
            url = f"{self.base_url}/job/{job_name}/buildWithParameters"
        else:
            url = f"{self.base_url}/job/{job_name}/build"
        
        try:
            response = requests.post(
                url,
                auth=self._get_auth(),
                headers=self._get_headers(),
                data=parameters or {},
                timeout=30
            )
            
            if response.status_code in [200, 201]:
                return {'success': True, 'message': 'Build triggered'}
            elif response.status_code == 201:
                # Queue item location in header
                queue_url = response.headers.get('Location')
                return {'success': True, 'queue_url': queue_url}
            else:
                return {'success': False, 'error': f"Status {response.status_code}"}
                
        except Exception as e:
            return {'success': False, 'error': str(e)}


# Provider registry - includes all SCM and CI/CD providers
PROVIDERS = {
    'gitlab': GitLabProvider,
    'github': GitHubProvider,
    'bitbucket': BitbucketProvider,
    'azure_devops': AzureDevOpsProvider,
}

# CI/CD-only providers (different interface)
CICD_PROVIDERS = {
    'jenkins': JenkinsProvider,
}


def get_provider(
    provider_name: str, 
    project_id: str, 
    access_token: str,
    base_url: Optional[str] = None,
    organization: Optional[str] = None,
) -> BaseProvider:
    """
    Factory function to get the appropriate SCM provider.
    
    Args:
        provider_name: Name of the provider ('gitlab', 'github', 'bitbucket', 'azure_devops')
        project_id: SCM project/repository ID
        access_token: API access token
        base_url: Optional custom base URL (for self-hosted instances)
        organization: Azure DevOps organization from the integration's
            credentials (ignored by the other providers)
        
    Returns:
        An instance of the appropriate provider class
        
    Raises:
        ValueError: If provider_name is not supported
    """
    provider_class = PROVIDERS.get(provider_name.lower())
    
    if not provider_class:
        supported = ", ".join(PROVIDERS.keys())
        raise ValueError(f"Unsupported provider: {provider_name}. Supported: {supported}")
    
    if provider_class is AzureDevOpsProvider:
        return provider_class(project_id, access_token, base_url, organization=organization)
    return provider_class(project_id, access_token, base_url)


def get_cicd_provider(
    provider_name: str,
    base_url: str,
    username: str = '',
    api_token: str = '',
    **kwargs
):
    """
    Factory function to get a CI/CD-only provider (e.g., Jenkins).
    
    Args:
        provider_name: Name of the provider ('jenkins')
        base_url: CI/CD server URL
        username: Username for authentication
        api_token: API token
        
    Returns:
        An instance of the appropriate CI/CD provider
        
    Raises:
        ValueError: If provider_name is not supported
    """
    provider_class = CICD_PROVIDERS.get(provider_name.lower())
    
    if not provider_class:
        supported = ", ".join(CICD_PROVIDERS.keys())
        raise ValueError(f"Unsupported CI/CD provider: {provider_name}. Supported: {supported}")
    
    return provider_class(base_url=base_url, username=username, api_token=api_token, **kwargs)
