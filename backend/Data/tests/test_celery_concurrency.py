"""
Tests for Phase 2 Celery worker concurrency optimization (Issue 5).

Verifies that Celery workers are configured with appropriate concurrency
to handle parallel batch processing efficiently.
"""

from django.test import TestCase
from celery import current_app
import os


class TestCeleryConfiguration(TestCase):
    """Test Celery worker configuration"""

    def test_worker_concurrency_setting(self):
        """Test that worker concurrency is properly configured"""
        # Get configured concurrency
        concurrency = current_app.conf.worker_concurrency

        # Should be at least 6 (minimum for parallel processing)
        self.assertGreaterEqual(concurrency, 6,
            f"Worker concurrency is {concurrency}, expected >= 6")

        # Should be reasonable (not too high)
        self.assertLessEqual(concurrency, 32,
            f"Worker concurrency is {concurrency}, seems too high")

    def test_worker_concurrency_calculation(self):
        """Test that concurrency is calculated based on CPU cores"""
        # Formula: max(6, cpu_count * 2)
        cpu_count = os.cpu_count() or 4  # Default to 4 if unavailable
        expected_min = max(6, cpu_count * 2)

        concurrency = current_app.conf.worker_concurrency

        # Should match formula
        self.assertEqual(concurrency, expected_min,
            f"Concurrency {concurrency} should be max(6, {cpu_count}*2) = {expected_min}")

    def test_worker_prefetch_multiplier_configured(self):
        """Test that worker prefetch multiplier is configured"""
        prefetch = current_app.conf.worker_prefetch_multiplier

        # Should be set to 2 (Phase 2 config)
        self.assertEqual(prefetch, 2,
            f"Prefetch multiplier is {prefetch}, expected 2")

    def test_worker_max_tasks_per_child_configured(self):
        """Test that worker restart policy is configured"""
        max_tasks = current_app.conf.worker_max_tasks_per_child

        # Should be 1000 (Phase 2 config) for memory leak prevention
        self.assertEqual(max_tasks, 1000,
            f"Max tasks per child is {max_tasks}, expected 1000")

    def test_celery_worker_config_for_parallel_processing(self):
        """Verify Celery configuration supports parallel batch processing"""
        config = current_app.conf

        # Verify key settings for parallel processing
        self.assertTrue(config.task_track_started,
            "task_track_started should be True")
        self.assertTrue(config.task_acks_late,
            "task_acks_late should be True for reliability")

    def test_worker_pool_configuration(self):
        """Test that worker pool is properly configured"""
        config = current_app.conf

        # Verify pool settings
        self.assertTrue(config.broker_connection_retry_on_startup,
            "broker_connection_retry_on_startup should be True")


class TestCeleryPerformanceSettings(TestCase):
    """Test Celery performance-related settings"""

    def test_task_time_limit_configured(self):
        """Test that tasks have appropriate time limits"""
        time_limit = current_app.conf.task_time_limit

        # Should have a reasonable time limit (1800s = 30 min)
        self.assertEqual(time_limit, 1800,
            f"Task time limit is {time_limit}s, expected 1800s")

    def test_broker_settings_for_reliability(self):
        """Test broker settings for reliable message delivery"""
        config = current_app.conf

        # broker_heartbeat=0 disables heartbeat (useful for long tasks)
        self.assertEqual(config.broker_heartbeat, 0,
            "broker_heartbeat should be 0 for long-running tasks")

    def test_celery_configuration_logging(self):
        """Test that Celery logs configuration on startup"""
        # This is a sanity check - ensure celery.py can be imported
        # without errors and configuration is accessible
        from api import celery as celery_module

        self.assertTrue(hasattr(celery_module, 'app'),
            "Celery app should be defined")
        self.assertTrue(hasattr(celery_module, 'worker_concurrency'),
            "worker_concurrency variable should be defined")


class TestConcurrencyImpact(TestCase):
    """Test impact of concurrency on task processing"""

    def test_concurrency_enables_parallel_execution(self):
        """Verify that concurrency setting allows parallel task execution"""
        concurrency = current_app.conf.worker_concurrency

        # With concurrency >= 6, multiple tasks can run simultaneously
        # This is critical for Phase 1's parallel batch processing
        self.assertGreaterEqual(concurrency, 6,
            "Need at least 6 workers for parallel batch processing")

        # Example: 50 projects * 3 environments = 150 parallel tasks
        # With concurrency=6, runs in ~25 rounds instead of 150 sequential
        # With concurrency=2, would run in ~75 rounds
        max_parallel_batches = concurrency
        expected_rounds_for_150_tasks = 150 / max_parallel_batches

        self.assertLess(expected_rounds_for_150_tasks, 30,
            f"With {concurrency} workers, 150 tasks would take {expected_rounds_for_150_tasks:.0f} rounds. "
            f"Too many rounds indicates low concurrency.")

    def test_prefetch_multiplier_optimizes_task_distribution(self):
        """Test that prefetch multiplier optimizes task distribution"""
        prefetch = current_app.conf.worker_prefetch_multiplier
        concurrency = current_app.conf.worker_concurrency

        # With prefetch=2, each worker can have 2 tasks queued
        # Total queued tasks = concurrency * prefetch
        total_prefetched = concurrency * prefetch

        # Should be able to prefetch at least 12 tasks (6 workers * 2)
        self.assertGreaterEqual(total_prefetched, 12,
            f"Total prefetch capacity is {total_prefetched}, expected >= 12")

    def test_worker_restart_prevents_memory_leaks(self):
        """Test that workers restart after processing many tasks"""
        max_tasks = current_app.conf.worker_max_tasks_per_child

        # Workers should restart every 1000 tasks
        # This prevents gradual memory accumulation from long-running workers
        self.assertEqual(max_tasks, 1000,
            "Workers should restart every 1000 tasks to prevent memory leaks")

        # Verify this is reasonable for production workload
        # If we process 1 batch/minute, worker restarts every ~16 hours
        # This is a good balance between stability and restart overhead
        hours_per_restart = (max_tasks * 1) / 60  # 1 task/min assumption
        self.assertGreater(hours_per_restart, 10,
            f"Worker restarts every {hours_per_restart:.1f} hours, might be too frequent")
        self.assertLess(hours_per_restart, 48,
            f"Worker restarts every {hours_per_restart:.1f} hours, might accumulate memory leaks")


class TestConcurrencyVsPreviousConfig(TestCase):
    """Compare new concurrency config vs old config"""

    def test_concurrency_increased_from_baseline(self):
        """Verify concurrency increased from baseline of 2"""
        old_concurrency = 2
        new_concurrency = current_app.conf.worker_concurrency

        # Should be at least 3x higher
        improvement_ratio = new_concurrency / old_concurrency

        self.assertGreaterEqual(improvement_ratio, 3.0,
            f"Concurrency improved by {improvement_ratio:.1f}x, expected >= 3x")

    def test_max_tasks_per_child_increased(self):
        """Verify max_tasks_per_child increased from 50 to 1000"""
        old_max_tasks = 50
        new_max_tasks = current_app.conf.worker_max_tasks_per_child

        # Should be 20x higher (allows longer worker lifetime)
        self.assertEqual(new_max_tasks, 1000)
        self.assertGreater(new_max_tasks, old_max_tasks * 10,
            f"max_tasks_per_child should be significantly higher than {old_max_tasks}")
