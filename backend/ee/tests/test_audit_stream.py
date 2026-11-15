"""Audit streaming (Enterprise, feature ``audit_streaming``): format, outbox, delivery, API."""
import datetime
import hashlib
import hmac
import json
from unittest import mock

from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from Data.audit import log_action
from Data.models import AuditLog
from Organisations.models import Organisations
from Users.models import User
from Utils import crypto
from Utils.edition import LICENSE_REQUIRED
from Utils.testing import licensed
from ee.audit_stream import events as wire
from ee.audit_stream import service, transports
from ee.models import AuditStreamDestination, AuditStreamPending
from ee.tests.stream_servers import HttpCollector, SyslogCollector, parse_octet_counted

API_URL = 'https://serops.acme.example/api'


def fake_dns(name, answers):
    """getaddrinfo answers ``answers`` for ``name`` only (the outbound check resolves literals too)."""
    import socket
    real = socket.getaddrinfo

    def getaddrinfo(host, *args, **kwargs):
        return answers if host == name else real(host, *args, **kwargs)
    return mock.patch('socket.getaddrinfo', getaddrinfo)


def entry(org, action='LOGIN', user=None, **details):
    return log_action(None, action, details, user=user, organisation=org)


@override_settings(API_URL=API_URL)
class StreamBase(APITestCase):
    def setUp(self):
        patcher = licensed('audit_streaming')
        patcher.start()
        self.addCleanup(patcher.stop)
        kick = mock.patch('ee.audit_stream.service.kick')
        self.kick = kick.start()
        self.addCleanup(kick.stop)
        self.org = Organisations.objects.create(name='Acme')
        self.admin = User.objects.create_user(username='admin', email='admin@acme.example', password='x',
                                              organisation=self.org, role='admin', is_active=True)
        self.http = HttpCollector()
        self.addCleanup(self.http.close)

    def http_destination(self, **kwargs):
        kwargs.setdefault('url', self.http.url)
        return AuditStreamDestination.objects.create(organisation=self.org, name=kwargs.pop('name', 'SIEM'),
                                                     kind='http', **kwargs)

    def syslog_destination(self, collector, **kwargs):
        return AuditStreamDestination.objects.create(
            organisation=self.org, name=kwargs.pop('name', 'syslog'), kind='syslog', host=kwargs.pop('host', '127.0.0.1'),
            port=collector.port, transport=collector.transport, **kwargs)


class EventFormatTest(StreamBase):
    def test_event(self):
        log = entry(self.org, 'TEAM_ROLE_CHANGE', user=self.admin, affected_user='bo@acme.example', role='admin')
        e = wire.event(log)
        self.assertEqual(e['schema'], 'serops.audit.v1')
        self.assertEqual(e['id'], log.pk)
        self.assertTrue(e['time'].endswith('Z'))
        self.assertEqual(e['organisation'], {'id': self.org.pk, 'name': 'Acme'})
        self.assertEqual((e['action'], e['action_label'], e['outcome']), ('TEAM_ROLE_CHANGE', 'Team Role Changed', 'success'))
        self.assertEqual(e['actor'], {'type': 'user', 'id': self.admin.pk, 'email': 'admin@acme.example'})
        self.assertEqual(e['details']['role'], 'admin')
        self.assertEqual(e['source']['host'], 'serops.acme.example')
        self.assertEqual(e['source']['product'], 'SerOps')

    def test_actor_without_user(self):
        self.assertEqual(wire.event(entry(self.org, 'SCIM_USER_CREATE', source='scim'))['actor'], {'type': 'scim'})
        self.assertEqual(wire.event(entry(self.org, 'LOGIN_FAILED'))['outcome'], 'failure')

    def test_syslog_rfc5424(self):
        e = wire.event(entry(self.org, 'LOGIN', user=self.admin))
        message = wire.syslog_message(e)
        pri_version, ts, host, app, procid, msgid, sd, body = message.decode().split(' ', 7)
        self.assertEqual((pri_version, host, app, procid, msgid, sd),
                         ('<109>1', 'serops.acme.example', 'serops', '-', 'LOGIN', '-'))  # log audit, notice
        self.assertEqual(ts, e['time'])
        self.assertEqual(json.loads(body)['id'], e['id'])
        failed = wire.syslog_message(wire.event(entry(self.org, 'LOGIN_FAILED')))
        self.assertTrue(failed.startswith(b'<108>1 '))  # warning
        self.assertEqual(parse_octet_counted(wire.octet_counted(message) + wire.octet_counted(failed)),
                         [message, failed])

    def test_http_bodies(self):
        events = [wire.event(entry(self.org, a)) for a in ('LOGIN', 'LOGOUT')]
        body, ctype = wire.http_body(events, 'json')
        self.assertEqual((ctype, [e['action'] for e in json.loads(body)]), ('application/json', ['LOGIN', 'LOGOUT']))
        body, ctype = wire.http_body(events, 'ndjson')
        self.assertEqual(ctype, 'application/x-ndjson')
        self.assertEqual([json.loads(line)['action'] for line in body.decode().splitlines()], ['LOGIN', 'LOGOUT'])
        body, _ = wire.http_body(events, 'splunk_hec')
        hec = [json.loads(line) for line in body.decode().splitlines()]
        self.assertEqual([h['event']['action'] for h in hec], ['LOGIN', 'LOGOUT'])
        self.assertEqual((hec[0]['sourcetype'], hec[0]['source']), ('serops:audit', 'serops'))
        self.assertIsInstance(hec[0]['time'], float)


