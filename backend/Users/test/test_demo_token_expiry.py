"""Demo tokens live hours, not 30 days; expired tokens are deleted (audit 2026-11-20, item 15)."""
from datetime import timedelta

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from knox.models import AuthToken
from rest_framework.test import APIClient

from api.celery import app as celery_app
from api.settings import _demo_token_hours
from Organisations.models import Organisations
from Users.models import SecuritySettings, User
from Users.tasks import delete_expired_auth_tokens

ME = '/api/auth/profile'


class DemoTokenTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Demo Org', is_demo=True)
        self.demo = User.objects.create_user(username='demo', email='demo@serops.example', password='Pass1234!',
                                             organisation=self.org, role='viewer', is_active=True, is_demo=True)
        self.client = APIClient()

    def _demo_login(self):
        r = self.client.post('/api/auth/demo-login', {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()['token']

    def test_demo_token_lives_hours(self):
        self._demo_login()
        token = AuthToken.objects.get(user=self.demo)
        expected = timezone.now() + settings.DEMO_TOKEN_TTL
        self.assertLess(abs((token.expiry - expected).total_seconds()), 60)
        self.assertLessEqual(settings.DEMO_TOKEN_TTL, timedelta(hours=24))

    def test_demo_token_is_not_renewed_on_use(self):
        raw = self._demo_login()
        token = AuthToken.objects.get(user=self.demo)
        issued = token.expiry
        AuthToken.objects.filter(pk=token.pk).update(expiry=issued - timedelta(hours=1))  # pretend time passed
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + raw)
        self.assertEqual(self.client.get(ME).status_code, 200)
        token.refresh_from_db()
        self.assertEqual(token.expiry, issued - timedelta(hours=1))

    def test_expired_demo_token_is_refused(self):
        raw = self._demo_login()
        AuthToken.objects.filter(user=self.demo).update(expiry=timezone.now() - timedelta(minutes=1))
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + raw)
        self.assertEqual(self.client.get(ME).status_code, 401)

    def test_inactivity_timeout_does_not_end_a_fresh_demo_token(self):
        SecuritySettings.objects.update_or_create(organisation=self.org, defaults={'session_timeout_minutes': 30})
        raw = self._demo_login()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + raw)
        self.assertEqual(self.client.get(ME).status_code, 200)

    def test_other_users_tokens_still_renew(self):
        user = User.objects.create_user(username='member', email='member@test.example', password='Pass1234!',
                                        organisation=Organisations.objects.create(name='Real Org'),
                                        role='admin', is_active=True)
        token, raw = AuthToken.objects.create(user)
        from knox.settings import knox_settings
        used_two_minutes_ago = timezone.now() + knox_settings.TOKEN_TTL - timedelta(minutes=2)
        AuthToken.objects.filter(pk=token.pk).update(expiry=used_two_minutes_ago)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + raw)
        self.assertEqual(self.client.get(ME).status_code, 200)
        token.refresh_from_db()
        self.assertGreater(token.expiry, used_two_minutes_ago)


class ExpiredTokenCleanupTest(TestCase):
    def test_only_expired_tokens_are_deleted(self):
        user = User.objects.create_user(username='u1', email='u1@test.example', password='Pass1234!',
                                        organisation=Organisations.objects.create(name='Org'), is_active=True)
        live, _ = AuthToken.objects.create(user)
        old, _ = AuthToken.objects.create(user)
        AuthToken.objects.filter(pk=old.pk).update(expiry=timezone.now() - timedelta(seconds=1))
        self.assertEqual(delete_expired_auth_tokens(), 1)
        self.assertEqual(list(AuthToken.objects.values_list('pk', flat=True)), [live.pk])

    def test_scheduled_hourly(self):
        entry = celery_app.conf.beat_schedule['delete-expired-auth-tokens']
        self.assertEqual(entry['task'], 'Users.tasks.delete_expired_auth_tokens')
        self.assertEqual(entry['schedule'], timedelta(hours=1))


class DemoTokenHoursSettingTest(SimpleTestCase):
    def test_parsing(self):
        self.assertEqual(_demo_token_hours('8'), 8)
        self.assertEqual(_demo_token_hours('2'), 2)
        self.assertEqual(_demo_token_hours('0'), 1)
        self.assertEqual(_demo_token_hours('bad'), 8)
        self.assertEqual(_demo_token_hours(None), 8)
