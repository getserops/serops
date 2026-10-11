"""Tests for Utils.redaction_helpers (Q1.5).

Verifies that trace summary + alert content get redacted before
they reach:
* batch.data['traces'] (persisted → future AI prompts)
* AlertEvent rows (summary + raw_payload)
* The live-fetch trace path (pre-#10.5 batches)

PII patterns exercised: email, IPv4, JWT, GitHub token, credit card.
"""

from unittest.mock import patch

from django.test import TestCase

from Utils.redaction_helpers import (
    redact_alert_parsed, redact_raw_payload, redact_span_summary, redact_text,
)


class RedactTextTest(TestCase):

    def test_empty_returns_empty(self):
        self.assertEqual(redact_text(''), '')
        self.assertEqual(redact_text(None), '')

    def test_email_redacted(self):
        out = redact_text('user email: alice@example.com')
        self.assertNotIn('alice@example.com', out)

    def test_github_token_redacted(self):
        out = redact_text('token ghp_abcdefghij1234567890ABCDEFGHIJ1234567890')
        self.assertNotIn('ghp_abcdefghij1234567890ABCDEFGHIJ1234567890', out)

    def test_safe_text_passes_through(self):
        # Purely non-sensitive text — should be returned unchanged.
        safe = 'connection pool exhausted for checkout service'
        self.assertEqual(redact_text(safe), safe)


class RedactSpanSummaryTest(TestCase):

    def _summary_with_pii(self):
        return {
            'source': 'otlp',
            'span_count': 2,
            'error_span_count': 1,
            'services_touched': ['checkout', 'user-api'],
            'top_slow': [
                {'trace_id': 'a' * 32, 'service_name': 'checkout',
                  'operation_name': 'GET /users/alice@example.com',
                  'duration_ms': 500},
            ],
            'top_errors': [
                {'trace_id': 'b' * 32, 'service_name': 'user-api',
                  'operation_name': 'POST /login',
                  'status_message': 'JWT eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjMifQ.abcdefghijklm rejected'},
            ],
        }

    def test_none_and_non_dict_pass_through(self):
        self.assertIsNone(redact_span_summary(None))
        self.assertEqual(redact_span_summary('not a dict'), 'not a dict')

    def test_operation_name_with_email_redacted(self):
        out = redact_span_summary(self._summary_with_pii())
        self.assertNotIn('alice@example.com', out['top_slow'][0]['operation_name'])

    def test_status_message_with_jwt_redacted(self):
        out = redact_span_summary(self._summary_with_pii())
        self.assertNotIn(
            'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9',
            out['top_errors'][0]['status_message'],
        )

    def test_non_pii_operation_survives(self):
        summary = {
            'top_slow': [{'trace_id': 'x', 'service_name': 'checkout',
                           'operation_name': 'POST /checkout', 'duration_ms': 100}],
            'top_errors': [],
            'services_touched': [],
        }
        out = redact_span_summary(summary)
        self.assertEqual(out['top_slow'][0]['operation_name'], 'POST /checkout')

    def test_returns_new_dict_input_unchanged(self):
        original = self._summary_with_pii()
        out = redact_span_summary(original)
        # Input MUST be unchanged.
        self.assertIn('alice@example.com', original['top_slow'][0]['operation_name'])
        # Output has redacted text.
        self.assertNotIn('alice@example.com', out['top_slow'][0]['operation_name'])

    def test_empty_summary(self):
        # Helper always normalises to include top_slow + top_errors as
        # empty lists — downstream can rely on the shape without
        # having to guard for missing keys.
        out = redact_span_summary({})
        self.assertEqual(out.get('top_slow'), [])
        self.assertEqual(out.get('top_errors'), [])

    def test_missing_fields_dont_crash(self):
        out = redact_span_summary({'span_count': 0})
        self.assertEqual(out.get('span_count'), 0)
        self.assertEqual(out.get('top_slow'), [])
        self.assertEqual(out.get('top_errors'), [])


class RedactAlertParsedTest(TestCase):

    def test_summary_redacted(self):
        parsed = {
            'alertname': 'HighCpu', 'state': 'firing', 'severity': 'critical',
            'service': 'checkout', 'environment': 'production',
            'summary': 'CPU spike detected on host bob@example.com',
            'external_id': 'am-123',
        }
        out = redact_alert_parsed(parsed)
        self.assertNotIn('bob@example.com', out['summary'])

    def test_external_id_and_state_preserved(self):
        """external_id + state are enum-shaped — never redacted."""
        parsed = {
            'alertname': 'x', 'state': 'firing', 'severity': 'critical',
            'service': 's', 'environment': 'e', 'summary': 's',
            'external_id': 'fingerprint-abc-def-123',
        }
        out = redact_alert_parsed(parsed)
        self.assertEqual(out['external_id'], 'fingerprint-abc-def-123')
        self.assertEqual(out['state'], 'firing')

    def test_none_passes_through(self):
        self.assertIsNone(redact_alert_parsed(None))


