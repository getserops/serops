"""Login: failed-attempt limits per account and source address, and per
account alone; timing (audit 2026-11-20, item 10)."""
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from api.settings import _positive_int
from Organisations.models import Organisations
from Users.models import User

URL = '/api/auth/login'
PW = 'Right' + 'Pass123!'
RF = {'DEFAULT_THROTTLE_RATES': {'auth_login': '1000/min'}, 'DEFAULT_AUTHENTICATION_CLASSES': [],
      'DEFAULT_PERMISSION_CLASSES': []}


@override_settings(LOGIN_MAX_FAILURES_PER_SOURCE=3, LOGIN_MAX_FAILURES_PER_ACCOUNT=6, REST_FRAMEWORK=RF)
class LoginLockoutTest(TestCase):
    def setUp(self):
        cache.clear()
        org = Organisations.objects.create(name='Lock Org')
        self.user = User.objects.create_user(username='locked', email='locked@test.example', password=PW,
                                             organisation=org, role='admin', is_active=True)
        self.client = APIClient()

    def login(self, email, password, ip='203.0.113.1'):
        return self.client.post(URL, {'email': email, 'password': password}, format='json', REMOTE_ADDR=ip)

    def test_source_is_locked_but_the_owner_elsewhere_is_not(self):
        for _ in range(3):
            self.assertEqual(self.login('locked@test.example', 'wrong').status_code, 401)
        self.assertEqual(self.login('locked@test.example', PW).status_code, 429)
        self.assertEqual(self.login('locked@test.example', PW, ip='198.51.100.7').status_code, 200)

    def test_account_cap_stops_many_sources(self):
        for i in range(6):
            self.login('locked@test.example', 'wrong', ip=f'203.0.113.{10 + i}')
        self.assertEqual(self.login('locked@test.example', PW, ip='198.51.100.99').status_code, 429)

    def test_success_resets_the_counts(self):
        for _ in range(2):
            self.login('locked@test.example', 'wrong')
        self.assertEqual(self.login('locked@test.example', PW).status_code, 200)
        for _ in range(2):
            self.assertEqual(self.login('locked@test.example', 'wrong').status_code, 401)
        self.assertEqual(self.login('locked@test.example', PW).status_code, 200)

    def test_unknown_address_behaves_the_same(self):
        for _ in range(3):
            self.assertEqual(self.login('nobody@test.example', 'wrong').status_code, 401)
        self.assertEqual(self.login('nobody@test.example', 'wrong').status_code, 429)

    def test_unknown_address_still_hashes_a_password(self):
        with mock.patch('Users.views.make_password') as hashed:
            self.login('nobody@test.example', 'whatever')
        hashed.assert_called_once_with('whatever')

    def test_other_accounts_are_not_affected(self):
        for _ in range(6):
            self.login('nobody@test.example', 'wrong')
        self.assertEqual(self.login('locked@test.example', PW).status_code, 200)

    def test_no_address_or_email_in_the_cache_keys(self):
        from Users.views import _login_fail_keys
        request = mock.Mock(META={'REMOTE_ADDR': '203.0.113.1'})
        for key in _login_fail_keys('locked@test.example', request).values():
            self.assertNotIn('203.0.113.1', key)
            self.assertNotIn('locked', key)


class SettingsParsingTest(SimpleTestCase):
    def test_positive_int(self):
        self.assertEqual(_positive_int('25', 10), 25)
        self.assertEqual(_positive_int('0', 10), 10)
        self.assertEqual(_positive_int('-3', 10), 10)
        self.assertEqual(_positive_int('x', 10), 10)
        self.assertEqual(_positive_int(None, 100), 100)
