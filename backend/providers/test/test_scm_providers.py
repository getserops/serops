"""
Unit Tests for SCM Providers

Tests cover:
- GitLab provider initialization and methods
- GitHub provider verify_connection and list_projects
- Bitbucket provider verify_connection and list_projects
- Azure DevOps provider methods
- Jenkins provider methods
- Provider factory functions
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import requests

from providers.scm_providers import (
    get_provider,
    get_cicd_provider,
    GitLabProvider,
    GitHubProvider,
    BitbucketProvider,
    AzureDevOpsProvider,
    JenkinsProvider,
    SCMProviderError,
    AuthenticationError,
    RateLimitError,
    PROVIDERS,
    CICD_PROVIDERS,
)


class TestGitLabProvider(unittest.TestCase):
    """Test cases for GitLabProvider class."""

    def setUp(self):
        """Set up test fixtures."""
        self.project_id = "12345"
        self.access_token = "test-token-abc123"
        self.provider = GitLabProvider(
            project_id=self.project_id,
            access_token=self.access_token
        )

    def test_initialization(self):
        """Test GitLabProvider initializes correctly."""
        self.assertEqual(self.provider.project_id, self.project_id)
        self.assertEqual(self.provider.access_token, self.access_token)
        self.assertEqual(self.provider.base_url, "https://gitlab.com")
        self.assertEqual(self.provider.provider_name, "gitlab")

    def test_custom_base_url(self):
        """Test GitLabProvider with custom base URL."""
        custom_url = "https://gitlab.company.com"
        provider = GitLabProvider(
            project_id=self.project_id,
            access_token=self.access_token,
            base_url=custom_url
        )
        self.assertEqual(provider.base_url, custom_url)

    def test_get_headers(self):
        """Test authentication headers are correctly formatted."""
        headers = self.provider._get_headers()
        self.assertEqual(headers["PRIVATE-TOKEN"], self.access_token)

    @patch('requests.request')
    def test_get_commits_success(self, mock_request):
        """Test successful commit fetching from GitLab."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": "commit1",
                "message": "Fix bug",
                "author_name": "John Doe",
                "author_email": "john@example.com",
                "committed_date": "2024-12-25T10:00:00Z"
            }
        ]
        mock_request.return_value = mock_response

        commits = self.provider.get_commits(limit=50)

        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0]['sha'], "commit1")
        self.assertEqual(commits[0]['author_name'], "John Doe")

    @patch('requests.request')
    def test_verify_connection_success(self, mock_request):
        """Test successful GitLab connection verification."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": 123,
            "username": "testuser",
            "name": "Test User",
            "email": "test@example.com"
        }
        mock_request.return_value = mock_response

        result = self.provider.verify_connection()

        self.assertEqual(result['username'], "testuser")
        self.assertEqual(result['name'], "Test User")

    @patch('requests.request')
    def test_list_projects_success(self, mock_request):
        """Test successful GitLab project listing."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": 1,
                "name": "test-project",
                "path_with_namespace": "group/test-project",
                "description": "A test project",
                "web_url": "https://gitlab.com/group/test-project",
                "default_branch": "main",
                "visibility": "private"
            }
        ]
        mock_request.return_value = mock_response

        projects = self.provider.list_projects()

        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]['name'], "test-project")
        self.assertEqual(projects[0]['default_branch'], "main")