class OutboxTest(StreamBase):
    def test_each_entry_is_queued_for_each_enabled_destination(self):
        a = self.http_destination(name='a')
        b = self.http_destination(name='b')
        self.http_destination(name='off', enabled=False)
        other = Organisations.objects.create(name='Other')
        AuditStreamDestination.objects.create(organisation=other, name='theirs', kind='http', url=self.http.url)
        log = entry(self.org)
        self.assertEqual(set(AuditStreamPending.objects.filter(audit_log=log).values_list('destination_id', flat=True)),
                         {a.pk, b.pk})

    def test_rolled_back_entry_is_never_queued(self):
        self.http_destination()
        try:
            with transaction.atomic():
                entry(self.org)
                raise RuntimeError('the request failed')
        except RuntimeError:
            pass
        self.assertFalse(AuditStreamPending.objects.exists())

    def test_delivery_is_kicked_after_commit(self):
        d = self.http_destination()
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            entry(self.org)
            self.kick.assert_not_called()
        self.assertEqual(len(callbacks), 1)
        self.kick.assert_called_once_with([d.pk])

    def test_nothing_is_queued_without_the_license(self):
        self.http_destination()
        with licensed():
            entry(self.org)
        self.assertFalse(AuditStreamPending.objects.exists())

    def test_retention_removes_queued_events_with_their_entry(self):
        self.http_destination()
        log = entry(self.org)
        log.delete()
        self.assertFalse(AuditStreamPending.objects.exists())

    def test_kick_survives_a_broker_outage(self):
        self.kick.stop()
        with mock.patch('ee.audit_stream.tasks.deliver_destination.delay', side_effect=ConnectionError('down')):
            service.kick([1])  # logged; the beat task delivers later
        self.kick.start()


