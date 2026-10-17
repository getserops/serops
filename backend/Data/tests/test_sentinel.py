from django.test import TestCase
from django.utils import timezone

from Organisations.models import Organisations
from Projects.models import Project, ProjectEnvironment
from Data.models import AIAnalyzedBatch, Issue, ProjectEnvironmentState


class ProjectEnvironmentStateModelTest(TestCase):
    """Tests for the ProjectEnvironmentState model."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Test Org')
        self.project = Project.objects.create(name='test-project', organisation=self.org)
        self.env = ProjectEnvironment.objects.create(
            project=self.project, name='production', display_name='Production'
        )

    def test_create_state(self):
        state = ProjectEnvironmentState.objects.create(
            project=self.project,
            environment=self.env,
            organisation=self.org,
        )
        self.assertEqual(state.baseline_error_rate, 0)
        self.assertEqual(state.error_counts, [])
        self.assertEqual(state.known_log_patterns, {})
        self.assertEqual(str(state), 'State: test-project / production')

    def test_unique_together_constraint(self):
        ProjectEnvironmentState.objects.create(
            project=self.project, environment=self.env, organisation=self.org,
        )
        with self.assertRaises(Exception):
            ProjectEnvironmentState.objects.create(
                project=self.project, environment=self.env, organisation=self.org,
            )


class SentinelEvaluateBatchTest(TestCase):
    """Tests for Data.sentinel.evaluate_batch."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Sentinel Org')
        self.project = Project.objects.create(name='sentinel-project', organisation=self.org)
        self.env = ProjectEnvironment.objects.create(
            project=self.project, name='production', display_name='Production'
        )

    def _make_batch_data(self, logs=None, metrics_summary=None, code_changes=None):
        return {
            'logs': logs or [],
            'metrics_summary': metrics_summary or {},
            'code_changes': code_changes or [],
        }

    def _make_error_log(self, message='NullPointerException in FooService', level='ERROR'):
        return {
            '_source': {
                'log_level': level,
                'message': message,
            }
        }

    def test_first_batch_returns_first(self):
        from Data.sentinel import evaluate_batch
        batch_data = self._make_batch_data(logs=[self._make_error_log()])
        decision, triggers = evaluate_batch(
            self.project, self.env, batch_data, self.org
        )
        self.assertEqual(decision, 'first')
        self.assertIn('first_batch', triggers)

        # State should have been created
        state = ProjectEnvironmentState.objects.get(
            project=self.project, environment=self.env
        )
        self.assertEqual(len(state.error_counts), 1)

    def test_quiet_batch_no_triggers(self):
        from Data.sentinel import evaluate_batch

        # First batch to seed state
        batch_data = self._make_batch_data()
        evaluate_batch(self.project, self.env, batch_data, self.org)

        # Second batch with same (empty) data — should be quiet
        decision, triggers = evaluate_batch(
            self.project, self.env, batch_data, self.org
        )
        self.assertEqual(decision, 'quiet')
        self.assertEqual(triggers, [])

    def test_deployment_detected(self):
        from Data.sentinel import evaluate_batch

        # Seed
        batch_data = self._make_batch_data(code_changes=[{'sha': 'abc123'}])
        evaluate_batch(self.project, self.env, batch_data, self.org)

        # New deployment
        batch_data2 = self._make_batch_data(code_changes=[{'sha': 'def456'}])
        decision, triggers = evaluate_batch(
            self.project, self.env, batch_data2, self.org
        )
        self.assertEqual(decision, 'alert')
        self.assertIn('deployment_detected', triggers)

    def test_error_rate_spike(self):
        from Data.sentinel import evaluate_batch

        # Seed with low errors to establish baseline
        for _ in range(5):
            batch_data = self._make_batch_data(logs=[self._make_error_log()])
            evaluate_batch(self.project, self.env, batch_data, self.org)

        # Spike: many errors
        spike_logs = [self._make_error_log(f'Error {i}') for i in range(20)]
        batch_data = self._make_batch_data(logs=spike_logs)
        decision, triggers = evaluate_batch(
            self.project, self.env, batch_data, self.org
        )
        self.assertEqual(decision, 'alert')
        self.assertIn('error_rate_spike', triggers)

    def test_new_error_pattern(self):
        from Data.sentinel import evaluate_batch

        # Seed with known error
        batch_data = self._make_batch_data(
            logs=[self._make_error_log('Known error pattern ABC')]
        )
        evaluate_batch(self.project, self.env, batch_data, self.org)

        # New error pattern
        batch_data2 = self._make_batch_data(
            logs=[self._make_error_log('Completely new error XYZ')]
        )
        decision, triggers = evaluate_batch(
            self.project, self.env, batch_data2, self.org
        )
        self.assertEqual(decision, 'alert')
        self.assertIn('new_error_pattern', triggers)

    def test_repeated_error_pattern_is_not_new(self):
        """An error seen in the previous window is known, not new again.

        Log patterns used to be compared with Issue fingerprints (another
        hashing scheme), so they never matched and every window with a
        warning or error was flagged new_error_pattern forever.
        """
        from Data.sentinel import evaluate_batch
        logs = [self._make_error_log('redis ConnectionError connecting to redis-cache:6379')]
        evaluate_batch(self.project, self.env, self._make_batch_data(logs=logs), self.org)  # first
        evaluate_batch(self.project, self.env, self._make_batch_data(logs=logs), self.org)  # learns it
        _, triggers = evaluate_batch(self.project, self.env, self._make_batch_data(logs=logs), self.org)
        self.assertNotIn('new_error_pattern', triggers)

    def test_changing_numbers_do_not_make_a_pattern_new(self):
        from Data.sentinel import evaluate_batch
        first = [self._make_error_log('2026-10-17T10:00:00Z upstream timeout after 5000ms (order 48213)')]
        later = [self._make_error_log('2026-10-17T10:15:04Z upstream timeout after 5001ms (order 77310)')]
        evaluate_batch(self.project, self.env, self._make_batch_data(logs=first), self.org)
        _, triggers = evaluate_batch(self.project, self.env, self._make_batch_data(logs=later), self.org)
        self.assertNotIn('new_error_pattern', triggers)

    def test_pattern_unseen_for_hours_is_new_again(self):
        from datetime import timedelta
        from django.utils import timezone
        from Data.sentinel import evaluate_batch, KNOWN_LOG_PATTERN_TTL
        logs = [self._make_error_log('disk full on /var/lib/data')]
        evaluate_batch(self.project, self.env, self._make_batch_data(logs=logs), self.org)
        state = ProjectEnvironmentState.objects.get(project=self.project, environment=self.env)
        old = (timezone.now() - KNOWN_LOG_PATTERN_TTL - timedelta(minutes=1)).isoformat()
        state.known_log_patterns = {fp: old for fp in state.known_log_patterns}
        state.save()
        _, triggers = evaluate_batch(self.project, self.env, self._make_batch_data(logs=logs), self.org)
        self.assertIn('new_error_pattern', triggers)

    def test_memory_anomaly(self):
        from Data.sentinel import evaluate_batch

        normal_metrics = {
            'memory': {'usage_percent': {'avg': 50}},
            'cpu': {'usage_percent': {'avg': 30}},
        }

        # Build stable baseline (several batches at ~50% memory)
        for _ in range(10):
            batch_data = self._make_batch_data(metrics_summary=normal_metrics)
            evaluate_batch(self.project, self.env, batch_data, self.org)

        # Spike memory to 99%
        spike_metrics = {
            'memory': {'usage_percent': {'avg': 99}},
            'cpu': {'usage_percent': {'avg': 30}},
        }
        batch_data = self._make_batch_data(metrics_summary=spike_metrics)
        decision, triggers = evaluate_batch(
            self.project, self.env, batch_data, self.org
        )
        self.assertEqual(decision, 'alert')
        self.assertIn('memory_anomaly', triggers)


