"""
DemoUserMiddleware — keep the public demo identity strictly read-only.

The demo user on app.serops.ai (``User.is_demo=True``) can browse the
seeded "Acme Cloud" org, read its issues and chat history, and explore
settings pages. They cannot mutate anything: no chat messages, no
profile edits, no resolve/mute/reopen/acknowledge, no password
change, no integration changes.

The check happens here rather than in every view because RBAC alone is
not enough — a demo user has the ``viewer`` role, and viewers ARE
allowed to send chat messages, acknowledge issues, and change their
own password. The demo flag is a defence-in-depth layer on top of
RBAC that simply rejects every unsafe HTTP method early.

Knox note
---------
The API is authenticated via Knox tokens, which are resolved by DRF's
``TokenAuthentication`` *inside* the view's dispatch — long after
Django middleware runs. That means ``request.user`` is still
``AnonymousUser`` when this middleware fires for token-authenticated
requests. So the middleware resolves the token itself before making
the demo check: it reads the ``Authorization: Token <value>`` header,
looks the token up via ``knox.auth.TokenAuthentication``, and uses
whatever user it returns. Session-authenticated requests still work
via the standard ``request.user`` path.

Safe methods (GET, HEAD, OPTIONS) and the logout endpoint are exempt
so visitors can still browse and sign out cleanly.
"""

import logging

from django.http import JsonResponse
from rest_framework.exceptions import AuthenticationFailed


logger = logging.getLogger(__name__)


# HTTP methods that are considered safe / idempotent reads.
_SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}

# Path prefixes that are allowed even for demo users. Logout must work
# so the visitor can leave the demo cleanly; auth/sso bootstrap paths
# are anonymous already and never reach this middleware with a
# demo-flagged user attached.
_EXEMPT_WRITE_PATH_PREFIXES = (
    '/api/auth/logout',
)


class DemoUserMiddleware:
    """Reject unsafe requests from demo users with HTTP 403."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.method not in _SAFE_METHODS
            and not self._is_exempt(request.path)
            and self._is_demo_user(request)
        ):
            logger.info(
                "DemoUserMiddleware: blocked %s %s for demo user",
                request.method, request.path,
            )
            return JsonResponse(
                {
                    'error': 'demo_read_only',
                    'message': (
                        "You're in the SerOps live demo — sign up to make "
                        "changes."
                    ),
                },
                status=403,
            )
        return self.get_response(request)

    @staticmethod
    def _is_exempt(path):
        return any(path.startswith(prefix) for prefix in _EXEMPT_WRITE_PATH_PREFIXES)

    @staticmethod
    def _is_demo_user(request) -> bool:
        """Return True iff the caller is an authenticated demo user.

        Checks the session user first (cheap, no DB hit). Falls back to
        resolving the Knox token from the Authorization header so
        API-authenticated requests are also caught — see the module
        docstring for why this is needed.
        """
        session_user = getattr(request, 'user', None)
        if (
            session_user is not None
            and getattr(session_user, 'is_authenticated', False)
            and getattr(session_user, 'is_demo', False)
        ):
            return True

        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith('Token '):
            return False

        # Lazy import — knox isn't needed if the header isn't there.
        try:
            from knox.auth import TokenAuthentication
        except ImportError:
            return False

        try:
            result = TokenAuthentication().authenticate(request)
        except AuthenticationFailed:
            return False
        if not result:
            return False
        user, _ = result
        return bool(getattr(user, 'is_demo', False))
