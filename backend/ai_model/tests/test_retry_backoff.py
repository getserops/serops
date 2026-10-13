"""Tests for the transient-error retry loop in ai_service (PR-AUDIT5,
RCA audit finding #2).

Before this fix, a single Gemini 503 (real Google capacity pressure)
or Claude 529 failed the batch immediately and required a manual
Reanalyze. The retry loop now transparently retries up to 2 times
with exponential backoff for known-transient error classes.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

from django.test import SimpleTestCase, override_settings

from ai_model.adapters.base import AIServiceError
from ai_model.ai_service import (
    _MAX_RETRIES,
    _RETRYABLE_ERROR_TYPES,
    _backoff_delay,
    _should_retry,
    _generate_with_retry,
)


class RetryPolicyTest(SimpleTestCase):

    def test_transient_error_classes_are_documented(self):
        # Regression guard: these are the error types the retry loop
        # will re-issue. If a new one is added the launch plan should
        # know about it.
        self.assertIn('server_error', _RETRYABLE_ERROR_TYPES)
        self.assertIn('overloaded', _RETRYABLE_ERROR_TYPES)
        self.assertIn('network_error', _RETRYABLE_ERROR_TYPES)
        self.assertIn('timeout', _RETRYABLE_ERROR_TYPES)

    def test_should_retry_true_for_transient(self):
        err = AIServiceError.from_type('server_error', 'HTTP 503')
        self.assertTrue(_should_retry(err))

    def test_should_retry_false_for_permanent(self):
        for et in ('auth_error', 'quota_exceeded', 'content_blocked',
                   'truncated', 'provider_not_supported', 'unknown'):
            err = AIServiceError.from_type(et, 'x')
            self.assertFalse(_should_retry(err), f'{et} must not retry')

    def test_should_retry_false_on_no_error(self):
        self.assertFalse(_should_retry(None))

    def test_backoff_delay_is_exponential(self):
        # First attempt sleeps ≥ base, second ≥ 2×base, capped.
        d0 = _backoff_delay(0)
        d1 = _backoff_delay(1)
        self.assertGreaterEqual(d0, 2.0)
        self.assertGreaterEqual(d1, 4.0)
        # Both stay under cap + jitter allowance.
        self.assertLess(d0, 9.0)
        self.assertLess(d1, 9.0)


class GenerateWithRetryTest(SimpleTestCase):

    def _make_adapter(self, side_effect):
        """Return a mock adapter whose ``generate`` returns each item
        from ``side_effect`` in order."""
        adapter = MagicMock()
        adapter.generate.side_effect = side_effect
        return adapter

    def test_first_success_no_retry(self):
        adapter = self._make_adapter([("ok text", None, 100, 200)])
        with patch('ai_model.ai_service.time.sleep') as sleep:
            out = _generate_with_retry(
                adapter, "prompt", {}, "key", None, "test",
            )
        self.assertEqual(out, ("ok text", None, 100, 200))
        self.assertEqual(adapter.generate.call_count, 1)
        sleep.assert_not_called()

    def test_transient_error_retries_then_succeeds(self):
        err = AIServiceError.from_type('server_error', 'HTTP 503')
        adapter = self._make_adapter([
            (None, err, 50, 0),
            ("recovered", None, 100, 200),
        ])
        with patch('ai_model.ai_service.time.sleep'):
            out = _generate_with_retry(
                adapter, "prompt", {}, "key", None, "test",
            )
        self.assertEqual(out, ("recovered", None, 100, 200))
        self.assertEqual(adapter.generate.call_count, 2)

    def test_permanent_error_does_not_retry(self):
        err = AIServiceError.from_type('auth_error', 'invalid key')
        adapter = self._make_adapter([(None, err, 0, 0)])
        with patch('ai_model.ai_service.time.sleep') as sleep:
            out = _generate_with_retry(
                adapter, "prompt", {}, "key", None, "test",
            )
        self.assertIs(out[1].error_type, 'auth_error')
        self.assertEqual(adapter.generate.call_count, 1)
        sleep.assert_not_called()

    def test_retries_exhausted_returns_last_error_first_tokens(self):
        err = AIServiceError.from_type('server_error', 'HTTP 503')
        # 3 failures — MAX_RETRIES=2 → 3 total attempts, all fail.
        adapter = self._make_adapter([
            (None, err, 42, 0),      # first-attempt token count
            (None, err, 0, 0),
            (None, err, 0, 0),
        ])
        with patch('ai_model.ai_service.time.sleep'):
            out = _generate_with_retry(
                adapter, "prompt", {}, "key", None, "test",
            )
        self.assertIsNone(out[0])
        self.assertIsNotNone(out[1])
        self.assertEqual(out[2], 42)   # first attempt's tokens survive
        self.assertEqual(adapter.generate.call_count, _MAX_RETRIES + 1)
