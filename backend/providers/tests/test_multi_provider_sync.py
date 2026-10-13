"""
Tests for multi-provider sync in sync_recent_deployments.

Verifies that:
- CICDBinding sync processes non-GitLab bindings
- GitLab bindings are excluded from the new section
- Inactive bindings are skipped
- last_sync_at is updated after successful sync
"""

from unittest.mock import patch, MagicMock
from django.test import SimpleTestCase


def _patch_sync():
    """Return a dict of patch context managers for sync_recent_deployments internals."""
    return {
        'requests': patch('providers.tasks.requests'),
        'GitlabProject': patch('providers.models.GitlabProject'),
        'Pipeline': patch('providers.models.Pipeline'),
        'CodeChange': patch('providers.models.CodeChange'),
        'Deployment': patch('providers.models.Deployment'),
        'CICDBinding': patch('Projects.models.CICDBinding'),
        'detect_env': patch('providers.webhook_base.detect_environment_generic', return_value='production'),
        'timezone': patch('providers.tasks.timezone'),
    }


class TestMultiProviderSync(SimpleTestCase):
    """Test the non-GitLab CICDBinding sync section of sync_recent_deployments."""

    def _run_sync(self, bindings_list):
        """Run sync_recent_deployments with all internals mocked."""
        patches = _patch_sync()
        mocks = {}
        try:
            for name, p in patches.items():
                mocks[name] = p.start()

            # GitLab section: no projects
            mocks['GitlabProject'].objects.exclude.return_value.exclude.return_value = MagicMock(
                exists=MagicMock(return_value=False)
            )

            # CICDBinding queryset
            mocks['CICDBinding'].objects.filter.return_value.exclude.return_value.select_related.return_value = bindings_list

            # Pipeline get_or_create
            mock_pipeline = MagicMock()
            mock_pipeline.status = ''
            mocks['Pipeline'].objects.get_or_create.return_value = (mock_pipeline, True)

            # CodeChange
            mocks['CodeChange'].objects.filter.return_value.first.return_value = None
            mocks['CodeChange'].objects.create.return_value = MagicMock()

            # Deployment
            mocks['Deployment'].objects.get_or_create.return_value = (MagicMock(), True)

            # timezone.now()
            mocks['timezone'].now.return_value = MagicMock()

            from providers.tasks import sync_recent_deployments
            result = sync_recent_deployments(hours=2)
            return result, mocks
        finally:
            for p in patches.values():
                p.stop()

    def test_sync_processes_github_bindings(self):
        mock_provider = MagicMock()
        mock_provider.list_recent_pipelines.return_value = [
            {'id': '100', 'status': 'success', 'ref': 'main', 'sha': 'abc123'},
        ]

        mock_binding = MagicMock()
        mock_binding.provider_type = 'github_actions'
        mock_binding.pipeline_id = 'owner/repo'
        mock_binding.get_provider.return_value = mock_provider
        mock_binding.project_service.project.organisation = None

        result, mocks = self._run_sync([mock_binding])

        mock_provider.list_recent_pipelines.assert_called_once_with(2)
        self.assertGreaterEqual(result['pipelines_synced'], 1)
        mock_binding.save.assert_called_with(update_fields=['last_sync_at'])

    def test_sync_skips_gitlab_bindings(self):
        patches = _patch_sync()
        mocks = {}
        try:
            for name, p in patches.items():
                mocks[name] = p.start()

            mocks['GitlabProject'].objects.exclude.return_value.exclude.return_value = MagicMock(
                exists=MagicMock(return_value=False)
            )

            mock_qs = MagicMock()
            mocks['CICDBinding'].objects.filter.return_value = mock_qs
            mock_qs.exclude.return_value.select_related.return_value = []

            from providers.tasks import sync_recent_deployments
            sync_recent_deployments(hours=2)

            mock_qs.exclude.assert_called_once_with(integration__provider_type='gitlab')
        finally:
            for p in patches.values():
                p.stop()

    def test_sync_skips_inactive_bindings(self):
        patches = _patch_sync()
        mocks = {}
        try:
            for name, p in patches.items():
                mocks[name] = p.start()

            mocks['GitlabProject'].objects.exclude.return_value.exclude.return_value = MagicMock(
                exists=MagicMock(return_value=False)
            )

            mocks['CICDBinding'].objects.filter.return_value.exclude.return_value.select_related.return_value = []

            from providers.tasks import sync_recent_deployments
            sync_recent_deployments(hours=2)

            mocks['CICDBinding'].objects.filter.assert_called_once_with(
                is_active=True,
                integration__is_active=True,
            )
        finally:
            for p in patches.values():
                p.stop()

    def test_sync_updates_last_sync_at(self):
        mock_provider = MagicMock()
        mock_provider.list_recent_pipelines.return_value = [
            {'id': '200', 'status': 'success', 'ref': 'main', 'sha': 'def456'},
        ]

        mock_binding = MagicMock()
        mock_binding.provider_type = 'github_actions'
        mock_binding.pipeline_id = 'owner/repo'
        mock_binding.get_provider.return_value = mock_provider
        mock_binding.project_service.project.organisation = None

        result, mocks = self._run_sync([mock_binding])

        mock_binding.save.assert_called_with(update_fields=['last_sync_at'])

    def test_sync_handles_provider_returning_empty(self):
        mock_provider = MagicMock()
        mock_provider.list_recent_pipelines.return_value = []

        mock_binding = MagicMock()
        mock_binding.provider_type = 'jenkins'
        mock_binding.pipeline_id = 'my-job'
        mock_binding.get_provider.return_value = mock_provider

        result, mocks = self._run_sync([mock_binding])

        self.assertEqual(result['pipelines_synced'], 0)
        mock_binding.save.assert_not_called()
