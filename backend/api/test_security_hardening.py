"""Brute-force hardening (2026-10-20 security review)."""
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.throttling import BaseThrottle


class DjangoAdminHardeningTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_admin_site_is_off_by_default(self):
        self.assertEqual(self.client.get('/api/admin/login/').status_code, 404)

    @override_settings(ROOT_URLCONF='api.test_security_hardening')
    def test_enabled_admin_login_locks_after_ten_failures(self):
        codes = [self.client.post('/api/admin/login/', {'username': 'admin@example.com', 'password': f'wrong{i}'}).status_code
                 for i in range(12)]
        self.assertEqual(codes[:10], [200] * 10)   # failed logins re-render the form
        self.assertEqual(codes[10:], [429, 429])


class ClientIdentTest(TestCase):
    def ident(self, xff, remote='10.0.0.1'):
        request = RequestFactory().get('/', HTTP_X_FORWARDED_FOR=xff, REMOTE_ADDR=remote)
        return BaseThrottle().get_ident(request)

    def test_client_written_forwarded_for_entries_are_ignored(self):
        # A load balancer appends the real client after whatever the client sent.
        self.assertEqual(self.ident('6.6.6.6, 198.51.100.20'), '198.51.100.20')
        self.assertEqual(self.ident('7.7.7.7, 198.51.100.20'), '198.51.100.20')

    @override_settings(REST_FRAMEWORK={'NUM_PROXIES': 2})
    def test_proxy_count_is_configurable(self):
        from rest_framework.settings import api_settings
        api_settings.reload()
        try:
            self.assertEqual(self.ident('6.6.6.6, 198.51.100.20, 10.1.1.1'), '198.51.100.20')
        finally:
            api_settings.reload()


# URLconf for the test above: the admin enabled, as with DJANGO_ADMIN_ENABLED=True.
import api.urls  # noqa: E402,F401  (installs the throttled admin login first)
from django.contrib import admin as _admin  # noqa: E402
from django.urls import path as _path  # noqa: E402
urlpatterns = [_path('api/admin/', _admin.site.urls)]
