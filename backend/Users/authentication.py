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

    def authenticate_credentials(self, token):
        msg = _('Invalid token.')
        token = token.decode("utf-8")

        # Single query: token + user + organisation via select_related
        token_model = get_token_model()
        queryset = token_model.objects.select_related(
            'user', 'user__organisation'
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
                if knox_settings.AUTO_REFRESH and auth_token.expiry:
                    self.renew_token(auth_token)
                return self.validate_user(auth_token)

        raise _auth_failed(msg)


def _auth_failed(msg):
    from rest_framework import exceptions
    return exceptions.AuthenticationFailed(msg)
