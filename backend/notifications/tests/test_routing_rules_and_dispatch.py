"""PR-N phase 2 (2026-09-26): routing rules + dispatcher rework."""
from __future__ import annotations
from unittest.mock import patch

from django.test import TestCase

from notifications.models import (
    IncidentNotificationChannel,
    NotificationRoutingRule,
)
from Organisations.models import Organisations


class RoutingRuleMatchingTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='rr-org')
        self.chan = IncidentNotificationChannel.objects.create(
            organisation=self.org, name='ch', kind='slack',
            webhook_url='enc', is_active=True,
        )

    def _rule(self, **kw):
        rule = NotificationRoutingRule.objects.create(
            organisation=self.org, name=kw.pop('name', 'r'), **kw,
        )
        rule.targets.add(self.chan)
        return rule

    def test_empty_matcher_matches_everything(self):
        r = self._rule()
        self.assertTrue(r.matches(event='batch_analyzed', severity='LOW',
                                  environment='prod', service='checkout'))

    def test_inactive_never_matches(self):
        r = self._rule(is_active=False)
        self.assertFalse(r.matches(event='batch_analyzed', severity='CRITICAL',
                                   environment='prod', service='checkout'))

    def test_event_type_filter(self):
        r = self._rule(event_types=['alert_triggered'])
        self.assertFalse(r.matches(event='batch_analyzed', severity='CRITICAL',
                                   environment='prod', service='checkout'))
        self.assertTrue(r.matches(event='alert_triggered', severity='CRITICAL',
                                  environment='prod', service='checkout'))

    def test_environment_filter(self):
        r = self._rule(environments=['prod'])
        self.assertTrue(r.matches(event='batch_analyzed', severity='CRITICAL',
                                  environment='prod', service='checkout'))
        self.assertFalse(r.matches(event='batch_analyzed', severity='CRITICAL',
                                   environment='staging', service='checkout'))

    def test_service_filter(self):
        r = self._rule(services=['checkout'])
        self.assertTrue(r.matches(event='batch_analyzed', severity='CRITICAL',
                                  environment='prod', service='checkout'))
        self.assertFalse(r.matches(event='batch_analyzed', severity='CRITICAL',
                                   environment='prod', service='billing'))

    def test_severity_floor(self):
        r = self._rule(min_severity='HIGH')
        self.assertFalse(r.matches(event='batch_analyzed', severity='MEDIUM',
                                   environment='prod', service='checkout'))
        self.assertTrue(r.matches(event='batch_analyzed', severity='HIGH',
                                  environment='prod', service='checkout'))
        self.assertTrue(r.matches(event='batch_analyzed', severity='CRITICAL',
                                  environment='prod', service='checkout'))

    def test_unknown_severity_does_not_block(self):
        r = self._rule(min_severity='HIGH')
        self.assertTrue(r.matches(event='batch_analyzed', severity='',
                                  environment='prod', service='checkout'))
        self.assertTrue(r.matches(event='batch_analyzed', severity='WHATEVER',
                                  environment='prod', service='checkout'))


