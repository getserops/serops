"""
Tests for get_gitlab_api_base() helper.

Verifies self-hosted GitLab URL resolution from:
- GitlabProject.gitlab_url
- project_id DB lookup
- url_hint (request data)
- Fallback to https://gitlab.com
"""

from unittest.mock import patch, MagicMock

from django.test import SimpleTestCase


class TestGetGitlabApiBase(SimpleTestCase):

    def test_returns_project_gitlab_url(self):
        from providers.utils import get_gitlab_api_base

        project = MagicMock()
        project.gitlab_url = 'https://gitlab.company.com'

        result = get_gitlab_api_base(project=project)
        self.assertEqual(result, 'https://gitlab.company.com')

    def test_strips_trailing_slash(self):
        from providers.utils import get_gitlab_api_base

        project = MagicMock()
        project.gitlab_url = 'https://gitlab.company.com/'

        result = get_gitlab_api_base(project=project)
        self.assertEqual(result, 'https://gitlab.company.com')

    def test_falls_back_to_default(self):
        from providers.utils import get_gitlab_api_base

        result = get_gitlab_api_base()
        self.assertEqual(result, 'https://gitlab.com')

    def test_empty_gitlab_url_falls_back(self):
        from providers.utils import get_gitlab_api_base

        project = MagicMock()
        project.gitlab_url = ''

        result = get_gitlab_api_base(project=project)
        self.assertEqual(result, 'https://gitlab.com')

    def test_url_hint_extracts_base(self):
        from providers.utils import get_gitlab_api_base

        result = get_gitlab_api_base(url_hint='https://gitlab.self-hosted.io/group/project')
        self.assertEqual(result, 'https://gitlab.self-hosted.io')

    def test_url_hint_simple_base(self):
        from providers.utils import get_gitlab_api_base

        result = get_gitlab_api_base(url_hint='https://gitlab.example.com')
        self.assertEqual(result, 'https://gitlab.example.com')

    @patch('providers.utils.GitlabProject.objects')
    def test_project_id_db_lookup(self, mock_objects):
        from providers.utils import get_gitlab_api_base

        mock_gp = MagicMock()
        mock_gp.gitlab_url = 'https://gitlab.internal.com'
        mock_objects.filter.return_value.only.return_value.first.return_value = mock_gp

        result = get_gitlab_api_base(project_id='12345')
        self.assertEqual(result, 'https://gitlab.internal.com')

    @patch('providers.utils.GitlabProject.objects')
    def test_project_id_not_found_falls_back(self, mock_objects):
        from providers.utils import get_gitlab_api_base

        mock_objects.filter.return_value.only.return_value.first.return_value = None

        result = get_gitlab_api_base(project_id='99999')
        self.assertEqual(result, 'https://gitlab.com')