class HttpDeliveryTest(StreamBase):
    def test_delivered_in_order_with_header_and_signature(self):
        d = self.http_destination(auth_header_name='Authorization',
                                  auth_header_value_encrypted=crypto.encrypt('Splunk 1234-token'),
                                  signing_secret_encrypted=crypto.encrypt('whsec'))
        logs = [entry(self.org, a) for a in ('LOGIN', 'SETTINGS_UPDATE', 'LOGOUT')]
        self.assertEqual(service.deliver(d.pk), 3)
        [request] = self.http.requests
        self.assertEqual([e['id'] for e in json.loads(request['body'])], [log.pk for log in logs])
        self.assertEqual(request['headers']['Authorization'], 'Splunk 1234-token')
        ts = request['headers']['X-SerOps-Timestamp']
        expected = 'sha256=' + hmac.new(b'whsec', ts.encode() + b'.' + request['body'], hashlib.sha256).hexdigest()
        self.assertEqual(request['headers']['X-SerOps-Signature'], expected)
        self.assertFalse(AuditStreamPending.objects.exists())
        d.refresh_from_db()
        self.assertEqual((d.delivered_count, d.last_error), (3, ''))
        self.assertIsNotNone(d.last_success_at)

    def test_batches_keep_order(self):
        d = self.http_destination(http_format='ndjson')
        with mock.patch.object(service, 'BATCH', 4):
            ids = [entry(self.org).pk for _ in range(10)]
            self.assertEqual(service.deliver(d.pk), 10)
        sent = [json.loads(line)['id'] for r in self.http.requests for line in r['body'].decode().splitlines()]
        self.assertEqual((sent, len(self.http.requests)), (ids, 3))

    def test_failure_keeps_the_events_and_backs_off(self):
        d = self.http_destination()
        log = entry(self.org)
        self.http.answer(503, 503)
        now = timezone.now()
        self.assertEqual(service.deliver(d.pk, now=now), 0)
        pending = AuditStreamPending.objects.get(audit_log=log)
        self.assertEqual(pending.attempts, 1)
        self.assertEqual(pending.next_attempt_at, now + datetime.timedelta(seconds=30))
        d.refresh_from_db()
        self.assertEqual(d.last_error, 'The destination answered HTTP 503')
        # Not due yet: nothing is sent.
        self.assertEqual(service.deliver(d.pk, now=now + datetime.timedelta(seconds=10)), 0)
        self.assertEqual(len(self.http.requests), 1)
        # Second failure doubles the wait, then it goes through.
        service.deliver(d.pk, now=now + datetime.timedelta(seconds=31))
        pending.refresh_from_db()
        self.assertEqual(pending.attempts, 2)
        self.assertEqual(service.deliver(d.pk, now=now + datetime.timedelta(seconds=200)), 1)
        self.assertFalse(AuditStreamPending.objects.exists())
        d.refresh_from_db()
        self.assertEqual(d.last_error, '')

    def test_https_with_the_collectors_ca(self):
        collector = HttpCollector(tls=True)
        self.addCleanup(collector.close)
        trusted = self.http_destination(name='trusted', url=collector.url, ca_certificate=collector.cert_pem)
        untrusted = self.http_destination(name='untrusted', url=collector.url)
        entry(self.org)
        self.assertEqual(service.deliver(trusted.pk), 1)
        self.assertEqual(len(collector.requests), 1)
        self.assertEqual(service.deliver(untrusted.pk), 0)
        untrusted.refresh_from_db()
        self.assertEqual(untrusted.last_error, 'TLS certificate of the destination not trusted')

    def test_backoff_is_capped(self):
        self.assertEqual([service.backoff(n) for n in (1, 2, 3, 20)], [30, 60, 120, 3600])

    def test_unreachable(self):
        d = self.http_destination(url='http://127.0.0.1:9/nothing')
        entry(self.org)
        service.deliver(d.pk)
        d.refresh_from_db()
        self.assertIn('Could not reach the destination', d.last_error)

    def test_events_wait_without_the_license_and_go_out_with_it(self):
        d = self.http_destination()
        entry(self.org)
        with licensed():
            self.assertEqual(service.deliver(d.pk), 0)
            self.assertEqual(service.deliver_due(), 0)
        self.assertEqual(AuditStreamPending.objects.count(), 1)
        self.assertEqual(service.deliver_due(), 1)

    def test_deliver_due_takes_every_destination(self):
        self.http_destination(name='a')
        self.http_destination(name='b')
        entry(self.org)
        self.assertEqual(service.deliver_due(), 2)

    def test_cloud_metadata_is_refused_at_send_time(self):
        d = self.http_destination(url='http://169.254.169.254/latest/meta-data/')
        entry(self.org)
        service.deliver(d.pk)
        d.refresh_from_db()
        self.assertIn('outbound policy', d.last_error)

    @override_settings(OUTBOUND_ALLOW_PRIVATE_URLS=False)
    def test_private_addresses_refused_when_the_install_says_so(self):
        d = self.http_destination()
        entry(self.org)
        service.deliver(d.pk)
        d.refresh_from_db()
        self.assertIn('outbound policy', d.last_error)
        self.assertEqual(self.http.requests, [])


