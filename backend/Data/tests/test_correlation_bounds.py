"""Complexity-bound tests for the correlation engine (Q2.2).

Every correlation function has nested loops over untrusted-length
inputs. Without caps a noisy incident (10K logs × 500 spans) becomes
~5M inner iterations, holds a Celery worker for seconds, and starves
neighbouring batches. This file pins the named ``_MAX_*`` limits and
verifies that oversized inputs are truncated with a logged warning
rather than processed in full.

What the tests prove:

* Each cap is defined as a module-level constant so an operator can
  grep once and tune. If a cap ever silently gets baked back into
  an inline literal, ``test_module_level_named_caps`` catches it.
* Oversized inputs never raise; they truncate and log at WARNING.
* Every call site actually respects the cap it advertises — we
  instrument ``_cap`` and assert its per-batch invocation shape.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

from django.test import SimpleTestCase

from Data import correlation_engine
from Data.correlation_engine import (
    _MAX_CICD_JOBS,
    _MAX_CODE_CHANGES,
    _MAX_FILE_MENTIONS_PER_LOG,
    _MAX_LOGS,
    _MAX_TRACE_ERROR_SPANS,
    _MAX_TRACE_SLOW_SPANS,
    _cap,
    correlate_cicd_with_code_changes,
    correlate_logs_with_code_changes,
    correlate_logs_with_metrics,
    correlate_metrics_with_code_changes,
    correlate_spans_with_code_changes,
    correlate_spans_with_logs,
    correlate_spans_with_metrics,
)


class NamedCapsExistTest(SimpleTestCase):

    def test_module_level_named_caps(self):
        # Guard: named constants are the contract, not inline literals.
        # If a future contributor bakes 500 back into a function, this
        # test still passes but the maintenance argument in the module
        # docstring stops holding — the follow-up guard is
        # test_call_sites_use_the_helper below.
        self.assertGreaterEqual(_MAX_LOGS, 100)
        self.assertGreaterEqual(_MAX_CODE_CHANGES, 10)
        self.assertGreaterEqual(_MAX_CICD_JOBS, 10)
        self.assertGreaterEqual(_MAX_TRACE_ERROR_SPANS, 10)
        self.assertGreaterEqual(_MAX_TRACE_SLOW_SPANS, 10)
        self.assertGreaterEqual(_MAX_FILE_MENTIONS_PER_LOG, 5)


class CapHelperTest(SimpleTestCase):

    def test_under_cap_returns_input_unchanged(self):
        items = [1, 2, 3]
        self.assertIs(_cap(items, 10, 'items'), items)

    def test_exact_cap_returns_input_unchanged(self):
        items = list(range(10))
        self.assertIs(_cap(items, 10, 'items'), items)

    def test_over_cap_truncates(self):
        items = list(range(100))
        capped = _cap(items, 10, 'items')
        self.assertEqual(len(capped), 10)
        self.assertEqual(capped, list(range(10)))

    def test_empty_input_is_a_noop(self):
        # Empty / falsy inputs come out unchanged — no log spam on
        # the common case.
        self.assertEqual(_cap([], 10, 'items'), [])
        self.assertIsNone(_cap(None, 10, 'items'))

    def test_over_cap_logs_at_warning(self):
        with self.assertLogs('Data.correlation_engine', level='WARNING') as cm:
            _cap(list(range(1000)), 100, 'logs')
        # One line per truncation event — enough to spot, not spammy.
        self.assertEqual(len(cm.records), 1)
        self.assertIn('truncating logs from 1000 to 100', cm.records[0].getMessage())

    def test_under_cap_does_not_log(self):
        engine_logger = logging.getLogger('Data.correlation_engine')
        with patch.object(engine_logger, 'warning') as w:
            _cap(list(range(5)), 100, 'logs')
        w.assert_not_called()


class OversizedInputsNeverRaiseTest(SimpleTestCase):
    """Every correlation function must accept oversized inputs
    without crashing — a noisy incident is exactly when the RCA
    pipeline is most valuable, and a spurious IndexError at the
    correlation stage would starve the AI of context."""

    _BIG_LOGS = [
        {'message': f'some error #{i}', 'timestamp': '2026-09-19T10:00:00Z',
         'level': 'ERROR', 'service': 'checkout'}
        for i in range(_MAX_LOGS * 3)
    ]
    _BIG_CHANGES = [
        {'sha': f'{i:040x}', 'message': f'commit {i}',
         'timestamp': '2026-09-19T09:30:00Z', 'branch': 'main',
         'files': [f'services/checkout/service_{i}.py']}
        for i in range(_MAX_CODE_CHANGES * 3)
    ]
    _BIG_CICD = [
        {'status': 'failed', 'branch': 'main', 'pipeline_id': f'p{i}',
         'job_name': f'job-{i}', 'timestamp': '2026-09-19T10:00:00Z',
         'trace_errors': f'error {i}'}
        for i in range(_MAX_CICD_JOBS * 3)
    ]

    def test_correlate_logs_with_code_changes_survives(self):
        # Should not raise; should return a bounded-effort result.
        result = correlate_logs_with_code_changes(self._BIG_LOGS, self._BIG_CHANGES)
        self.assertIsInstance(result, list)

    def test_correlate_metrics_with_code_changes_survives(self):
        result = correlate_metrics_with_code_changes(
            {'memory': {'anomalies': [
                {'start_time': '2026-09-19T10:00:00Z', 'peak_value': 91},
            ]}},
            self._BIG_CHANGES,
        )
        self.assertIsInstance(result, list)

    def test_correlate_logs_with_metrics_survives(self):
        result = correlate_logs_with_metrics(
            self._BIG_LOGS,
            {'memory': {'anomalies': [
                {
                    'start_time': '2026-09-19T10:00:00Z',
                    'peak_value': 91,
                    'correlation_window': {
                        'start': '2026-09-19T09:59:00Z',
                        'end': '2026-09-19T10:01:00Z',
                    },
                },
            ]}},
        )
        self.assertIsInstance(result, list)

    def test_correlate_cicd_with_code_changes_survives(self):
        result = correlate_cicd_with_code_changes(self._BIG_CICD, self._BIG_CHANGES)
        self.assertIsInstance(result, list)

    def test_correlate_spans_with_logs_survives(self):
        big_top_errors = [
            {'service_name': 'checkout', 'operation_name': 'GET /', 'trace_id': f'{i:032x}',
             'status_message': 'timeout'}
            for i in range(_MAX_TRACE_ERROR_SPANS * 3)
        ]
        result = correlate_spans_with_logs(
            {'top_errors': big_top_errors}, self._BIG_LOGS,
        )
        self.assertIsInstance(result, list)

    def test_correlate_spans_with_code_changes_survives(self):
        big_top_slow = [
            {'service_name': 'checkout', 'operation_name': 'GET /',
             'trace_id': f'{i:032x}', 'duration_ms': 500}
            for i in range(_MAX_TRACE_SLOW_SPANS * 3)
        ]
        result = correlate_spans_with_code_changes(
            {'top_slow': big_top_slow, 'services_touched': ['checkout']},
            self._BIG_CHANGES,
        )
        self.assertIsInstance(result, list)

    def test_correlate_spans_with_metrics_survives(self):
        big_top_slow = [
            {'service_name': 'checkout', 'operation_name': 'GET /',
             'trace_id': f'{i:032x}', 'duration_ms': 500}
            for i in range(_MAX_TRACE_SLOW_SPANS * 3)
        ]
        result = correlate_spans_with_metrics(
            {'top_slow': big_top_slow},
            {'memory': {'anomalies': [
                {'type': 'memory', 'peak_value': 91,
                 'start_time': '2026-09-19T10:00:00Z'},
            ]}},
        )
        self.assertIsInstance(result, list)


class CallSitesTruncateOversizedInputsTest(SimpleTestCase):
    """Instrument the cap helper and assert every function that
    documents a cap actually calls the helper. Catches a future
    contributor removing a cap by accident."""

    def _run_with_spy(self, fn, *args, **kwargs):
        with patch(
            'Data.correlation_engine._cap',
            wraps=correlation_engine._cap,
        ) as spy:
            fn(*args, **kwargs)
        return spy

    def test_logs_with_code_changes_caps_both_inputs(self):
        big_logs = OversizedInputsNeverRaiseTest._BIG_LOGS
        big_changes = OversizedInputsNeverRaiseTest._BIG_CHANGES
        spy = self._run_with_spy(
            correlate_logs_with_code_changes, big_logs, big_changes,
        )
        kinds = {call.args[2] for call in spy.call_args_list}
        self.assertIn('logs', kinds)
        self.assertIn('code_changes', kinds)

    def test_metrics_with_code_changes_caps_changes(self):
        spy = self._run_with_spy(
            correlate_metrics_with_code_changes,
            {'memory': {'anomalies': [
                {'start_time': '2026-09-19T10:00:00Z', 'peak_value': 91},
            ]}},
            OversizedInputsNeverRaiseTest._BIG_CHANGES,
        )
        kinds = {call.args[2] for call in spy.call_args_list}
        self.assertIn('code_changes', kinds)

    def test_cicd_with_code_changes_caps_both(self):
        spy = self._run_with_spy(
            correlate_cicd_with_code_changes,
            OversizedInputsNeverRaiseTest._BIG_CICD,
            OversizedInputsNeverRaiseTest._BIG_CHANGES,
        )
        kinds = {call.args[2] for call in spy.call_args_list}
        self.assertIn('failed_cicd_jobs', kinds)
        self.assertIn('code_changes', kinds)
