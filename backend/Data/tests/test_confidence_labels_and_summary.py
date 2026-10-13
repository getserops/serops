"""Tests for PR-AUDIT3 — RCA audit findings #6 + #10.

Two related fixes:

  * #6: ``correlate_logs_with_metrics`` (``logs_during_metric_spike``)
    now emits a confidence label + score. Rule: 3+ correlated logs
    during the spike window is a strong co-occurrence signal (HIGH),
    1-2 is suggestive (MEDIUM).
  * #10: ``build_comprehensive_correlations`` summary now exposes
    ``medium_confidence_count`` + ``low_confidence_count`` alongside
    ``high_confidence_count`` so Dashboard truthfully reports every
    band. Several correlation types are MEDIUM by construction
    (span-based per PR-CONF1) — reporting only HIGH under-represents
    the analysis.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from Data.correlation_engine import (
    HIGH, LOW, MEDIUM, SCORE_HIGH, SCORE_MEDIUM,
    build_comprehensive_correlations,
    correlate_logs_with_metrics,
)


def _log(msg, ts):
    return {"timestamp": ts.isoformat(), "message": msg, "level": "ERROR"}


def _metrics_summary_with_anomaly(window_start, window_end, peak=91, kind="memory"):
    return {
        kind: {
            "usage_percent": {"avg": 70, "max": peak, "current": peak, "trend": "INCREASING"},
            "anomalies": [{
                "start_time": window_start.isoformat(),
                "peak_value": peak,
                "duration_seconds": 600,
                "correlation_window": {
                    "start": window_start.isoformat(),
                    "end": window_end.isoformat(),
                },
                "type": kind,
            }],
        },
    }


class LogsDuringMetricSpikeConfidenceTest(SimpleTestCase):

    def _window(self):
        # 10 min window ending 5 min ago
        end = datetime.now(timezone.utc) - timedelta(minutes=5)
        start = end - timedelta(minutes=10)
        return start, end

    def test_three_plus_logs_yields_high(self):
        start, end = self._window()
        mid = start + timedelta(minutes=5)
        logs = [_log(f"error #{i}", mid) for i in range(3)]
        corrs = correlate_logs_with_metrics(
            logs, _metrics_summary_with_anomaly(start, end),
        )
        self.assertEqual(len(corrs), 1)
        self.assertEqual(corrs[0]["confidence"], HIGH)
        self.assertEqual(corrs[0]["score"], SCORE_HIGH)
        self.assertEqual(corrs[0]["correlated_log_count"], 3)

    def test_two_logs_yields_medium(self):
        start, end = self._window()
        mid = start + timedelta(minutes=5)
        logs = [_log(f"error #{i}", mid) for i in range(2)]
        corrs = correlate_logs_with_metrics(
            logs, _metrics_summary_with_anomaly(start, end),
        )
        self.assertEqual(len(corrs), 1)
        self.assertEqual(corrs[0]["confidence"], MEDIUM)
        self.assertEqual(corrs[0]["score"], SCORE_MEDIUM)

    def test_one_log_yields_medium(self):
        start, end = self._window()
        logs = [_log("solo error", start + timedelta(minutes=5))]
        corrs = correlate_logs_with_metrics(
            logs, _metrics_summary_with_anomaly(start, end),
        )
        self.assertEqual(corrs[0]["confidence"], MEDIUM)

    def test_zero_logs_produces_no_correlation(self):
        # Regression guard: the caller does not receive a MEDIUM-labelled
        # entry with correlated_log_count=0 — the whole correlation is
        # dropped when no logs are in the window.
        start, end = self._window()
        corrs = correlate_logs_with_metrics(
            [_log("out of window", start - timedelta(hours=1))],
            _metrics_summary_with_anomaly(start, end),
        )
        self.assertEqual(corrs, [])


class SummaryReportsAllBandsTest(SimpleTestCase):

    def test_summary_exposes_medium_and_low_counters(self):
        start = datetime.now(timezone.utc) - timedelta(minutes=15)
        end = start + timedelta(minutes=10)
        mid = start + timedelta(minutes=5)
        # 3 logs in-window → 1 HIGH correlation
        # 1 code_change 20 min before those logs → 1 HIGH file_to_error
        logs = [
            {
                "timestamp": mid.isoformat(),
                "message": f'File "checkout/api.py", line {i}, in fn err',
                "level": "ERROR",
            }
            for i in range(3)
        ]
        code_changes = [{
            "sha": "aabbccdd",
            "message": "chg",
            "files": ["checkout/api.py"],
            "timestamp": (mid - timedelta(minutes=20)).isoformat(),
            "branch": "main",
            "author": "Alice",
        }]

        out = build_comprehensive_correlations(
            logs=logs,
            metrics_summary=_metrics_summary_with_anomaly(start, end),
            code_changes=code_changes,
        )
        summary = out["summary"]
        self.assertIn("high_confidence_count", summary)
        self.assertIn("medium_confidence_count", summary)
        self.assertIn("low_confidence_count", summary)
        # Two HIGH: file_to_error (3 log matches) + logs_during_metric_spike
        self.assertGreaterEqual(summary["high_confidence_count"], 2)
        self.assertEqual(summary["low_confidence_count"], 0)

    def test_all_three_band_counters_never_missing(self):
        # Even on a completely empty analysis, the shape stays stable
        # so downstream consumers don't need to guard on presence.
        out = build_comprehensive_correlations(
            logs=[], metrics_summary={}, code_changes=[],
        )
        summary = out["summary"]
        self.assertEqual(summary["high_confidence_count"], 0)
        self.assertEqual(summary["medium_confidence_count"], 0)
        self.assertEqual(summary["low_confidence_count"], 0)
        self.assertEqual(summary["total_correlations"], 0)