class TestGitHubProvider(unittest.TestCase):
    """Test cases for GitHubProvider class."""

    def setUp(self):
        """Set up test fixtures."""
        self.provider = GitHubProvider(
            project_id="owner/repo",
            access_token="github-token"
        )

    def test_provider_name(self):
        """Test GitHub provider name."""
        self.assertEqual(self.provider.provider_name, "github")

    def test_default_base_url(self):
        """Test GitHub uses correct default API URL."""
        self.assertEqual(self.provider.base_url, "https://api.github.com")

    def test_get_headers(self):
        """Test GitHub headers include Bearer token."""
        headers = self.provider._get_headers()
        self.assertIn("Bearer", headers["Authorization"])
        self.assertEqual(headers["Accept"], "application/vnd.github.v3+json")

    @patch('requests.request')
    def test_verify_connection_success(self, mock_request):
        """Test successful GitHub connection verification."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "login": "octocat",
            "name": "The Octocat",
            "email": "octocat@github.com",
            "avatar_url": "https://avatars.githubusercontent.com/u/583231",
            "html_url": "https://github.com/octocat",
            "type": "User"
        }
        mock_request.return_value = mock_response

        result = self.provider.verify_connection()

        self.assertEqual(result['username'], "octocat")
        self.assertEqual(result['name'], "The Octocat")
        self.assertEqual(result['type'], "User")

    @patch('requests.request')
    def test_verify_connection_invalid_token(self, mock_request):
        """Test GitHub verification with invalid token."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_request.return_value = mock_response

        with self.assertRaises(SCMProviderError) as context:
            self.provider.verify_connection()

        self.assertIn("Authentication failed", str(context.exception))

    @patch('requests.request')
    def test_list_projects_success(self, mock_request):
        """Test successful GitHub repository listing."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": 12345,
                "name": "test-repo",
                "full_name": "owner/test-repo",
                "description": "A test repository",
                "html_url": "https://github.com/owner/test-repo",
                "clone_url": "https://github.com/owner/test-repo.git",
                "default_branch": "main",
                "private": False,
                "owner": {"login": "owner"},
                "updated_at": "2024-01-01T00:00:00Z"
            }
        ]
        mock_request.return_value = mock_response

        projects = self.provider.list_projects()

        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]['id'], "12345")
        self.assertEqual(projects[0]['name'], "test-repo")
        self.assertEqual(projects[0]['full_name'], "owner/test-repo")
        self.assertEqual(projects[0]['default_branch'], "main")
        self.assertFalse(projects[0]['is_private'])

    @patch('requests.request')
    def test_get_commits_success(self, mock_request):
        """Test successful GitHub commit fetching."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "sha": "abc123",
                "commit": {
                    "message": "Fix bug",
                    "author": {
                        "name": "John Doe",
                        "email": "john@example.com",
                        "date": "2024-01-01T00:00:00Z"
                    }
                }
            }
        ]
        mock_request.return_value = mock_response

        commits = self.provider.get_commits()

        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0]['sha'], "abc123")
        self.assertEqual(commits[0]['message'], "Fix bug")


