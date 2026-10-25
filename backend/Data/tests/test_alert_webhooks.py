"""Tests for Items #13 + #14: alert webhooks + on-demand analysis pipeline."""

from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from Data.models import AlertEvent
from Organisations.models import Organisations


_TEST_SECRETS = {
    'alertmanager': 'am-secret',
    'grafana': 'graf-secret',
    'datadog': 'dd-secret',
}


@override_settings(ALERT_WEBHOOK_SECRETS=_TEST_SECRETS)
class AlertWebhookAuthTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='AWTOrg')
        self.client = APIClient()

    def _url(self, source, org_id=None):
        return f'/api/webhooks/alerts/{source}/{org_id or self.org.pk}/'

    def _sample_am(self):
        return {'alerts': [{
            'status': 'firing', 'fingerprint': 'abc123',
            'labels': {'alertname': 'HighCpu', 'severity': 'critical',
                        'service': 'checkout', 'environment': 'prod'},
            'annotations': {'summary': 'CPU over 95%'},
        }]}

    def test_missing_auth_401(self):
        response = self.client.post(
            self._url('alertmanager'), self._sample_am(), format='json',
        )
        self.assertEqual(response.status_code, 401)

    def test_wrong_auth_401(self):
        response = self.client.post(
            self._url('alertmanager'), self._sample_am(),
            format='json', HTTP_AUTHORIZATION='Bearer wrong',
        )
        self.assertEqual(response.status_code, 401)

    def test_no_bearer_prefix_401(self):
        response = self.client.post(
            self._url('alertmanager'), self._sample_am(),
            format='json', HTTP_AUTHORIZATION='am-secret',
        )
        self.assertEqual(response.status_code, 401)

    def test_unknown_source_400(self):
        response = self.client.post(
            self._url('newrelic'), self._sample_am(),
            format='json', HTTP_AUTHORIZATION='Bearer am-secret',
        )
        self.assertEqual(response.status_code, 400)

    def test_unknown_org_404(self):
        response = self.client.post(
            self._url('alertmanager', org_id=99999), self._sample_am(),
            format='json', HTTP_AUTHORIZATION='Bearer am-secret',
        )
        self.assertEqual(response.status_code, 404)


@override_settings(ALERT_WEBHOOK_SECRETS=_TEST_SECRETS)
class AlertWebhookIngestTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='IngestOrg')
        self.client = APIClient()

    def _url(self, source='alertmanager'):
        return f'/api/webhooks/alerts/{source}/{self.org.pk}/'

    @patch('Data.tasks.analyze_alert_ondemand.delay')
    def test_alertmanager_creates_event_and_enqueues(self, delay_mock):
        payload = {'alerts': [{
            'status': 'firing', 'fingerprint': 'am-1',
            'labels': {'alertname': 'HighCpu', 'severity': 'critical',
                        'service': 'checkout', 'environment': 'prod'},
            'annotations': {'summary': 'CPU over 95%'},
        }]}
        response = self.client.post(
            self._url(), payload,
            format='json', HTTP_AUTHORIZATION='Bearer am-secret',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'accepted': 1, 'deduplicated': 0})
        event = AlertEvent.objects.get()
        self.assertEqual(event.source, 'alertmanager')
        self.assertEqual(event.alertname, 'HighCpu')
        self.assertEqual(event.service, 'checkout')
        self.assertEqual(event.environment, 'prod')
        self.assertEqual(event.external_id, 'am-1')
        delay_mock.assert_called_once_with(event.pk)

    @patch('Data.tasks.analyze_alert_ondemand.delay')
    def test_multiple_alerts_in_one_request(self, delay_mock):
        payload = {'alerts': [
            {'status': 'firing', 'fingerprint': 'a',
              'labels': {'alertname': 'X', 'service': 's1'},
              'annotations': {}},
            {'status': 'firing', 'fingerprint': 'b',
              'labels': {'alertname': 'X', 'service': 's2'},
              'annotations': {}},
        ]}
        response = self.client.post(
            self._url(), payload,
            format='json', HTTP_AUTHORIZATION='Bearer am-secret',
        )
        self.assertEqual(response.json()['accepted'], 2)
        self.assertEqual(AlertEvent.objects.count(), 2)
        self.assertEqual(delay_mock.call_count, 2)

    @patch('Data.tasks.analyze_alert_ondemand.delay')
    def test_duplicate_within_window_skipped(self, delay_mock):
        payload = {'alerts': [{
            'status': 'firing', 'fingerprint': 'dup',
            'labels': {'alertname': 'X', 'service': 's'},
            'annotations': {},
        }]}
        # First → accepted
        r1 = self.client.post(self._url(), payload, format='json',
                              HTTP_AUTHORIZATION='Bearer am-secret')
        # Second (retry) → deduped
        r2 = self.client.post(self._url(), payload, format='json',
                              HTTP_AUTHORIZATION='Bearer am-secret')
        self.assertEqual(r1.json()['accepted'], 1)
        self.assertEqual(r2.json(), {'accepted': 0, 'deduplicated': 1})
        self.assertEqual(AlertEvent.objects.count(), 1)
        self.assertEqual(delay_mock.call_count, 1)

    @patch('Data.tasks.analyze_alert_ondemand.delay')
    def test_datadog_payload_parsed(self, delay_mock):
        payload = {
            'event_type': 'triggered',
            'alert_title': 'DD-HighLatency',
            'body': 'Latency over 500ms',
            'tags': 'service:api,env:prod',
            'id': 'dd-42',
            'priority': 'P1',
        }
        response = self.client.post(
            f'/api/webhooks/alerts/datadog/{self.org.pk}/',
            payload,
            format='json',
            HTTP_AUTHORIZATION='Bearer dd-secret',
        )
        self.assertEqual(response.status_code, 200)
        event = AlertEvent.objects.get()
        self.assertEqual(event.source, 'datadog')
        self.assertEqual(event.alertname, 'DD-HighLatency')
        self.assertEqual(event.service, 'api')
        self.assertEqual(event.environment, 'prod')
        self.assertEqual(event.external_id, 'dd-42')

    @patch('Data.tasks.analyze_alert_ondemand.delay')
    def test_grafana_uses_alertmanager_format(self, delay_mock):
        payload = {'alerts': [{
            'status': 'firing', 'fingerprint': 'gr-1',
            'labels': {'alertname': 'GrafAlert', 'service': 'svc'},
            'annotations': {},
        }]}
        response = self.client.post(
            f'/api/webhooks/alerts/grafana/{self.org.pk}/',
            payload,
            format='json',
            HTTP_AUTHORIZATION='Bearer graf-secret',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AlertEvent.objects.get().source, 'grafana')

    def test_empty_alerts_list_200(self):
        response = self.client.post(
            self._url(), {'alerts': []}, format='json',
            HTTP_AUTHORIZATION='Bearer am-secret',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'accepted': 0, 'deduplicated': 0})


