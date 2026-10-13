from unittest.mock import MagicMock, patch
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from django.contrib.auth.models import AnonymousUser
from datetime import timedelta

from Middlewares.OrganisationMiddleware import OrganisationsPermissions
from Middlewares.rbac import (
    Permissions, ROLE_PERMISSIONS, PermissionBackend,
    has_permission, get_user_permissions,
    IsAdminRole, IsUserOrAdmin, ReadOnlyForViewer, SameOrganisation, RBACPermission,
)
from Middlewares.QueryTimeoutMiddleware import QueryTimeoutMiddleware


# =============================================================================
# OrganisationMiddleware.OrganisationsPermissions
# =============================================================================

class TestOrganisationsPermissions(SimpleTestCase):
    """Tests for the OrganisationsPermissions DRF permission class."""

    def setUp(self):
        self.permission = OrganisationsPermissions()

    def test_admin_role_allowed(self):
        request = MagicMock()
        request.user.role = 'admin'
        self.assertTrue(self.permission.has_permission(request, None))

    def test_non_admin_role_denied(self):
        request = MagicMock()
        request.user.role = 'user'
        self.assertFalse(self.permission.has_permission(request, None))

    def test_no_role_denied(self):
        request = MagicMock(spec=[])
        request.user = MagicMock(spec=[])  # No role attribute
        self.assertFalse(self.permission.has_permission(request, None))


# =============================================================================
# RBAC Permissions constants and ROLE_PERMISSIONS mapping
# =============================================================================

class TestRBACPermissions(SimpleTestCase):
    """Tests for RBAC permission constants and role-permission mapping."""

    def test_admin_has_all_permissions(self):
        admin_perms = ROLE_PERMISSIONS['admin']
        self.assertEqual(len(admin_perms), 24)

    def test_user_permissions_subset(self):
        user_perms = ROLE_PERMISSIONS['user']
        self.assertEqual(len(user_perms), 15)
        # User should NOT have destructive/admin-only permissions
        self.assertNotIn(Permissions.PROJECT_DELETE, user_perms)
        self.assertNotIn(Permissions.SERVICE_DELETE, user_perms)
        self.assertNotIn(Permissions.BATCH_DELETE, user_perms)
        self.assertNotIn(Permissions.ISSUE_DELETE, user_perms)
        self.assertNotIn(Permissions.USER_INVITE, user_perms)
        self.assertNotIn(Permissions.USER_UPDATE, user_perms)
        self.assertNotIn(Permissions.USER_DELETE, user_perms)
        self.assertNotIn(Permissions.USER_ROLE_CHANGE, user_perms)
        self.assertNotIn(Permissions.SETTINGS_UPDATE, user_perms)

    def test_viewer_read_only(self):
        viewer_perms = ROLE_PERMISSIONS['viewer']
        self.assertEqual(len(viewer_perms), 5)
        self.assertIn(Permissions.PROJECT_READ, viewer_perms)
        self.assertIn(Permissions.SERVICE_READ, viewer_perms)
        self.assertIn(Permissions.BATCH_READ, viewer_perms)
        self.assertIn(Permissions.ISSUE_READ, viewer_perms)
        self.assertIn(Permissions.CHAT_USE, viewer_perms)

    def test_unknown_role_no_permissions(self):
        self.assertEqual(ROLE_PERMISSIONS.get('nonexistent', []), [])


# =============================================================================
# PermissionBackend and public helpers
# =============================================================================

class TestPermissionBackend(SimpleTestCase):
    """Tests for PermissionBackend.has_permission and module-level helpers."""

    def _make_user(self, role='user', is_authenticated=True):
        user = MagicMock()
        user.role = role
        user.is_authenticated = is_authenticated
        user.organisation = None
        return user

    def test_has_permission_admin_full_access(self):
        user = self._make_user(role='admin')
        self.assertTrue(has_permission(user, Permissions.PROJECT_DELETE))
        self.assertTrue(has_permission(user, Permissions.USER_ROLE_CHANGE))
        self.assertTrue(has_permission(user, Permissions.SETTINGS_UPDATE))

    def test_has_permission_user_limited(self):
        user = self._make_user(role='user')
        self.assertTrue(has_permission(user, Permissions.PROJECT_READ))
        self.assertTrue(has_permission(user, Permissions.SERVICE_WEBHOOK))
        self.assertFalse(has_permission(user, Permissions.PROJECT_DELETE))
        self.assertFalse(has_permission(user, Permissions.USER_ROLE_CHANGE))

    def test_has_permission_viewer_read_only(self):
        user = self._make_user(role='viewer')
        self.assertTrue(has_permission(user, Permissions.PROJECT_READ))
        self.assertFalse(has_permission(user, Permissions.PROJECT_CREATE))
        self.assertFalse(has_permission(user, Permissions.BATCH_EXPORT))

    def test_has_permission_unauthenticated(self):
        user = self._make_user(is_authenticated=False)
        self.assertFalse(has_permission(user, Permissions.PROJECT_READ))

    def test_get_user_permissions_returns_list(self):
        user = self._make_user(role='viewer')
        perms = get_user_permissions(user)
        self.assertIsInstance(perms, list)
        self.assertEqual(len(perms), 5)
        self.assertIn(Permissions.PROJECT_READ, perms)