class TestBitbucketProvider(unittest.TestCase):
    """Test cases for BitbucketProvider class."""

    def setUp(self):
        """Set up test fixtures."""
        self.provider = BitbucketProvider(
            project_id="workspace/repo",
            access_token="bitbucket-token"
        )

    def test_provider_name(self):
        """Test Bitbucket provider name."""
        self.assertEqual(self.provider.provider_name, "bitbucket")

    def test_default_base_url(self):
        """Test Bitbucket uses correct default API URL."""
        self.assertEqual(self.provider.base_url, "https://api.bitbucket.org/2.0")

    @patch('requests.request')
    def test_verify_connection_success(self, mock_request):
        """Test successful Bitbucket connection verification."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "username": "testuser",
            "display_name": "Test User",
            "uuid": "{12345}",
            "account_id": "abc123",
            "links": {"avatar": {"href": "https://avatar.url"}},
            "type": "user"
        }
        mock_request.return_value = mock_response

        result = self.provider.verify_connection()

        self.assertEqual(result['username'], "testuser")
        self.assertEqual(result['display_name'], "Test User")

    @patch('requests.request')
    def test_verify_connection_invalid_token(self, mock_request):
        """Test Bitbucket verification with invalid token."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_request.return_value = mock_response

        with self.assertRaises(SCMProviderError) as context:
            self.provider.verify_connection()

        self.assertIn("Authentication failed", str(context.exception))

    @patch('requests.request')
    def test_list_projects_success(self, mock_request):
        """Test successful Bitbucket repository listing."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "values": [
                {
                    "uuid": "{repo-uuid}",
                    "name": "test-repo",
                    "full_name": "workspace/test-repo",
                    "description": "A test repository",
                    "links": {
                        "html": {"href": "https://bitbucket.org/workspace/test-repo"},
                        "clone": [{"name": "https", "href": "https://bitbucket.org/workspace/test-repo.git"}]
                    },
                    "mainbranch": {"name": "master"},
                    "is_private": True,
                    "owner": {"username": "workspace"},
                    "updated_on": "2024-01-01T00:00:00Z"
                }
            ]
        }
        mock_request.return_value = mock_response

        projects = self.provider.list_projects()

        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]['name'], "test-repo")
        self.assertEqual(projects[0]['default_branch'], "master")
        self.assertTrue(projects[0]['is_private'])


class TestAzureDevOpsProvider(unittest.TestCase):
    """Test cases for AzureDevOpsProvider class."""

    def setUp(self):
        """Set up test fixtures."""
        self.provider = AzureDevOpsProvider(
            project_id="myorg/myproject",
            access_token="azure-pat-token"
        )

    def test_provider_name(self):
        """Test Azure DevOps provider name."""
        self.assertEqual(self.provider.provider_name, "azure_devops")

    def test_default_base_url(self):
        """Test Azure DevOps uses correct default URL."""
        self.assertEqual(self.provider.base_url, "https://dev.azure.com")

    def test_org_project_parsing(self):
        """Test organization and project are parsed correctly."""
        self.assertEqual(self.provider.organization, "myorg")
        self.assertEqual(self.provider.project, "myproject")

    def test_org_only_parsing(self):
        """Test parsing when only organization is provided."""
        provider = AzureDevOpsProvider(
            project_id="myorg",
            access_token="token"
        )
        self.assertEqual(provider.organization, "myorg")
        self.assertIsNone(provider.project)

    @patch('requests.request')
    def test_verify_connection_success(self, mock_request):
        """Test successful Azure DevOps connection verification."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "authenticatedUser": {
                "providerDisplayName": "Test User",
                "id": "user-id-123",
                "descriptor": "desc123"
            }
        }
        mock_request.return_value = mock_response

        result = self.provider.verify_connection()

        self.assertEqual(result['username'], "Test User")
        self.assertEqual(result['organization'], "myorg")

    @patch('requests.request')
    def test_verify_connection_invalid_pat(self, mock_request):
        """Test Azure DevOps verification with invalid PAT."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_request.return_value = mock_response

        with self.assertRaises(SCMProviderError) as context:
            self.provider.verify_connection()

        self.assertIn("Authentication failed", str(context.exception))

    @patch('requests.request')
    def test_list_projects_success(self, mock_request):
        """The Azure picker lists Git repositories (a project can hold several)."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "value": [
                {
                    "id": "repo-guid-1",
                    "name": "payments-api",
                    "defaultBranch": "refs/heads/main",
                    "webUrl": "https://dev.azure.com/myorg/MyProject/_git/payments-api",
                    "project": {"name": "MyProject", "description": "A project", "visibility": "private"},
                }
            ]
        }
        mock_request.return_value = mock_response

        projects = self.provider.list_projects()

        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]['id'], "myorg/MyProject/payments-api")
        self.assertEqual(projects[0]['name'], "payments-api")
        self.assertEqual(projects[0]['full_name'], "MyProject/payments-api")
        self.assertEqual(projects[0]['default_branch'], "main")
        self.assertTrue(projects[0]['is_private'])


