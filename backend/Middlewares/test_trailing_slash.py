"""A trailing slash on a slashless API route must not 404.

SerOps' API paths have no trailing slash (``/api/auth/login``), which is the
opposite of the DRF convention most clients and copy-pasted snippets assume.
``POST /api/auth/login/`` returned 404, and on the login form a 404 with no
usable body reads as "invalid credentials" — sending the user to re-type a
password that was always correct.

Django's APPEND_SLASH cannot help: it only ever ADDS a slash to reach a match.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase


class TrailingSlashFallbackTest(TestCase):
    """Asserts against a REAL login: a made-up address fails either way, so
    it cannot tell "route missing" apart from "bad credentials", which is the
    exact confusion under test."""

    PASSWORD = 'tsfm-Test-Passw0rd'

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            email='slash@example.com', username='slashuser', password=self.PASSWORD,
        )
        # LoginView refuses an unactivated account with 403, which would mask
        # what these tests are actually measuring.
        self.user.status = 'active'
        self.user.is_active = True
        self.user.save(update_fields=['status', 'is_active'])

    def _login(self, path):
        return self.client.post(
            path, {'email': self.user.email, 'password': self.PASSWORD},
            content_type='application/json',
        )

    def test_slashless_route_still_works(self):
        """The canonical spelling must be untouched."""
        self.assertEqual(self._login('/api/auth/login').status_code, 200)

    def test_trailing_slash_reaches_the_same_view(self):
        self.assertEqual(self._login('/api/auth/login/').status_code, 200,
                         'a trailing slash must not read as a missing endpoint')

    def test_the_request_body_survives(self):
        """A 301 redirect would turn the POST into a GET and drop the body,
        which is why this re-dispatches instead of redirecting. The token in
        the response proves the credentials arrived."""
        response = self._login('/api/auth/login/')
        self.assertIn('token', response.json())

    def test_it_does_not_redirect(self):
        self.assertNotIn(self._login('/api/auth/login/').status_code, (301, 302))

    def test_both_spellings_agree(self):
        a, b = self._login('/api/auth/login'), self._login('/api/auth/login/')
        self.assertEqual(a.status_code, b.status_code)
        self.assertEqual(set(a.json()), set(b.json()))

    def test_a_genuinely_missing_route_still_404s(self):
        """The fallback must not invent endpoints."""
        self.assertEqual(self.client.get('/api/auth/no-such-endpoint/').status_code, 404)

    def test_other_endpoints_benefit_too(self):
        """This is a global fix, not a login-specific patch."""
        self.assertNotEqual(
            self.client.get('/api/auth/registration-status/').status_code, 404)

    def test_root_path_is_left_alone(self):
        self.assertNotEqual(self.client.get('/').status_code, 500)
