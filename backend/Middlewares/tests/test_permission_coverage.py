"""
Every API route declares the permission each of its methods needs.

A route without a ``Requires(...)`` declaration, or with a method or
viewset action the declaration doesn't cover, fails this test. That keeps
access deny-by-default: a new endpoint can't ship open to every signed-in
user because someone forgot a check (the 2026-10-20 security review found
15 such gaps before this test existed).

Public endpoints (login, webhooks, ingest…) authenticate some other way —
a token, a signature, a secret — and are listed in PUBLIC with the reason.
"""
from django.test import SimpleTestCase
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.permissions import AllowAny

from Middlewares.rbac import is_requires

# path prefix (under api/) -> how the caller is authenticated instead
PUBLIC = {
    'auth/login': 'credentials, throttled',
    'auth/demo-login': 'public demo account, read-only by middleware, throttled',
    'auth/registration-status': 'public flag',
    'auth/register': 'open registration gate, throttled',
    'auth/activate/': 'signed activation token',
    'auth/accept/invitation/': 'signed invitation token',
    'auth/password/forget': 'email ownership, throttled',
    'auth/password/set/': 'password-reset token',
    'auth/accept/password': 'signed invitation JWT',
    'auth/avatar/': 'unguessable per-upload key',
    'auth/sso/init': 'starts OIDC flow, throttled',
    'auth/sso/callback': 'OIDC state + code',
    'auth/sso/exchange': 'one-time SSO exchange code',
    'providers/webhook/': 'binding webhook secret (HMAC or bearer)',
    'webhooks/': 'binding webhook secret / signature, or org alert-ingest secret',
    'traces/v1/traces': 'per-org ingest key',
    'docs/': 'API schema',
    'health/': 'liveness probe',
    'version/': 'version string',
}

HTTP_METHODS = ('get', 'post', 'put', 'patch', 'delete')


def iter_routes(patterns, prefix=''):
    for p in patterns:
        if isinstance(p, URLResolver):
            yield from iter_routes(p.url_patterns, prefix + str(p.pattern))
        elif isinstance(p, URLPattern):
            yield prefix + str(p.pattern), p.callback


def view_class(callback):
    return getattr(callback, 'cls', None) or getattr(callback, 'view_class', None)


def is_public(path):
    sub = path[len('api/'):]
    return any(sub.startswith(prefix) for prefix in PUBLIC)


class PermissionCoverageTest(SimpleTestCase):
    def test_every_route_declares_its_permissions(self):
        problems = []
        for path, callback in iter_routes(get_resolver().url_patterns):
            if not path.startswith('api/') or path.startswith('api/admin'):
                continue
            cls = view_class(callback)
            if cls is None:
                continue  # plain Django function views: health/version
            if cls.__module__.startswith('rest_framework.routers'):
                continue  # DRF router root listing
            perms = list(getattr(cls, 'permission_classes', []))
            if is_public(path):
                continue
            if any(p is AllowAny for p in perms):
                problems.append(f'{path}: AllowAny but not listed in PUBLIC')
                continue
            requires = [p for p in perms if is_requires(p)]
            if not requires:
                problems.append(f'{path}: no Requires(...) ({cls.__module__}.{cls.__name__})')
                continue
            actions = getattr(callback, 'actions', None)  # viewsets: {'get': 'list', ...}
            if actions:
                pairs = [(m.upper(), a) for m, a in actions.items()]
            else:
                pairs = [(m.upper(), None) for m in HTTP_METHODS if hasattr(cls, m)]
            for method, action in pairs:
                if any(r.permission_for(method, action) is None for r in requires):
                    problems.append(f'{path}: {method}{" " + action if action else ""} not covered '
                                    f'({cls.__module__}.{cls.__name__})')
        self.assertEqual(problems, [], '\n' + '\n'.join(sorted(set(problems))))


class NoSourceFileRouteTest(SimpleTestCase):
    def test_backend_directory_is_not_served(self):
        """MEDIA_ROOT is the backend directory: serving it (static() under
        DEBUG) would publish .env and the source."""
        from django.urls import Resolver404, resolve
        for path in ('/images/.env', '/images/manage.py'):
            with self.assertRaises(Resolver404, msg=path):
                resolve(path)
