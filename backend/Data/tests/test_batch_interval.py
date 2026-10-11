"""
Tests for per-organisation batch generation interval.

Covers:
- get_batch_interval_for_org() with DB, cache, and fallback paths
- invalidate_batch_interval_cache()
- Org-grouping & interval gating in create_batches_for_all_projects
"""

from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.core.cache import cache
from django.utils import timezone

from Data.models import RetentionPolicy
from Data.batch_config import (
    get_batch_interval_for_org,
    invalidate_batch_interval_cache,
    SYSTEM_DEFAULT_INTERVAL,
    _CACHE_KEY_PREFIX,
)
from Organisations.models import Organisations
from Projects.models import Project, ProjectService


class TestGetBatchIntervalForOrg(TestCase):
    """Test get_batch_interval_for_org helper."""

    def setUp(self):
        cache.clear()
        self.org = Organisations.objects.create(name='test-org')

    def tearDown(self):
        cache.clear()

    def test_returns_system_default_for_none_org(self):
        self.assertEqual(get_batch_interval_for_org(None), SYSTEM_DEFAULT_INTERVAL)

    def test_returns_db_value_when_policy_exists(self):
        RetentionPolicy.objects.create(
            organisation=self.org,
            batch_generation_interval=30,
        )
        result = get_batch_interval_for_org(self.org)
        self.assertEqual(result, 30)

    def test_returns_system_default_when_no_policy(self):
        result = get_batch_interval_for_org(self.org)
        self.assertEqual(result, SYSTEM_DEFAULT_INTERVAL)

    def test_caches_value_in_redis(self):
        RetentionPolicy.objects.create(
            organisation=self.org,
            batch_generation_interval=15,
        )
        get_batch_interval_for_org(self.org)
        cached = cache.get(f'{_CACHE_KEY_PREFIX}{self.org.id}')
        self.assertEqual(cached, 15)

    def test_returns_cached_value_without_db_hit(self):
        cache.set(f'{_CACHE_KEY_PREFIX}{self.org.id}', 45, 300)
        result = get_batch_interval_for_org(self.org)
        self.assertEqual(result, 45)

    def test_accepts_org_id_int(self):
        RetentionPolicy.objects.create(
            organisation=self.org,
            batch_generation_interval=20,
        )
        result = get_batch_interval_for_org(self.org.id)
        self.assertEqual(result, 20)


class TestInvalidateCache(TestCase):
    """Test invalidate_batch_interval_cache."""

    def setUp(self):
        cache.clear()
        self.org = Organisations.objects.create(name='cache-org')

    def tearDown(self):
        cache.clear()

    def test_removes_cached_key(self):
        key = f'{_CACHE_KEY_PREFIX}{self.org.id}'
        cache.set(key, 30, 300)
        self.assertIsNotNone(cache.get(key))
        invalidate_batch_interval_cache(self.org.id)
        self.assertIsNone(cache.get(key))

    def test_noop_when_key_missing(self):
        invalidate_batch_interval_cache(self.org.id)


