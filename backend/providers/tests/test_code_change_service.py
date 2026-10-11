"""
Tests for provider-agnostic code change service.

Verifies that get_changes_for_project_name resolves SCM project IDs
exclusively from SCMBinding.
"""

from datetime import datetime
from unittest.mock import MagicMock, Mock, PropertyMock, patch

from django.test import SimpleTestCase


class TestGetChangesForProjectNameAgnostic(SimpleTestCase):
    """Test that get_changes_for_project_name uses SCMBinding only."""

    def _setup_code_change_mock(self, MockCodeChange):
        """Set up the CodeChange queryset mock chain."""
        mock_qs = MagicMock()
        mock_qs.order_by.return_value = mock_qs
        mock_qs.__getitem__ = Mock(return_value=[])
        MockCodeChange.objects.filter.return_value = mock_qs
        return mock_qs

    @patch('providers.code_change_service.CodeChange')
    @patch('Projects.models.ProjectService.objects')
    def test_resolves_scm_binding_repository_id(
        self, mock_ps_objects, MockCodeChange,
    ):
        """Should resolve project IDs from SCMBinding."""
        from providers.code_change_service import CodeChangeService

        scm_binding = Mock()
        scm_binding.repository_id = 'owner/repo'

        svc = Mock()
        svc.scm_binding = scm_binding

        mock_ps_objects.filter.return_value = [svc]
        self._setup_code_change_mock(MockCodeChange)

        CodeChangeService.get_changes_for_project_name(
            project_name='MyProject',
            start_time=datetime(2026, 1, 1, 10, 0),
            end_time=datetime(2026, 1, 1, 11, 0),
        )

        filter_kwargs = MockCodeChange.objects.filter.call_args[1]
        self.assertIn('project_id__in', filter_kwargs)
        self.assertIn('owner/repo', filter_kwargs['project_id__in'])

    @patch('providers.code_change_service.CodeChange')
    @patch('Projects.models.ProjectService.objects')
    def test_multiple_scm_bindings(
        self, mock_ps_objects, MockCodeChange,
    ):
        """Should collect IDs from multiple SCMBindings across services."""
        from providers.code_change_service import CodeChangeService

        svc1 = Mock()
        svc1.scm_binding = Mock(repository_id='gh-owner/repo')

        svc2 = Mock()
        svc2.scm_binding = Mock(repository_id='bb-team/repo')

        mock_ps_objects.filter.return_value = [svc1, svc2]
        self._setup_code_change_mock(MockCodeChange)

        CodeChangeService.get_changes_for_project_name(
            project_name='MultiProvider',
            start_time=datetime(2026, 1, 1, 10, 0),
            end_time=datetime(2026, 1, 1, 11, 0),
        )

        filter_kwargs = MockCodeChange.objects.filter.call_args[1]
        project_ids = filter_kwargs['project_id__in']
        self.assertIn('gh-owner/repo', project_ids)
        self.assertIn('bb-team/repo', project_ids)

    @patch('providers.code_change_service.CodeChange')
    @patch('Projects.models.ProjectService.objects')
    def test_returns_empty_when_no_services(
        self, mock_ps_objects, MockCodeChange,
    ):
        """Should return empty list when no matching project services exist."""
        from providers.code_change_service import CodeChangeService

        mock_ps_objects.filter.return_value = []

        result = CodeChangeService.get_changes_for_project_name(
            project_name='NonExistent',
            start_time=datetime(2026, 1, 1, 10, 0),
            end_time=datetime(2026, 1, 1, 11, 0),
        )

        self.assertEqual(result, [])
        MockCodeChange.objects.filter.assert_not_called()

    @patch('providers.code_change_service.CodeChange')
    @patch('Projects.models.ProjectService.objects')
    def test_returns_empty_when_no_scm_binding(
        self, mock_ps_objects, MockCodeChange,
    ):
        """Should return empty list when services have no SCMBinding."""
        from providers.code_change_service import CodeChangeService

        svc = Mock()
        svc.scm_binding = None

        mock_ps_objects.filter.return_value = [svc]

        result = CodeChangeService.get_changes_for_project_name(
            project_name='NoBindings',
            start_time=datetime(2026, 1, 1, 10, 0),
            end_time=datetime(2026, 1, 1, 11, 0),
        )

        self.assertEqual(result, [])
        MockCodeChange.objects.filter.assert_not_called()

    @patch('providers.code_change_service.CodeChange')
    @patch('Projects.models.ProjectService.objects')
    def test_dedup_scm_ids_across_services(
        self, mock_ps_objects, MockCodeChange,
    ):
        """Same repository_id from multiple services should not duplicate."""
        from providers.code_change_service import CodeChangeService

        svc1 = Mock()
        svc1.scm_binding = Mock(repository_id='shared-repo')

        svc2 = Mock()
        svc2.scm_binding = Mock(repository_id='shared-repo')

        mock_ps_objects.filter.return_value = [svc1, svc2]
        self._setup_code_change_mock(MockCodeChange)

        CodeChangeService.get_changes_for_project_name(
            project_name='DupProject',
            start_time=datetime(2026, 1, 1, 10, 0),
            end_time=datetime(2026, 1, 1, 11, 0),
        )

        filter_kwargs = MockCodeChange.objects.filter.call_args[1]
        project_ids = filter_kwargs['project_id__in']
        self.assertEqual(project_ids.count('shared-repo'), 1)

    @patch('providers.code_change_service.CodeChange')
    @patch('Projects.models.ProjectService.objects')
    def test_query_uses_case_insensitive_project_name(
        self, mock_ps_objects, MockCodeChange,
    ):
        """Should use case-insensitive lookup for project name."""
        from providers.code_change_service import CodeChangeService

        mock_ps_objects.filter.return_value = []

        CodeChangeService.get_changes_for_project_name(
            project_name='MyProject',
            start_time=datetime(2026, 1, 1, 10, 0),
            end_time=datetime(2026, 1, 1, 11, 0),
        )

        filter_kwargs = mock_ps_objects.filter.call_args[1]
        self.assertIn('project__name__iexact', filter_kwargs)
        self.assertEqual(filter_kwargs['project__name__iexact'], 'MyProject')
