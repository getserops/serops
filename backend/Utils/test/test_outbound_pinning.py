"""Resolve once, check every address, connect to a checked one (audit 2026-11-20, item 3).

The URL check resolved the name, then requests resolved it again to connect:
a DNS answer that changed in between (rebinding) reached an address no
check had seen. PinnedAdapter resolves once and dials the checked address
while the Host header, SNI and certificate check keep the name.
"""
import datetime
import http.server
import socket
import ssl
import tempfile
import threading
from unittest import mock

import requests
from django.test import SimpleTestCase, override_settings

from Utils import outbound
from Utils.outbound import BlockedOutboundURL, GuardedSession, PinnedAdapter, guarded_request, resolve_checked

REAL_GETADDRINFO = socket.getaddrinfo


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.seen_hosts.append(self.headers.get('Host'))
        if self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', '/final')
            self.end_headers()
            return
        body = b'ok'
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _serve(tls_context=None):
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
    server.seen_hosts = []
    if tls_context:
        server.socket = tls_context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _fake_dns(mapping, calls=None):
    """getaddrinfo that answers for test names (a list per name, popped in turn
    when it is a list of lists) and defers to the real resolver otherwise."""
    def fake(host, port, *args, **kwargs):
        if calls is not None:
            calls.append(host)
        answers = mapping.get(host)
        if answers is None:
            return REAL_GETADDRINFO(host, port, *args, **kwargs)
        if answers and isinstance(answers[0], list):
            answers = answers.pop(0) if len(answers) > 1 else answers[0]
        out = []
        for a in answers:
            fam = socket.AF_INET6 if ':' in a else socket.AF_INET
            out.append((fam, socket.SOCK_STREAM, 6, '', (a, port or 0) if fam == socket.AF_INET else (a, port or 0, 0, 0)))
        return out
    return fake


def _dns(mapping, calls=None):
    fake = _fake_dns(mapping, calls)
    return mock.patch.multiple(socket, getaddrinfo=fake)


@override_settings(OUTBOUND_ALLOW_PRIVATE_URLS=True)
class PinningTest(SimpleTestCase):
    def setUp(self):
        self.server = _serve()
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]

    def test_connects_to_the_checked_address_with_the_name_as_host(self):
        with _dns({'pinned.test': ['127.0.0.1']}):
            r = GuardedSession().get(f'http://pinned.test:{self.port}/', timeout=5)
        self.assertEqual(r.text, 'ok')
        self.assertEqual(self.server.seen_hosts, [f'pinned.test:{self.port}'])

    def test_a_dns_answer_that_changes_after_the_check_is_never_used(self):
        # The hop check in guarded_request, the URL check in the adapter and
        # resolve_checked see an allowed answer; any later lookup would get
        # the metadata address. The connection goes to the checked address:
        # no lookup at connect time.
        calls = []
        with _dns({'rebind.test': [['127.0.0.1'], ['127.0.0.1'], ['127.0.0.1'], ['169.254.169.254']]}, calls):
            r = guarded_request('GET', f'http://rebind.test:{self.port}/', timeout=5)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.server.seen_hosts, [f'rebind.test:{self.port}'])
        self.assertEqual(calls.count('rebind.test'), 3)

    def test_one_refused_address_refuses_the_name(self):
        with _dns({'mixed.test': ['127.0.0.1', '169.254.169.254']}):
            with self.assertRaises(BlockedOutboundURL):
                GuardedSession().get(f'http://mixed.test:{self.port}/', timeout=5)
            with self.assertRaises(BlockedOutboundURL):
                resolve_checked(f'http://mixed.test:{self.port}/')
        self.assertEqual(self.server.seen_hosts, [])

    def test_several_addresses_the_unreachable_one_is_skipped(self):
        # 127.0.0.2 has nothing listening on this port: connection refused,
        # never connected, so the next checked address is tried.
        with _dns({'multi.test': ['127.0.0.2', '127.0.0.1']}):
            r = GuardedSession().get(f'http://multi.test:{self.port}/', timeout=5)
        self.assertEqual(r.text, 'ok')

    def test_same_origin_redirect_is_followed_through_the_pinned_address(self):
        with _dns({'pinned.test': ['127.0.0.1']}):
            r = guarded_request('GET', f'http://pinned.test:{self.port}/redirect', timeout=5)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.server.seen_hosts), 2)

    def test_drop_in_get_keeps_allow_redirects_false(self):
        with _dns({'pinned.test': ['127.0.0.1']}):
            r = outbound.get(f'http://pinned.test:{self.port}/redirect', timeout=5, allow_redirects=False)
        self.assertEqual(r.status_code, 302)

    @override_settings(OUTBOUND_ALLOW_PRIVATE_URLS=False)
    def test_public_only_install_refuses_a_name_that_resolves_private(self):
        with _dns({'internal.test': ['10.0.0.5']}):
            with self.assertRaises(BlockedOutboundURL):
                outbound.get('https://internal.test/', timeout=5)


def _self_signed(name):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    cert_file = tempfile.NamedTemporaryFile('wb', suffix='.pem', delete=False)
    cert_file.write(cert.public_bytes(serialization.Encoding.PEM)); cert_file.close()
    key_file = tempfile.NamedTemporaryFile('wb', suffix='.key', delete=False)
    key_file.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption())); key_file.close()
    return cert_file.name, key_file.name


@override_settings(OUTBOUND_ALLOW_PRIVATE_URLS=True)
class PinnedTlsTest(SimpleTestCase):
    def setUp(self):
        self.cert, key = _self_signed('pinned.test')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert, key)
        self.server = _serve(context)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]

    def test_sni_and_certificate_check_use_the_name(self):
        with _dns({'pinned.test': ['127.0.0.1']}):
            r = GuardedSession().get(f'https://pinned.test:{self.port}/', timeout=5, verify=self.cert)
        self.assertEqual(r.text, 'ok')

    def test_a_certificate_for_another_name_is_refused(self):
        with _dns({'other.test': ['127.0.0.1']}):
            with self.assertRaises(requests.exceptions.SSLError):
                GuardedSession().get(f'https://other.test:{self.port}/', timeout=5, verify=self.cert)


class SsoTokenSessionTest(SimpleTestCase):
    def test_token_fetch_session_is_pinned_and_same_origin_only(self):
        from Users.services.sso import _guarded_oauth_session
        client = _guarded_oauth_session('client', 'secret', redirect_uri='https://app/cb')
        self.assertIsInstance(client.get_adapter('https://idp.example.com/token'), PinnedAdapter)
        resp = mock.Mock(url='https://idp.example.com/token', is_redirect=True,
                         headers={'location': 'https://evil.example.net/steal'})
        resp.raw = mock.Mock()
        self.assertIsNone(client.get_redirect_target(resp))

    def test_literal_metadata_address_refused(self):
        with self.assertRaises(BlockedOutboundURL):
            resolve_checked('http://169.254.169.254/latest/meta-data/')
