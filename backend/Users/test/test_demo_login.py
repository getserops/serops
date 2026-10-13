"""
Tests for the public one-click demo bootstrap (POST /api/auth/demo-login).
"""

from knox.models import AuthToken
from rest_framework import status
from rest_framework.test import APITestCase

from Organisations.models import Organisations
from Users.models import User


DEMO_LOGIN_URL = '/api/auth/demo-login'


class DemoLoginEndpointTest(APITestCase):
    def test_returns_404_when_no_demo_org_seeded(self):
        """Self-hosters who have not run seed_demo_org get a clear
        message rather than a half-broken response."""
        response = self.client.post(DEMO_LOGIN_URL)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['error'], 'demo_not_configured')
        self.assertIn('seed_demo_org', response.data['message'])

    def test_returns_token_when_demo_user_exists(self):
        org = Organisations.objects.create(name='Demo Test Org', is_demo=True)
        user = User.objects.create_user(
            username='demo', email='demo@serops.ai',
            password='demo', organisation=org,
            role='viewer', is_active=True, is_demo=True,
        )

        response = self.client.post(DEMO_LOGIN_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('token', response.data)
        self.assertTrue(response.data['token'])
        self.assertEqual(response.data['user']['id'], user.id)
        self.assertEqual(response.data['user']['email'], 'demo@serops.ai')
        self.assertEqual(response.data['user']['role'], 'viewer')
        self.assertTrue(response.data['user']['is_demo'])
        self.assertEqual(response.data['user']['organisation_id'], org.id)

    def test_each_call_creates_a_fresh_token(self):
        """No token reuse — each visitor gets their own."""
        org = Organisations.objects.create(name='Demo Tokens Org', is_demo=True)
        User.objects.create_user(
            username='demo', email='demo@serops.ai',
            password='demo', organisation=org,
            role='viewer', is_active=True, is_demo=True,
        )

        r1 = self.client.post(DEMO_LOGIN_URL)
        r2 = self.client.post(DEMO_LOGIN_URL)
        self.assertEqual(r1.status_code, status.HTTP_200_OK)
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertNotEqual(r1.data['token'], r2.data['token'])
        # Both rows exist; revoking one does not log the other out.
        self.assertGreaterEqual(AuthToken.objects.count(), 2)

    def test_user_without_is_demo_flag_is_ignored(self):
        """A regular user named demo@serops.ai must NOT be picked up."""
        org = Organisations.objects.create(name='Not Demo Org')  # is_demo=False
        User.objects.create_user(
            username='demo', email='demo@serops.ai',
            password='demo', organisation=org,
            role='admin', is_active=True,
            # is_demo defaults to False
        )

        response = self.client.post(DEMO_LOGIN_URL)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_inactive_demo_user_is_ignored(self):
        org = Organisations.objects.create(name='Inactive Demo Org', is_demo=True)
        User.objects.create_user(
            username='demo', email='demo@serops.ai',
            password='demo', organisation=org,
            role='viewer', is_active=False, is_demo=True,
        )
        response = self.client.post(DEMO_LOGIN_URL)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class DemoLoginThrottleWiringTest(APITestCase):
    """Throttle wiring is asserted by class attribute — DRF caches the
    rate at import time so override_settings is unreliable for
    exercising the limiter in tests."""

    def test_view_is_scoped_to_auth_demo_login(self):
        from rest_framework.throttling import ScopedRateThrottle
        from Users.views import DemoLoginView

        self.assertIn(ScopedRateThrottle, DemoLoginView.throttle_classes)
        self.assertEqual(
            getattr(DemoLoginView, 'throttle_scope', None),
            'auth_demo_login',
        )

    def test_settings_define_the_rate(self):
        from django.conf import settings as django_settings
        rates = django_settings.REST_FRAMEWORK.get('DEFAULT_THROTTLE_RATES', {})
        self.assertIn('auth_demo_login', rates)
