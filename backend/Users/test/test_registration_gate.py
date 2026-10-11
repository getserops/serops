"""
Tests for the REGISTRATION_ENABLED gate on POST /api/auth/register
and the public GET /api/auth/registration-status endpoint.

Both matter for the two intended deployment modes:
  1. Self-host — REGISTRATION_ENABLED=True (default), users create
     their org through the normal register form.
  2. Public demo host (app.serops.ai) — REGISTRATION_ENABLED=False,
     open registration is closed; only the one-click demo user + team
     invites work.
"""

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase


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
