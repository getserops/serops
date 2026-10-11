"""
Tests for provider-agnostic deployment service.

Verifies that:
- Organisation filtering uses direct CodeChange.organisation FK
- Pipeline deployment creation uses external_project_id exclusively
"""

from datetime import datetime
from unittest.mock import MagicMock, Mock, call, patch

from django.test import SimpleTestCase


class TestGetDeploymentsForBatchOrgIsolation(SimpleTestCase):
    """Test that get_deployments_for_batch uses provider-agnostic org filter."""

    @patch('providers.deployment_service.Deployment')
    def test_org_filter_uses_direct_fk(self, MockDeployment):
        """Organisation filter should use code_change__organisation_id."""
        from providers.deployment_service import DeploymentService

        mock_qs = MagicMock()
        MockDeployment.objects.filter.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.order_by.return_value = iter([])

        DeploymentService.get_deployments_for_batch(
            environment='production',
            start_time=datetime(2026, 1, 1, 10, 0),
            end_time=datetime(2026, 1, 1, 11, 0),
            organisation_id=42,
        )

        # Collect all filter kwargs across the chain
        all_filter_kwargs = {}
        for c in mock_qs.filter.call_args_list:
            all_filter_kwargs.update(c[1])

        self.assertIn('code_change__organisation_id', all_filter_kwargs)
        self.assertEqual(all_filter_kwargs['code_change__organisation_id'], 42)
        # Must NOT traverse through gitlab_project
        self.assertNotIn(
            'code_change__gitlab_project__organisation_id',
            all_filter_kwargs,
        )

    @patch('providers.deployment_service.Deployment')
    def test_org_filter_not_applied_when_none(self, MockDeployment):
        """No org filter should be applied when organisation_id is None."""
        from providers.deployment_service import DeploymentService

        mock_qs = MagicMock()
        MockDeployment.objects.filter.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.order_by.return_value = iter([])

        DeploymentService.get_deployments_for_batch(
            environment='production',
            start_time=datetime(2026, 1, 1, 10, 0),
            end_time=datetime(2026, 1, 1, 11, 0),
            organisation_id=None,
        )

        all_filter_kwargs = {}
        for c in mock_qs.filter.call_args_list:
            all_filter_kwargs.update(c[1])

        self.assertNotIn('code_change__organisation_id', all_filter_kwargs)

    @patch('providers.deployment_service.Deployment')
    def test_status_filter_when_only_successful(self, MockDeployment):
        """Should filter by status='success' when only_successful=True."""
        from providers.deployment_service import DeploymentService

        mock_qs = MagicMock()
        MockDeployment.objects.filter.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.order_by.return_value = iter([])

        DeploymentService.get_deployments_for_batch(
            environment='production',
            start_time=datetime(2026, 1, 1, 10, 0),
            end_time=datetime(2026, 1, 1, 11, 0),
            only_successful=True,
        )

        all_filter_kwargs = {}
        for c in mock_qs.filter.call_args_list:
            all_filter_kwargs.update(c[1])

        self.assertEqual(all_filter_kwargs.get('status'), 'success')

    @patch('providers.deployment_service.Deployment')
    def test_dedup_by_commit_sha(self, MockDeployment):
        """Duplicate commit SHAs should be deduplicated."""
        from providers.deployment_service import DeploymentService

        cc1 = Mock(commit_sha='abc123def')
        cc2 = Mock(commit_sha='abc123def')  # duplicate SHA
        cc3 = Mock(commit_sha='xyz789abc')

        mock_qs = MagicMock()
        MockDeployment.objects.filter.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.order_by.return_value = iter([
            Mock(code_change=cc1),
            Mock(code_change=cc2),
            Mock(code_change=cc3),
        ])

        result = DeploymentService.get_deployments_for_batch(
            environment='production',
            start_time=datetime(2026, 1, 1, 10, 0),
            end_time=datetime(2026, 1, 1, 11, 0),
        )

        self.assertEqual(len(result), 2)
        shas = [cc.commit_sha for cc in result]
        self.assertEqual(shas, ['abc123def', 'xyz789abc'])


