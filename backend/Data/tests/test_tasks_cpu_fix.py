"""
Tests for CPU metrics calculation in batch creation tasks.

Covers:
- Pre-computed CPU usage from Prometheus PromQL rate expression
- Fallback calculate_cpu_usage for non-Prometheus providers
- Integration with fetch_metrics_with_provider
"""

from datetime import datetime, timedelta
from django.test import TestCase
from unittest.mock import Mock, patch, MagicMock

from integrations.metrics_processing import calculate_cpu_usage, fetch_metrics_with_provider
from integrations.schemas import TimeSeries, TimeSeriesPoint


class TestCalculateCPUUsage(TestCase):
    """Test the fallback Python-side CPU usage calculation."""

    def test_empty_metrics(self):
        result = calculate_cpu_usage([])
        self.assertEqual(result, [])

    def test_single_point_skipped(self):
        """A single data point can't produce a rate."""
        metrics = [
            {'time': datetime(2024, 1, 1, 10, 0), 'value': 1000.0, 'series_id': 1},
        ]
        result = calculate_cpu_usage(metrics)
        self.assertEqual(result, [])

    def test_two_points_produces_rate(self):
        """Two consecutive points in one series produce one rate value."""
        metrics = [
            {'time': datetime(2024, 1, 1, 10, 0, 0), 'value': 1000.0, 'series_id': 1},
            {'time': datetime(2024, 1, 1, 10, 1, 0), 'value': 1060.0, 'series_id': 1},
        ]
        result = calculate_cpu_usage(metrics)
        self.assertEqual(len(result), 1)
        # delta=60, time_diff=60s, 1 core → (60/60*1)*100 = 100%
        self.assertAlmostEqual(result[0]['value'], 100.0, places=1)

    def test_multiple_series(self):
        """Each series_id is computed independently."""
        metrics = [
            {'time': datetime(2024, 1, 1, 10, 0, 0), 'value': 100.0, 'series_id': 1},
            {'time': datetime(2024, 1, 1, 10, 1, 0), 'value': 130.0, 'series_id': 1},
            {'time': datetime(2024, 1, 1, 10, 0, 0), 'value': 200.0, 'series_id': 2},
            {'time': datetime(2024, 1, 1, 10, 1, 0), 'value': 260.0, 'series_id': 2},
        ]
        result = calculate_cpu_usage(metrics)
        # 2 series → num_cores=2, each produces 1 rate point
        self.assertEqual(len(result), 2)


class TestFetchMetricsWithProviderCPU(TestCase):
    """Test that fetch_metrics_with_provider uses PromQL for CPU when available."""

    def _make_mock_provider(self, has_expr=True, cpu_points=None):
        """Create a mock metric provider."""
        provider = Mock()
        provider.__class__.__name__ = 'PrometheusMetricProvider'

        if cpu_points is None:
            cpu_points = [
                TimeSeriesPoint(timestamp=datetime(2024, 1, 1, 10, 0), value=42.5),
                TimeSeriesPoint(timestamp=datetime(2024, 1, 1, 10, 1), value=43.1),
            ]

        cpu_ts = [TimeSeries(metric_name='cpu_usage_percent', labels={}, points=cpu_points)]
        empty_ts = [TimeSeries(metric_name='test', labels={}, points=[])]

        if has_expr:
            provider.query_range_expr = Mock(return_value=cpu_ts)
        else:
            # Remove query_range_expr so hasattr returns False
            del provider.query_range_expr

        provider.query_range = Mock(return_value=empty_ts)
        return provider

    @patch('integrations.registry.IntegrationRegistry')
    def test_promql_rate_used_when_available(self, mock_registry):
        """When provider has query_range_expr, it should be called for CPU."""
        provider = self._make_mock_provider(has_expr=True)
        mock_registry.get_metric_provider_for_org.return_value = provider

        mock_org = Mock()
        mock_org.name = 'serops'
        mock_project = Mock()
        mock_project.organisation = mock_org

        start = datetime(2024, 1, 1, 10, 0)
        end = datetime(2024, 1, 1, 10, 5)

        result = fetch_metrics_with_provider(start, end, project_obj=mock_project, project_name_str='demo')

        # query_range_expr should have been called with a PromQL expression
        provider.query_range_expr.assert_called_once()
        expr_arg = provider.query_range_expr.call_args[0][0]
        self.assertIn('rate(node_cpu_seconds_total', expr_arg)
        self.assertIn('mode="idle"', expr_arg)

        # cpu_usage_percent should be pre-populated
        self.assertIn('cpu_usage_percent', result)
        self.assertEqual(len(result['cpu_usage_percent']), 2)
        self.assertAlmostEqual(result['cpu_usage_percent'][0]['value'], 42.5)

    @patch('integrations.registry.IntegrationRegistry')
    def test_fallback_raw_counters_when_no_expr(self, mock_registry):
        """When provider lacks query_range_expr, raw counters are fetched."""
        provider = self._make_mock_provider(has_expr=False)
        mock_registry.get_metric_provider_for_org.return_value = provider

        mock_org = Mock()
        mock_org.name = 'serops'
        mock_project = Mock()
        mock_project.organisation = mock_org

        start = datetime(2024, 1, 1, 10, 0)
        end = datetime(2024, 1, 1, 10, 5)

        result = fetch_metrics_with_provider(start, end, project_obj=mock_project, project_name_str='demo')

        # Should have called query_range (not query_range_expr)
        self.assertTrue(provider.query_range.called)
        # cpu_usage_percent should NOT be pre-populated (left for calculate_cpu_usage)
        self.assertNotIn('cpu_usage_percent', result)


class TestTasksCPUSkipPrecomputed(TestCase):
    """Test that tasks.py skips calculate_cpu_usage when metrics are pre-computed."""

    def test_skip_when_precomputed(self):
        """If cpu_usage_percent already in metrics, calculate_cpu_usage is not called."""
        metrics = {
            'cpu': [{'time': '2024-01-01T10:00:00', 'value': 42.5, 'series_id': 0}],
            'cpu_usage_percent': [{'time': '2024-01-01T10:00:00', 'value': 42.5, 'series_id': 0}],
        }

        # Simulate the tasks.py logic
        if 'cpu_usage_percent' not in metrics:
            metrics['cpu_usage_percent'] = calculate_cpu_usage(metrics.get('cpu', []))

        # Value should remain as pre-computed
        self.assertEqual(metrics['cpu_usage_percent'][0]['value'], 42.5)

    def test_calculate_when_not_precomputed(self):
        """If cpu_usage_percent is missing, calculate_cpu_usage is called."""
        metrics = {
            'cpu': [
                {'time': datetime(2024, 1, 1, 10, 0, 0), 'value': 1000.0, 'series_id': 1},
                {'time': datetime(2024, 1, 1, 10, 1, 0), 'value': 1060.0, 'series_id': 1},
            ],
        }

        if 'cpu_usage_percent' not in metrics:
            metrics['cpu_usage_percent'] = calculate_cpu_usage(metrics.get('cpu', []))

        self.assertIn('cpu_usage_percent', metrics)
        self.assertEqual(len(metrics['cpu_usage_percent']), 1)
