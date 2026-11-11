"""
HTTPS terminated by a proxy (Caddy in the quick-start, the Helm ingress).

v1.2.14 set SEROPS_HTTPS for these installs, but Django saw every request as
plain HTTP: HSTS, which Django sends only on secure requests, never went out,
and URLs built from the request (the webhook URL registered with GitHub or
GitLab) were http://.
"""
import json
import os
import subprocess
import sys

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

PROXY_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


def _settings_with(env):
    """The production settings module as it loads with this environment."""
    code = ("import json, api.settings as s; print(json.dumps({"
            "'proxy': getattr(s, 'SECURE_PROXY_SSL_HEADER', None), 'hsts': getattr(s, 'SECURE_HSTS_SECONDS', 0), "
            "'session': s.SESSION_COOKIE_SECURE, 'csrf': s.CSRF_COOKIE_SECURE}))")
    clean = {k: v for k, v in os.environ.items() if k not in ('SEROPS_HTTPS', 'SECURE_SSL_REDIRECT', 'DEBUG')}
    out = subprocess.run([sys.executable, '-c', code], env={**clean, 'DEBUG': 'False', 'SEROPS_ENCRYPTION_KEY': 'A' * 43 + '=', **env},
                         cwd=settings.BASE_DIR, capture_output=True, text=True, check=True).stdout
    return json.loads(out.strip().splitlines()[-1])


class SettingsTest(SimpleTestCase):
    def test_https_install_trusts_the_proxy_scheme(self):
        s = _settings_with({'SEROPS_HTTPS': 'True'})
        self.assertEqual(tuple(s['proxy']), PROXY_HEADER)
        self.assertEqual(s['hsts'], 31536000)
        self.assertTrue(s['session'] and s['csrf'])

    def test_django_redirect_does_not_loop_behind_the_proxy(self):
        s = _settings_with({'SECURE_SSL_REDIRECT': 'True'})
        self.assertEqual(tuple(s['proxy']), PROXY_HEADER)

    def test_plain_http_install_does_not(self):
        s = _settings_with({})
        self.assertIsNone(s['proxy'])
        self.assertFalse(s['hsts'])
        self.assertFalse(s['session'] or s['csrf'])


@override_settings(SECURE_PROXY_SSL_HEADER=PROXY_HEADER, SECURE_HSTS_SECONDS=31536000)
class BehindProxyTest(TestCase):
    def test_hsts_is_sent_on_requests_the_proxy_received_over_https(self):
        response = self.client.get('/api/version/', HTTP_X_FORWARDED_PROTO='https')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Strict-Transport-Security'], 'max-age=31536000')

    def test_not_on_plain_http(self):
        # Health probes reach the pod directly over HTTP, with no proxy header.
        response = self.client.get('/api/version/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Strict-Transport-Security', response)

    def test_urls_built_from_the_request_are_https(self):
        request = RequestFactory().post('/api/projects/1/setup-webhook/', HTTP_X_FORWARDED_PROTO='https',
                                        HTTP_HOST='testserver')
        self.assertEqual(request.build_absolute_uri('/'), 'https://testserver/')
