"""PR-N (2026-09-21): email sender + backfill migration sanity."""
from __future__ import annotations

from django.test import TestCase, override_settings

from notifications.models import IncidentNotificationChannel
from notifications.senders import SENDER_BY_KIND
from Organisations.models import Organisations


class SenderRegistryTest(TestCase):
    def test_email_sender_registered(self):
        self.assertIn('email', SENDER_BY_KIND)

    def test_all_kind_choices_have_a_sender(self):
        kinds = {k for k, _ in IncidentNotificationChannel.KIND_CHOICES}
        registered = set(SENDER_BY_KIND.keys())
        self.assertEqual(kinds, registered)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailSenderTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='email-org')

    def _make_channel(self, extra_config):
        return IncidentNotificationChannel.objects.create(
            organisation=self.org, name='ops@example.com',
            kind='email', extra_config=extra_config,
        )

    def _payload(self):
        return {
            'batch_id': 'bg-1', 'project_name': 'checkout', 'environment': 'prod',
            'title': 'Redis outage', 'top_severity': 'CRITICAL', 'issue_count': 2,
            'issues': [
                {'severity': 'CRITICAL', 'description': 'Redis unreachable'},
                {'severity': 'CRITICAL', 'description': 'Session store down'},
            ],
        }

    def test_send_with_string_to(self):
        from notifications.senders import send_email
        from django.core import mail

        channel = self._make_channel({'to': 'ops@example.com'})
        ok, msg = send_email(channel, self._payload())
        self.assertTrue(ok, msg)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('CRITICAL', mail.outbox[0].subject)
        self.assertIn('checkout', mail.outbox[0].subject)
        self.assertIn('Redis unreachable', mail.outbox[0].body)

    def test_send_with_list_to(self):
        from notifications.senders import send_email
        from django.core import mail

        channel = self._make_channel({'to': ['a@ex.com', 'b@ex.com']})
        ok, _msg = send_email(channel, self._payload())
        self.assertTrue(ok)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['a@ex.com', 'b@ex.com'])

    def test_send_with_comma_separated_to(self):
        from notifications.senders import send_email
        from django.core import mail

        channel = self._make_channel({'to': 'a@ex.com, b@ex.com'})
        ok, _msg = send_email(channel, self._payload())
        self.assertTrue(ok)
        self.assertEqual(mail.outbox[0].to, ['a@ex.com', 'b@ex.com'])

    def test_empty_to_is_a_soft_failure(self):
        from notifications.senders import send_email

        channel = self._make_channel({})
        ok, msg = send_email(channel, self._payload())
        self.assertFalse(ok)
        self.assertIn('empty', msg.lower())

    def test_reply_to_override(self):
        from notifications.senders import send_email
        from django.core import mail

        channel = self._make_channel({'to': 'ops@ex.com', 'reply_to': 'oncall@ex.com'})
        ok, _msg = send_email(channel, self._payload())
        self.assertTrue(ok)
        self.assertEqual(mail.outbox[0].reply_to, ['oncall@ex.com'])
