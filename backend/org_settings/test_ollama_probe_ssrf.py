"""The Ollama probe (POST /api/settings/ai/ollama/probe/) fetches a URL an
admin types, so it is the one place CodeQL flags as full SSRF.

What makes it safe, proved here:
* cloud metadata and every link-local address are refused before any request;
* redirects are not followed, so an allowed host cannot bounce the probe
  to a metadata address;
* localhost and private addresses stay allowed on purpose: Ollama usually
  runs at http://localhost:11434 or in the same cluster
  (docs/src/security/data-protection.md, "Outbound requests").
"""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from Organisations.models import Organisations

URL = '/api/settings/ai/ollama/probe/'

REFUSED = [
    'http://169.254.169.254/latest/meta-data/',   # AWS, Azure, GCP metadata
    'http://169.254.170.2/v2/credentials',        # ECS task credentials
    'http://169.254.1.1:11434',                   # any link-local address
    'http://[::ffff:169.254.169.254]/',           # the same, IPv4-mapped
    'http://[fe80::1]:11434',                     # IPv6 link-local
    'http://[fd00:ec2::254]/',                    # AWS IPv6 metadata
    'http://100.100.100.200/',                    # Alibaba metadata
    'http://metadata.google.internal/',           # GCP metadata alias
    'file:///etc/passwd',                         # not http(s)
]


class _Server:
    """A local HTTP server that records the paths it is asked for."""

    def __init__(self, handler_body):
        hits = self.hits = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                handler_body(self)

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.httpd.server_port}'
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class OllamaProbeSsrfTest(TestCase):

    def setUp(self):
        org = Organisations.objects.create(name='Probe Org')
        user = get_user_model().objects.create_user(
            username='probe-admin', email='probe@test.com', password='testpass123',
            organisation=org, role='admin')
        self.client = APIClient()
        self.client.force_authenticate(user=user)

    def test_metadata_and_link_local_are_refused_before_any_request(self):
        with patch('requests.get') as get:
            for url in REFUSED:
                with self.subTest(url=url):
                    r = self.client.post(URL, {'base_url': url}, format='json')
                    self.assertEqual(r.status_code, 400, r.data)
                    self.assertFalse(r.data['reachable'])
            get.assert_not_called()

    def test_localhost_is_allowed_and_redirects_are_off(self):
        with patch('requests.get') as get:
            get.return_value.json.return_value = {'models': [{'name': 'llama3'}]}
            r = self.client.post(URL, {'base_url': 'http://localhost:11434/v1'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['models'], ['llama3'])
        get.assert_called_once()
        self.assertEqual(get.call_args.args[0], 'http://localhost:11434/v1/models')
        self.assertIs(get.call_args.kwargs.get('allow_redirects'), False)

    def test_a_redirect_is_not_followed(self):
        # The allowed host answers 302 to a second server; the probe must
        # never reach the second one (in production, a metadata address).
        target = _Server(lambda h: (h.send_response(200), h.end_headers(), h.wfile.write(b'{"models": []}')))
        self.addCleanup(target.close)

        def bounce(h):
            h.send_response(302)
            h.send_header('Location', target.url + '/latest/meta-data/')
            h.end_headers()

        allowed = _Server(bounce)
        self.addCleanup(allowed.close)

        r = self.client.post(URL, {'base_url': allowed.url}, format='json')
        self.assertEqual(allowed.hits, ['/models'])
        self.assertEqual(target.hits, [])
        self.assertFalse(r.data['reachable'])

    def test_only_settings_managers_can_probe(self):
        viewer = get_user_model().objects.create_user(
            username='probe-viewer', email='viewer@test.com', password='testpass123',
            organisation=Organisations.objects.get(name='Probe Org'), role='viewer')
        client = APIClient()
        client.force_authenticate(user=viewer)
        with patch('requests.get') as get:
            r = client.post(URL, {'base_url': 'http://localhost:11434'}, format='json')
        self.assertEqual(r.status_code, 403)
        get.assert_not_called()