@override_settings(ALERT_WEBHOOK_SECRETS={'alertmanager': ''})
class AlertWebhookNoSecretConfiguredTest(TestCase):

    def test_unconfigured_source_rejects_all(self):
        """A source with no configured secret rejects even 'correct'-looking auth.
        Never allow un-authenticated webhooks."""
        org = Organisations.objects.create(name='NoSecretOrg')
        client = APIClient()
        response = client.post(
            f'/api/webhooks/alerts/alertmanager/{org.pk}/',
            {'alerts': [{'status': 'firing', 'labels': {'alertname': 'X'}}]},
            format='json',
            HTTP_AUTHORIZATION='Bearer ',
        )
        self.assertEqual(response.status_code, 401)


class AnalyzeAlertOndemandTest(TestCase):

    def test_missing_event_returns_skipped(self):
        from Data.tasks import analyze_alert_ondemand
        result = analyze_alert_ondemand(99999)
        self.assertEqual(result, {'status': 'skipped', 'reason': 'event_not_found'})

    def test_no_project_returns_skipped(self):
        from Data.tasks import analyze_alert_ondemand
        org = Organisations.objects.create(name='NoProjOrg')
        event = AlertEvent.objects.create(
            organisation=org, source='alertmanager', alertname='X',
            state='firing', service='foo',
        )
        result = analyze_alert_ondemand(event.pk)
        self.assertEqual(result, {'status': 'skipped', 'reason': 'no_project'})
        event.refresh_from_db()
        self.assertIsNotNone(event.processed_at)

    @patch('Data.tasks.create_log_batch_with_project_name')
    def test_project_found_analysis_invoked(self, mock_pipeline):
        from Data.tasks import analyze_alert_ondemand
        from Projects.models import Project
        mock_pipeline.return_value = {'status': 'ok'}
        org = Organisations.objects.create(name='WithProjOrg')
        Project.objects.create(organisation=org, name='p1')
        event = AlertEvent.objects.create(
            organisation=org, source='datadog', alertname='HighCpu',
            state='firing', service='p1',
        )
        result = analyze_alert_ondemand(event.pk)
        self.assertEqual(result['status'], 'analysed')
        self.assertTrue(mock_pipeline.called)
        event.refresh_from_db()
        self.assertIsNotNone(event.processed_at)


class AlertmanagerLabelTest(TestCase):
    """Rules copy the canonical labels our metrics docs set (service_name)."""

    def test_service_name_label_is_the_service(self):
        from Data.alert_webhooks import _parse_alertmanager
        parsed = _parse_alertmanager({'alerts': [{
            'status': 'firing', 'fingerprint': 'f1',
            'labels': {'alertname': 'PaymentsErrors', 'service_name': 'payments', 'environment': 'production'},
            'annotations': {}}]})
        self.assertEqual(parsed[0]['service'], 'payments')
        self.assertEqual(parsed[0]['environment'], 'production')