class TestCreateBatchesOrgGrouping(TestCase):
    """Test org-grouping and interval gating in create_batches_for_all_projects."""

    def setUp(self):
        cache.clear()
        self.org_fast = Organisations.objects.create(name='org-fast')
        self.org_slow = Organisations.objects.create(name='org-slow')
        RetentionPolicy.objects.create(
            organisation=self.org_fast,
            batch_generation_interval=5,
        )
        RetentionPolicy.objects.create(
            organisation=self.org_slow,
            batch_generation_interval=30,
        )

    def tearDown(self):
        cache.clear()

    def _create_project(self, org, name):
        project = Project.objects.create(
            name=name,
            organisation=org,
            es_index_name=f'ci_cd-logs-project-{name}',
        )
        ProjectService.objects.create(
            project=project, name=f'{name}-svc', service_type='application'
        )
        return project

    @patch('Data.tasks.IntegrationRegistry')
    @patch('providers.tasks.sync_recent_deployments')
    def test_first_run_includes_all_orgs(self, mock_sync, mock_registry):
        """On first run (no last-run timestamps), all orgs should be eligible."""
        self._create_project(self.org_fast, 'fast-proj')
        self._create_project(self.org_slow, 'slow-proj')

        mock_provider = MagicMock()
        mock_provider.get_indices.return_value = ['index-1']
        mock_provider.client.cat.indices.return_value = []
        mock_registry.get_log_provider_for_org.return_value = mock_provider

        from Data.tasks import create_batches_for_all_projects
        with patch('celery.group') as mock_group:
            mock_group.return_value.apply_async.return_value = MagicMock(id='grp-1')
            result = create_batches_for_all_projects()

        self.assertEqual(result['skipped_orgs'], 0)
        self.assertGreater(result['total_tasks'], 0)

    @patch('Data.tasks.IntegrationRegistry')
    @patch('providers.tasks.sync_recent_deployments')
    def test_skips_org_within_interval(self, mock_sync, mock_registry):
        """Org whose interval has not elapsed should be skipped."""
        self._create_project(self.org_slow, 'slow-proj')

        last_run_key = f'batch_last_run:org:{self.org_slow.id}'
        cache.set(last_run_key, timezone.now().timestamp() - 300, timeout=3600)

        mock_provider = MagicMock()
        mock_provider.get_indices.return_value = ['index-1']
        mock_provider.client.cat.indices.return_value = []
        mock_registry.get_log_provider_for_org.return_value = mock_provider

        from Data.tasks import create_batches_for_all_projects
        result = create_batches_for_all_projects()

        self.assertEqual(result['skipped_orgs'], 1)
        self.assertEqual(result['total_tasks'], 0)

    @patch('Data.tasks.IntegrationRegistry')
    @patch('providers.tasks.sync_recent_deployments')
    def test_includes_org_after_interval_elapsed(self, mock_sync, mock_registry):
        """Org whose interval has fully elapsed should be included."""
        self._create_project(self.org_fast, 'fast-proj')

        last_run_key = f'batch_last_run:org:{self.org_fast.id}'
        cache.set(last_run_key, timezone.now().timestamp() - 360, timeout=3600)

        mock_provider = MagicMock()
        mock_provider.get_indices.return_value = ['index-1']
        mock_provider.client.cat.indices.return_value = []
        mock_registry.get_log_provider_for_org.return_value = mock_provider

        from Data.tasks import create_batches_for_all_projects
        with patch('celery.group') as mock_group:
            mock_group.return_value.apply_async.return_value = MagicMock(id='grp-1')
            result = create_batches_for_all_projects()

        self.assertEqual(result['skipped_orgs'], 0)
        self.assertGreater(result['total_tasks'], 0)

    @patch('Data.tasks.IntegrationRegistry')
    @patch('providers.tasks.sync_recent_deployments')
    def test_interval_minutes_passed_to_subtasks(self, mock_sync, mock_registry):
        """Verify that interval_minutes is included in sub-task signatures."""
        self._create_project(self.org_fast, 'fast-proj')

        mock_provider = MagicMock()
        mock_provider.get_indices.return_value = ['index-1']
        mock_provider.client.cat.indices.return_value = []
        mock_registry.get_log_provider_for_org.return_value = mock_provider

        from Data.tasks import create_batches_for_all_projects
        with patch('Data.tasks.create_log_batch_with_project_name') as mock_task:
            mock_si = MagicMock()
            mock_task.si.return_value = mock_si
            with patch('celery.group') as mock_group:
                mock_group.return_value.apply_async.return_value = MagicMock(id='grp-1')
                create_batches_for_all_projects()

            call_kwargs = mock_task.si.call_args[1]
            self.assertEqual(call_kwargs['interval_minutes'], 5)
