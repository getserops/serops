"""Tests for the span↔log fuzzy match — PR-AUDIT4, RCA audit finding #12.

Real client libraries decorate raw exception messages before logging
them. The pre-fix ``span_msg[:40] in log_msg`` check refused to match
even when both messages clearly described the same event, forcing
HIGH-quality correlations to degrade to MEDIUM.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from Data.correlation_engine import (
    HIGH,
    MEDIUM,
    _SPAN_LOG_TOKEN_OVERLAP_MIN,
    _span_log_equivalent,
    correlate_spans_with_logs,
)


class SpanLogEquivalentUnitTest(SimpleTestCase):

    def test_exact_substring_still_matches(self):
        # Cheap path retained.
        span = "ConnectionError: db down"
        log = "worker: ConnectionError: db down at 10:00"
        self.assertTrue(_span_log_equivalent(span, log))

    def test_pymongo_style_decoration(self):
        span = "ServerSelectionTimeoutError: mongo1:27017 Connection refused"
        log = (
            "pymongo.errors.ServerSelectionTimeoutError: "
            "mongodb://mongo1:27017 [Errno 111] Connection refused"
        )
        # Pre-fix: substring test failed because 'mongodb://' broke
        # the sequence. Post-fix: token overlap catches it.
        self.assertTrue(_span_log_equivalent(span, log))

    def test_urllib3_wrapper(self):
        span = "APIConnectionError: HTTPSConnectionPool host stripe.com read timeout"
        log = (
            "urllib3.exceptions.MaxRetryError: HTTPSConnectionPool "
            "wrapping stripe APIConnectionError: read timeout host stripe.com"
        )
        self.assertTrue(_span_log_equivalent(span, log))

    def test_stripe_style_module_prefix(self):
        span = "APIConnectionError: HTTPSConnectionPool api.stripe.com read timeout"
        log = "stripe.error.APIConnectionError: HTTPSConnectionPool(api.stripe.com) read timeout"
        self.assertTrue(_span_log_equivalent(span, log))

    def test_completely_unrelated_messages_do_not_match(self):
        span = "ConnectionError: mongodb primary down"
        log = "user login succeeded for user_id=42"
        self.assertFalse(_span_log_equivalent(span, log))

    def test_empty_inputs_do_not_match(self):
        self.assertFalse(_span_log_equivalent("", "some log"))
        self.assertFalse(_span_log_equivalent("some span", ""))
        self.assertFalse(_span_log_equivalent(None, None))

    def test_overlap_threshold_bounds(self):
        # The threshold is exposed as a module-level constant; if it
        # slides below 0.5 the test surface should get much broader.
        self.assertGreaterEqual(_SPAN_LOG_TOKEN_OVERLAP_MIN, 0.5)


class CorrelateSpansWithLogsHigherConfidenceTest(SimpleTestCase):

    def test_pymongo_decoration_yields_high_not_medium(self):
        traces = {
            "top_errors": [
                {
                    "trace_id": "a" * 32,
                    "service_name": "checkout",
                    "operation_name": "MongoDB.find_one",
                    "status_message": (
                        "ServerSelectionTimeoutError: mongo1:27017 "
                        "Connection refused"
                    ),
                },
            ],
        }
        logs = [
            {
                "timestamp": "2026-09-19T10:00:00Z",
                "message": (
                    "pymongo.errors.ServerSelectionTimeoutError: "
                    "mongodb://mongo1:27017 [Errno 111] Connection refused"
                ),
                "level": "ERROR",
                "service": "checkout",
            }
        ]
        corrs = correlate_spans_with_logs(traces, logs)
        self.assertGreater(len(corrs), 0)
        self.assertEqual(corrs[0]["confidence"], HIGH)
