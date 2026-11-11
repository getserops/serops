"""Parse and verify a license key.

A license key is a JSON document::

    {
        "format": 1,
        "payload": {
            "id": "lic_2026_0001",
            "licensee": "Acme Corp",
            "features": ["saml", "scim"],
            "issued": "2026-10-21",
            "expires": "2027-10-21"
        },
        "signature": "<base64 Ed25519 signature of the canonical payload>"
    }

The canonical payload is its JSON with sorted keys and no spaces (see
``canonical``). A license is valid through the whole of its ``expires`` day
(UTC). Feature codes this release doesn't know are ignored, so a newer key
works on an older install.
"""

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import date

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from django.utils import timezone

from . import keys
from .features import FEATURES

FORMAT = 1
MAX_LENGTH = 64 * 1024


class LicenseError(ValueError):
    """The text is not a valid SerOps license key (the message says why)."""


@dataclass(frozen=True)
class License:
    id: str
    licensee: str
    features: frozenset
    issued: date
    expires: date

    def is_expired(self, today=None):
        return (today or timezone.now().date()) > self.expires

    def as_dict(self, today=None):
        return {
            'id': self.id,
            'licensee': self.licensee,
            'features': sorted(self.features),
            'issued': self.issued.isoformat(),
            'expires': self.expires.isoformat(),
            'status': 'expired' if self.is_expired(today) else 'valid',
        }


def canonical(payload):
    """The bytes that are signed."""
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def _date(payload, field):
    try:
        return date.fromisoformat(payload[field])
    except (KeyError, TypeError, ValueError):
        raise LicenseError(f'"{field}" must be a date (YYYY-MM-DD)')


def verify(text, public_keys=None):
    """Return the License in ``text``, or raise LicenseError.

    Expiry is not an error here: an expired key is still genuine, and the
    caller decides (``License.is_expired``).
    """
    if not isinstance(text, str) or not text.strip():
        raise LicenseError('The license key is empty')
    if len(text) > MAX_LENGTH:
        raise LicenseError('The license key is too long')
    try:
        doc = json.loads(text)
    except ValueError:
        raise LicenseError('The license key is not valid JSON')
    if not isinstance(doc, dict) or doc.get('format') != FORMAT:
        raise LicenseError('Unknown license key format')
    payload, signature = doc.get('payload'), doc.get('signature')
    if not isinstance(payload, dict) or not isinstance(signature, str):
        raise LicenseError('The license key needs a payload and a signature')
    try:
        signature_bytes = base64.b64decode(signature, validate=True)
    except (binascii.Error, ValueError):
        raise LicenseError('The signature is not valid base64')

    message = canonical(payload)
    for encoded in (keys.PUBLIC_KEYS if public_keys is None else public_keys):
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(encoded)).verify(signature_bytes, message)
            break
        except InvalidSignature:
            continue
    else:
        raise LicenseError('The signature does not match: this is not a genuine SerOps license key, or it was edited')

    license_id, licensee, features = payload.get('id'), payload.get('licensee'), payload.get('features')
    if not isinstance(license_id, str) or not license_id:
        raise LicenseError('"id" is missing')
    if not isinstance(licensee, str) or not licensee.strip():
        raise LicenseError('"licensee" is missing')
    if not isinstance(features, list) or not all(isinstance(f, str) for f in features):
        raise LicenseError('"features" must be a list of feature names')
    issued, expires = _date(payload, 'issued'), _date(payload, 'expires')
    if expires < issued:
        raise LicenseError('"expires" is before "issued"')
    return License(
        id=license_id,
        licensee=licensee.strip(),
        features=frozenset(f for f in features if f in FEATURES),
        issued=issued,
        expires=expires,
    )
