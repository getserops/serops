"""
Role-based access control: one catalogue, one check.

Modelled on Airflow (action x resource, cumulative roles Viewer < User <
Admin) and Grafana (named actions such as ``dashboards:write``, a server
admin above organisation roles):

* ``PERMISSIONS`` names every action. ``ROLE_PERMISSIONS`` grants them to
  the three organisation roles, cumulatively.
* Platform permissions are not granted by an organisation role: they touch
  state shared by every organisation on the install (see
  ``PLATFORM_PERMISSIONS``).
* Views declare what they need with ``Requires(...)``, per HTTP method or
  viewset action. Anything a view doesn't declare is denied, and
  ``Middlewares/tests/test_permission_coverage.py`` fails the build when a
  route doesn't declare its permissions.
* The UI gets the caller's permissions from ``/api/auth/profile`` and the
  login response (``UserSerializer.permissions``) instead of keeping a copy
  of this table.

Object-level isolation (a user only ever sees their own organisation's
rows) is separate: every queryset filters by ``request.user.organisation``.
"""
import logging

from rest_framework.permissions import BasePermission

logger = logging.getLogger(__name__)


# Every action, with what it covers. Names are ``resource.action``.
PERMISSIONS = {
    # Every role
    'self.manage': 'Own profile, password, photo, account, notifications, preferences, subscriptions, chat sessions',
    'org.read': 'Organisation name, logo, capabilities and setup status',
    'project.read': 'Projects, services, bindings, deployments',
    'batch.read': 'Analyses, logs, metrics, traces, timelines, code changes, dashboards',
    'issue.read': 'Issues and their details',
    'integration.read': 'The list of integrations, log/metric sources and clusters (no secrets)',
    'alerting.read': 'The list of delivery channels (no secrets)',
    'chat.use': 'Ask AI Chat about existing analyses',
    # User and admin
    'issue.update': 'Resolve, mute, reopen, acknowledge issues',
    'batch.analyze': 'Run analyses, re-analyses, investigations and post-mortems (spends the AI budget)',
    'project.write': 'Create and edit projects, services, bindings, deployments; set up webhooks; setup flow',
    'integration.use': 'Verify, sync and health-check existing integrations',
    'settings.read': 'Read organisation settings (security, SSO, retention, data usage, AI budget)',
    # Admin
    'project.delete': 'Delete projects and services',
    'integration.manage': 'Add, edit, delete or test integrations, log/metric sources, clusters, ingest keys',
    'alerting.manage': 'Delivery channels, routing rules, escalation rules, alert ingest secret',
    'settings.manage': 'Organisation info and settings, AI providers and keys, Sentinel, retention, data deletion',
    'team.manage': 'Invite and remove members, change roles, audit log',
    # Platform (not granted by an organisation role)
    'ai_catalogue.manage': 'The AI provider catalogue shared by every organisation',
    'platform.manage': 'Install-wide operations (AI circuit breakers)',
}

_VIEWER = [
    'self.manage', 'org.read', 'project.read', 'batch.read', 'issue.read',
    'integration.read', 'alerting.read', 'chat.use',
]
_USER = _VIEWER + [
    'issue.update', 'batch.analyze', 'project.write', 'integration.use', 'settings.read',
]
_ADMIN = _USER + [
    'project.delete', 'integration.manage', 'alerting.manage', 'settings.manage', 'team.manage',
]

ROLE_PERMISSIONS = {'viewer': _VIEWER, 'user': _USER, 'admin': _ADMIN}

PLATFORM_PERMISSIONS = {'ai_catalogue.manage', 'platform.manage'}


def can_manage_shared_settings(user):
    """Settings shared by every organisation on the install (the AI provider
    catalogue): platform staff, or an org admin when the install has only one
    organisation, so no other tenant is affected."""
    if not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_staff', False):
        return True
    if getattr(user, 'role', None) != 'admin':
        return False
    from Organisations.models import Organisations
    return Organisations.objects.count() <= 1


