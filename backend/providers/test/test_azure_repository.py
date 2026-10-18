"""
Azure DevOps bindings point at the right Git repository.

An Azure project can hold several repositories, named differently from the
project. The provider used to assume repository == project, and the
organization saved with an integration never reached the provider, so the
repository picker called https://dev.azure.com//_apis/projects.
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from providers.scm_providers import AzureDevOpsProvider, GitHubProvider, get_provider


def _ok(json):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = json
    return r


class RepositoryIdParsingTests(SimpleTestCase):
    def test_org_project_still_means_the_repo_named_like_the_project(self):
        p = AzureDevOpsProvider('acme/Shop', 'pat')
        self.assertEqual((p.organization, p.project, p.repository), ('acme', 'Shop', 'Shop'))

    def test_org_project_repository(self):
        p = AzureDevOpsProvider('acme/Shop/payments-api', 'pat')
        self.assertEqual((p.organization, p.project, p.repository), ('acme', 'Shop', 'payments-api'))

    def test_organization_from_the_integration(self):
        p = AzureDevOpsProvider('Shop/payments-api', 'pat', organization='acme')
        self.assertEqual((p.organization, p.project, p.repository), ('acme', 'Shop', 'payments-api'))

    def test_full_id_with_organization_given_is_not_doubled(self):
        p = AzureDevOpsProvider('acme/Shop/payments-api', 'pat', organization='acme')
        self.assertEqual((p.organization, p.project, p.repository), ('acme', 'Shop', 'payments-api'))

    def test_organization_url_as_base_url(self):
        p = AzureDevOpsProvider('Shop/payments-api', 'pat', base_url='https://dev.azure.com/acme/')
        self.assertEqual(p.base_url, 'https://dev.azure.com')
        self.assertEqual((p.organization, p.project, p.repository), ('acme', 'Shop', 'payments-api'))

    def test_integration_level_provider_has_the_organization(self):
        p = AzureDevOpsProvider('', 'pat', organization='acme')
        self.assertEqual(p.organization, 'acme')
        self.assertIsNone(p.project)


class RequestUrlTests(SimpleTestCase):
    @patch('requests.request')
    def test_commits_use_the_repository_not_the_project(self, mock_request):
        mock_request.return_value = _ok({'value': []})
        AzureDevOpsProvider('acme/Shop/payments-api', 'pat').get_commits()
        url = mock_request.call_args.kwargs['url']
        self.assertIn('/acme/Shop/_apis/git/repositories/payments-api/commits', url)

    @patch('requests.request')
    def test_diff_uses_the_repository(self, mock_request):
        mock_request.return_value = _ok({'changes': [], 'parents': []})
        AzureDevOpsProvider('acme/Shop/payments-api', 'pat').get_commit_diff('abc')
        urls = [c.kwargs['url'] for c in mock_request.call_args_list]
        self.assertTrue(all('/_apis/git/repositories/payments-api/' in u for u in urls), urls)

    @patch('requests.request')
    def test_picker_lists_repositories_across_the_organization(self, mock_request):
        mock_request.return_value = _ok({'value': [
            {'name': 'web', 'project': {'name': 'Shop'}},
            {'name': 'payments-api', 'project': {'name': 'Shop', 'visibility': 'public'}, 'defaultBranch': 'refs/heads/trunk'},
            {'name': 'infra', 'project': {'name': 'Platform'}},
        ]})
        repos = AzureDevOpsProvider('', 'pat', organization='acme').list_projects(search='shop')
        self.assertEqual(mock_request.call_args.kwargs['url'], 'https://dev.azure.com/acme/_apis/git/repositories?api-version=7.0')
        self.assertEqual([r['id'] for r in repos], ['acme/Shop/payments-api', 'acme/Shop/web'])
        self.assertEqual(repos[0]['default_branch'], 'trunk')
        self.assertFalse(repos[0]['is_private'])

    @patch('requests.request')
    def test_picker_pagination(self, mock_request):
        mock_request.return_value = _ok({'value': [{'name': f'r{i:02d}', 'project': {'name': 'P'}} for i in range(25)]})
        page2 = AzureDevOpsProvider('', 'pat', organization='acme').list_projects(page=2, per_page=20)
        self.assertEqual([r['name'] for r in page2], ['r20', 'r21', 'r22', 'r23', 'r24'])


class FactoryTests(SimpleTestCase):
    def test_organization_reaches_azure(self):
        p = get_provider('azure_devops', 'Shop/payments-api', 'pat', organization='acme')
        self.assertEqual((p.organization, p.repository), ('acme', 'payments-api'))

    def test_other_providers_ignore_it(self):
        p = get_provider('github', 'acme/api', 'tok', organization='ignored')
        self.assertIsInstance(p, GitHubProvider)
        self.assertEqual(p.project_id, 'acme/api')


class IntegrationWiringTests(SimpleTestCase):
    """The organization saved in an integration's credentials reaches every
    provider built from it."""

    def _integration(self, creds):
        from providers.models import ProviderIntegration
        integ = ProviderIntegration(provider_type='azure_devops', name='Azure', base_url='https://dev.azure.com')
        integ.set_credentials(creds)
        return integ

    def test_provider_organization(self):
        self.assertEqual(self._integration({'access_token': 'pat-123456789', 'organization': 'acme'}).provider_organization(), 'acme')
        self.assertEqual(self._integration({'access_token': 'pat-123456789'}).provider_organization(), '')

    def test_scm_binding_builds_the_provider_with_it(self):
        from Projects.models import SCMBinding
        binding = SCMBinding(repository_id='Shop/payments-api')
        binding.integration = self._integration({'access_token': 'pat-123456789', 'organization': 'acme'})
        p = binding.get_provider()
        self.assertEqual((p.organization, p.project, p.repository), ('acme', 'Shop', 'payments-api'))
