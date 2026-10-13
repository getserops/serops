"""
Tests for Jenkins build polling Celery task.

Verifies that:
- Builds are fetched and Pipeline records created
- In-progress builds are skipped
- Missing binding returns skipped status
- Missing job name returns skipped status
"""

from unittest.mock import patch, MagicMock
from django.test import TestCase

from Organisations.models import Organisations


class TestFetchJenkinsBuildsForBinding(TestCase):
    """Test fetch_jenkins_builds_for_binding Celery task."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='Jenkins Poll Org')

    @patch('providers.models.Pipeline.objects')
    @patch('Projects.models.CICDBinding.objects')
    def test_creates_pipeline_records(self, mock_binding_qs, mock_pipeline_qs):
        """Completed builds should create Pipeline records."""
        from providers.tasks import fetch_jenkins_builds_for_binding

        mock_provider = MagicMock()
        mock_provider.list_recent_builds.return_value = [
            {'number': 10, 'result': 'SUCCESS', 'building': False,
             'timestamp': 1704067200000, 'duration': 30000, 'url': 'http://j/10', 'id': '10'},
            {'number': 9, 'result': 'FAILURE', 'building': False,
             'timestamp': 1704060000000, 'duration': 15000, 'url': 'http://j/9', 'id': '9'},
        ]

        mock_binding = MagicMock()
        mock_binding.pipeline_id = 'my-job'
        mock_binding.get_provider.return_value = mock_provider
        mock_binding_qs.select_related.return_value.get.return_value = mock_binding

        mock_pipeline_qs.get_or_create.return_value = (MagicMock(), True)

        result = fetch_jenkins_builds_for_binding(1)

        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['pipelines_created'], 2)
        self.assertEqual(mock_pipeline_qs.get_or_create.call_count, 2)

    @patch('providers.models.Pipeline.objects')
    @patch('Projects.models.CICDBinding.objects')
    def test_skips_building_builds(self, mock_binding_qs, mock_pipeline_qs):
        """In-progress builds should be skipped."""
        from providers.tasks import fetch_jenkins_builds_for_binding

        mock_provider = MagicMock()
        mock_provider.list_recent_builds.return_value = [
            {'number': 11, 'result': None, 'building': True,
             'timestamp': None, 'duration': 0, 'url': 'http://j/11', 'id': '11'},
        ]

        mock_binding = MagicMock()
        mock_binding.pipeline_id = 'my-job'
        mock_binding.get_provider.return_value = mock_provider
        mock_binding_qs.select_related.return_value.get.return_value = mock_binding

        result = fetch_jenkins_builds_for_binding(1)

        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['pipelines_created'], 0)
        mock_pipeline_qs.get_or_create.assert_not_called()

    @patch('Projects.models.CICDBinding.objects')
    def test_binding_not_found_returns_skipped(self, mock_binding_qs):
        """Missing CICDBinding should return skipped status."""
        from providers.tasks import fetch_jenkins_builds_for_binding
        from Projects.models import CICDBinding

        mock_binding_qs.select_related.return_value.get.side_effect = CICDBinding.DoesNotExist

        result = fetch_jenkins_builds_for_binding(9999)

        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(result['reason'], 'binding_not_found')

    @patch('providers.models.Pipeline.objects')
    @patch('Projects.models.CICDBinding.objects')
    def test_no_job_name_returns_skipped(self, mock_binding_qs, mock_pipeline_qs):
        """Missing pipeline_id (job name) should return skipped."""
        from providers.tasks import fetch_jenkins_builds_for_binding

        mock_binding = MagicMock()
        mock_binding.pipeline_id = ''
        mock_binding_qs.select_related.return_value.get.return_value = mock_binding

        result = fetch_jenkins_builds_for_binding(1)

        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(result['reason'], 'no_job_name')
