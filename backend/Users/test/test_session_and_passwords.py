"""The inactivity timeout an admin sets is real, and every password path validates."""
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone
from knox.models import AuthToken
from knox.settings import knox_settings
from rest_framework.test import APITestCase

from Data.models import AuditLog
from Organisations.models import Organisations
from Users.models import SecuritySettings, User
from Utils.email_utils import make_invitation_token

PASSWORD = 'TestPass123!'


class Base(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = Organisations.objects.create(name='Org', website='https://org.test')
        self.user = User.objects.create_user(
            username='u', email='u@example.com', password=PASSWORD, organisation=self.org, role='user', is_active=True)


class InactivityTimeoutTest(Base):
    def _request_after_idle(self, minutes):
        instance, token = AuthToken.objects.create(self.user)
        last_used = timezone.now() - timedelta(minutes=minutes)
        AuthToken.objects.filter(pk=instance.pk).update(expiry=last_used + knox_settings.TOKEN_TTL)
        return self.client.get('/api/auth/profile', HTTP_AUTHORIZATION=f'Token {token}')

    def _timeout(self, minutes):
        SecuritySettings.objects.update_or_create(organisation=self.org, defaults={'session_timeout_minutes': minutes})

    def test_idle_session_within_the_timeout_works(self):
        self._timeout(30)
        self.assertEqual(self._request_after_idle(29).status_code, 200)

    def test_idle_session_past_the_timeout_is_ended(self):
        self._timeout(30)
        self.assertEqual(self._request_after_idle(31).status_code, 401)
        self.assertEqual(AuthToken.objects.filter(user=self.user).count(), 0)

    def test_never_keeps_the_session(self):
        self._timeout(0)
        self.assertEqual(self._request_after_idle(60 * 24 * 20).status_code, 200)

    def test_organisation_that_never_saved_settings_gets_the_documented_8_hours(self):
        self.assertEqual(self._request_after_idle(60 * 7).status_code, 200)
        self.assertEqual(self._request_after_idle(60 * 9).status_code, 401)

    def test_use_extends_the_session(self):
        self._timeout(30)
        instance, token = AuthToken.objects.create(self.user)
        last_used = timezone.now() - timedelta(minutes=20)
        AuthToken.objects.filter(pk=instance.pk).update(expiry=last_used + knox_settings.TOKEN_TTL)
        self.client.get('/api/auth/profile', HTTP_AUTHORIZATION=f'Token {token}')
        instance.refresh_from_db()
        self.assertLess(timezone.now() - (instance.expiry - knox_settings.TOKEN_TTL), timedelta(minutes=1))

    def test_setting_is_the_one_the_settings_page_writes(self):
        self.user.role = 'admin'
        self.user.save()
        self.client.force_authenticate(user=self.user)
        self.client.put('/api/data/settings/security/', {'session': {'timeout_minutes': 60}}, format='json')
        self.assertEqual(SecuritySettings.objects.get(organisation=self.org).session_timeout_minutes, 60)


class FailedLoginAuditTest(Base):
    def test_json_login_with_a_wrong_password_is_audited(self):
        response = self.client.post('/api/auth/login', {'email': self.user.email, 'password': 'wrong'}, format='json')
        self.assertEqual(response.status_code, 401)
        entry = AuditLog.objects.get(organisation=self.org, action='LOGIN_FAILED')
        self.assertEqual(entry.details['email'], self.user.email)

    def test_unknown_email_still_gets_the_same_answer(self):
        response = self.client.post('/api/auth/login', {'email': 'nobody@example.com', 'password': 'wrong'}, format='json')
        self.assertEqual(response.status_code, 401)
        self.assertFalse(AuditLog.objects.filter(action='LOGIN_FAILED').exists())


class PasswordValidationTest(Base):
    def test_changing_to_a_weak_password_is_refused(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post('/api/auth/password', {
            'old_password': PASSWORD, 'new_password': '1234', 'new_password_copy': '1234'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_invitation_with_a_weak_password_is_refused(self):
        response = self.client.post('/api/auth/accept/password', {
            'token': make_invitation_token(self.user), 'password': '1234', 'password_confirmation': '1234'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))
