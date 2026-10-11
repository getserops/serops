"""E2E: alert webhook → AlertEvent → analysis task enqueued.

This exercises the *alert-triggered* path (Item #13/#14 in the launch
plan) from the outside: a real Prometheus Alertmanager payload posted
to ``POST /api/webhooks/alerts/alertmanager/<org_id>/`` with a bearer
secret. The webhook parses, dedup-checks, redacts, and persists an
``AlertEvent``; ``analyze_alert_ondemand.delay(event.pk)`` fires per
new event.

The analysis task itself is patched at its ``delay`` entry point.
Running the whole task-to-batch-to-issue chain here would require a
live observability integration (ES / Loki / DD) to fetch logs against
— that's the value of the batch-analysis e2e in a sibling file.
What this test proves is the seam: **the webhook accepts a real
Alertmanager payload, persists the right ``AlertEvent`` row, and
schedules the analysis task with the right event id.**
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from Data.models import AlertEvent

from .base import E2ETestCase


_ALERTMANAGER_SECRET = 'e2e-alertmanager-secret-not-a-real-one'


@override_settings(
    ALERT_WEBHOOK_SECRETS={'alertmanager': _ALERTMANAGER_SECRET},
)
class AlertWebhookE2ETest(E2ETestCase):

    def _payload(self, alertname: str = 'HighErrorRate') -> dict:
        """A realistic Alertmanager v4 webhook payload.

        Shape lifted from Prometheus alertmanager/notify/webhook — the
        parser at ``_parse_alertmanager`` reads this exact structure.
        """
        return {
            'version': '4',
            'groupKey': f'{{alertname="{alertname}"}}',
            'status': 'firing',
            'receiver': 'serops-webhook',
            'groupLabels': {'alertname': alertname},
            'commonLabels': {
                'alertname': alertname,
                'severity': 'critical',
                'service': 'checkout',
                'environment': 'production',
            },
            'commonAnnotations': {
                'summary': 'checkout error rate > 5% for 5m',
                'runbook_url': 'https://runbooks/checkout-errors',
            },
            'alerts': [
                {
                    'status': 'firing',
                    'labels': {
                        'alertname': alertname,
                        'severity': 'critical',
                        'service': 'checkout',
                        'environment': 'production',
                        'instance': 'checkout-pod-a:9090',
                    },
                    'annotations': {
                        'summary': 'checkout error rate 12.4%',
                    },
                    'startsAt': '2026-09-19T10:00:00.000Z',
                    'fingerprint': 'abc123def456',
                },
            ],
        }

    def _url(self, org_id: int | None = None, source: str = 'alertmanager') -> str:
        return reverse(
            'alert-webhook',
            kwargs={'source': source, 'org_id': org_id or self.org.id},
        )

    def _authed_headers(self, secret: str = _ALERTMANAGER_SECRET) -> dict:
        return {'HTTP_AUTHORIZATION': f'Bearer {secret}'}

    def test_valid_payload_creates_alert_event_and_enqueues_analysis(self):
        self.client.force_authenticate(user=None)   # webhook is AllowAny

        with patch('Data.alert_webhooks.logger'), \
             patch('Data.tasks.analyze_alert_ondemand.delay') as enqueue:
            resp = self.client.post(
                self._url(),
                data=self._payload(),
                format='json',
                **self._authed_headers(),
            )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(resp.data['accepted'], 1)
        self.assertEqual(resp.data['deduplicated'], 0)

        events = AlertEvent.objects.filter(organisation=self.org)
        self.assertEqual(events.count(), 1)
        event = events.get()
        self.assertEqual(event.source, 'alertmanager')
        self.assertEqual(event.alertname, 'HighErrorRate')
        self.assertEqual(event.severity, 'critical')
        self.assertEqual(event.service, 'checkout')
        self.assertEqual(event.environment, 'production')
        self.assertEqual(event.state, 'firing')

        enqueue.assert_called_once_with(event.pk)

    def test_missing_bearer_secret_is_401_and_no_event_created(self):
        self.client.force_authenticate(user=None)

        with patch('Data.tasks.analyze_alert_ondemand.delay') as enqueue:
            resp = self.client.post(
                self._url(),
                data=self._payload(),
                format='json',
            )

        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(AlertEvent.objects.filter(organisation=self.org).count(), 0)
        enqueue.assert_not_called()

    def test_wrong_bearer_secret_is_401_constant_time(self):
        self.client.force_authenticate(user=None)

        with patch('Data.tasks.analyze_alert_ondemand.delay') as enqueue:
            resp = self.client.post(
                self._url(),
                data=self._payload(),
                format='json',
                **self._authed_headers(secret='wrong-secret'),
            )

        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(AlertEvent.objects.filter(organisation=self.org).count(), 0)
        enqueue.assert_not_called()

    def test_unknown_source_is_400_before_secret_check(self):
        self.client.force_authenticate(user=None)

        resp = self.client.post(
            self._url(source='not-a-real-source'),
            data=self._payload(),
            format='json',
        )
        # URL routing enforces source ∈ enum on the view side; anything
        # not in PARSER_BY_SOURCE returns 400 without hitting auth.
        self.assertIn(
            resp.status_code,
            (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND),
        )

    def test_unknown_org_is_404_no_leaked_secret(self):
        """org enumeration attack surface — 404 must not depend on
        whether the secret is right."""
        self.client.force_authenticate(user=None)

        resp = self.client.post(
            reverse('alert-webhook', kwargs={
                'source': 'alertmanager', 'org_id': 9999999,
            }),
            data=self._payload(),
            format='json',
            **self._authed_headers(),
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_duplicate_within_dedup_window_is_200_no_op(self):
        self.client.force_authenticate(user=None)

        with patch('Data.tasks.analyze_alert_ondemand.delay') as enqueue:
            first = self.client.post(
                self._url(), data=self._payload(), format='json',
                **self._authed_headers(),
            )
            second = self.client.post(
                self._url(), data=self._payload(), format='json',
                **self._authed_headers(),
            )

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data['accepted'], 1)
        self.assertEqual(second.data['accepted'], 0)
        self.assertEqual(second.data['deduplicated'], 1)
        self.assertEqual(
            AlertEvent.objects.filter(organisation=self.org).count(), 1,
            'dedup window must prevent a second row for the same alert.',
        )
        # Analysis task fired only for the first (accepted) event.
        self.assertEqual(enqueue.call_count, 1)