class TestCreateDeploymentsFromPipelineAgnostic(SimpleTestCase):
    """Test that create_deployments_from_pipeline uses external_project_id only."""

    @patch('providers.deployment_service.DeploymentService.create_deployment')
    @patch('providers.deployment_service.CodeChange')
    @patch('providers.deployment_service.timezone')
    def test_finds_code_change_by_external_project_id(
        self, mock_tz, MockCodeChange, mock_create,
    ):
        """Should find CodeChange via external_project_id."""
        from providers.deployment_service import DeploymentService

        mock_tz.now.return_value = datetime(2026, 1, 1, 12, 0)

        pipeline = Mock()
        pipeline.external_project_id = 'owner/repo'
        pipeline.pipeline_id = 'gh-123'

        mock_cc = Mock()
        mock_filter_qs = MagicMock()
        mock_filter_qs.first.return_value = mock_cc
        MockCodeChange.objects.filter.return_value = mock_filter_qs
        MockCodeChange.DoesNotExist = Exception

        mock_create.return_value = Mock()

        result = DeploymentService.create_deployments_from_pipeline(
            pipeline=pipeline,
            commit_shas=['abc123'],
            environment='production',
            status='success',
        )

        MockCodeChange.objects.filter.assert_called_with(
            commit_sha='abc123',
            project_id='owner/repo',
        )
        self.assertEqual(len(result), 1)

    @patch('providers.deployment_service.DeploymentService.create_deployment')
    @patch('providers.deployment_service.CodeChange')
    @patch('providers.deployment_service.timezone')
    def test_skips_when_no_external_project_id(
        self, mock_tz, MockCodeChange, mock_create,
    ):
        """Should skip commits when pipeline has no external_project_id."""
        from providers.deployment_service import DeploymentService

        mock_tz.now.return_value = datetime(2026, 1, 1, 12, 0)

        pipeline = Mock()
        pipeline.external_project_id = ''
        pipeline.pipeline_id = 'p-1'

        MockCodeChange.DoesNotExist = Exception

        result = DeploymentService.create_deployments_from_pipeline(
            pipeline=pipeline,
            commit_shas=['abc123'],
            environment='production',
        )

        self.assertEqual(len(result), 0)
        MockCodeChange.objects.filter.assert_not_called()
        mock_create.assert_not_called()

    @patch('providers.deployment_service.DeploymentService.create_deployment')
    @patch('providers.deployment_service.CodeChange')
    @patch('providers.deployment_service.timezone')
    def test_skips_commit_when_not_found(
        self, mock_tz, MockCodeChange, mock_create,
    ):
        """Should skip commits not found by project_id lookup."""
        from providers.deployment_service import DeploymentService

        mock_tz.now.return_value = datetime(2026, 1, 1, 12, 0)

        pipeline = Mock()
        pipeline.external_project_id = '999'
        pipeline.pipeline_id = 'p-1'

        mock_filter_qs = MagicMock()
        mock_filter_qs.first.return_value = None
        MockCodeChange.objects.filter.return_value = mock_filter_qs
        MockCodeChange.DoesNotExist = Exception

        result = DeploymentService.create_deployments_from_pipeline(
            pipeline=pipeline,
            commit_shas=['not-found'],
            environment='production',
        )

        self.assertEqual(len(result), 0)
        mock_create.assert_not_called()

    @patch('providers.deployment_service.DeploymentService.create_deployment')
    @patch('providers.deployment_service.CodeChange')
    @patch('providers.deployment_service.timezone')
    def test_records_failed_pipeline_status(
        self, mock_tz, MockCodeChange, mock_create,
    ):
        """Should pass through failed status for root cause analysis."""
        from providers.deployment_service import DeploymentService

        mock_tz.now.return_value = datetime(2026, 1, 1, 12, 0)

        pipeline = Mock()
        pipeline.external_project_id = 'owner/repo'
        pipeline.pipeline_id = 'gh-fail'

        mock_cc = Mock()
        mock_filter_qs = MagicMock()
        mock_filter_qs.first.return_value = mock_cc
        MockCodeChange.objects.filter.return_value = mock_filter_qs
        MockCodeChange.DoesNotExist = Exception

        mock_create.return_value = Mock()

        DeploymentService.create_deployments_from_pipeline(
            pipeline=pipeline,
            commit_shas=['abc123'],
            environment='production',
            status='failed',
        )

        mock_create.assert_called_once()
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs['status'], 'failed')
        self.assertEqual(kwargs['environment'], 'production')
        self.assertIs(kwargs['pipeline'], pipeline)

    @patch('providers.deployment_service.DeploymentService.create_deployment')
    @patch('providers.deployment_service.CodeChange')
    @patch('providers.deployment_service.timezone')
    def test_handles_multiple_commits(
        self, mock_tz, MockCodeChange, mock_create,
    ):
        """Should create deployments for each found commit."""
        from providers.deployment_service import DeploymentService

        mock_tz.now.return_value = datetime(2026, 1, 1, 12, 0)

        pipeline = Mock()
        pipeline.external_project_id = 'owner/repo'
        pipeline.pipeline_id = 'gh-multi'

        mock_filter_qs = MagicMock()
        mock_filter_qs.first.return_value = Mock()
        MockCodeChange.objects.filter.return_value = mock_filter_qs
        MockCodeChange.DoesNotExist = Exception

        mock_create.return_value = Mock()

        result = DeploymentService.create_deployments_from_pipeline(
            pipeline=pipeline,
            commit_shas=['sha1', 'sha2', 'sha3'],
            environment='production',
        )

        self.assertEqual(len(result), 3)
        self.assertEqual(mock_create.call_count, 3)
