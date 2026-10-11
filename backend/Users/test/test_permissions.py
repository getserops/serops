from unittest.mock import MagicMock
from django.test import SimpleTestCase
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from Users.permissions import (
    ROLE_HIERARCHY, ACTION_PERMISSIONS,
    has_role, can_perform, require_role, require_action,
    get_user_permissions, RolePermissionMixin,
)


# =============================================================================
# has_role()
# =============================================================================

class TestHasRole(SimpleTestCase):
    """Tests for has_role() — role hierarchy checking."""

    def _make_user(self, role='user', is_authenticated=True):
        user = MagicMock()
        user.role = role
        user.is_authenticated = is_authenticated
        return user

    def test_admin_has_admin_role(self):
        self.assertTrue(has_role(self._make_user('admin'), 'admin'))

    def test_admin_has_user_role(self):
        self.assertTrue(has_role(self._make_user('admin'), 'user'))

    def test_admin_has_viewer_role(self):
        self.assertTrue(has_role(self._make_user('admin'), 'viewer'))

    def test_user_lacks_admin_role(self):
        self.assertFalse(has_role(self._make_user('user'), 'admin'))

    def test_viewer_lacks_user_role(self):
        self.assertFalse(has_role(self._make_user('viewer'), 'user'))

    def test_unauthenticated_returns_false(self):
        self.assertFalse(has_role(self._make_user(is_authenticated=False), 'viewer'))


# =============================================================================
# can_perform()
# =============================================================================

class TestCanPerform(SimpleTestCase):
    """Tests for can_perform() — action-based permission checking."""

    def _make_user(self, role='user'):
        user = MagicMock()
        user.role = role
        user.is_authenticated = True
        return user

    def test_admin_can_manage_team(self):
        self.assertTrue(can_perform(self._make_user('admin'), 'manage_team'))

    def test_user_can_trigger_analysis(self):
        self.assertTrue(can_perform(self._make_user('user'), 'trigger_analysis'))

    def test_viewer_can_view_dashboard(self):
        self.assertTrue(can_perform(self._make_user('viewer'), 'view_dashboard'))

    def test_viewer_cannot_manage_settings(self):
        self.assertFalse(can_perform(self._make_user('viewer'), 'manage_settings'))

    def test_unknown_action_defaults_admin(self):
        # Unknown actions default to requiring admin
        self.assertTrue(can_perform(self._make_user('admin'), 'nonexistent_action'))
        self.assertFalse(can_perform(self._make_user('user'), 'nonexistent_action'))


# =============================================================================
# require_role() decorator
# =============================================================================

class TestRequireRoleDecorator(SimpleTestCase):
    """Tests for @require_role decorator on class-based view methods."""

    def _make_request(self, role='admin'):
        request = MagicMock()
        user = MagicMock()
        user.role = role
        user.is_authenticated = True
        user.email = f'{role}@test.com'
        request.user = user
        return request

    def test_admin_passes_admin_required(self):
        class DummyView:
            @require_role('admin')
            def my_view(self, request):
                return Response({'ok': True}, status=status.HTTP_200_OK)

        view = DummyView()
        response = view.my_view(self._make_request('admin'))
        self.assertEqual(response.status_code, 200)

    def test_user_blocked_from_admin_view(self):
        class DummyView:
            @require_role('admin')
            def my_view(self, request):
                return Response({'ok': True}, status=status.HTTP_200_OK)

        view = DummyView()
        response = view.my_view(self._make_request('user'))
        self.assertEqual(response.status_code, 403)

    def test_response_includes_role_info(self):
        class DummyView:
            @require_role('admin')
            def my_view(self, request):
                return Response({'ok': True})

        view = DummyView()
        response = view.my_view(self._make_request('viewer'))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['required_role'], 'admin')
        self.assertEqual(response.data['current_role'], 'viewer')

    def test_require_action_delegates_to_require_role(self):
        # require_action('manage_team') should behave like require_role('admin')
        class DummyView:
            @require_action('manage_team')
            def my_view(self, request):
                return Response({'ok': True})

        view = DummyView()
        self.assertEqual(view.my_view(self._make_request('admin')).status_code, 200)
        self.assertEqual(view.my_view(self._make_request('user')).status_code, 403)


# =============================================================================
# get_user_permissions()
# =============================================================================

class TestGetUserPermissions(SimpleTestCase):
    """Tests for get_user_permissions() — returns {action: bool} dict."""

    def _make_user(self, role='admin'):
        user = MagicMock()
        user.role = role
        user.is_authenticated = True
        return user

    def test_admin_all_actions_true(self):
        perms = get_user_permissions(self._make_user('admin'))
        self.assertEqual(len(perms), len(ACTION_PERMISSIONS))
        self.assertTrue(all(perms.values()))

    def test_viewer_only_view_actions(self):
        perms = get_user_permissions(self._make_user('viewer'))
        view_keys = [k for k in ACTION_PERMISSIONS if k.startswith('view_') and ACTION_PERMISSIONS[k] == 'viewer']
        for key in view_keys:
            self.assertTrue(perms[key], f'Viewer should have {key}')
        manage_keys = [k for k in ACTION_PERMISSIONS if k.startswith('manage_')]
        for key in manage_keys:
            self.assertFalse(perms[key], f'Viewer should NOT have {key}')

    def test_returns_all_defined_actions(self):
        perms = get_user_permissions(self._make_user('user'))
        self.assertEqual(set(perms.keys()), set(ACTION_PERMISSIONS.keys()))


# =============================================================================
# RolePermissionMixin
# =============================================================================

class TestRolePermissionMixin(SimpleTestCase):
    """Tests for RolePermissionMixin on class-based views."""

    def test_mixin_allows_sufficient_role(self):
        class TestView(RolePermissionMixin, APIView):
            required_role = 'admin'

        view = TestView()
        factory = APIRequestFactory()
        request = factory.get('/')
        user = MagicMock()
        user.role = 'admin'
        user.is_authenticated = True
        request.user = user
        # DRF wraps the request internally; simulate DRF's request processing
        from rest_framework.request import Request
        drf_request = Request(request)
        drf_request._user = user
        drf_request._auth = None
        # check_permissions should not raise
        try:
            view.check_permissions(drf_request)
        except PermissionDenied:
            self.fail('check_permissions raised PermissionDenied for admin')

    def test_mixin_raises_permission_denied(self):
        class TestView(RolePermissionMixin, APIView):
            required_role = 'admin'

        view = TestView()
        factory = APIRequestFactory()
        request = factory.get('/')
        user = MagicMock()
        user.role = 'viewer'
        user.is_authenticated = True
        request.user = user
        from rest_framework.request import Request
        drf_request = Request(request)
        drf_request._user = user
        drf_request._auth = None
        with self.assertRaises(PermissionDenied):
            view.check_permissions(drf_request)
