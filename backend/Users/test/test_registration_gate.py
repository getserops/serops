"""
Tests for the REGISTRATION_ENABLED gate on POST /api/auth/register
and the public GET /api/auth/registration-status endpoint.

Three modes:
  1. Unset (default) — automatic: open until the first real organisation
     exists, then closed, so a single-company install closes itself.
  2. REGISTRATION_ENABLED=True — always open (instance hosting several
     teams).
  3. REGISTRATION_ENABLED=False — always closed (public demo host); only
     the one-click demo user + team invites work.
"""

from django.test import SimpleTestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from Organisations.models import Organisations
from Users.models import User
from api.settings import _registration_flag


REGISTER_URL = '/api/auth/register'
STATUS_URL = '/api/auth/registration-status'

_VALID_PAYLOAD = {
    'user': {
        'email': 'newuser@example.com',
        'password': 'Str0ngPass123!',
        'password_confirmation': 'Str0ngPass123!',
        'first_name': 'New',
        'last_name': 'User',
        'phone': '+1000000000',
    },
    'organisation': {
        'name': 'New Test Org',
        'website': 'https://newtest.example',
    },
}


class RegistrationStatusEndpointTest(APITestCase):
    """Public flag the Login page reads at load time."""

    @override_settings(REGISTRATION_ENABLED=None)
    def test_status_defaults_to_enabled(self):
        response = self.client.get(STATUS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['registration_enabled'])

    @override_settings(REGISTRATION_ENABLED=False)
    def test_status_reports_disabled_when_flag_off(self):
        response = self.client.get(STATUS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['registration_enabled'])

    def test_status_is_anonymous(self):
        # No auth header — must still return 200 (public endpoint).
        response = self.client.get(STATUS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class RegistrationGateTest(APITestCase):
    """RegisterView must respect REGISTRATION_ENABLED."""

    @override_settings(REGISTRATION_ENABLED=False)
    def test_register_returns_403_when_disabled(self):
        response = self.client.post(REGISTER_URL, _VALID_PAYLOAD, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['error'], 'registration_disabled')
        # Message must point self-hosters at the docs so the outcome is
        # not a dead end.
        self.assertIn('self-host', response.data['message'].lower())

    @override_settings(REGISTRATION_ENABLED=False)
    def test_gate_short_circuits_before_body_validation(self):
        # An empty body would normally trip validation and return 400.
        # With the gate closed we should reach 403 first — proves the
        # gate runs before any DB/serializer work.
        response = self.client.post(REGISTER_URL, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @override_settings(REGISTRATION_ENABLED=True)
    def test_register_reaches_normal_flow_when_enabled(self):
        # The full register flow has many moving pieces (email
        # activation, organisation serializer, etc.) so we don't
        # exhaustively test happy path here — that's covered in
        # Users.test.test_views. What we assert is that with the flag
        # on, the endpoint does NOT return the 403 gate response.
        response = self.client.post(REGISTER_URL, {}, format='json')
        self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)


def _member(org, *, is_demo=False, username='member'):
    return User.objects.create_user(
        username=username, email=f'{username}@example.com',
        password='Str0ngPass123!', organisation=org, is_demo=is_demo,
        is_active=True,
    )


@override_settings(REGISTRATION_ENABLED=None)
class AutomaticRegistrationTest(APITestCase):
    """Unset flag: open on a fresh instance, closed once it is set up."""

    def _open(self):
        return self.client.get(STATUS_URL).data['registration_enabled']

    def test_fresh_instance_is_open(self):
        self.assertTrue(self._open())
        response = self.client.post(REGISTER_URL, {}, format='json')
        self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_closes_once_a_real_organisation_has_a_member(self):
        _member(Organisations.objects.create(name='Acme'))
        self.assertFalse(self._open())
        response = self.client.post(REGISTER_URL, _VALID_PAYLOAD, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['error'], 'registration_disabled')

    def test_seeded_demo_org_does_not_close_it(self):
        demo_org = Organisations.objects.create(name='Demo', is_demo=True)
        _member(demo_org, is_demo=True, username='demo')
        self.assertTrue(self._open())

    def test_user_without_an_organisation_does_not_close_it(self):
        User.objects.create_user(
            username='loner', email='loner@example.com', password='x1!Abcdef')
        self.assertTrue(self._open())

    @override_settings(REGISTRATION_ENABLED=True)
    def test_explicit_true_stays_open_after_setup(self):
        _member(Organisations.objects.create(name='Acme'))
        self.assertTrue(self._open())

    @override_settings(REGISTRATION_ENABLED=False)
    def test_explicit_false_is_closed_on_a_fresh_instance(self):
        self.assertFalse(self._open())


class RegistrationFlagParsingTest(SimpleTestCase):

    def test_unset_and_auto_mean_automatic(self):
        for raw in (None, '', '  ', 'auto', 'AUTO'):
            self.assertIsNone(_registration_flag(raw), raw)

    def test_explicit_values(self):
        for raw in ('true', 'True', '1', 'yes'):
            self.assertIs(_registration_flag(raw), True, raw)
        for raw in ('false', 'False', '0', 'no'):
            self.assertIs(_registration_flag(raw), False, raw)