class SentinelHelperTest(TestCase):
    """Tests for sentinel helper functions."""

    def test_extract_batch_stats_empty(self):
        from Data.sentinel import _extract_batch_stats
        stats = _extract_batch_stats({})
        self.assertEqual(stats['error_count'], 0)
        self.assertEqual(stats['log_count'], 0)
        self.assertIsNone(stats['memory_avg'])
        self.assertIsNone(stats['cpu_avg'])

    def test_extract_batch_stats_with_data(self):
        from Data.sentinel import _extract_batch_stats
        batch_data = {
            'logs': [
                {'_source': {'log_level': 'ERROR', 'message': 'fail'}},
                {'_source': {'log_level': 'INFO', 'message': 'ok'}},
                {'_source': {'log_level': 'CRITICAL', 'message': 'bad'}},
            ],
            'metrics_summary': {
                'memory': {'usage_percent': {'avg': 72.5}},
                'cpu': {'usage_percent': {'avg': 45.0}},
            },
        }
        stats = _extract_batch_stats(batch_data)
        self.assertEqual(stats['error_count'], 2)  # ERROR + CRITICAL
        self.assertEqual(stats['log_count'], 3)
        self.assertAlmostEqual(stats['memory_avg'], 72.5)
        self.assertAlmostEqual(stats['cpu_avg'], 45.0)

    def test_generate_log_fingerprints(self):
        from Data.sentinel import _generate_log_fingerprints
        logs = [
            {'_source': {'log_level': 'ERROR', 'message': 'NullPointerException in FooService'}},
            {'_source': {'log_level': 'INFO', 'message': 'Startup complete'}},
            {'_source': {'log_level': 'ERROR', 'message': 'NullPointerException in FooService'}},  # duplicate
        ]
        fps = _generate_log_fingerprints(logs)
        # INFO log should not generate a fingerprint; duplicate ERROR should deduplicate
        self.assertEqual(len(fps), 1)

    def test_update_rolling_state(self):
        from Data.sentinel import update_rolling_state
        org = Organisations.objects.create(name='Helper Org')
        project = Project.objects.create(name='helper-project', organisation=org)
        env = ProjectEnvironment.objects.create(
            project=project, name='staging', display_name='Staging'
        )
        state = ProjectEnvironmentState.objects.create(
            project=project, environment=env, organisation=org,
        )
        stats = {
            'error_count': 5,
            'memory_avg': 60.0,
            'cpu_avg': 40.0,
            'log_count': 20,
        }
        update_rolling_state(state, stats)
        self.assertEqual(state.error_counts, [5])
        self.assertEqual(state.log_volume, [20])
        self.assertAlmostEqual(state.baseline_error_rate, 5.0)
        self.assertAlmostEqual(state.baseline_memory, 60.0)

    def test_ema(self):
        from Data.sentinel import _ema
        # First value: EMA should equal the value itself
        self.assertEqual(_ema(0, 100), 100.0)
        # Second value: should be weighted average
        result = _ema(100, 50)
        self.assertAlmostEqual(result, 0.1 * 50 + 0.9 * 100)


