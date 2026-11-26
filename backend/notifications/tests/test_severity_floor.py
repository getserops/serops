"""1.5.6: the minimum-severity floor of delivery channels and routing rules.

Before 1.5.6 the floor was ordered LOW / MEDIUM / HIGH / CRITICAL while
issues carry CRITICAL / WARNING / INFO, so a floor never blocked anything:
a "critical only" rule fired on every analysis.
"""
from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from notifications import models as nm
from notifications.models import (
    IncidentNotificationChannel,
    NotificationRoutingRule,
    severity_meets_floor,
)
from Organisations.models import Organisations

# (stored floor, top issue severities that fire, ones that do not)
TABLE = [
    ('', ['CRITICAL', 'WARNING', 'INFO', 'UNKNOWN', ''], []),
    ('INFO', ['INFO', 'WARNING', 'CRITICAL'], ['UNKNOWN', '']),
    ('LOW', ['INFO', 'WARNING', 'CRITICAL'], ['UNKNOWN', '']),
    ('WARNING', ['WARNING', 'CRITICAL'], ['INFO', 'UNKNOWN', '']),
    ('MEDIUM', ['WARNING', 'CRITICAL'], ['INFO', 'UNKNOWN', '']),
    ('CRITICAL', ['CRITICAL'], ['WARNING', 'INFO', 'UNKNOWN', '']),
    ('HIGH', ['CRITICAL'], ['WARNING', 'INFO', 'UNKNOWN', '']),
]


class SeverityFloorTableTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='floor-org')

    def _channel(self, floor):
        return IncidentNotificationChannel.objects.create(
            organisation=self.org, name=f'ch-{floor or "any"}', kind='slack',
            webhook_url='enc', is_active=True, min_severity=floor,
        )

    def _rule(self, floor):
        return NotificationRoutingRule.objects.create(
            organisation=self.org, name=f'r-{floor or "any"}', min_severity=floor,
        )

    def test_channel_floor_every_row(self):
        for floor, fire, quiet in TABLE:
            ch = self._channel(floor)
            for sev in fire:
                self.assertTrue(ch.meets_severity(sev), (floor, sev))
            for sev in quiet:
                self.assertFalse(ch.meets_severity(sev), (floor, sev))

    def test_rule_floor_every_row(self):
        for floor, fire, quiet in TABLE:
            rule = self._rule(floor)
            for sev in fire:
                self.assertTrue(rule.matches(event='batch_analyzed', severity=sev,
                                             environment='prod', service='checkout'), (floor, sev))
            for sev in quiet:
                self.assertFalse(rule.matches(event='batch_analyzed', severity=sev,
                                              environment='prod', service='checkout'), (floor, sev))

    def test_lower_case_floor_and_severity(self):
        self.assertTrue(severity_meets_floor('critical', 'warning'))
        self.assertFalse(severity_meets_floor('info', 'Warning'))

    def test_unknown_floor_is_empty_and_logged_once(self):
        nm._warned_floors.clear()
        ch = self._channel('SEVERE')
        rule = self._rule('SEVERE')
        with self.assertLogs('notifications.models', level='WARNING') as logs:
            self.assertTrue(ch.meets_severity(''))
            self.assertTrue(ch.meets_severity('INFO'))
            self.assertTrue(rule.matches(event='batch_analyzed', severity='',
                                         environment='prod', service='checkout'))
            self.assertTrue(rule.matches(event='batch_analyzed', severity='INFO',
                                         environment='prod', service='checkout'))
        # once for the channel, once for the rule; not on every call
        self.assertEqual(len(logs.records), 2)


class SeverityFloorDispatchTest(TestCase):
    """End to end through the dispatcher: a floor of Critical does not fire
    on a warning-only analysis and does fire on a critical one."""

    def setUp(self):
        self.org = Organisations.objects.create(name='floor-disp')
        self.chan = IncidentNotificationChannel.objects.create(
            organisation=self.org, name='slk', kind='slack',
            webhook_url='enc', is_active=True,
        )
        self.rule = NotificationRoutingRule.objects.create(organisation=self.org, name='all')
        self.rule.targets.set([self.chan])

    def _dispatch(self, top_severity):
        from notifications import incident_dispatcher as d
        payload = {
            'title': 'x', 'batch_id': 'b1', 'project_name': 'checkout',
            'environment': 'prod', 'top_severity': top_severity, 'issue_count': 1,
            'root_cause': '', 'recommendation': '', 'incident_url': '',
            'alert_event_id': None,
        }
        sent = []
        with patch.object(d, '_build_payload', return_value=payload), \
             patch('notifications.senders.SENDER_BY_KIND',
                   {'slack': lambda c, p: (sent.append(c.pk) or True, 'ok')}):
            class B:
                pass
            b = B()
            b.organisation = self.org
            b.batch_id = 'b1'
            d._dispatch(b, 'batch_analyzed', alert_event=None)
        return sent

    def test_rule_floor_critical(self):
        self.rule.min_severity = 'CRITICAL'
        self.rule.save()
        self.assertEqual(self._dispatch('WARNING'), [])
        self.assertEqual(self._dispatch(''), [])
        self.assertEqual(self._dispatch('CRITICAL'), [self.chan.pk])

    def test_channel_floor_critical(self):
        self.chan.min_severity = 'CRITICAL'
        self.chan.save()
        self.assertEqual(self._dispatch('WARNING'), [])
        self.assertEqual(self._dispatch('CRITICAL'), [self.chan.pk])

    def test_old_stored_floor_keeps_working(self):
        self.chan.min_severity = 'HIGH'
        self.chan.save()
        self.assertEqual(self._dispatch('WARNING'), [])
        self.assertEqual(self._dispatch('CRITICAL'), [self.chan.pk])


class SeverityFloorAPITest(TestCase):
    """The API accepts the app's values (and the old ones) for both floors."""

    def setUp(self):
        from rest_framework.test import APIClient
        from Users.models import User
        self.org = Organisations.objects.create(name='floor-api')
        admin = User.objects.create_user(
            username='floorapi', email='floorapi@example.com', password='pw',
            organisation=self.org, role='admin',
        )
        self.chan = IncidentNotificationChannel.objects.create(
            organisation=self.org, name='ch', kind='slack', webhook_url='enc', is_active=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=admin)

    def test_rule_accepts_app_values(self):
        for i, value in enumerate(['INFO', 'warning', 'CRITICAL', 'HIGH', '']):
            r = self.client.post('/api/notification/routing-rules/', data={
                'name': f'r{i}', 'min_severity': value, 'target_ids': [self.chan.pk],
                'event_types': [], 'environments': [], 'services': [], 'priority': 50,
            }, format='json')
            self.assertEqual(r.status_code, 201, (value, r.data))
            self.assertEqual(r.data['min_severity'], value.upper())

    def test_rule_refuses_unknown_value(self):
        r = self.client.post('/api/notification/routing-rules/', data={
            'name': 'bad', 'min_severity': 'SEVERE', 'target_ids': [self.chan.pk],
            'event_types': [], 'environments': [], 'services': [], 'priority': 50,
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_channel_accepts_app_values_and_refuses_unknown(self):
        url = f'/api/notification/incident-channels/{self.chan.pk}/'
        r = self.client.patch(url, data={'min_severity': 'warning'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['min_severity'], 'WARNING')
        r = self.client.patch(url, data={'min_severity': 'SEVERE'}, format='json')
        self.assertEqual(r.status_code, 400)
