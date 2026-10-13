"""
Tests for DemoUserMiddleware.

The middleware enforces the demo-org promise: visitors browsing the
public Acme Cloud org on app.serops.ai can read everything but mutate
nothing — regardless of what their RBAC role would otherwise allow.

Coverage:
  - safe methods (GET/HEAD/OPTIONS) always pass through for demo users
  - unsafe methods are rejected with 403 + a JSON `demo_read_only` body
  - the logout endpoint is exempt even when called with POST
  - non-demo users are never affected (admins / users / viewers all
    keep their existing behaviour)
  - anonymous requests are passed through (middleware only acts on
    authenticated demo users)
"""

from unittest.mock import MagicMock

from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase

from Middlewares.DemoUserMiddleware import DemoUserMiddleware


def _make_request(method, path, user):
    request = MagicMock()
    request.method = method
    request.path = path
    request.user = user
    return request


def _demo_user():
    user = MagicMock()
    user.is_authenticated = True
    user.is_demo = True
    user.email = 'demo@serops.ai'
    return user


def _regular_user(role='viewer'):
    user = MagicMock()
    user.is_authenticated = True
    user.is_demo = False
    user.role = role
    user.email = f'{role}@test.com'
    return user


class DemoUserMiddlewareTest(SimpleTestCase):
    def setUp(self):
        self.get_response = MagicMock(return_value='downstream-response')
        self.middleware = DemoUserMiddleware(self.get_response)

    # ── Safe methods ────────────────────────────────────────────────

    def test_demo_user_get_request_passes_through(self):
        request = _make_request('GET', '/api/data/batches', _demo_user())
        self.middleware(request)
        self.get_response.assert_called_once_with(request)

    def test_demo_user_head_request_passes_through(self):
        request = _make_request('HEAD', '/api/data/batches', _demo_user())
        self.middleware(request)
        self.get_response.assert_called_once_with(request)

    def test_demo_user_options_request_passes_through(self):
        # CORS preflight must always work — otherwise the SPA cannot
        # even render the demo session.
        request = _make_request('OPTIONS', '/api/data/issues/1/', _demo_user())
        self.middleware(request)
        self.get_response.assert_called_once_with(request)

    # ── Unsafe methods are blocked ─────────────────────────────────

    def test_demo_user_post_returns_403(self):
        request = _make_request('POST', '/api/chat/generate-text/', _demo_user())
        response = self.middleware(request)
        self.assertEqual(response.status_code, 403)
        body = response.content.decode()
        self.assertIn('demo_read_only', body)
        self.get_response.assert_not_called()

    def test_demo_user_put_returns_403(self):
        request = _make_request('PUT', '/api/settings/issues/', _demo_user())
        response = self.middleware(request)
        self.assertEqual(response.status_code, 403)
        self.get_response.assert_not_called()

    def test_demo_user_patch_returns_403(self):
        request = _make_request('PATCH', '/api/auth/profile', _demo_user())
        response = self.middleware(request)
        self.assertEqual(response.status_code, 403)
        self.get_response.assert_not_called()

    def test_demo_user_delete_returns_403(self):
        request = _make_request('DELETE', '/api/data/issues/1/', _demo_user())
        response = self.middleware(request)
        self.assertEqual(response.status_code, 403)
        self.get_response.assert_not_called()

    # ── Logout exemption ───────────────────────────────────────────

    def test_demo_user_can_logout_via_post(self):
        # Logout MUST stay reachable so the demo session can be ended
        # cleanly. POST /api/auth/logout is unsafe by method but exempt
        # by path.
        request = _make_request('POST', '/api/auth/logout', _demo_user())
        self.middleware(request)
        self.get_response.assert_called_once_with(request)

    # ── Regular users are untouched ────────────────────────────────

    def test_admin_user_post_passes_through(self):
        request = _make_request('POST', '/api/projects/', _regular_user('admin'))
        self.middleware(request)
        self.get_response.assert_called_once_with(request)

    def test_viewer_user_post_passes_through(self):
        # Whether viewers can POST is a separate (RBAC) concern — this
        # middleware does not have an opinion. It must pass through.
        request = _make_request('POST', '/api/chat/generate-text/', _regular_user('viewer'))
        self.middleware(request)
        self.get_response.assert_called_once_with(request)

    def test_anonymous_request_passes_through(self):
        request = _make_request('POST', '/api/auth/login', AnonymousUser())
        self.middleware(request)
        self.get_response.assert_called_once_with(request)

    def test_authenticated_user_without_is_demo_attr_passes_through(self):
        # Defensive: an old User row without the new column would have
        # is_demo=False by default, but we cover the missing-attribute
        # case anyway so the middleware never crashes on edge data.
        user = MagicMock(spec=['is_authenticated', 'email'])
        user.is_authenticated = True
        user.email = 'legacy@test.com'
        request = _make_request('POST', '/api/projects/', user)
        self.middleware(request)
        self.get_response.assert_called_once_with(request)