class SyslogDeliveryTest(StreamBase):
    def deliver_to(self, collector, **kwargs):
        self.addCleanup(collector.close)
        d = self.syslog_destination(collector, **kwargs)
        logs = [entry(self.org, a, user=self.admin) for a in ('LOGIN', 'LOGIN_FAILED')]
        self.assertEqual(service.deliver(d.pk), 2, AuditStreamDestination.objects.get(pk=d.pk).last_error)
        messages = collector.messages(expected=2)
        self.assertEqual(len(messages), 2)
        bodies = [json.loads(m.split(b' ', 7)[7]) for m in messages]
        self.assertEqual([b['id'] for b in bodies], [log.pk for log in logs])
        self.assertTrue(messages[0].startswith(b'<109>1 '))
        self.assertTrue(messages[1].startswith(b'<108>1 '))
        return d

    def test_tcp(self):
        self.deliver_to(SyslogCollector('tcp'))

    def test_udp(self):
        self.deliver_to(SyslogCollector('udp'))

    def test_tls_with_the_collectors_ca(self):
        collector = SyslogCollector('tls')
        self.deliver_to(collector, host='localhost', ca_certificate=collector.cert_pem)

    def test_tls_refuses_an_untrusted_certificate(self):
        collector = SyslogCollector('tls')
        self.addCleanup(collector.close)
        d = self.syslog_destination(collector, host='localhost')  # system CAs only
        entry(self.org)
        self.assertEqual(service.deliver(d.pk), 0)
        d.refresh_from_db()
        self.assertIn('TLS certificate not trusted', d.last_error)
        self.assertEqual(AuditStreamPending.objects.count(), 1)

    def test_tls_refuses_a_certificate_from_another_ca(self):
        from ee.tests.stream_servers import self_signed
        collector = SyslogCollector('tls')
        self.addCleanup(collector.close)
        other_ca, _ = self_signed('other.example')
        d = self.syslog_destination(collector, host='localhost', ca_certificate=other_ca)
        entry(self.org)
        service.deliver(d.pk)
        d.refresh_from_db()
        self.assertIn('TLS certificate not trusted', d.last_error)

    def test_falls_back_to_the_next_address(self):
        # CI runners resolve "localhost" to ::1 first; the collector listens on IPv4 only.
        import socket
        collector = SyslogCollector('tcp')
        self.addCleanup(collector.close)
        d = self.syslog_destination(collector, host='collector.internal')
        answers = [(socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('::1', collector.port, 0, 0)),
                   (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', collector.port))]
        entry(self.org)
        with fake_dns('collector.internal', answers):
            self.assertEqual(service.deliver(d.pk), 1, AuditStreamDestination.objects.get(pk=d.pk).last_error)
        self.assertEqual(len(collector.messages(expected=1)), 1)

    def test_skips_addresses_the_policy_refuses(self):
        import socket
        collector = SyslogCollector('tcp')
        self.addCleanup(collector.close)
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('169.254.169.254', collector.port)),
                   (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', collector.port))]
        with fake_dns('mixed.internal', answers):
            self.assertEqual([a[3][0] for a in transports.resolve('mixed.internal', collector.port, 'tcp')],
                             ['127.0.0.1'])

    def test_metadata_address_refused(self):
        with self.assertRaisesMessage(transports.DeliveryError, 'outbound policy'):
            transports.resolve('169.254.169.254', 514, 'udp')


class AuditStreamApiTest(StreamBase):
    url = '/api/ee/audit-streams/'

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.admin)

    def test_create_list_and_secrets_are_write_only(self):
        r = self.client.post(self.url, {'name': 'Splunk', 'kind': 'http', 'url': self.http.url, 'http_format': 'splunk_hec',
                                        'auth_header_name': 'Authorization', 'auth_header_value': 'Splunk s3cr3t',
                                        'signing_secret': 'whsec'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data['auth_header_configured'] and r.data['signing_secret_configured'])
        listed = self.client.get(self.url).data
        self.assertTrue(listed['licensed'])
        self.assertNotIn('s3cr3t', json.dumps(listed))
        self.assertNotIn('whsec', json.dumps(listed))
        d = AuditStreamDestination.objects.get()
        self.assertEqual(crypto.decrypt(d.auth_header_value_encrypted), 'Splunk s3cr3t')
        self.assertTrue(AuditLog.objects.filter(action='AUDIT_STREAM_CREATE', details__name='Splunk').exists())

    def test_syslog_defaults_and_validation(self):
        r = self.client.post(self.url, {'name': 'SIEM', 'kind': 'syslog', 'host': 'siem.acme.example'}, format='json')
        self.assertEqual((r.status_code, r.data['transport'], r.data['port']), (201, 'tls', 6514), r.data)
        for bad in ({'host': 'x y'}, {'port': 70000}, {'transport': 'smoke'}, {'ca_certificate': 'not a pem'}):
            r = self.client.post(self.url, {'name': 'bad', 'kind': 'syslog', 'host': 'siem.acme.example', **bad},
                                 format='json')
            self.assertEqual(r.status_code, 400, bad)

    def test_url_rules(self):
        for url, ok in [('http://169.254.169.254/', False), ('ftp://siem.example/', False),
                        ('https://user:pw@siem.example/', False), ('http://8.8.8.8/ingest', False),
                        (self.http.url, True), ('https://8.8.8.8/ingest', True)]:
            r = self.client.post(self.url, {'name': url[:90], 'kind': 'http', 'url': url}, format='json')
            self.assertEqual(r.status_code == 201, ok, (url, r.data))

    def test_put_keeps_clears_and_sets_secrets(self):
        d = self.http_destination(auth_header_name='Authorization', auth_header_value_encrypted=crypto.encrypt('a'))
        r = self.client.put(f'{self.url}{d.pk}/', {'name': 'Renamed'}, format='json')
        self.assertTrue(r.data['auth_header_configured'])
        r = self.client.put(f'{self.url}{d.pk}/', {'auth_header_value': ''}, format='json')
        self.assertFalse(r.data['auth_header_configured'])
        self.assertTrue(AuditLog.objects.filter(action='AUDIT_STREAM_UPDATE', details__changed=['auth_header_value'])
                        .exists())

    def test_turning_off_is_delivered_before_it_stops(self):
        d = self.http_destination()
        r = self.client.put(f'{self.url}{d.pk}/', {'enabled': False}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        sent = [e for req in self.http.requests for e in json.loads(req['body'])]
        self.assertEqual([(e['action'], e['details']['enabled']) for e in sent], [('AUDIT_STREAM_UPDATE', False)])
        entry(self.org)
        self.assertFalse(AuditStreamPending.objects.exists())

    def test_removal_is_delivered_before_it_goes(self):
        d = self.http_destination()
        self.assertEqual(self.client.delete(f'{self.url}{d.pk}/').status_code, 204)
        sent = [e['action'] for req in self.http.requests for e in json.loads(req['body'])]
        self.assertEqual(sent, ['AUDIT_STREAM_DELETE'])
        self.assertFalse(AuditStreamDestination.objects.exists())

    def test_test_event(self):
        d = self.http_destination()
        self.assertEqual(self.client.post(f'{self.url}{d.pk}/test/').data, {'ok': True})
        [event] = json.loads(self.http.requests[0]['body'])
        self.assertEqual((event['action'], event['id']), ('AUDIT_STREAM_TEST', None))
        self.assertFalse(AuditLog.objects.filter(action='AUDIT_STREAM_TEST').exists())
        self.http.answer(401)
        self.assertEqual(self.client.post(f'{self.url}{d.pk}/test/').data,
                         {'ok': False, 'error': 'The destination answered HTTP 401'})

    def test_only_admins_change_destinations(self):
        member = User.objects.create_user(username='m', email='m@acme.example', password='x', organisation=self.org,
                                          role='user', is_active=True)
        d = self.http_destination()
        self.client.force_authenticate(member)
        self.assertEqual(self.client.post(self.url, {'name': 'x', 'kind': 'http', 'url': self.http.url},
                                          format='json').status_code, 403)
        self.assertEqual(self.client.delete(f'{self.url}{d.pk}/').status_code, 403)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_other_organisations_destinations(self):
        other = Organisations.objects.create(name='Other')
        theirs = AuditStreamDestination.objects.create(organisation=other, name='theirs', kind='http', url=self.http.url)
        self.assertEqual(self.client.get(self.url).data['destinations'], [])
        for method in ('get', 'put', 'delete'):
            self.assertEqual(getattr(self.client, method)(f'{self.url}{theirs.pk}/', {}, format='json').status_code, 404)
        self.assertEqual(self.client.post(f'{self.url}{theirs.pk}/test/').status_code, 404)

    def test_without_the_license(self):
        d = self.http_destination()
        with licensed():
            self.assertFalse(self.client.get(self.url).data['licensed'])
            r = self.client.post(self.url, {'name': 'x', 'kind': 'http', 'url': self.http.url}, format='json')
            self.assertEqual((r.status_code, r.data['code']), (403, LICENSE_REQUIRED))
            self.assertEqual(self.client.put(f'{self.url}{d.pk}/', {'name': 'y'}, format='json').status_code, 403)
            self.assertEqual(self.client.post(f'{self.url}{d.pk}/test/').status_code, 403)
            # Turning off and removing always work.
            self.assertEqual(self.client.put(f'{self.url}{d.pk}/', {'enabled': False}, format='json').status_code, 200)
            self.assertEqual(self.client.put(f'{self.url}{d.pk}/', {'enabled': True}, format='json').status_code, 403)
            self.assertEqual(self.client.delete(f'{self.url}{d.pk}/').status_code, 204)

    def test_status_shows_the_queue(self):
        d = self.http_destination()
        log = entry(self.org)
        row = self.client.get(f'{self.url}{d.pk}/').data
        self.assertEqual((row['pending'], row['oldest_pending_at']), (1, log.created_at.isoformat()))


class WiringTest(TestCase):
    def test_routes(self):
        from django.urls import resolve

        from ee.audit_stream import views
        self.assertIs(resolve('/api/ee/audit-streams/').func.view_class, views.AuditStreamsView)
        self.assertIs(resolve('/api/ee/audit-streams/3/test/').func.view_class, views.AuditStreamTestView)

    def test_receiver_is_connected(self):
        from django.db.models.signals import post_save
        self.assertTrue(any(r[0][0] == 'ee.audit_stream' for r in post_save.receivers))

    def test_beat_and_routes(self):
        from api.celery import app
        self.assertEqual(app.conf.beat_schedule['audit-stream-deliver-due']['task'], 'ee.audit_stream.tasks.deliver_due')
        self.assertIn('ee.audit_stream.tasks.deliver_destination', app.tasks)

    def test_secrets_are_rotated(self):
        from Data.management.commands.rotate_secrets import _enterprise_fields
        self.assertIn(('ee.AuditStreamDestination', 'auth_header_value_encrypted'), _enterprise_fields())
        self.assertIn(('ee.AuditStreamDestination', 'signing_secret_encrypted'), _enterprise_fields())

    def test_broken_install_fails_startup_loudly(self):
        import builtins
        import sys

        from django.core.exceptions import ImproperlyConfigured

        from ee.apps import load_audit_streaming
        real_import = builtins.__import__

        def broken(name, globals=None, locals=None, fromlist=(), level=0):
            if name == 'ee.audit_stream' and fromlist and 'transports' in fromlist:
                raise ImportError("cannot import name 'transports'")
            return real_import(name, globals, locals, fromlist, level)

        with mock.patch.dict(sys.modules), mock.patch('builtins.__import__', broken):
            with self.assertRaisesMessage(ImproperlyConfigured, 'audit streaming cannot load'):
                load_audit_streaming()
