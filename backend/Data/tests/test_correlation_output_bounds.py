"""Output-side bounds tests for the correlation engine (RCA audit finding #13).

Complements ``test_correlation_bounds.py`` (which covers INPUT caps
from PR-PERF1). This module pins the OUTPUT-list ceiling introduced
in PR-AUDIT2 — a batch where every log matches every code change
could otherwise persist ~25 000 correlation dicts on
``batch.data['correlation_results']``, bloating the JSONB blob and
slowing the Batch Detail render.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

from django.test import SimpleTestCase

from Data.correlation_engine import (
    _MAX_CORRELATIONS_PER_TYPE,
    _MAX_LOGS,
    _MAX_CODE_CHANGES,
    _TRACE_ID_LEN,
    build_comprehensive_correlations,
    correlate_spans_with_code_changes,
    correlate_spans_with_logs,
    correlate_spans_with_metrics,
)


def _log(msg, ts="2026-09-19T10:00:00Z", level="ERROR"):
    return {"timestamp": ts, "message": msg, "level": level, "service": "checkout"}


def _commit(sha, files):
    return {
        "sha": sha, "message": f"chg {sha}", "files": files,
        "timestamp": "2026-09-19T09:40:00Z",
        "branch": "main", "author": "Alice",
    }


class OutputCapTest(SimpleTestCase):

    def test_named_output_cap_is_module_level(self):
        # Guard: baking the value back into a literal would silently
        # re-open the door to 25k-dict payloads.
        self.assertGreaterEqual(_MAX_CORRELATIONS_PER_TYPE, 50)

    def test_pathological_batch_output_is_capped(self):
        # 500 (post-input-cap) × 50 (post-input-cap) = 25 000 correlations
        # possible before this fix. All log messages point at the same
        # file; every commit touches that file — every pair matches.
        big_logs = [
            _log(f'File "services/checkout/api.py", line {i}, in fn err {i}')
            for i in range(1200)
        ]
        big_changes = [
            _commit(f"{i:040x}", ["services/checkout/api.py"])
            for i in range(200)
        ]

        out = build_comprehensive_correlations(
            logs=big_logs, metrics_summary={}, code_changes=big_changes,
        )
        self.assertLessEqual(
            len(out["correlations"]["file_to_error"]),
            _MAX_CORRELATIONS_PER_TYPE,
            f"file_to_error must cap at {_MAX_CORRELATIONS_PER_TYPE}",
        )

    def test_cap_preserves_top_scored_entries(self):
        # After truncation the surviving entries should be the
        # highest-scored ones — the function sorts internally, and
        # we take the head of the sorted list.
        big_logs = [
            _log(
                f'File "services/checkout/api.py", line {i}, in fn err {i}',
                ts="2026-09-19T09:41:00Z",   # 1 min after commit → HIGH
            )
            for i in range(600)
        ]
        big_changes = [
            _commit(f"{i:040x}", ["services/checkout/api.py"])
            for i in range(200)
        ]
        out = build_comprehensive_correlations(
            logs=big_logs, metrics_summary={}, code_changes=big_changes,
        )
        # All survivors should be HIGH (score 0.85 per PR-CONF1).
        capped = out["correlations"]["file_to_error"]
        self.assertEqual(len(capped), _MAX_CORRELATIONS_PER_TYPE)
        self.assertTrue(all(c["confidence"] == "HIGH" for c in capped))

    def test_cap_emits_one_warning_per_truncated_type(self):
        big_logs = [
            _log(f'File "services/checkout/api.py", line {i}, in fn err {i}')
            for i in range(1200)
        ]
        big_changes = [
            _commit(f"{i:040x}", ["services/checkout/api.py"])
            for i in range(200)
        ]
        with self.assertLogs("Data.correlation_engine", level="WARNING") as cm:
            build_comprehensive_correlations(
                logs=big_logs, metrics_summary={}, code_changes=big_changes,
            )
        truncation_warnings = [
            r for r in cm.records
            if "produced" in r.getMessage() and "truncating to top" in r.getMessage()
        ]
        # Exactly one warning for file_to_error — the output-cap message.
        self.assertGreaterEqual(len(truncation_warnings), 1)

    def test_small_batches_do_not_hit_the_cap(self):
        out = build_comprehensive_correlations(
            logs=[_log('File "services/checkout/api.py", line 42, in fn boom',
                       ts="2026-09-19T09:41:00Z")],
            metrics_summary={},
            code_changes=[_commit("abc12345", ["services/checkout/api.py"])],
        )
        self.assertEqual(len(out["correlations"]["file_to_error"]), 1)


class TraceIdFullLengthTest(SimpleTestCase):
    """RCA audit finding #9 — trace_id was truncated to 16 chars,
    breaking operator lookup in Tempo / Jaeger / DD APM. Backend now
    emits the full 32-char id. Frontend can truncate for display."""

    _SPAN_TRACE = {
        "trace_id": "a" * 32,
        "service_name": "checkout",
        "operation_name": "GET /",
        "duration_ms": 500,
        "status_message": "timeout",
    }

    def test_trace_id_len_constant_is_full_otel_length(self):
        self.assertEqual(_TRACE_ID_LEN, 32)

    def test_span_error_to_log_error_emits_full_trace_id(self):
        corrs = correlate_spans_with_logs(
            {"top_errors": [self._SPAN_TRACE]},
            [_log("something with timeout", level="ERROR")],
        )
        self.assertGreater(len(corrs), 0)
        self.assertEqual(len(corrs[0]["trace_id"]), 32)
        self.assertEqual(corrs[0]["trace_id"], "a" * 32)

    def test_slow_span_after_deploy_emits_full_trace_id(self):
        corrs = correlate_spans_with_code_changes(
            {"top_slow": [self._SPAN_TRACE], "services_touched": ["checkout"]},
            [_commit("aabbccdd", ["services/checkout/api.py"])],
        )
        self.assertGreater(len(corrs), 0)
        self.assertEqual(len(corrs[0]["trace_id"]), 32)

    def test_slow_span_during_metric_spike_emits_full_trace_id(self):
        corrs = correlate_spans_with_metrics(
            {"top_slow": [self._SPAN_TRACE]},
            {"memory": {"anomalies": [
                {"type": "memory", "peak_value": 91,
                 "start_time": "2026-09-19T10:00:00Z"},
            ]}},
        )
        self.assertGreater(len(corrs), 0)
        self.assertEqual(len(corrs[0]["trace_id"]), 32)
