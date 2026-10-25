"""Tests for IncidentNotificationChannel model + senders + dispatcher +
CRUD API (Items #22 + #23).
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from notifications.incident_dispatcher import dispatch
from notifications.models import IncidentNotificationChannel
from Organisations.models import Organisations
from Projects.models import Project

User = get_user_model()

# Webhook URLs are checked with validate_public_url, which resolves the
# hostname. Resolve every name to a public test address so the suite never
# needs network access; tests about refusals use IP literals or patch this.
_PUBLIC_DNS = patch('Utils.url_validator.socket.getaddrinfo',
                    return_value=[(2, 1, 6, '', ('52.95.110.1', 0))])


def setUpModule():
    _PUBLIC_DNS.start()


def tearDownModule():
    _PUBLIC_DNS.stop()


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class IncidentChannelModelTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='CH-Org')

    def test_matches_event_empty_list_matches_all(self):
        c = IncidentNotificationChannel(
            organisation=self.org, name='x', kind='slack',
            trigger_events=[], is_active=True,
        )
        self.assertTrue(c.matches_event('batch_analyzed'))
        self.assertTrue(c.matches_event('alert_triggered'))

    def test_matches_event_specific_list(self):
        c = IncidentNotificationChannel(
            organisation=self.org, name='x', kind='slack',
            trigger_events=['alert_triggered'], is_active=True,
        )
        self.assertFalse(c.matches_event('batch_analyzed'))
        self.assertTrue(c.matches_event('alert_triggered'))

    def test_inactive_never_matches(self):
        c = IncidentNotificationChannel(
            organisation=self.org, name='x', kind='slack',
            trigger_events=[], is_active=False,
        )
        self.assertFalse(c.matches_event('batch_analyzed'))

    def test_meets_severity_default_any(self):
        c = IncidentNotificationChannel(
            organisation=self.org, name='x', kind='slack', min_severity='',
        )
        self.assertTrue(c.meets_severity('LOW'))
        self.assertTrue(c.meets_severity('CRITICAL'))

    def test_meets_severity_floor(self):
        c = IncidentNotificationChannel(
            organisation=self.org, name='x', kind='slack', min_severity='HIGH',
        )
        self.assertFalse(c.meets_severity('LOW'))
        self.assertFalse(c.meets_severity('MEDIUM'))
        self.assertTrue(c.meets_severity('HIGH'))
        self.assertTrue(c.meets_severity('CRITICAL'))

    def test_encryption_round_trip(self):
        c = IncidentNotificationChannel(
            organisation=self.org, name='x', kind='slack',
        )
        c.set_webhook_url('https://hooks.slack.com/services/T/B/xyz')
        c.save()
        self.assertEqual(
            c.get_webhook_url(),
            'https://hooks.slack.com/services/T/B/xyz',
        )
        # Encrypted at rest — raw column value differs.
        self.assertNotEqual(c.webhook_url, 'https://hooks.slack.com/services/T/B/xyz')


# ---------------------------------------------------------------------------
# Senders (all HTTP mocked)
# ---------------------------------------------------------------------------


def _mock_resp(status_code=200, text='ok'):
    m = MagicMock()
    m.status_code = status_code
    m.text = text
    return m


def _payload():
    return {
        'title': 'Test RCA',
        'project_name': 'checkout',
        'environment': 'production',
        'top_severity': 'CRITICAL',
        'issue_count': 3,
        'root_cause': 'Connection pool exhausted',
        'recommendation': 'Increase pool size',
        'incident_url': 'https://serops.local/dash/issues/batch_1',
    }


class SlackSenderTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='SL-Org')
        self.channel = IncidentNotificationChannel(
            organisation=self.org, name='x', kind='slack',
        )
        self.channel.set_webhook_url('https://hooks.slack.com/x')
        self.channel.save()

    @patch('notifications.senders.slack.requests.post')
    def test_success(self, post):
        post.return_value = _mock_resp(200, 'ok')
        from notifications.senders.slack import send
        ok, msg = send(self.channel, _payload())
        self.assertTrue(ok)
        # Verify body contains Block Kit + fallback text.
        body = post.call_args.kwargs['json']
        self.assertIn('blocks', body)
        self.assertIn('text', body)

    @patch('notifications.senders.slack.requests.post')
    def test_http_error_returns_false(self, post):
        post.return_value = _mock_resp(500, 'server error')
        from notifications.senders.slack import send
        ok, msg = send(self.channel, _payload())
        self.assertFalse(ok)
        self.assertIn('500', msg)

    @patch('notifications.senders.slack.requests.post')
    def test_network_error_returns_false(self, post):
        from requests.exceptions import ConnectionError as ReqConnErr
        post.side_effect = ReqConnErr('down')
        from notifications.senders.slack import send
        ok, msg = send(self.channel, _payload())
        self.assertFalse(ok)
        self.assertIn('Network error', msg)

    @patch('notifications.senders.slack.requests.post')
    def test_stored_internal_url_is_refused_at_send_time(self, post):
        c = IncidentNotificationChannel(organisation=self.org, name='old', kind='slack')
        c.set_webhook_url('https://169.254.169.254/latest/meta-data/')   # saved before validation existed
        c.save()
        from notifications.senders.slack import send
        ok, msg = send(c, _payload())
        self.assertFalse(ok)
        self.assertIn('Refused webhook URL', msg)
        post.assert_not_called()

    def test_missing_url(self):
        c = IncidentNotificationChannel(
            organisation=self.org, name='y', kind='slack',
        )
        c.save()
        from notifications.senders.slack import send
        ok, msg = send(c, _payload())
        self.assertFalse(ok)
        self.assertIn('Missing', msg)


class TeamsSenderTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='TM-Org')
        self.channel = IncidentNotificationChannel(
            organisation=self.org, name='x', kind='teams',
        )
        self.channel.set_webhook_url('https://outlook.office.com/webhook/x')
        self.channel.save()

    @patch('notifications.senders.teams.requests.post')
    def test_success_uses_message_card(self, post):
        post.return_value = _mock_resp(200)
        from notifications.senders.teams import send
        ok, msg = send(self.channel, _payload())
        self.assertTrue(ok)
        body = post.call_args.kwargs['json']
        self.assertEqual(body['@type'], 'MessageCard')


class PagerdutySenderTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='PD-Org')
        self.channel = IncidentNotificationChannel(
            organisation=self.org, name='x', kind='pagerduty',
        )
        self.channel.set_api_key('int-key-abc')
        self.channel.save()

    @patch('notifications.senders.pagerduty.requests.post')
    def test_success_hits_change_events_endpoint(self, post):
        post.return_value = _mock_resp(202)
        from notifications.senders.pagerduty import send
        ok, msg = send(self.channel, _payload())
        self.assertTrue(ok)
        url = post.call_args.args[0]
        self.assertIn('events.pagerduty.com/v2/change/enqueue', url)
        body = post.call_args.kwargs['json']
        self.assertEqual(body['routing_key'], 'int-key-abc')
        self.assertIn('summary', body['payload'])


class OpsgenieSenderTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='OG-Org')
        self.channel = IncidentNotificationChannel(
            organisation=self.org, name='x', kind='opsgenie',
            extra_config={'region': 'eu'},
        )
        self.channel.set_api_key('og-key')
        self.channel.save()

    @patch('notifications.senders.opsgenie.requests.post')
    def test_eu_region_hits_eu_host(self, post):
        post.return_value = _mock_resp(202)
        from notifications.senders.opsgenie import send
        ok, msg = send(self.channel, _payload())
        self.assertTrue(ok)
        url = post.call_args.args[0]
        self.assertIn('api.eu.opsgenie.com', url)
        headers = post.call_args.kwargs['headers']
        self.assertEqual(headers['Authorization'], 'GenieKey og-key')

    def test_unknown_region_rejected(self):
        c = IncidentNotificationChannel(
            organisation=self.org, name='y', kind='opsgenie',
            extra_config={'region': 'moon'},
        )
        c.set_api_key('x')
        c.save()
        from notifications.senders.opsgenie import send
        ok, msg = send(c, _payload())
        self.assertFalse(ok)
        self.assertIn('region', msg.lower())


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class DispatcherTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='D-Org')
        cls.project = Project.objects.create(name='d-proj', organisation=cls.org)

    def _make_batch(self):
        class _B:
            pass
        b = _B()
        b.batch_id = 'batch_x'
        b.organisation = self.org
        b.project = self.project
        b.environment = 'production'
        # Fake .issues queryset — dispatcher only calls .all() (ordered by
        # Data.issue_order.root_cause_first) and .count().
        issue = MagicMock()
        issue.severity = 'HIGH'
        issue.root_cause = 'x'
        issue.recommendation = 'y'
        qs = MagicMock()
        qs.all.return_value = [issue]
        qs.count.return_value = 1
        b.issues = qs
        return b

    def _catch_all_rule(self, channels, name='catch-all', **kw):
        """PR-N phase 2 (2026-09-26): the dispatcher walks routing rules
        now — the tests below need to declare a rule that targets each
        channel under test, otherwise the channel is never contacted."""
        from notifications.models import NotificationRoutingRule
        r = NotificationRoutingRule.objects.create(
            organisation=self.org, name=name, is_active=True, **kw,
        )
        r.targets.set(channels)
        return r

    @patch('notifications.senders.slack.requests.post')
    def test_fires_matching_channels(self, post):
        post.return_value = _mock_resp(200)
        c = IncidentNotificationChannel(
            organisation=self.org, name='fires', kind='slack',
            trigger_events=[], is_active=True,
        )
        c.set_webhook_url('https://hooks.slack.com/x')
        c.save()
        self._catch_all_rule([c])
        result = dispatch(self._make_batch(), event='batch_analyzed')
        self.assertEqual(result['sent'], 1)
        self.assertEqual(result['failed'], 0)

    @patch('notifications.senders.slack.requests.post')
    def test_skips_non_matching_event(self, post):
        """A routing rule scoped to alert_triggered doesn't fire on
        a batch_analyzed dispatch."""
        post.return_value = _mock_resp(200)
        c = IncidentNotificationChannel(
            organisation=self.org, name='alert-only', kind='slack',
            trigger_events=[], is_active=True,
        )
        c.set_webhook_url('https://hooks.slack.com/x')
        c.save()
        self._catch_all_rule([c], event_types=['alert_triggered'])
        result = dispatch(self._make_batch(), event='batch_analyzed')
        self.assertEqual(result['sent'], 0)
        # No channels contacted at all when no rule matches: dispatcher
        # returns early with sent=failed=skipped=0.
        self.assertEqual(result['failed'], 0)
        post.assert_not_called()

    @patch('notifications.senders.slack.requests.post')
    def test_severity_floor_skips(self, post):
        """A routing rule with min_severity=CRITICAL doesn't match a
        HIGH-severity batch."""
        post.return_value = _mock_resp(200)
        c = IncidentNotificationChannel(
            organisation=self.org, name='crit-only', kind='slack',
            is_active=True,
        )
        c.set_webhook_url('https://hooks.slack.com/x')
        c.save()
        self._catch_all_rule([c], min_severity='CRITICAL')
        result = dispatch(self._make_batch(), event='batch_analyzed')
        self.assertEqual(result['sent'], 0)
        self.assertEqual(result['failed'], 0)
        post.assert_not_called()

    @patch('notifications.senders.slack.requests.post')
    def test_sender_failure_recorded_not_raised(self, post):
        post.return_value = _mock_resp(500, 'boom')
        c = IncidentNotificationChannel(
            organisation=self.org, name='breaks', kind='slack',
            trigger_events=[], is_active=True,
        )
        c.set_webhook_url('https://hooks.slack.com/x')
        c.save()
        self._catch_all_rule([c])
        result = dispatch(self._make_batch(), event='batch_analyzed')
        self.assertEqual(result['failed'], 1)
        c.refresh_from_db()
        self.assertIn('500', c.last_error)

    def test_no_channels_no_ops(self):
        result = dispatch(self._make_batch(), event='batch_analyzed')
        self.assertEqual(result, {'sent': 0, 'failed': 0, 'skipped': 0})

    def test_none_batch_safe(self):
        self.assertEqual(
            dispatch(None, event='batch_analyzed'),
            {'sent': 0, 'failed': 0, 'skipped': 0},
        )


# ---------------------------------------------------------------------------
# CRUD API + test-send
# ---------------------------------------------------------------------------


class CrudEndpointTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='API-Org')
        self.other_org = Organisations.objects.create(name='Foreign-Org')
        self.admin = User.objects.create_user(
            username='a', email='a@t.com', password='p',
            organisation=self.org, role='admin', is_active=True,
        )
        self.user = User.objects.create_user(
            username='u', email='u@t.com', password='p',
            organisation=self.org, role='user', is_active=True,
        )
        self.client = APIClient()
        self.url = '/api/notification/incident-channels/'

    def test_list_requires_auth(self):
        self.assertIn(self.client.get(self.url).status_code, (401, 403))

    def test_authenticated_user_can_list(self):
        c = IncidentNotificationChannel(organisation=self.org, name='mine', kind='slack')
        c.set_webhook_url('https://hooks/x')
        c.save()
        # Foreign row — must not leak.
        f = IncidentNotificationChannel(organisation=self.other_org, name='foreign', kind='slack')
        f.set_webhook_url('https://hooks/f')
        f.save()
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        rows = body['results'] if isinstance(body, dict) else body
        names = {r['name'] for r in rows}
        self.assertEqual(names, {'mine'})

    def test_non_admin_cannot_create(self):
        self.client.force_authenticate(user=self.user)
        r = self.client.post(self.url, {
            'name': 'x', 'kind': 'slack',
            'webhook_url_input': 'https://hooks/x',
        }, format='json')
        self.assertIn(r.status_code, (401, 403))

    def test_admin_create_slack(self):
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(self.url, {
            'name': 'sre-slack', 'kind': 'slack',
            'webhook_url_input': 'https://hooks.slack.com/xyz',
        }, format='json')
        self.assertEqual(r.status_code, 201)
        c = IncidentNotificationChannel.objects.get()
        self.assertEqual(c.name, 'sre-slack')
        self.assertEqual(c.organisation, self.org)
        self.assertNotEqual(c.webhook_url, 'https://hooks.slack.com/xyz')   # encrypted
        self.assertEqual(c.get_webhook_url(), 'https://hooks.slack.com/xyz')

    def test_create_refuses_internal_webhook_urls(self):
        """SSRF: an org admin cannot point a channel inside the network."""
        self.client.force_authenticate(user=self.admin)
        for url in ('http://hooks.slack.com/plain-http', 'https://10.0.0.5/hook',
                    'https://169.254.169.254/latest/meta-data/', 'https://127.0.0.1:8000/admin/'):
            r = self.client.post(self.url, {'name': 'x', 'kind': 'slack', 'webhook_url_input': url}, format='json')
            self.assertEqual(r.status_code, 400, url)
            self.assertIn('webhook_url_input', r.json())
        self.assertFalse(IncidentNotificationChannel.objects.exists())

    def test_create_missing_webhook_url_fails(self):
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(self.url, {'name': 'x', 'kind': 'slack'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_create_pagerduty_needs_api_key(self):
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(self.url, {'name': 'x', 'kind': 'pagerduty'}, format='json')
        self.assertEqual(r.status_code, 400)

    @patch('notifications.senders.slack.requests.post')
    def test_test_send_action(self, post):
        post.return_value = _mock_resp(200)
        c = IncidentNotificationChannel(organisation=self.org, name='x', kind='slack')
        c.set_webhook_url('https://hooks/x')
        c.save()
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(f'{self.url}{c.pk}/test-send/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])

    def test_cross_org_delete_404(self):
        foreign = IncidentNotificationChannel(
            organisation=self.other_org, name='foreign', kind='slack',
        )
        foreign.set_webhook_url('https://x/')
        foreign.save()
        self.client.force_authenticate(user=self.admin)
        r = self.client.delete(f'{self.url}{foreign.pk}/')
        self.assertEqual(r.status_code, 404)