class TestJenkinsProvider(unittest.TestCase):
    """Test cases for JenkinsProvider class."""

    def setUp(self):
        """Set up test fixtures."""
        self.provider = JenkinsProvider(
            base_url="https://jenkins.company.com",
            username="admin",
            api_token="jenkins-token"
        )

    def test_provider_name(self):
        """Test Jenkins provider name."""
        self.assertEqual(self.provider.provider_name, "jenkins")

    def test_base_url_normalized(self):
        """Test base URL trailing slash is removed."""
        provider = JenkinsProvider(
            base_url="https://jenkins.company.com/",
            username="admin",
            api_token="token"
        )
        self.assertEqual(provider.base_url, "https://jenkins.company.com")

    def test_auth_tuple(self):
        """Test authentication tuple is correct."""
        auth = self.provider._get_auth()
        self.assertEqual(auth, ("admin", "jenkins-token"))

    def test_no_auth_when_missing(self):
        """Test no auth when credentials missing."""
        provider = JenkinsProvider(base_url="https://jenkins.com")
        self.assertIsNone(provider._get_auth())

    @patch('requests.get')
    def test_verify_connection_success(self, mock_get):
        """Test successful Jenkins connection verification."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'X-Jenkins': '2.401.1'}
        mock_response.json.return_value = {
            "mode": "NORMAL",
            "numExecutors": 2,
            "url": "https://jenkins.company.com/",
            "description": "Jenkins CI",
            "jobs": [{}, {}, {}]
        }
        mock_get.return_value = mock_response

        result = self.provider.verify_connection()

        self.assertEqual(result['jenkins_version'], "2.401.1")
        self.assertEqual(result['jobs_count'], 3)

    @patch('requests.get')
    def test_verify_connection_invalid_credentials(self, mock_get):
        """Test Jenkins verification with invalid credentials."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response

        with self.assertRaises(SCMProviderError) as context:
            self.provider.verify_connection()

        self.assertIn("Invalid Jenkins credentials", str(context.exception))

    @patch('requests.get')
    def test_verify_connection_cannot_connect(self, mock_get):
        """Test Jenkins verification when server unreachable."""
        mock_get.side_effect = requests.exceptions.ConnectionError()

        with self.assertRaises(SCMProviderError) as context:
            self.provider.verify_connection()

        self.assertIn("Cannot connect to Jenkins", str(context.exception))

    @patch('requests.get')
    def test_list_projects_success(self, mock_get):
        """Test successful Jenkins job listing."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jobs": [
                {
                    "name": "build-job",
                    "url": "https://jenkins.company.com/job/build-job/",
                    "color": "blue",
                    "description": "Main build job",
                    "buildable": True,
                    "lastBuild": {
                        "number": 42,
                        "result": "SUCCESS",
                        "timestamp": 1704067200000
                    }
                }
            ]
        }
        mock_get.return_value = mock_response

        jobs = self.provider.list_projects()

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['name'], "build-job")
        self.assertEqual(jobs[0]['color'], "blue")
        self.assertEqual(jobs[0]['last_build']['number'], 42)
        self.assertEqual(jobs[0]['last_build']['result'], "SUCCESS")

    @patch('requests.get')
    def test_list_projects_with_search(self, mock_get):
        """Test Jenkins job listing with search filter."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jobs": [
                {"name": "build-job", "url": "url1"},
                {"name": "deploy-job", "url": "url2"},
                {"name": "test-job", "url": "url3"}
            ]
        }
        mock_get.return_value = mock_response

        jobs = self.provider.list_projects(search="deploy")

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['name'], "deploy-job")

    @patch('requests.get')
    def test_get_build_logs_success(self, mock_get):
        """Test successful build log retrieval."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "Started by user admin\nBuilding...\nFinished: SUCCESS"
        mock_get.return_value = mock_response

        logs = self.provider.get_build_logs("my-job", 42)

        self.assertEqual(logs, "Started by user admin\nBuilding...\nFinished: SUCCESS")
        mock_get.assert_called_once_with(
            "https://jenkins.company.com/job/my-job/42/consoleText",
            auth=("admin", "jenkins-token"),
            timeout=30,
        )

    @patch('requests.get')
    def test_get_build_logs_not_found(self, mock_get):
        """Test build log retrieval returns empty string on 404."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        logs = self.provider.get_build_logs("missing-job", 1)

        self.assertEqual(logs, '')

    @patch('requests.get')
    def test_get_build_logs_connection_error(self, mock_get):
        """Test build log retrieval returns empty string on connection error."""
        mock_get.side_effect = requests.exceptions.ConnectionError()

        logs = self.provider.get_build_logs("my-job", 42)

        self.assertEqual(logs, '')

    @patch('requests.get')
    def test_list_recent_builds_success(self, mock_get):
        """Test successful recent builds listing."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "builds": [
                {
                    "number": 10,
                    "result": "SUCCESS",
                    "timestamp": 1704067200000,
                    "duration": 30000,
                    "url": "https://jenkins.company.com/job/my-job/10/",
                    "building": False,
                },
                {
                    "number": 9,
                    "result": "FAILURE",
                    "timestamp": 1704060000000,
                    "duration": 15000,
                    "url": "https://jenkins.company.com/job/my-job/9/",
                    "building": False,
                },
            ]
        }
        mock_get.return_value = mock_response

        builds = self.provider.list_recent_builds("my-job", count=5)

        self.assertEqual(len(builds), 2)
        self.assertEqual(builds[0]['number'], 10)
        self.assertEqual(builds[0]['result'], 'SUCCESS')
        self.assertEqual(builds[0]['id'], '10')
        self.assertFalse(builds[0]['building'])
        self.assertEqual(builds[1]['result'], 'FAILURE')

    @patch('requests.get')
    def test_list_recent_builds_empty(self, mock_get):
        """Test recent builds listing returns empty list on failure."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        builds = self.provider.list_recent_builds("my-job")

        self.assertEqual(builds, [])

    @patch('requests.get')
    def test_list_recent_builds_connection_error(self, mock_get):
        """Test recent builds listing returns empty list on connection error."""
        mock_get.side_effect = requests.exceptions.ConnectionError()

        builds = self.provider.list_recent_builds("my-job")

        self.assertEqual(builds, [])