class CorrelationSectionPromptTest(TestCase):
    """Tests for correlation section formatting in AI prompts."""

    def test_no_correlations_produces_empty_section(self):
        from ai_model.prompt_context import DataSourceContext
        from ai_model.prompts import get_batch_analysis_prompt
        prompt = get_batch_analysis_prompt(
            DataSourceContext(
                batch_data={'batch_id': 'test', 'timestamp': '2024-01-01', 'environment': 'prod'},
                correlations=None,
            ),
        )
        # Should not contain correlation header
        self.assertNotIn('Correlation Analysis (Auto-detected)', prompt)

    def test_correlations_appear_in_prompt(self):
        from ai_model.prompt_context import DataSourceContext
        from ai_model.prompts import get_batch_analysis_prompt
        correlations = {
            'correlations': {
                'file_to_error': [{
                    'confidence': 'HIGH',
                    'commit_sha': 'abc12345',
                    'matching_files': ['app/models.py'],
                    'time_since_commit_minutes': 15.0,
                    'log_message': 'NullPointerException in models.py line 42',
                }],
                'deployment_to_metric_spike': [],
                'metric_spike_to_errors': [],
            },
            'summary': {
                'total_correlations': 1,
                'high_confidence_count': 1,
                'primary_correlation': {
                    'type': 'file_to_error',
                    'details': {},
                },
            },
        }
        prompt = get_batch_analysis_prompt(
            DataSourceContext(
                batch_data={'batch_id': 'test', 'timestamp': '2024-01-01', 'environment': 'prod'},
                correlations=correlations,
            ),
        )
        self.assertIn('Correlation Analysis (Auto-detected)', prompt)
        self.assertIn('File-to-Error Correlations (1)', prompt)
        self.assertIn('abc12345', prompt)
        self.assertIn('app/models.py', prompt)


