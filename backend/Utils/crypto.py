"""
Encryption of the secrets SerOps stores: AI keys, integration credentials,
source-control tokens, notification channels and the OIDC client secret.

Everything is encrypted with SEROPS_ENCRYPTION_KEY, which does nothing else.
These values used to be encrypted with a hash of DJANGO_SECRET_KEY, so
anything that exposed that key also opened every stored credential, and it
could not be changed without losing them. A value written the old way is
still readable, and ``manage.py rotate_secrets`` rewrites it.

To change the key, move it to SEROPS_ENCRYPTION_KEY_PREVIOUS, set a new one
and run ``rotate_secrets``.
"""
import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings

logger = logging.getLogger(__name__)

PREFIX = 'v1:'
_LEGACY_PREFIX = 'gAAAAA'  # Every Fernet token starts this way.


class DecryptionError(InvalidToken):
    """A stored secret cannot be read: wrong key or damaged value."""


def _fernets():
    keys = [settings.SEROPS_ENCRYPTION_KEY, *settings.SEROPS_ENCRYPTION_KEY_PREVIOUS]
    return MultiFernet([Fernet(k.encode()) for k in keys])


def _legacy_fernets():
    derived = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    keys = [derived]
    if os.environ.get('SSO_ENCRYPTION_KEY'):
        keys.append(os.environ['SSO_ENCRYPTION_KEY'].encode())
    return MultiFernet([Fernet(k) for k in keys])


def is_ciphertext(value):
    return isinstance(value, str) and value.startswith((PREFIX, _LEGACY_PREFIX))


def encrypt(plaintext):
    return PREFIX + _fernets().encrypt(plaintext.encode()).decode()


def _decrypt(value):
    if value.startswith(PREFIX):
        return _fernets().decrypt(value[len(PREFIX):].encode()).decode()
    return _legacy_fernets().decrypt(value.encode()).decode()


def decrypt(value):
    """The plaintext, or DecryptionError: never an empty value that looks like no secret."""
    try:
        return _decrypt(value)
    except (InvalidToken, ValueError, TypeError) as exc:
        logger.error('A stored secret cannot be decrypted: wrong SEROPS_ENCRYPTION_KEY or a damaged value')
        raise DecryptionError() from exc


def can_decrypt(value):
    """Whether ``value`` is one of ours. Quiet: a miss is normal for freshly entered text."""
    try:
        _decrypt(value)
    except (InvalidToken, ValueError, TypeError, AttributeError):
        return False
    return True


def needs_rewrite(value):
    """Whether ``value`` is not encrypted under the current key in the current format."""
    if not value.startswith(PREFIX):
        return True
    try:
        Fernet(settings.SEROPS_ENCRYPTION_KEY.encode()).decrypt(value[len(PREFIX):].encode())
    except InvalidToken:
        return True
    return False