class TestProviderFactory(unittest.TestCase):
    """Test cases for provider factory functions."""

    def test_provider_registry_contains_all(self):
        """Test PROVIDERS registry contains all SCM providers."""
        self.assertIn('gitlab', PROVIDERS)
        self.assertIn('github', PROVIDERS)
        self.assertIn('bitbucket', PROVIDERS)
        self.assertIn('azure_devops', PROVIDERS)

    def test_cicd_provider_registry(self):
        """Test CICD_PROVIDERS registry contains Jenkins."""
        self.assertIn('jenkins', CICD_PROVIDERS)

    def test_get_gitlab_provider(self):
        """Test factory returns GitLabProvider for gitlab."""
        provider = get_provider('gitlab', '123', 'token')
        self.assertIsInstance(provider, GitLabProvider)

    def test_get_github_provider(self):
        """Test factory returns GitHubProvider for github."""
        provider = get_provider('github', 'owner/repo', 'token')
        self.assertIsInstance(provider, GitHubProvider)

    def test_get_bitbucket_provider(self):
        """Test factory returns BitbucketProvider for bitbucket."""
        provider = get_provider('bitbucket', 'workspace/repo', 'token')
        self.assertIsInstance(provider, BitbucketProvider)

    def test_get_azure_devops_provider(self):
        """Test factory returns AzureDevOpsProvider for azure_devops."""
        provider = get_provider('azure_devops', 'org/project', 'token')
        self.assertIsInstance(provider, AzureDevOpsProvider)

    def test_case_insensitive(self):
        """Test factory handles case-insensitive provider names."""
        provider1 = get_provider('GitLab', '123', 'token')
        provider2 = get_provider('GITLAB', '123', 'token')
        self.assertIsInstance(provider1, GitLabProvider)
        self.assertIsInstance(provider2, GitLabProvider)

    def test_unsupported_scm_provider(self):
        """Test factory raises ValueError for unsupported SCM providers."""
        with self.assertRaises(ValueError) as context:
            get_provider('unknown', '123', 'token')

        self.assertIn("Unsupported provider", str(context.exception))

    def test_custom_base_url(self):
        """Test factory passes custom base_url to provider."""
        custom_url = "https://gitlab.custom.com"
        provider = get_provider('gitlab', '123', 'token', base_url=custom_url)
        self.assertEqual(provider.base_url, custom_url)

    def test_get_jenkins_provider(self):
        """Test CICD factory returns JenkinsProvider."""
        provider = get_cicd_provider(
            'jenkins',
            base_url='https://jenkins.com',
            username='admin',
            api_token='token'
        )
        self.assertIsInstance(provider, JenkinsProvider)

    def test_unsupported_cicd_provider(self):
        """Test CICD factory raises ValueError for unsupported providers."""
        with self.assertRaises(ValueError) as context:
            get_cicd_provider('unknown', base_url='https://example.com')

        self.assertIn("Unsupported CI/CD provider", str(context.exception))


if __name__ == '__main__':
    unittest.main()
