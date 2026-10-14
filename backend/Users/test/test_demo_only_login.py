"""DEMO_ONLY_LOGIN: on a public demo host only the seeded demo user signs in,
and the login form does not tell anyone which emails have an account."""
from django.test import override_settings
from rest_framework.test import APITestCase

from Organisations.models import Organisations
from Users.models import User

LOGIN_URL = '/api/auth/login'
STATUS_URL = '/api/auth/registration-status'
PASSWORD = 'Str0ngPass123!'


class LoginTestBase(APITestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Real Org', website='https://real.example')
        self.user = User.objects.create_user(
            username='real', email='real@example.com', password=PASSWORD,
            organisation=self.org, role='admin', is_active=True,
        )

    def login(self, email, password=PASSWORD):
        return self.client.post(LOGIN_URL, {'email': email, 'password': password}, format='json')


class LoginEnumerationTest(LoginTestBase):
    def test_unknown_email_and_wrong_password_look_the_same(self):
        unknown = self.login('nobody@example.com')
        wrong = self.login('real@example.com', 'not-the-password')
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(unknown.data, wrong.data)

    def test_good_credentials_still_work(self):
        self.assertEqual(self.login('real@example.com').status_code, 200)


@override_settings(DEMO_ONLY_LOGIN=True)
class DemoOnlyLoginTest(LoginTestBase):
    def test_password_login_is_refused(self):
        response = self.login('real@example.com')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['error'], 'demo_only')
        self.assertNotIn('token', response.data)

    def test_password_reset_is_refused(self):
        response = self.client.post('/api/auth/password/forget', {'email': 'real@example.com'}, format='json')
        self.assertEqual(response.status_code, 403)

    @override_settings(REGISTRATION_ENABLED=True)
    def test_registration_is_closed(self):
        response = self.client.get(STATUS_URL)
        self.assertFalse(response.data['registration_enabled'])
        self.assertTrue(response.data['demo_only'])

    def test_demo_login_still_works(self):
        demo_org = Organisations.objects.create(name='Demo', website='https://demo.example', is_demo=True)
        User.objects.create_user(
            username='demo', email='demo@example.com', password=None,
            organisation=demo_org, role='viewer', is_active=True, is_demo=True,
        )
        self.assertEqual(self.client.post('/api/auth/demo-login').status_code, 200)


class RegistrationStatusDemoFlagsTest(LoginTestBase):
    def test_flags_default_off(self):
        data = self.client.get(STATUS_URL).data
        self.assertFalse(data['demo_only'])
        self.assertFalse(data['demo_available'])

    def test_demo_available_once_seeded(self):
        demo_org = Organisations.objects.create(name='Demo', website='https://demo.example', is_demo=True)
        User.objects.create_user(
            username='demo', email='demo@example.com', password=None,
            organisation=demo_org, role='viewer', is_active=True, is_demo=True,
        )
        self.assertTrue(self.client.get(STATUS_URL).data['demo_available'])
