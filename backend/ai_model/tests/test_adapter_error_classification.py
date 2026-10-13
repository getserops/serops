"""Batch 29 (Q hardening): AI-adapter error normalization tests.

Adapters previously classified almost every non-quota/non-auth error as
``UNKNOWN_ERROR``. That masked three important cases:

* **Timeout** — a hung provider looks the same as a bug, but the right
  reaction is retry-with-backoff, not surface-to-user.
* **Overloaded (529)** — Claude Sonnet spikes 529s during peak load.
  We don't want to count those against quota_exceeded (which affects
  fallback decisions) or against unknown (which shouldn't retry).
* **Server error (5xx)** — provider outage vs. our bug: the retry
  strategy differs.

These tests pin the classification so a future adapter tweak can't
silently regress the categorisation the tasks pipeline relies on.
"""

from django.test import SimpleTestCase

from ai_model.adapters.claude import ClaudeAdapter
from ai_model.adapters.gemini import GeminiAdapter
from ai_model.adapters.openai_generic import GenericOpenAIAdapter


class AllAdaptersErrorClassificationTest(SimpleTestCase):

    def _adapters(self):
        return [ClaudeAdapter(), GeminiAdapter(), GenericOpenAIAdapter()]

    def test_timeout_maps_to_timeout(self):
        for adapter in self._adapters():
            for msg in ('Read timeout', 'Request timed out', 'httpx.TimeoutError'):
                err = adapter.normalize_error(Exception(msg))
                self.assertEqual(
                    err.error_type, 'timeout',
                    f"{adapter.__class__.__name__} misclassified {msg!r}",
                )

    def test_rate_limit_maps_to_quota(self):
        for adapter in self._adapters():
            for msg in ('429 Too Many Requests', 'rate limit exceeded'):
                err = adapter.normalize_error(Exception(msg))
                self.assertEqual(err.error_type, 'quota_exceeded')

    def test_auth_maps_to_auth(self):
        for adapter in self._adapters():
            for msg in ('401 Unauthorized', 'Invalid API key'):
                err = adapter.normalize_error(Exception(msg))
                self.assertEqual(err.error_type, 'auth_error')

    def test_overloaded_529_maps_to_overloaded(self):
        # Claude Sonnet returns 529 during peak load. OpenAI-compat
        # backends occasionally do too. Distinguishing from quota
        # matters because overload isn't the user's fault + retry is
        # the right response (quota → fallback provider).
        for adapter in (ClaudeAdapter(), GenericOpenAIAdapter()):
            for msg in ('529 Overloaded', 'Provider is overloaded'):
                err = adapter.normalize_error(Exception(msg))
                self.assertEqual(err.error_type, 'overloaded')

    def test_server_5xx_maps_to_server_error(self):
        for adapter in self._adapters():
            for msg in ('500 Internal Server Error', '503 Service Unavailable', '502 Bad Gateway'):
                err = adapter.normalize_error(Exception(msg))
                self.assertEqual(
                    err.error_type, 'server_error',
                    f"{adapter.__class__.__name__} misclassified {msg!r}",
                )

    def test_network_maps_to_network_error(self):
        for adapter in self._adapters():
            for msg in ('Connection refused', 'Network is unreachable',
                         'Name or service not known'):
                err = adapter.normalize_error(Exception(msg))
                self.assertEqual(
                    err.error_type, 'network_error',
                    f"{adapter.__class__.__name__} misclassified {msg!r}",
                )

    def test_gemini_safety_block_maps_to_content_blocked(self):
        # Gemini's strong content filter returns SAFETY blocks. Users
        # can retry only by rephrasing / redacting — retry logic must
        # NOT loop on this.
        adapter = GeminiAdapter()
        for msg in ('SAFETY_BLOCK triggered', 'blocked by safety filter',
                     'PROHIBITED_CONTENT'):
            err = adapter.normalize_error(Exception(msg))
            self.assertEqual(err.error_type, 'content_blocked')

    def test_raw_error_is_capped_at_500_chars(self):
        # Gemini previously returned unbounded str(e) which spammed
        # logs when the provider echoed the request payload back in
        # error responses.
        huge = 'x' * 10_000
        for adapter in self._adapters():
            err = adapter.normalize_error(Exception(huge))
            self.assertLessEqual(
                len(err.raw_error or ''), 500,
                f"{adapter.__class__.__name__} did not truncate raw_error",
            )

    def test_truly_unknown_still_falls_through(self):
        for adapter in self._adapters():
            err = adapter.normalize_error(Exception('some novel exotic failure'))
            self.assertEqual(err.error_type, 'unknown')
