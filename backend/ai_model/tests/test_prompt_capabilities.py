"""Tests for capability-driven section omission in the RCA prompt."""

from dataclasses import replace

from django.test import TestCase

from ai_model.prompt_context import DataSourceContext
from ai_model.prompts import get_batch_analysis_prompt_parts


BASE_CTX = DataSourceContext(
    batch_data={'batch_id': 'B', 'timestamp': 'T', 'environment': 'prod'},
    logs=['[2026-09-04] error boom'],
    metrics_summary={'memory': {'usage_percent': {'avg': 42}}},
    code_changes=[{'sha': 'aabbccdd', 'author': 'me', 'message': 'wip', 'timestamp': 'T'}],
    ci_cd_outputs=['[CI/CD] Job x FAILED'],
    traces_summary={
        'source': 'otlp', 'span_count': 3, 'error_span_count': 1,
        'trace_count': 1, 'services_touched': ['api'],
        'top_slow': [{'trace_id': 'a' * 32, 'service_name': 'api',
                       'operation_name': 'GET /', 'duration_ms': 500}],
        'top_errors': [{'trace_id': 'a' * 32, 'service_name': 'api',
                         'operation_name': 'GET /', 'status_message': 'timeout'}],
    },
)


class PromptCapabilityGatingTest(TestCase):

    def test_no_capabilities_arg_keeps_all_sections(self):
        """Legacy call sites (no enabled_capabilities) → pre-#29 behaviour."""
        _system, user = get_batch_analysis_prompt_parts(BASE_CTX)
        self.assertIn('Logs to Analyze', user)
        self.assertIn('System Metrics Summary', user)
        self.assertIn('Recent Code Changes', user)
        self.assertIn('CI/CD Pipeline Outputs', user)
        self.assertIn('Distributed Traces', user)
        # No capability note when caller didn't opt in.
        self.assertNotIn('Available data sources for this org', user)

    def test_logs_only_omits_the_other_four(self):
        _system, user = get_batch_analysis_prompt_parts(
            replace(BASE_CTX, enabled_capabilities=['logs']),
        )
        self.assertIn('Logs to Analyze', user)
        self.assertNotIn('System Metrics Summary', user)
        self.assertNotIn('Recent Code Changes', user)
        self.assertNotIn('CI/CD Pipeline Outputs', user)
        self.assertNotIn('Distributed Traces', user)
        # AI is explicitly told what to expect.
        self.assertIn('Available data sources for this org: logs', user)

    def test_metrics_only_omits_logs(self):
        _system, user = get_batch_analysis_prompt_parts(
            replace(BASE_CTX, enabled_capabilities=['metrics']),
        )
        self.assertNotIn('Logs to Analyze', user)
        self.assertIn('System Metrics Summary', user)

    def test_no_capabilities_says_none_configured(self):
        _system, user = get_batch_analysis_prompt_parts(
            replace(BASE_CTX, enabled_capabilities=[]),
        )
        self.assertNotIn('Logs to Analyze', user)
        self.assertNotIn('System Metrics Summary', user)
        self.assertIn('none configured', user)

    def test_all_enabled_keeps_all(self):
        _system, user = get_batch_analysis_prompt_parts(
            replace(
                BASE_CTX,
                enabled_capabilities=['logs', 'metrics', 'code', 'cicd', 'traces'],
            ),
        )
        self.assertIn('Logs to Analyze', user)
        self.assertIn('System Metrics Summary', user)
        self.assertIn('Recent Code Changes', user)
        self.assertIn('CI/CD Pipeline Outputs', user)
        self.assertIn('Distributed Traces', user)
        self.assertIn(
            'Available data sources for this org: cicd, code, logs, metrics, traces',
            user,
        )
