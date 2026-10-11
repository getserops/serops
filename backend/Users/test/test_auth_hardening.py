"""
Tests for auth hardening — rate limiting on sensitive endpoints and
token revocation on password change/reset.
"""

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from knox.models import AuthToken
from rest_framework import status
from rest_framework.test import APITestCase

from Organisations.models import Organisations
from Users.models import User


class PasswordChangeTokenRevocationTest(APITestCase):
    """Password change / reset must invalidate every existing token."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Token Rev Org')
        self.user = User.objects.create_user(
            username='tokenrev', email='tokenrev@test.com',
            password='OldPass123!', organisation=self.org,
            role='admin', is_active=True,
        )
        # Pre-create two active tokens to simulate concurrent sessions.
        AuthToken.objects.create(self.user)
        AuthToken.objects.create(self.user)
        self.assertEqual(AuthToken.objects.filter(user=self.user).count(), 2)

    def test_password_update_revokes_all_tokens(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            '/api/auth/password',
            {
                'old_password': 'OldPass123!',
                'new_password': 'NewPass456!',
                'new_password_copy': 'NewPass456!',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Every token must be gone.
        self.assertEqual(AuthToken.objects.filter(user=self.user).count(), 0)
        # And the new password must work.
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewPass456!'))

    def test_invalid_old_password_does_not_revoke_tokens(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            '/api/auth/password',
            {
                'old_password': 'wrong',
                'new_password': 'NewPass456!',
                'new_password_copy': 'NewPass456!',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(AuthToken.objects.filter(user=self.user).count(), 2)

    def test_password_reset_revokes_all_tokens(self):
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = PasswordResetTokenGenerator().make_token(self.user)
        response = self.client.post(
            reverse('set-password', kwargs={'uidb64': uidb64, 'token': token}),
            {
                'new_password': 'ResetPass789!',
                'new_password_confirm': 'ResetPass789!',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(AuthToken.objects.filter(user=self.user).count(), 0)


class AuthThrottleWiringTest(APITestCase):
    """Verify the sensitive auth views are wired to ScopedRateThrottle.

    We check the class attributes rather than exercising rate limits in a
    request loop — DRF caches throttle rates at module import via
    api_settings, which makes `override_settings`-based rate tests
    unreliable. Confirming the attributes is sufficient to prove the
    settings.py rate config is what governs these endpoints.
    """

    def _assert_scoped(self, view_class, expected_scope):
        from rest_framework.throttling import ScopedRateThrottle
        self.assertIn(ScopedRateThrottle, view_class.throttle_classes)
        self.assertEqual(getattr(view_class, 'throttle_scope', None), expected_scope)

    def test_login_view_is_scoped(self):
        from Users.views import LoginView
        self._assert_scoped(LoginView, 'auth_login')

    def test_register_view_is_scoped(self):
        from Users.views import RegisterView
        self._assert_scoped(RegisterView, 'auth_register')

    def test_forget_password_view_is_scoped(self):
        from Users.views import ForgetPasswordView
        self._assert_scoped(ForgetPasswordView, 'auth_password_reset')

    def test_sso_init_view_is_scoped(self):
        from Users.sso_views import SSOInitView
        self._assert_scoped(SSOInitView, 'auth_sso_init')

    def test_settings_define_all_four_rates(self):
        """settings.py must define a rate for every scope the views use."""
        from django.conf import settings as django_settings
        rates = django_settings.REST_FRAMEWORK.get('DEFAULT_THROTTLE_RATES', {})
        for scope in ('auth_login', 'auth_register', 'auth_password_reset', 'auth_sso_init'):
            self.assertIn(scope, rates, f"Missing throttle rate for {scope}")