class AIAnalyzedBatchSentinelFieldsTest(TestCase):
    """Tests for sentinel fields on AIAnalyzedBatch."""

    def test_default_sentinel_fields(self):
        batch = AIAnalyzedBatch.objects.create(
            batch_id='sentinel-test-001',
            timestamp=timezone.now(),
        )
        self.assertEqual(batch.sentinel_decision, 'shadow')
        self.assertEqual(batch.sentinel_triggers, [])
        self.assertFalse(batch.ai_skipped)

    def test_set_sentinel_fields(self):
        batch = AIAnalyzedBatch.objects.create(
            batch_id='sentinel-test-002',
            timestamp=timezone.now(),
        )
        batch.sentinel_decision = 'alert'
        batch.sentinel_triggers = ['deployment_detected', 'error_rate_spike']
        batch.save(update_fields=['sentinel_decision', 'sentinel_triggers'])
        batch.refresh_from_db()
        self.assertEqual(batch.sentinel_decision, 'alert')
        self.assertEqual(batch.sentinel_triggers, ['deployment_detected', 'error_rate_spike'])

    def test_ai_skipped_field(self):
        batch = AIAnalyzedBatch.objects.create(
            batch_id='sentinel-test-003',
            timestamp=timezone.now(),
        )
        batch.ai_skipped = True
        batch.save(update_fields=['ai_skipped'])
        batch.refresh_from_db()
        self.assertTrue(batch.ai_skipped)


class SentinelConfigTest(TestCase):
    """Tests for _get_sentinel_config()."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Config Org')

    def test_returns_defaults_when_no_config(self):
        from Data.sentinel import _get_sentinel_config
        active_mode, thresholds = _get_sentinel_config(self.org)
        self.assertFalse(active_mode)
        self.assertEqual(thresholds['error_spike_multiplier'], 2.0)
        self.assertEqual(thresholds['z_score_threshold'], 3.0)
        self.assertEqual(thresholds['max_quiet_batches'], 12)

    def test_returns_overrides_when_config_exists(self):
        from Data.sentinel import _get_sentinel_config
        from org_settings.models import SentinelConfig
        SentinelConfig.objects.create(
            organisation=self.org,
            active_mode=True,
            error_spike_multiplier=5.0,
            z_score_threshold=4.0,
            max_quiet_batches=20,
        )
        active_mode, thresholds = _get_sentinel_config(self.org)
        self.assertTrue(active_mode)
        self.assertEqual(thresholds['error_spike_multiplier'], 5.0)
        self.assertEqual(thresholds['z_score_threshold'], 4.0)
        self.assertEqual(thresholds['max_quiet_batches'], 20)

    def test_zero_overrides_fall_back_to_defaults(self):
        from Data.sentinel import _get_sentinel_config
        from org_settings.models import SentinelConfig
        SentinelConfig.objects.create(
            organisation=self.org,
            active_mode=True,
            error_spike_multiplier=0,
            z_score_threshold=0,
            max_quiet_batches=12,
        )
        active_mode, thresholds = _get_sentinel_config(self.org)
        self.assertTrue(active_mode)
        self.assertEqual(thresholds['error_spike_multiplier'], 2.0)
        self.assertEqual(thresholds['z_score_threshold'], 3.0)


class SentinelActiveModeTest(TestCase):
    """Tests for evaluate_batch() with custom thresholds and forced_periodic."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Active Org')
        self.project = Project.objects.create(name='active-project', organisation=self.org)
        self.env = ProjectEnvironment.objects.create(
            project=self.project, name='production', display_name='Production'
        )

    def test_custom_thresholds_used(self):
        from Data.sentinel import evaluate_batch
        # Seed
        batch_data = {'logs': [], 'metrics_summary': {}, 'code_changes': []}
        evaluate_batch(self.project, self.env, batch_data, self.org)

        # With very high error_spike_multiplier, a moderate spike should NOT trigger
        logs = [{'_source': {'log_level': 'ERROR', 'message': f'Err {i}'}} for i in range(10)]
        batch_data2 = {'logs': logs, 'metrics_summary': {}, 'code_changes': []}

        # Seed a few more batches to build baseline
        for _ in range(5):
            evaluate_batch(self.project, self.env,
                           {'logs': [{'_source': {'log_level': 'ERROR', 'message': 'x'}}],
                            'metrics_summary': {}, 'code_changes': []},
                           self.org, thresholds={'error_spike_multiplier': 100.0,
                                                  'z_score_threshold': 100.0,
                                                  'max_quiet_batches': 999})

        decision, triggers = evaluate_batch(
            self.project, self.env, batch_data2, self.org,
            thresholds={'error_spike_multiplier': 100.0,
                        'z_score_threshold': 100.0,
                        'max_quiet_batches': 999}
        )
        # Should not have error_rate_spike since multiplier is 100x
        self.assertNotIn('error_rate_spike', triggers)

    def test_forced_periodic_trigger(self):
        from Data.sentinel import evaluate_batch
        # Seed
        batch_data = {'logs': [], 'metrics_summary': {}, 'code_changes': []}
        evaluate_batch(self.project, self.env, batch_data, self.org)

        # Set max_quiet_batches=3 and run 3 quiet batches
        thresholds = {'error_spike_multiplier': 2.0, 'z_score_threshold': 3.0, 'max_quiet_batches': 3}
        for _ in range(3):
            decision, triggers = evaluate_batch(
                self.project, self.env, batch_data, self.org, thresholds=thresholds
            )

        # The 3rd batch should hit forced_periodic
        self.assertIn('forced_periodic', triggers)
        self.assertEqual(decision, 'alert')


