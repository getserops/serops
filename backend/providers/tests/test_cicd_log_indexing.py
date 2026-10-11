"""
Tests for CI/CD log indexing changes.

Verifies that:
- Pipeline-level summary docs are indexed for all terminal statuses
- Failed pipelines produce both job-level and pipeline-level docs
- Non-terminal statuses produce no docs
"""

from unittest.mock import patch, MagicMock
from django.test import SimpleTestCase


class TestStoreCicdLogsGeneric(SimpleTestCase):
    """Test store_cicd_logs_generic() pipeline-level doc behavior."""

    @patch('providers.utils._resolve_log_provider')
    @patch('providers.utils.GitlabProject')
    def test_indexes_pipeline_summary_for_success(self, mock_gp_cls, mock_resolve_log):
        from providers.utils import store_cicd_logs_generic

        mock_provider = MagicMock()
        mock_provider.index.return_value = 1
        mock_resolve_log.return_value = mock_provider
        mock_gp_cls.objects.filter.return_value.first.return_value = None

        normalized = {
            'project_id': '42',
            'pipeline_id': '100',
            'status': 'success',
            'branch': 'main',
            'environment': 'production',
            'commit_shas': ['abc123'],
            'jobs': [],
        }

        store_cicd_logs_generic('github_actions', normalized)

        mock_provider.index.assert_called_once()
        docs = mock_provider.index.call_args[0][0]
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]['job']['name'], 'pipeline')
        self.assertEqual(docs[0]['job']['status'], 'success')
        self.assertEqual(docs[0]['pipeline']['status'], 'success')

    @patch('providers.utils._resolve_log_provider')
    @patch('providers.utils.GitlabProject')
    def test_indexes_pipeline_summary_and_job_docs_for_failed(self, mock_gp_cls, mock_resolve_log):
        from providers.utils import store_cicd_logs_generic

        mock_provider = MagicMock()
        mock_provider.index.return_value = 3
        mock_resolve_log.return_value = mock_provider
        mock_gp_cls.objects.filter.return_value.first.return_value = None

        normalized = {
            'project_id': '42',
            'pipeline_id': '100',
            'status': 'failed',
            'branch': 'main',
            'environment': 'production',
            'commit_shas': ['abc123'],
            'jobs': [
                {'id': '1', 'name': 'build', 'stage': 'build', 'status': 'failed', 'duration': 30},
                {'id': '2', 'name': 'test', 'stage': 'test', 'status': 'failed', 'duration': 15},
                {'id': '3', 'name': 'lint', 'stage': 'test', 'status': 'success', 'duration': 5},
            ],
        }

        store_cicd_logs_generic('gitlab', normalized)

        mock_provider.index.assert_called_once()
        docs = mock_provider.index.call_args[0][0]
        # 2 failed job docs + 1 pipeline summary = 3
        self.assertEqual(len(docs), 3)
        job_names = [d['job']['name'] for d in docs]
        self.assertIn('build', job_names)
        self.assertIn('test', job_names)
        self.assertIn('pipeline', job_names)
        # Pipeline summary should have pipeline-level status
        pipeline_doc = [d for d in docs if d['job']['name'] == 'pipeline'][0]
        self.assertEqual(pipeline_doc['job']['status'], 'failed')

    @patch('providers.utils._resolve_log_provider')
    @patch('providers.utils.GitlabProject')
    def test_skips_non_terminal_statuses(self, mock_gp_cls, mock_resolve_log):
        from providers.utils import store_cicd_logs_generic

        mock_provider = MagicMock()
        mock_resolve_log.return_value = mock_provider
        mock_gp_cls.objects.filter.return_value.first.return_value = None

        for status in ('running', 'pending', 'created'):
            mock_provider.reset_mock()
            normalized = {
                'project_id': '42',
                'pipeline_id': '100',
                'status': status,
                'branch': 'main',
                'environment': 'development',
                'commit_shas': [],
                'jobs': [],
            }

            store_cicd_logs_generic('gitlab', normalized)

            # No docs should be indexed for non-terminal statuses
            mock_provider.index.assert_not_called()

    @patch('providers.utils._resolve_log_provider')
    @patch('providers.utils.GitlabProject')
    def test_indexes_pipeline_summary_for_canceled(self, mock_gp_cls, mock_resolve_log):
        from providers.utils import store_cicd_logs_generic

        mock_provider = MagicMock()
        mock_provider.index.return_value = 1
        mock_resolve_log.return_value = mock_provider
        mock_gp_cls.objects.filter.return_value.first.return_value = None

        normalized = {
            'project_id': '42',
            'pipeline_id': '100',
            'status': 'canceled',
            'branch': 'main',
            'environment': 'staging',
            'commit_shas': [],
            'jobs': [],
        }

        store_cicd_logs_generic('jenkins', normalized)

        mock_provider.index.assert_called_once()
        docs = mock_provider.index.call_args[0][0]
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]['job']['name'], 'pipeline')
        self.assertEqual(docs[0]['job']['status'], 'canceled')
