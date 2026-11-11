"""
Optimized Knox TokenAuthentication that minimizes DB queries.

Knox's default auth does multiple DB queries per request: token lookup,
user fetch, expired-token cleanup, then an organisation fetch on first
use. This class collapses them into 2 queries by selecting the user and
organisation eagerly:
  1. Token lookup with select_related(user, user__organisation)
  2. Data query (the actual view)
"""
import binascii

from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from knox.auth import TokenAuthentication as KnoxTokenAuthentication
from knox.crypto import hash_token
from knox.models import get_token_model
from knox.settings import CONSTANTS, knox_settings

try:
    from hmac import compare_digest
except ImportError:
    from knox.crypto import compare_digest


class OptimizedTokenAuthentication(KnoxTokenAuthentication):
    """
    Knox auth with two key optimizations for high-latency DB connections:
    1. select_related('user__organisation') to avoid separate user/org queries
    2. Skip per-request token cleanup (expired tokens cleaned on login/logout instead)
    """

    def authenticate(self, request):
        # The demo read-only rule, enforced where the token is parsed: whatever
        # header form Knox accepts, the same check sees it. The middleware
        # parsed the header itself and missed 'token <value>' (external review,
        # 2026-11); this second layer cannot drift from Knox's own parsing.
        result = super().authenticate(request)
        if result is not None:
            from Middlewares.DemoUserMiddleware import is_demo_write
            if is_demo_write(result[0], request):
                from rest_framework import exceptions
                raise exceptions.PermissionDenied(
                    "You're in the SerOps live demo — sign up to make changes.")
        return result

    def authenticate_credentials(self, token):
        msg = _('Invalid token.')
        token = token.decode("utf-8")

        # Single query: token + user + organisation via select_related
        token_model = get_token_model()
        queryset = token_model.objects.select_related(
            'user', 'user__organisation', 'user__organisation__security_settings', 'user__custom_role'
        ).filter(token_key=token[:CONSTANTS.TOKEN_KEY_LENGTH])

        for auth_token in queryset:
            # Skip expired tokens (without loading all tokens for cleanup)
            if auth_token.expiry is not None and auth_token.expiry < timezone.now():
                continue

            try:
                digest = hash_token(token)
            except (TypeError, binascii.Error):
                raise _auth_failed(msg)

            if compare_digest(digest, auth_token.digest):
                if _idle_too_long(auth_token):
                    auth_token.delete()
                    raise _auth_failed(_('Your session expired.'))
                if knox_settings.AUTO_REFRESH and auth_token.expiry:
                    self.renew_token(auth_token)
                return self.validate_user(auth_token)

        raise _auth_failed(msg)


def _idle_too_long(auth_token):
    """Whether the organisation's inactivity timeout has passed for this token.

    Knox moves the expiry forward as the token is used, so expiry minus the
    token lifetime is when it was last used (to the minute, see
    MIN_REFRESH_INTERVAL).
    """
    organisation = auth_token.user.organisation
    if auth_token.expiry is None or organisation is None:
        return False
    from Users.models import SecuritySettings
    try:
        minutes = organisation.security_settings.session_timeout_minutes
    except SecuritySettings.DoesNotExist:
        minutes = SecuritySettings._meta.get_field('session_timeout_minutes').default
    if not minutes:  # "Never": only the token's own lifetime applies.
        return False
    last_used = auth_token.expiry - knox_settings.TOKEN_TTL
    return timezone.now() - last_used > timedelta(minutes=minutes)


def _auth_failed(msg):
    from rest_framework import exceptions
    return exceptions.AuthenticationFailed(msg)
