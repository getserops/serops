"""Refused requests land in the organisation's audit log, once per window."""
from unittest import mock

from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.test import APIClient

from Data.audit import get_client_ip
from Data.models import AuditLog
from Organisations.models import Organisations
from Users.models import User


class AuditDeniedTest(TestCase):
    def setUp(self):
        cache.clear()
        self.org = Organisations.objects.create(name='Audit Org')
        self.viewer = User.objects.create_user(
            username='v', email='viewer@audit.example', password='x', organisation=self.org, role='viewer')
        self.client = APIClient()
        self.client.force_authenticate(user=self.viewer)

    def denied(self):
        return AuditLog.objects.filter(organisation=self.org, action='ACCESS_DENIED')

    def test_refusal_is_audited_with_what_was_missing(self):
        self.assertEqual(self.client.get('/api/organisation/team/').status_code, 403)
        entry = self.denied().get()
        self.assertEqual(entry.user, self.viewer)
        self.assertEqual(entry.details, {
            'permission': 'team.manage', 'role': 'viewer', 'method': 'GET', 'path': '/api/organisation/team/'})

    def test_repeats_are_recorded_once_per_window(self):
        for _ in range(5):
            self.client.get('/api/organisation/team/')
        self.client.post('/api/projects/', {}, format='json')
        self.assertEqual(self.denied().count(), 2)

    def test_allowed_requests_are_not_audited(self):
        self.assertEqual(self.client.get('/api/projects/').status_code, 200)
        self.assertFalse(self.denied().exists())

    def test_audit_failure_still_answers_403(self):
        with mock.patch('Data.audit.log_action', side_effect=RuntimeError('db down')):
            self.assertEqual(self.client.get('/api/organisation/team/').status_code, 403)


class ClientIpTest(TestCase):
    def request(self, xff=None):
        meta = {'REMOTE_ADDR': '10.0.0.2'}
        if xff:
            meta['HTTP_X_FORWARDED_FOR'] = xff
        return RequestFactory().get('/', **meta)

    @override_settings(REST_FRAMEWORK={'NUM_PROXIES': 1})
    def test_client_written_entries_are_ignored(self):
        self.assertEqual(get_client_ip(self.request('6.6.6.6, 203.0.113.9')), '203.0.113.9')

    @override_settings(REST_FRAMEWORK={'NUM_PROXIES': 0})
    def test_no_trusted_proxy_uses_the_socket(self):
        self.assertEqual(get_client_ip(self.request('6.6.6.6')), '10.0.0.2')

    @override_settings(REST_FRAMEWORK={'NUM_PROXIES': 1})
    def test_no_header_uses_the_socket(self):
        self.assertEqual(get_client_ip(self.request()), '10.0.0.2')