class SentinelRecordAIAnalysisTest(TestCase):
    """Tests for record_ai_analysis()."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Record Org')
        self.project = Project.objects.create(name='record-project', organisation=self.org)
        self.env = ProjectEnvironment.objects.create(
            project=self.project, name='production', display_name='Production'
        )

    def test_resets_batches_since_last_ai(self):
        from Data.sentinel import record_ai_analysis
        state = ProjectEnvironmentState.objects.create(
            project=self.project, environment=self.env, organisation=self.org,
            batches_since_last_ai=10,
        )
        record_ai_analysis(self.project, self.env)
        state.refresh_from_db()
        self.assertEqual(state.batches_since_last_ai, 0)
        self.assertIsNotNone(state.last_ai_analysis_at)

    def test_no_error_when_state_missing(self):
        from Data.sentinel import record_ai_analysis
        # Should not raise even if no state exists
        record_ai_analysis(self.project, self.env)


class SentinelStatsViewTest(TestCase):
    """Tests for SentinelStatsView API endpoint."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient
        User = get_user_model()
        self.org = Organisations.objects.create(name='Stats Org')
        self.user = User.objects.create_user(
            username='statstest', email='statstest@test.com',
            password='testpass123', organisation=self.org
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        # Create test batches
        for i in range(5):
            AIAnalyzedBatch.objects.create(
                batch_id=f'stats-batch-{i}',
                timestamp=timezone.now(),
                organisation=self.org,
                sentinel_decision='alert' if i < 2 else 'quiet',
                ai_skipped=(i >= 2),
                token_count=1000 if i < 2 else 0,
            )

    def test_sentinel_stats_endpoint(self):
        response = self.client.get('/api/data/analytics/sentinel/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['total_batches'], 5)
        self.assertEqual(data['decisions']['alert'], 2)
        self.assertEqual(data['decisions']['quiet'], 3)
        self.assertEqual(data['ai_skipped'], 3)
        self.assertEqual(data['ai_analyzed'], 2)
        self.assertGreater(data['skip_rate_percent'], 0)

    def test_sentinel_stats_with_days_filter(self):
        response = self.client.get('/api/data/analytics/sentinel/?days=1')
        self.assertEqual(response.status_code, 200)
