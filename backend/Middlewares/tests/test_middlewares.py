from unittest.mock import MagicMock, patch
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from django.contrib.auth.models import AnonymousUser
from datetime import timedelta

from Middlewares.rbac import (
    PERMISSIONS, PLATFORM_PERMISSIONS, ROLE_PERMISSIONS, Requires,
    get_user_permissions, has_permission,
)
from Middlewares.QueryTimeoutMiddleware import QueryTimeoutMiddleware


# =============================================================================
# Middlewares.rbac: the permission catalogue and Requires
# =============================================================================

def _user(role, staff=False, authenticated=True):
    user = MagicMock()
    user.is_authenticated = authenticated
    user.role = role
    user.is_staff = staff
    return user


class TestPermissionCatalogue(SimpleTestCase):
    def test_roles_are_cumulative(self):
        viewer, user, admin = (set(ROLE_PERMISSIONS[r]) for r in ('viewer', 'user', 'admin'))
        self.assertLess(viewer, user)
        self.assertLess(user, admin)

    def test_every_granted_permission_is_defined(self):
        for role, codes in ROLE_PERMISSIONS.items():
            for code in codes:
                self.assertIn(code, PERMISSIONS, f'{role}: {code}')

    def test_platform_permissions_are_not_role_grants(self):
        for codes in ROLE_PERMISSIONS.values():
            self.assertFalse(PLATFORM_PERMISSIONS & set(codes))

    def test_has_permission_by_role(self):
        self.assertTrue(has_permission(_user('viewer'), 'issue.read'))
        self.assertFalse(has_permission(_user('viewer'), 'issue.update'))
        self.assertTrue(has_permission(_user('user'), 'issue.update'))
        self.assertFalse(has_permission(_user('user'), 'project.delete'))
        self.assertTrue(has_permission(_user('admin'), 'team.manage'))

    def test_unauthenticated_and_unknown_role_have_nothing(self):
        self.assertFalse(has_permission(_user('admin', authenticated=False), 'issue.read'))
        self.assertFalse(has_permission(_user('owner'), 'issue.read'))
        self.assertEqual(get_user_permissions(_user('admin', authenticated=False)), [])

    def test_unknown_permission_is_an_error(self):
        with self.assertRaises(ValueError):
            has_permission(_user('admin'), 'everything.do')

    def test_platform_manage_needs_staff(self):
        self.assertFalse(has_permission(_user('admin'), 'platform.manage'))
        self.assertTrue(has_permission(_user('viewer', staff=True), 'platform.manage'))

    def test_user_permissions_list_includes_platform_grants(self):
        self.assertIn('platform.manage', get_user_permissions(_user('admin', staff=True)))
        with patch('Organisations.models.Organisations.objects.count', return_value=2):
            self.assertNotIn('platform.manage', get_user_permissions(_user('admin')))


class TestRequires(SimpleTestCase):
    HANDLERS = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']

    def check(self, permission_class, role, method, action=None, handlers=HANDLERS):
        request = MagicMock(method=method, user=_user(role), path='/x')
        view = MagicMock(spec=handlers + ['action'], action=action)
        with patch('Middlewares.rbac.audit_denied'):  # audited in test_audit_denied
            return permission_class().has_permission(request, view)

    def test_per_method(self):
        p = Requires(GET='project.read', POST='project.write')
        self.assertTrue(self.check(p, 'viewer', 'GET'))
        self.assertFalse(self.check(p, 'viewer', 'POST'))
        self.assertTrue(self.check(p, 'user', 'POST'))

    def test_head_and_options_follow_get(self):
        p = Requires(GET='project.read')
        self.assertTrue(self.check(p, 'viewer', 'HEAD'))
        self.assertTrue(self.check(p, 'viewer', 'OPTIONS'))

    def test_undeclared_method_is_denied_even_for_admin(self):
        self.assertFalse(self.check(Requires(GET='project.read'), 'admin', 'DELETE'))

    def test_method_without_handler_is_left_to_405(self):
        self.assertTrue(self.check(Requires(GET='project.read'), 'viewer', 'DELETE', handlers=['get']))

    def test_action_takes_precedence_over_method(self):
        p = Requires(GET='integration.read', POST='integration.use', create='integration.manage')
        self.assertFalse(self.check(p, 'user', 'POST', action='create'))
        self.assertTrue(self.check(p, 'user', 'POST', action='sync'))

    def test_default(self):
        p = Requires(GET='project.read', default='project.write')
        self.assertTrue(self.check(p, 'user', 'PATCH'))
        self.assertFalse(self.check(p, 'viewer', 'PATCH'))

    def test_unknown_permission_fails_at_declaration(self):
        with self.assertRaises(ValueError):
            Requires(GET='nope.read')


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


