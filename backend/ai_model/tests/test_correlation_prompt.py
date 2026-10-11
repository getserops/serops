from django.test import TestCase

from ai_model.prompt_context import DataSourceContext
from ai_model.prompts import get_batch_analysis_prompt


BATCH_DATA = {'batch_id': 'b1', 'timestamp': '2024-01-01', 'environment': 'prod'}


class CorrelationPromptWiringTest(TestCase):
    """Tests that correlation data is properly wired into AI prompts."""

    def test_empty_correlations_no_section(self):
        prompt = get_batch_analysis_prompt(
            DataSourceContext(batch_data=BATCH_DATA, correlations={}),
        )
        self.assertNotIn('Correlation Analysis', prompt)

    def test_none_correlations_no_section(self):
        prompt = get_batch_analysis_prompt(
            DataSourceContext(batch_data=BATCH_DATA, correlations=None),
        )
        self.assertNotIn('Correlation Analysis', prompt)

    def test_deployment_to_metric_in_prompt(self):
        correlations = {
            'correlations': {
                'file_to_error': [],
                'deployment_to_metric_spike': [{
                    'confidence': 'HIGH',
                    'metric_type': 'memory',
                    'anomaly_peak': '95%',
                    'time_after_deploy_minutes': 30.0,
                    'commit_sha': 'deadbeef',
                }],
                'metric_spike_to_errors': [],
            },
            'summary': {
                'total_correlations': 1,
                'high_confidence_count': 1,
                'primary_correlation': None,
            },
        }
        prompt = get_batch_analysis_prompt(
            DataSourceContext(
                batch_data={'batch_id': 'b2', 'timestamp': '2024-01-01', 'environment': 'prod'},
                correlations=correlations,
            ),
        )
        self.assertIn('Deployment-to-Metric Correlations (1)', prompt)
        self.assertIn('Memory spike', prompt)
        self.assertIn('95%', prompt)
        self.assertIn('deadbeef', prompt)

    def test_metric_spike_to_errors_in_prompt(self):
        correlations = {
            'correlations': {
                'file_to_error': [],
                'deployment_to_metric_spike': [],
                'metric_spike_to_errors': [{
                    'metric': 'CPU',
                    'peak_value': '92%',
                    'correlated_log_count': 7,
                }],
            },
            'summary': {
                'total_correlations': 1,
                'high_confidence_count': 0,
                'primary_correlation': None,
            },
        }
        prompt = get_batch_analysis_prompt(
            DataSourceContext(
                batch_data={'batch_id': 'b3', 'timestamp': '2024-01-01', 'environment': 'prod'},
                correlations=correlations,
            ),
        )
        self.assertIn('Metric-Spike-to-Error Correlations (1)', prompt)
        self.assertIn('CPU spike', prompt)
        self.assertIn('7 error logs', prompt)