# =============================================================================
# DRF Permission Classes
# =============================================================================

class TestRBACDRFPermissionClasses(SimpleTestCase):
    """Tests for IsAdminRole, IsUserOrAdmin, ReadOnlyForViewer, SameOrganisation, RBACPermission."""

    def _make_request(self, role='admin', method='GET', is_authenticated=True):
        request = MagicMock()
        request.user.is_authenticated = is_authenticated
        request.user.role = role
        request.user.organisation = MagicMock()
        request.method = method
        return request

    def test_is_admin_role_allows_admin(self):
        perm = IsAdminRole()
        request = self._make_request(role='admin')
        self.assertTrue(perm.has_permission(request, None))

    def test_is_admin_role_blocks_user(self):
        perm = IsAdminRole()
        request = self._make_request(role='user')
        self.assertFalse(perm.has_permission(request, None))

    def test_is_user_or_admin_allows_both(self):
        perm = IsUserOrAdmin()
        self.assertTrue(perm.has_permission(self._make_request(role='admin'), None))
        self.assertTrue(perm.has_permission(self._make_request(role='user'), None))
        self.assertFalse(perm.has_permission(self._make_request(role='viewer'), None))

    def test_read_only_for_viewer_safe_methods(self):
        perm = ReadOnlyForViewer()
        self.assertTrue(perm.has_permission(self._make_request(role='viewer', method='GET'), None))
        self.assertFalse(perm.has_permission(self._make_request(role='viewer', method='POST'), None))

    def test_read_only_for_viewer_admin_all_methods(self):
        perm = ReadOnlyForViewer()
        self.assertTrue(perm.has_permission(self._make_request(role='admin', method='POST'), None))
        self.assertTrue(perm.has_permission(self._make_request(role='admin', method='DELETE'), None))

    def test_same_organisation_checks_obj_org(self):
        perm = SameOrganisation()
        org = MagicMock()
        request = self._make_request(role='admin')
        request.user.organisation = org

        # Matching org
        obj_match = MagicMock()
        obj_match.organisation = org
        self.assertTrue(perm.has_object_permission(request, None, obj_match))

        # Different org
        obj_diff = MagicMock()
        obj_diff.organisation = MagicMock()
        self.assertFalse(perm.has_object_permission(request, None, obj_diff))


# =============================================================================
# QueryTimeoutMiddleware
# =============================================================================

class TestQueryTimeoutMiddleware(SimpleTestCase):
    """Tests for QueryTimeoutMiddleware.__call__()."""

    @patch('Middlewares.QueryTimeoutMiddleware.connection')
    def test_sets_timeout_on_new_connection(self, mock_conn):
        inner_conn = MagicMock()
        mock_conn.connection = inner_conn
        mock_conn._timeout_conn_id = None  # No previous connection

        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        get_response = MagicMock()
        middleware = QueryTimeoutMiddleware(get_response)
        middleware(MagicMock())

        mock_cursor.execute.assert_called_once_with("SET statement_timeout = '30s'")
        get_response.assert_called_once()

    @patch('Middlewares.QueryTimeoutMiddleware.connection')
    def test_skips_timeout_on_same_connection(self, mock_conn):
        inner_conn = MagicMock()
        mock_conn.connection = inner_conn
        mock_conn._timeout_conn_id = id(inner_conn)  # Already set for this conn

        get_response = MagicMock()
        middleware = QueryTimeoutMiddleware(get_response)
        middleware(MagicMock())

        mock_conn.cursor.assert_not_called()
        get_response.assert_called_once()

    @patch('Middlewares.QueryTimeoutMiddleware.connection')
    def test_resets_timeout_on_connection_recycle(self, mock_conn):
        old_conn = MagicMock()
        new_conn = MagicMock()
        mock_conn.connection = new_conn
        mock_conn._timeout_conn_id = id(old_conn)  # Different from new_conn

        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        get_response = MagicMock()
        middleware = QueryTimeoutMiddleware(get_response)
        middleware(MagicMock())

        mock_cursor.execute.assert_called_once_with("SET statement_timeout = '30s'")


