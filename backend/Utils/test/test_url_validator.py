"""Tests for the SSRF guard used by the webhook-test endpoint.

We can't easily exercise the DNS-resolution path in a hermetic test
run (no network in CI), so those cases use ``socket.getaddrinfo``
mocks. The IP-in-URL path runs offline and is the tighter of the two
checks anyway — mostly what we care about.
"""

from unittest.mock import patch

from django.test import SimpleTestCase

from Utils.url_validator import validate_public_url


class ValidatePublicUrlSchemeTest(SimpleTestCase):
    def test_https_required(self):
        with self.assertRaisesMessage(ValueError, 'https'):
            validate_public_url('http://example.com/hook')

    def test_file_scheme_rejected(self):
        with self.assertRaisesMessage(ValueError, 'https'):
            validate_public_url('file:///etc/passwd')

    def test_gopher_scheme_rejected(self):
        with self.assertRaisesMessage(ValueError, 'https'):
            validate_public_url('gopher://internal/')

    def test_empty_input_rejected(self):
        with self.assertRaises(ValueError):
            validate_public_url('')
        with self.assertRaises(ValueError):
            validate_public_url(None)


class ValidatePublicUrlIPLiteralTest(SimpleTestCase):
    """Hostnames that are literal IPs — checked without DNS."""

    def _reject(self, url):
        with self.assertRaisesMessage(ValueError, 'non-public'):
            validate_public_url(url)

    def test_loopback_rejected(self):
        self._reject('https://127.0.0.1/hook')

    def test_loopback_v6_rejected(self):
        self._reject('https://[::1]/hook')

    def test_rfc1918_10_rejected(self):
        self._reject('https://10.0.0.5/hook')

    def test_rfc1918_192_rejected(self):
        self._reject('https://192.168.1.100/hook')

    def test_rfc1918_172_rejected(self):
        self._reject('https://172.16.0.1/hook')

    def test_aws_metadata_rejected(self):
        # 169.254.169.254 is link-local, catches the classic AWS SSRF.
        self._reject('https://169.254.169.254/latest/meta-data/')

    def test_link_local_v6_rejected(self):
        self._reject('https://[fe80::1]/hook')

    def test_multicast_rejected(self):
        self._reject('https://224.0.0.1/hook')

    def test_public_ip_allowed(self):
        # 8.8.8.8 is a well-known public IP — should pass.
        self.assertTrue(validate_public_url('https://8.8.8.8/hook'))


class ValidatePublicUrlDNSTest(SimpleTestCase):
    """Hostname paths — mocked to keep the test hermetic."""

    @patch('Utils.url_validator.socket.getaddrinfo')
    def test_public_hostname_allowed(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, '', ('93.184.216.34', 0)),  # example.com-ish
        ]
        self.assertTrue(validate_public_url('https://hooks.slack.com/services/T00'))

    @patch('Utils.url_validator.socket.getaddrinfo')
    def test_hostname_resolving_to_private_rejected(self, mock_getaddrinfo):
        # An attacker uses a domain whose A record points at RFC1918.
        # Even if the *name* looks public, we reject on the resolved IP.
        mock_getaddrinfo.return_value = [
            (2, 1, 6, '', ('10.0.0.5', 0)),
        ]
        with self.assertRaisesMessage(ValueError, 'non-public'):
            validate_public_url('https://sneaky.example.com/hook')

    @patch('Utils.url_validator.socket.getaddrinfo')
    def test_hostname_with_mixed_ips_rejected_if_any_private(self, mock_getaddrinfo):
        # Multi-A-record trick: one public, one private. Reject
        # conservatively — any private address in the answer set kills it.
        mock_getaddrinfo.return_value = [
            (2, 1, 6, '', ('8.8.8.8', 0)),
            (2, 1, 6, '', ('127.0.0.1', 0)),
        ]
        with self.assertRaisesMessage(ValueError, 'non-public'):
            validate_public_url('https://mixed.example.com/hook')

    @patch('Utils.url_validator.socket.getaddrinfo')
    def test_unresolvable_hostname_rejected(self, mock_getaddrinfo):
        import socket
        mock_getaddrinfo.side_effect = socket.gaierror('nodename nor servname')
        with self.assertRaisesMessage(ValueError, 'Could not resolve'):
            validate_public_url('https://nonexistent.example/hook')
