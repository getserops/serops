"""
Tests for unified environment detection.

Verifies that:
- project_id triggers ProjectEnvironment DB lookup
- Without project_id, heuristics are used (existing behavior)
- Falls back when no DB match
- SCMBinding lookup works for non-GitLab project_ids
"""

from unittest.mock import patch, MagicMock
from django.test import SimpleTestCase


class TestDetectEnvironmentGeneric(SimpleTestCase):
    """Test detect_environment_generic with unified behavior."""

    def test_without_project_id_uses_heuristics_main(self):
        from providers.webhook_base import detect_environment_generic

        result = detect_environment_generic(branch='main')
        self.assertEqual(result, 'production')

    def test_without_project_id_uses_heuristics_develop(self):
        from providers.webhook_base import detect_environment_generic

        result = detect_environment_generic(branch='develop')
        self.assertEqual(result, 'development')

    def test_without_project_id_uses_heuristics_staging(self):
        from providers.webhook_base import detect_environment_generic

        result = detect_environment_generic(branch='staging')
        self.assertEqual(result, 'staging')

    def test_explicit_env_takes_priority(self):
        from providers.webhook_base import detect_environment_generic

        result = detect_environment_generic(
            branch='main', explicit_env='staging',
        )
        self.assertEqual(result, 'staging')

    def test_job_name_pattern(self):
        from providers.webhook_base import detect_environment_generic

        result = detect_environment_generic(job_name='deploy-to-production')
        self.assertEqual(result, 'production')

    def test_default_is_development(self):
        from providers.webhook_base import detect_environment_generic

        result = detect_environment_generic()
        self.assertEqual(result, 'development')

    @patch('Projects.models.SCMBinding')
    @patch('Projects.models.ProjectEnvironment')
    @patch('Projects.models.ProjectService')
    @patch('providers.models.GitlabProject')
    def test_with_project_id_checks_project_environment(
        self, mock_gp, mock_ps, mock_pe, mock_scm
    ):
        from providers.webhook_base import detect_environment_generic

        # Set up SCMBinding to return a project
        mock_project = MagicMock()
        mock_binding = MagicMock()
        mock_binding.project_service.project = mock_project
        mock_scm.objects.filter.return_value.select_related.return_value.first.return_value = mock_binding

        # Set up ProjectEnvironment to match
        mock_env = MagicMock()
        mock_env.name = 'staging'
        mock_env.matches_branch.return_value = True
        mock_pe.objects.filter.return_value = [mock_env]

        result = detect_environment_generic(branch='release/1.0', project_id='owner/repo')
        self.assertEqual(result, 'staging')

    @patch('Projects.models.SCMBinding')
    @patch('Projects.models.ProjectEnvironment')
    @patch('Projects.models.ProjectService')
    @patch('providers.models.GitlabProject')
    def test_falls_back_when_no_db_match(
        self, mock_gp, mock_ps, mock_pe, mock_scm
    ):
        from providers.webhook_base import detect_environment_generic

        # SCMBinding returns nothing
        mock_scm.objects.filter.return_value.select_related.return_value.first.return_value = None
        # GitlabProject returns nothing
        mock_gp.objects.filter.return_value.first.return_value = None

        # Should fall through to branch heuristics
        result = detect_environment_generic(branch='main', project_id='unknown-project')
        self.assertEqual(result, 'production')

    @patch('Projects.models.SCMBinding')
    @patch('Projects.models.ProjectEnvironment')
    @patch('Projects.models.ProjectService')
    @patch('providers.models.GitlabProject')
    def test_scm_binding_lookup(self, mock_gp, mock_ps, mock_pe, mock_scm):
        from providers.webhook_base import detect_environment_generic

        # SCMBinding resolves the project
        mock_project = MagicMock()
        mock_binding = MagicMock()
        mock_binding.project_service.project = mock_project
        mock_scm.objects.filter.return_value.select_related.return_value.first.return_value = mock_binding

        # ProjectEnvironment matches
        mock_env = MagicMock()
        mock_env.name = 'production'
        mock_env.matches_branch.return_value = True
        mock_pe.objects.filter.return_value = [mock_env]

        result = detect_environment_generic(branch='release/v2', project_id='owner/repo')

        # Verify SCMBinding was queried with the project_id
        mock_scm.objects.filter.assert_called_with(repository_id='owner/repo')
        self.assertEqual(result, 'production')

    @patch('Projects.models.SCMBinding')
    @patch('Projects.models.ProjectEnvironment')
    @patch('Projects.models.ProjectService')
    @patch('providers.models.GitlabProject')
    def test_gitlab_project_fallback_lookup(self, mock_gp, mock_ps, mock_pe, mock_scm):
        from providers.webhook_base import detect_environment_generic

        # SCMBinding returns nothing
        mock_scm.objects.filter.return_value.select_related.return_value.first.return_value = None

        # GitlabProject + ProjectService returns a project
        mock_gp_instance = MagicMock()
        mock_gp.objects.filter.return_value.first.return_value = mock_gp_instance

        mock_project = MagicMock()
        mock_ps_instance = MagicMock()
        mock_ps_instance.project = mock_project
        mock_ps.objects.filter.return_value.select_related.return_value.first.return_value = mock_ps_instance

        # ProjectEnvironment matches
        mock_env = MagicMock()
        mock_env.name = 'staging'
        mock_env.matches_branch.return_value = True
        mock_pe.objects.filter.return_value = [mock_env]

        result = detect_environment_generic(branch='staging-v2', project_id='12345')
        self.assertEqual(result, 'staging')

    def test_no_branch_skips_db_lookup(self):
        """When branch is None/empty, DB lookup is skipped even with project_id."""
        from providers.webhook_base import detect_environment_generic

        result = detect_environment_generic(branch='', project_id='42', job_name='deploy-staging')
        self.assertEqual(result, 'staging')

    @patch('Projects.models.SCMBinding')
    def test_db_exception_falls_through(self, mock_scm):
        """DB errors should be caught silently, falling through to heuristics."""
        from providers.webhook_base import detect_environment_generic

        mock_scm.objects.filter.side_effect = Exception("DB error")

        result = detect_environment_generic(branch='main', project_id='42')
        self.assertEqual(result, 'production')