def _platform_permission(user, code):
    if code == 'ai_catalogue.manage':
        return can_manage_shared_settings(user)
    if code == 'platform.manage':
        return bool(getattr(user, 'is_staff', False))
    return False


def has_permission(user, code):
    """True when ``user`` holds the permission ``code``."""
    if code not in PERMISSIONS:
        raise ValueError(f'Unknown permission {code!r}')
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if code in PLATFORM_PERMISSIONS:
        return _platform_permission(user, code)
    return code in ROLE_PERMISSIONS.get(getattr(user, 'role', None), ())


def get_user_permissions(user):
    """Every permission ``user`` holds, sorted (sent to the UI)."""
    if not user or not getattr(user, 'is_authenticated', False):
        return []
    granted = set(ROLE_PERMISSIONS.get(getattr(user, 'role', None), ()))
    granted.update(code for code in PLATFORM_PERMISSIONS if _platform_permission(user, code))
    return sorted(granted)


_SAFE_ALIASES = {'HEAD': 'GET', 'OPTIONS': 'GET'}

# One audit entry per user, method and path in this window: a page retrying
# a forbidden call doesn't flood the audit log.
AUDIT_DENIED_WINDOW = 600


def audit_denied(request, code):
    """Record a refused request in the organisation's audit log."""
    from django.core.cache import cache
    user = request.user
    key = f'rbac-denied:{user.pk}:{request.method}:{request.path}'[:240]
    try:
        if not cache.add(key, 1, AUDIT_DENIED_WINDOW):
            return
        from Data.audit import log_action
        log_action(request, 'ACCESS_DENIED', {
            'permission': code,
            'role': getattr(user, 'role', None),
            'method': request.method,
            'path': request.path,
        })
    except Exception:  # auditing must never turn a 403 into a 500
        logger.exception('Could not audit a denied request')


def Requires(default=None, **by_key):
    """A DRF permission class requiring permissions per method or action.

    Keys are HTTP methods (``GET=``, ``POST=``…) or viewset actions
    (``list=``, ``create=``, ``destroy=``, or a custom ``@action`` name);
    ``default`` covers the rest. A viewset action takes precedence over the
    method. A request that matches nothing is denied.

        permission_classes = [IsAuthenticated, Requires(GET='project.read', POST='project.write')]
        permission_classes = [IsAuthenticated, Requires(list='integration.read', default='integration.manage')]
    """
    for code in [default, *by_key.values()]:
        if code is not None and code not in PERMISSIONS:
            raise ValueError(f'Unknown permission {code!r}')

    class _Requires(BasePermission):
        required = dict(by_key)
        required_default = default

        @classmethod
        def permission_for(cls, method, action=None):
            if action and action in cls.required:
                return cls.required[action]
            method = _SAFE_ALIASES.get(method, method)
            return cls.required.get(method, cls.required_default)

        def has_permission(self, request, view):
            if not hasattr(view, request.method.lower()):
                return True  # no handler: DRF answers 405, nothing to protect
            code = self.permission_for(request.method, getattr(view, 'action', None))
            if code is None:
                logger.warning('No permission declared for %s %s on %s: denied',
                               request.method, getattr(view, 'action', None), type(view).__name__)
                return False
            allowed = has_permission(request.user, code)
            if not allowed:
                logger.info('Permission denied: %s lacks %s (%s %s)',
                            getattr(request.user, 'email', '?'), code, request.method, request.path)
                audit_denied(request, code)
            return allowed

    _Requires.__name__ = 'Requires'
    _Requires.__qualname__ = 'Requires(' + ', '.join(
        [f'default={default}'] * (default is not None) + [f'{k}={v}' for k, v in by_key.items()]) + ')'
    return _Requires


def is_requires(permission_class):
    """True for a class built by ``Requires`` (used by the coverage test)."""
    return hasattr(permission_class, 'permission_for') and hasattr(permission_class, 'required')
