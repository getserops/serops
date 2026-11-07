"""Outbound URL policy and the guarded HTTP helpers.

Security review 2026-11, finding 3: user-configured URLs were checked once,
on save, the metadata check matched exact strings only, and requests then
followed redirects anywhere.
"""

import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from Utils.outbound import BlockedOutboundURL, GuardedSession, guarded_request
from Utils.url_validator import validate_internal_url_no_metadata, validate_outbound_url


def _resolves_to(ip):
    return patch('Utils.url_validator.socket.getaddrinfo',
                 return_value=[(socket.AF_INET, None, None, '', (ip, 0))])


class MetadataGuardTest(SimpleTestCase):

    def test_the_whole_link_local_range_is_refused(self):
        # ECS task metadata, not on the old exact-match list.
        with self.assertRaises(ValueError):
            validate_internal_url_no_metadata('http://169.254.170.2/v2/credentials')

    def test_an_ipv4_mapped_metadata_address_is_refused(self):
        with self.assertRaises(ValueError):
            validate_internal_url_no_metadata('http://[::ffff:169.254.169.254]/latest/meta-data/')

    def test_a_hostname_resolving_into_link_local_is_refused(self):
        with _resolves_to('169.254.170.2'), self.assertRaises(ValueError):
            validate_internal_url_no_metadata('http://innocent.example.com/')

    def test_private_and_loopback_addresses_stay_allowed_by_default(self):
        for url in ('http://10.0.0.5:3100', 'http://localhost:11434/v1', 'http://loki.monitoring:3100'):
            with _resolves_to('10.0.0.5'):
                self.assertEqual(validate_outbound_url(url), url)

    @override_settings(OUTBOUND_ALLOW_PRIVATE_URLS=False)
    def test_an_install_can_refuse_private_addresses(self):
        with self.assertRaises(ValueError):
            validate_outbound_url('http://10.0.0.5:3100')
        with _resolves_to('192.168.1.10'), self.assertRaises(ValueError):
            validate_outbound_url('http://loki.monitoring:3100')
        with _resolves_to('93.184.216.34'):
            validate_outbound_url('https://logs.example.com')


def _redirect_response(location, status=302):
    response = MagicMock(status_code=status)
    response.headers = {'Location': location}
    return response


class GuardedRequestTest(SimpleTestCase):

    @patch('Utils.outbound.requests.request')
    def test_a_metadata_url_is_refused_before_any_request(self, request):
        with self.assertRaises(BlockedOutboundURL):
            guarded_request('GET', 'http://169.254.169.254/latest/meta-data/')
        request.assert_not_called()

    @patch('Utils.outbound.requests.request')
    def test_a_redirect_to_another_host_is_not_followed(self, request):
        request.return_value = _redirect_response('http://169.254.169.254/latest/meta-data/')

        response = guarded_request('GET', 'http://gitlab.internal/api/v4/projects/1')

        self.assertEqual(response.status_code, 302)
        request.assert_called_once()
        self.assertFalse(request.call_args.kwargs['allow_redirects'])

    @patch('Utils.outbound.requests.request')
    def test_a_same_host_redirect_is_followed(self, request):
        final = MagicMock(status_code=200)
        request.side_effect = [_redirect_response('/api/v4/projects/2'), final]

        response = guarded_request('GET', 'http://gitlab.internal/api/v4/projects/1')

        self.assertIs(response, final)
        self.assertEqual(request.call_args.kwargs['url'], 'http://gitlab.internal/api/v4/projects/2')


class _RedirectToMetadata(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(302)
        self.send_header('Location', 'http://169.254.169.254/latest/meta-data/')
        self.end_headers()

    def log_message(self, *args):
        pass


class GuardedSessionTest(SimpleTestCase):

    def test_a_session_refuses_a_metadata_url(self):
        with self.assertRaises(BlockedOutboundURL):
            GuardedSession().get('http://169.254.169.254/latest/meta-data/', timeout=1)

    def test_a_session_does_not_follow_a_redirect_to_the_metadata_endpoint(self):
        server = HTTPServer(('127.0.0.1', 0), _RedirectToMetadata)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            response = GuardedSession().get(f'http://127.0.0.1:{server.server_port}/', timeout=5)
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.history, [])