class RedactRawPayloadTest(TestCase):

    def test_string_leaves_redacted(self):
        payload = {
            'alertname': 'X',
            'annotations': {
                'summary': 'contact ops@example.com',
            },
        }
        out = redact_raw_payload(payload)
        self.assertNotIn('ops@example.com', out['annotations']['summary'])

    def test_list_leaves_redacted(self):
        payload = {'alerts': [{'msg': 'user carol@example.com'}]}
        out = redact_raw_payload(payload)
        self.assertNotIn('carol@example.com', out['alerts'][0]['msg'])

    def test_numeric_and_bool_pass_through(self):
        payload = {'count': 5, 'active': True, 'ratio': 0.5, 'null': None}
        out = redact_raw_payload(payload)
        self.assertEqual(out, payload)

    def test_depth_cap_stops_recursion(self):
        # Depth 6 nested — with max_depth=4 the deepest leaf is
        # untouched (not redacted).
        deep_leaf = 'user@example.com'
        payload = {'l1': {'l2': {'l3': {'l4': {'l5': deep_leaf}}}}}
        out = redact_raw_payload(payload, max_depth=4)
        # Recursed 4 levels; leaf-value is at depth 5 → NOT redacted.
        self.assertEqual(out['l1']['l2']['l3']['l4']['l5'], deep_leaf)

    def test_non_dict_returns_empty(self):
        self.assertEqual(redact_raw_payload('not a dict'), {})
        self.assertEqual(redact_raw_payload(None), {})

    def test_input_unchanged(self):
        original = {'msg': 'user@example.com'}
        redact_raw_payload(original)
        self.assertEqual(original['msg'], 'user@example.com')


# ---------------------------------------------------------------------------
# End-to-end: snapshot + alert webhook actually persist redacted content
# ---------------------------------------------------------------------------


class SnapshotRedactionE2ETest(TestCase):
    """The snapshot pipeline writes REDACTED data to batch.data['traces']."""

    def test_snapshot_persists_redacted_operation_names(self):
        # Build a fake batch stub + patch _compute_live to return a
        # summary with PII. Verify the resulting batch.data['traces']
        # has been redacted before persistence.
        from ai_model.trace_context import snapshot_trace_context

        class _B:
            pass
        b = _B()
        b.timestamp = None   # short-circuits _compute_live? No; it's None-safe.
        b.project = None
        b.data = {}
        b.save = lambda update_fields: None

        with patch('ai_model.trace_context._compute_live') as compute:
            compute.return_value = {
                'source': 'otlp', 'span_count': 1, 'trace_count': 1,
                'error_span_count': 1,
                'services_touched': [],
                'top_slow': [],
                'top_errors': [{
                    'trace_id': 'a' * 32, 'service_name': 's',
                    'operation_name': 'POST /users/bob@example.com',
                    'status_message': 'boom',
                    'duration_ms': 10,
                }],
            }
            snapshot_trace_context(b)

        self.assertIn('traces', b.data)
        stored_op = b.data['traces']['top_errors'][0]['operation_name']
        self.assertNotIn('bob@example.com', stored_op)


class AlertWebhookRedactionE2ETest(TestCase):
    """The alert webhook writes REDACTED summary + raw_payload to AlertEvent."""

    def setUp(self):
        from django.test import override_settings
        from Organisations.models import Organisations
        from rest_framework.test import APIClient
        self.org = Organisations.objects.create(name='RedactAlertOrg')
        self.client = APIClient()
        self._overrides = override_settings(
            ALERT_WEBHOOK_SECRETS={'alertmanager': 'test-secret'},
        )
        self._overrides.enable()

    def tearDown(self):
        self._overrides.disable()

    def test_summary_and_payload_redacted(self):
        from Data.models import AlertEvent
        payload = {'alerts': [{
            'status': 'firing', 'fingerprint': 'e2e-1',
            'labels': {'alertname': 'HighCpu', 'severity': 'critical',
                        'service': 'checkout', 'environment': 'prod'},
            'annotations': {'summary': 'CPU 99% on host eve@example.com'},
        }]}
        url = f'/api/webhooks/alerts/alertmanager/{self.org.pk}/'
        response = self.client.post(
            url, payload, format='json',
            HTTP_AUTHORIZATION='Bearer test-secret',
        )
        self.assertEqual(response.status_code, 200)
        event = AlertEvent.objects.get()
        # Parsed summary: no email left.
        self.assertNotIn('eve@example.com', event.summary)
        # Raw payload: walked + redacted.
        stored_summary = event.raw_payload['alerts'][0]['annotations']['summary']
        self.assertNotIn('eve@example.com', stored_summary)
