"""Phase 3 review SC-01 / SC-02: the alert analysis looks at when the alert
started, and an alert that matches no service is not analysed against an
arbitrary project."""
from datetime import datetime, timedelta, timezone as dt_tz
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from Data.alert_webhooks import _parse_alertmanager, _parse_datadog, _parse_time
from Data.models import AIAnalyzedBatch, AlertEvent
from Organisations.models import Organisations
from Projects.models import Project, ProjectEnvironment, ProjectService


class AlertStartTimeParsingTest(TestCase):
    def setUp(self):
        # A fixed moment in the past: the parser refuses future times.
        self.t = (timezone.now() - timedelta(hours=1)).replace(microsecond=0)
        self.z = self.t.astimezone(dt_tz.utc).strftime('%Y-%m-%dT%H:%M:%S')

    def test_alertmanager_nanosecond_starts_at(self):
        t = _parse_time(f'{self.z}.123456789Z')
        self.assertEqual(t, self.t.replace(microsecond=123456))

    def test_zero_time_future_and_garbage_are_none(self):
        self.assertIsNone(_parse_time('0001-01-01T00:00:00Z'))
        self.assertIsNone(_parse_time((timezone.now() + timedelta(hours=1)).isoformat()))
        self.assertIsNone(_parse_time('yesterday'))
        self.assertIsNone(_parse_time(None))

    def test_datadog_epoch_milliseconds(self):
        ms = int(self.t.timestamp() * 1000)
        parsed = _parse_datadog({'title': '[Triggered] High error rate', 'id': '1', 'date': str(ms)})[0]
        self.assertEqual(parsed['starts_at'], self.t)

    def test_alertmanager_keeps_starts_at_and_labels(self):
        parsed = _parse_alertmanager({'alerts': [{
            'status': 'firing', 'fingerprint': 'f1', 'startsAt': f'{self.z}Z',
            'labels': {'alertname': 'KubePodCrashLooping', 'container': 'payments-api',
                       'namespace': 'payments', 'job': 'kube-state-metrics'}}]})[0]
        self.assertEqual(parsed['starts_at'], self.t)
        self.assertEqual(parsed['labels']['container'], 'payments-api')


class AlertWindowTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='WinOrg')

    def _event(self, received, starts=None, **kw):
        e = AlertEvent.objects.create(organisation=self.org, source='alertmanager',
                                      alertname='HighErrorRate', state='firing', starts_at=starts, **kw)
        AlertEvent.objects.filter(pk=e.pk).update(received_at=received)
        e.refresh_from_db()
        return e

    def test_window_covers_the_onset_not_only_the_receipt(self):
        """Deploy at -13 min, alert started -12 min (``for: 10m``), received now."""
        from Data.tasks import _alert_window
        now = timezone.now().replace(microsecond=0)
        start_iso, end_iso = _alert_window(self._event(now, starts=now - timedelta(minutes=12)))
        start, end = datetime.fromisoformat(start_iso), datetime.fromisoformat(end_iso)
        self.assertLessEqual(start, now - timedelta(minutes=13))   # the deploy
        self.assertGreaterEqual(end, now)

    def test_without_a_start_time_it_looks_back_from_receipt(self):
        from Data.tasks import _alert_window, _ALERT_LOOKBACK_MINUTES
        now = timezone.now().replace(microsecond=0)
        start_iso, _ = _alert_window(self._event(now))
        self.assertEqual(datetime.fromisoformat(start_iso), now - timedelta(minutes=_ALERT_LOOKBACK_MINUTES))

    def test_an_old_start_is_capped(self):
        from Data.tasks import _alert_window, _ALERT_MAX_SPAN_MINUTES
        now = timezone.now().replace(microsecond=0)
        start_iso, end_iso = _alert_window(self._event(now, starts=now - timedelta(days=2)))
        span = datetime.fromisoformat(end_iso) - datetime.fromisoformat(start_iso)
        self.assertEqual(span, timedelta(minutes=_ALERT_MAX_SPAN_MINUTES))


class AlertRoutingTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='RouteOrg')
        self.marketing = Project.objects.create(organisation=self.org, name='marketing-site')
        self.payments = Project.objects.create(organisation=self.org, name='payments')
        ProjectService.objects.create(project=self.marketing, name='web')
        ProjectService.objects.create(project=self.payments, name='payments-api')
        ProjectEnvironment.objects.create(project=self.payments, name='production')

    def _event(self, **kw):
        kw.setdefault('alertname', 'KubeContainerOOM')
        return AlertEvent.objects.create(organisation=self.org, source='alertmanager', state='firing', **kw)

    def test_kubernetes_container_label_routes_to_its_project(self):
        from Data.tasks import _resolve_alert_project
        event = self._event(service='kube-state-metrics',
                            labels={'container': 'payments-api', 'namespace': 'payments',
                                    'job': 'kube-state-metrics'})
        self.assertEqual(_resolve_alert_project(event), self.payments)

    def test_namespace_naming_a_project_routes_to_it(self):
        from Data.tasks import _resolve_alert_project
        event = self._event(service='', labels={'namespace': 'payments', 'pod': 'x-123'})
        self.assertEqual(_resolve_alert_project(event), self.payments)

    def test_no_match_is_not_analysed_against_the_first_project(self):
        from Data.tasks import analyze_alert_ondemand
        event = self._event(service='nothing-like-this', labels={'job': 'node-exporter'})
        with patch('Data.tasks.create_log_batch_with_project_name') as create:
            result = analyze_alert_ondemand.run(event.pk)
        create.assert_not_called()
        self.assertEqual(result['reason'], 'unmatched')
        event.refresh_from_db()
        self.assertEqual(event.match_status, AlertEvent.MATCH_UNMATCHED)
        self.assertIn('nothing-like-this', event.match_detail)
        self.assertIsNotNone(event.processed_at)

    def test_single_project_org_still_analyses(self):
        from Data.tasks import _resolve_alert_project
        solo = Organisations.objects.create(name='Solo')
        only = Project.objects.create(organisation=solo, name='only')
        event = AlertEvent.objects.create(organisation=solo, source='alertmanager', alertname='X',
                                          state='firing', service='unknown')
        self.assertEqual(_resolve_alert_project(event), only)

    def test_prod_alert_picks_the_production_environment(self):
        from Data.tasks import _alert_project_environment
        env = _alert_project_environment(self.payments, 'prod')
        self.assertEqual(env.name, 'production')

    def test_matched_alert_runs_the_batch_on_the_onset_window(self):
        from Data.tasks import analyze_alert_ondemand
        now = timezone.now().replace(microsecond=0)
        event = self._event(service='payments-api', environment='production',
                            starts_at=now - timedelta(minutes=12))
        with patch('Data.tasks.create_log_batch_with_project_name') as create:
            analyze_alert_ondemand.run(event.pk)
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs['project'], self.payments)
        self.assertLessEqual(datetime.fromisoformat(kwargs['window_start_iso']), now - timedelta(minutes=13))
        event.refresh_from_db()
        self.assertEqual(event.match_status, AlertEvent.MATCH_MATCHED)

    def test_a_repeat_notification_of_an_analysed_firing_is_not_analysed_again(self):
        from Data.tasks import analyze_alert_ondemand
        started = timezone.now().replace(microsecond=0) - timedelta(hours=4)
        batch = AIAnalyzedBatch.objects.create(batch_id='payments-alert-1', project=self.payments,
                                               organisation=self.org)
        self._event(service='payments-api', external_id='fp1', starts_at=started, triggered_batch=batch)
        repeat = self._event(service='payments-api', external_id='fp1', starts_at=started)
        with patch('Data.tasks.create_log_batch_with_project_name') as create:
            result = analyze_alert_ondemand.run(repeat.pk)
        create.assert_not_called()
        self.assertEqual(result['reason'], 'repeat')
        repeat.refresh_from_db()
        self.assertEqual(repeat.triggered_batch, batch)
        self.assertEqual(repeat.match_status, AlertEvent.MATCH_REPEAT)
