"""Live: audit streaming into a real Vector collector (skipped unless configured).

    SEROPS_TEST_VECTOR_HOST=vector          collector host (syslog TLS 6514, TCP 514, HTTPS 8443)
    SEROPS_TEST_VECTOR_CA=/vector/tls/cert.pem   CA (or self-signed cert) of the collector
    SEROPS_TEST_VECTOR_OUT=/vector/out      directory Vector's file sink writes to

Destinations are created through the API (validation included), events
are recorded with log_action and delivered by the service, and the test
reads back what Vector parsed: RFC 5424 fields for syslog, the JSON body
and headers for HTTPS.
"""
import glob
import json
import os
import time
import unittest

from django.test import override_settings
from rest_framework.test import APITestCase

from Data.audit import log_action
from Organisations.models import Organisations
from Users.models import User
from Utils.testing import licensed
from ee.audit_stream import service
from ee.models import AuditStreamDestination

HOST = os.environ.get('SEROPS_TEST_VECTOR_HOST')
CA = os.environ.get('SEROPS_TEST_VECTOR_CA')
OUT = os.environ.get('SEROPS_TEST_VECTOR_OUT')


def collected(pattern, predicate, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for path in glob.glob(os.path.join(OUT, pattern)):
            with open(path) as f:
                for line in f:
                    record = json.loads(line)
                    if predicate(record):
                        return record
        time.sleep(0.5)
    return None


@unittest.skipUnless(HOST and CA and OUT, 'SEROPS_TEST_VECTOR_* not set')
@override_settings(API_URL='https://serops.acme.example/api')
class VectorLiveTest(APITestCase):
    def setUp(self):
        patcher = licensed('audit_streaming')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organisations.objects.create(name=f'Vector {time.time_ns()}')
        self.admin = User.objects.create_user(username=f'a{time.time_ns()}'[:20], email=f'{time.time_ns()}@acme.example',
                                              password='x', organisation=self.org, role='admin', is_active=True)
        self.client.force_authenticate(self.admin)
        with open(CA) as f:
            self.ca = f.read()

    def mine(self, message, entry):
        """This run's event: ids restart with each test database, organisation names do not."""
        return f'"id":{entry.pk},' in message and json.dumps(self.org.name) in message

    def add(self, **body):
        r = self.client.post('/api/ee/audit-streams/', body, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return AuditStreamDestination.objects.get(pk=r.data['id'])

    def record(self, action='LOGIN_FAILED'):
        return log_action(None, action, {'email': 'ana@acme.example'}, organisation=self.org)

    def test_syslog_over_tls(self):
        d = self.add(name='tls', kind='syslog', host=HOST, port=6514, transport='tls', ca_certificate=self.ca)
        entry = self.record()
        # Two: the destination's own creation (an audit event too), then this one.
        self.assertEqual(service.deliver(d.pk), 2, AuditStreamDestination.objects.get(pk=d.pk).last_error)
        got = collected('syslog-*.log', lambda r: self.mine(r.get('message', ''), entry))
        self.assertIsNotNone(got, 'Vector did not receive the event')
        self.assertEqual((got['appname'], got['msgid'], got['hostname'], got['severity'], got['facility']),
                         ('serops', 'LOGIN_FAILED', 'serops.acme.example', 'warning', 'audit'))
        self.assertEqual(json.loads(got['message'])['action'], 'LOGIN_FAILED')  # plain JSON, no BOM
        self.assertTrue(self.client.post(f'/api/ee/audit-streams/{d.pk}/test/').data['ok'])

    def test_syslog_over_tls_refuses_without_the_ca(self):
        d = self.add(name='tls-no-ca', kind='syslog', host=HOST, port=6514, transport='tls')
        self.record()
        self.assertEqual(service.deliver(d.pk), 0)
        d.refresh_from_db()
        self.assertIn('TLS certificate not trusted', d.last_error)

    def test_syslog_over_tcp(self):
        d = self.add(name='tcp', kind='syslog', host=HOST, port=514, transport='tcp')
        entry = self.record('LOGIN')
        # Two: the destination's own creation (an audit event too), then this one.
        self.assertEqual(service.deliver(d.pk), 2, AuditStreamDestination.objects.get(pk=d.pk).last_error)
        got = collected('syslog-*.log', lambda r: self.mine(r.get('message', ''), entry))
        self.assertIsNotNone(got)
        self.assertEqual((got['msgid'], got['severity']), ('LOGIN', 'notice'))

    def test_https_json(self):
        d = self.add(name='https', kind='http', url=f'https://{HOST}:8443/ingest', http_format='json',
                     auth_header_name='Authorization', auth_header_value='Bearer live-test', signing_secret='whsec',
                     ca_certificate=self.ca)
        entry = self.record('LOGIN')
        # Two: the destination's own creation (an audit event too), then this one.
        self.assertEqual(service.deliver(d.pk), 2, AuditStreamDestination.objects.get(pk=d.pk).last_error)
        got = collected('http_server-*.log', lambda r: r.get('id') == entry.pk
                        and r.get('organisation', {}).get('name') == self.org.name)
        self.assertIsNotNone(got)
        self.assertEqual((got['schema'], got['action']), ('serops.audit.v1', 'LOGIN'))
        self.assertEqual(got['Authorization'], 'Bearer live-test')
        self.assertTrue(got['X-SerOps-Signature'].startswith('sha256='))
