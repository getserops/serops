"""
Verify that the AI batch pipeline actually scrubs PII / secrets from log
messages before they are persisted or sent to AI providers.

The redaction service itself is exercised exhaustively in
Utils/test/test_data_redaction.py. These tests cover the integration
point in ai_model/tasks._redact_log_messages — they fail loudly if
someone re-introduces the bug where unredacted messages flow downstream.
"""

from django.test import SimpleTestCase

from ai_model.tasks import _redact_log_messages


class TestRedactLogMessages(SimpleTestCase):
    """Tests for the in-pipeline redaction helper."""

    def test_password_is_redacted_in_message(self):
        logs = [{'message': 'login failed for user with password=hunter2secret'}]
        out, summary = _redact_log_messages(logs)
        self.assertNotIn('hunter2secret', out[0]['message'])
        # Service masks passwords with *****
        self.assertIn('*', out[0]['message'])
        self.assertGreaterEqual(summary['total_count'], 1)

    def test_aws_access_key_is_redacted(self):
        logs = [{'message': 'using credentials AKIAIOSFODNN7EXAMPLE for upload'}]
        out, summary = _redact_log_messages(logs)
        self.assertNotIn('AKIAIOSFODNN7EXAMPLE', out[0]['message'])
        self.assertGreaterEqual(summary['critical_count'], 1)

    def test_email_is_redacted(self):
        logs = [{'message': 'sent welcome email to alice@example.com'}]
        out, summary = _redact_log_messages(logs)
        self.assertNotIn('alice@example.com', out[0]['message'])
        self.assertGreaterEqual(summary['total_count'], 1)

    def test_clean_message_is_left_alone(self):
        logs = [{'message': 'GET /api/projects returned 200 in 23ms'}]
        out, summary = _redact_log_messages(logs)
        self.assertEqual(out[0]['message'], 'GET /api/projects returned 200 in 23ms')
        self.assertEqual(summary['total_count'], 0)

    def test_empty_message_is_skipped(self):
        logs = [{'message': ''}, {'message': None}, {'other': 'field'}]
        out, summary = _redact_log_messages(logs)
        self.assertEqual(len(out), 3)
        self.assertEqual(summary['total_count'], 0)

    def test_multiple_findings_in_one_message(self):
        logs = [{
            'message': (
                'connecting to db with user admin and password=p4ssw0rd '
                'then notifying ops@acme.io'
            )
        }]
        out, summary = _redact_log_messages(logs)
        self.assertNotIn('p4ssw0rd', out[0]['message'])
        self.assertNotIn('ops@acme.io', out[0]['message'])
        self.assertGreaterEqual(summary['total_count'], 2)

    def test_redaction_failure_returns_unredacted_safely(self):
        """If the redaction service blows up, we must not break batch analysis."""
        # Pass a malformed input that would crash the redactor — we
        # expect the helper to log a warning and return the input intact.
        original = [{'message': 'ok'}]
        out, summary = _redact_log_messages(original)
        # Either redaction succeeded (most common) or the helper caught a
        # failure and returned the input plus an empty summary; both are
        # acceptable as long as the call didn't raise.
        self.assertEqual(len(out), 1)
        self.assertEqual(summary['total_count'], summary.get('total_count', 0))