class DispatcherRoutingWalkTest(TestCase):
    """The dispatcher must walk rules → union of targets → dedup."""

    def setUp(self):
        self.org = Organisations.objects.create(name='disp-org')
        self.slack = IncidentNotificationChannel.objects.create(
            organisation=self.org, name='slk', kind='slack',
            webhook_url='enc', is_active=True,
        )
        self.email = IncidentNotificationChannel.objects.create(
            organisation=self.org, name='eml', kind='email',
            extra_config={'to': 'a@example.com'}, is_active=True,
        )

    def _rule(self, name, targets, **kw):
        rule = NotificationRoutingRule.objects.create(
            organisation=self.org, name=name, **kw,
        )
        rule.targets.set(targets)
        return rule

    def _run_dispatch(self, event='batch_analyzed'):
        """Patch out the batch resolution and senders; drive the dispatcher."""
        from notifications import incident_dispatcher as d

        payload = {
            'title': 'x', 'batch_id': 'b1', 'project_name': 'checkout',
            'environment': 'prod', 'top_severity': 'CRITICAL', 'issue_count': 1,
            'root_cause': '', 'recommendation': '', 'incident_url': '',
            'alert_event_id': None,
        }
        with patch.object(d, '_build_payload', return_value=payload), \
             patch('notifications.senders.SENDER_BY_KIND',
                   {'slack': lambda c, p: (True, 'ok'),
                    'email': lambda c, p: (True, 'ok'),
                    'teams': lambda c, p: (True, 'ok'),
                    'pagerduty': lambda c, p: (True, 'ok'),
                    'opsgenie': lambda c, p: (True, 'ok')}):
            # Minimal batch stub — dispatcher only reads .organisation
            class B: pass
            b = B()
            b.organisation = self.org
            b.batch_id = 'b1'
            return d._dispatch(b, event, alert_event=None)

    def test_no_rules_skips_send(self):
        r = self._run_dispatch()
        self.assertEqual(r['sent'], 0)
        self.assertEqual(r.get('failed', 0), 0)

    def test_single_rule_targets_one_channel(self):
        self._rule('r1', [self.slack])
        r = self._run_dispatch()
        self.assertEqual(r['sent'], 1)

    def test_two_rules_union_and_dedup(self):
        # Both rules match; slack is in both. Slack is contacted ONCE.
        self._rule('r1', [self.slack])
        self._rule('r2', [self.slack, self.email])
        r = self._run_dispatch()
        self.assertEqual(r['sent'], 2, r)

    def test_rule_severity_filter_excludes_channel(self):
        # LOW-severity rule against a CRITICAL payload: rule doesn't match,
        # so the channel isn't included.
        self._rule('r_lo', [self.slack], min_severity='CRITICAL')  # matches
        self._rule('r_hi', [self.email], min_severity='CRITICAL')  # matches
        r = self._run_dispatch()
        self.assertEqual(r['sent'], 2)

    def test_matching_service_only(self):
        self._rule('r_svc', [self.slack], services=['billing'])   # no match
        self._rule('r_any', [self.email])                          # matches
        r = self._run_dispatch()
        self.assertEqual(r['sent'], 1)


class RoutingRuleAPITest(TestCase):
    """Serializer/viewset smoke coverage — org scoping + validation."""

    def setUp(self):
        from rest_framework.test import APIClient
        from Users.models import User
        self.org = Organisations.objects.create(name='api-org')
        self.other_org = Organisations.objects.create(name='api-other')
        self.admin = User.objects.create_user(
            username='rrap', email='rrap@example.com', password='pw',
            organisation=self.org, role='admin',
        )
        self.chan = IncidentNotificationChannel.objects.create(
            organisation=self.org, name='ch', kind='slack',
            webhook_url='enc', is_active=True,
        )
        self.other_chan = IncidentNotificationChannel.objects.create(
            organisation=self.other_org, name='other', kind='slack',
            webhook_url='enc', is_active=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_create_lists_within_org(self):
        r = self.client.post('/api/notification/routing-rules/', data={
            'name': 'sre-crit', 'min_severity': 'CRITICAL',
            'target_ids': [self.chan.pk], 'event_types': [], 'environments': [],
            'services': [], 'priority': 50,
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)

        r2 = self.client.get('/api/notification/routing-rules/')
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(len(r2.data), 1)

    def test_cannot_target_other_org_channel(self):
        r = self.client.post('/api/notification/routing-rules/', data={
            'name': 'x', 'target_ids': [self.other_chan.pk],
            'event_types': [], 'environments': [], 'services': [],
        }, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        # error is on target_ids being outside the queryset
        self.assertIn('target_ids', r.data)

    def test_invalid_event_type_rejected(self):
        r = self.client.post('/api/notification/routing-rules/', data={
            'name': 'x', 'event_types': ['not_a_thing'],
            'environments': [], 'services': [],
        }, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn('event_types', r.data)
