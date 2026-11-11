"""The installed license, and the provider Community asks.

Every check reads the license row (one tiny indexed query), so installing or
removing a key takes effect at once in every web and Celery process. The
signature is verified again only when the row changes.
"""

import logging

from django.db import DatabaseError

from .features import FEATURES
from .verify import LicenseError, verify

logger = logging.getLogger(__name__)

# (row id, installed_at) -> (License or None, error or None)
_verified = {}


def clear_cache():
    _verified.clear()


def current():
    """(License or None, error message or None) for the installed key."""
    from ee.models import InstalledLicense
    try:
        row = InstalledLicense.objects.order_by('-installed_at').only('id', 'installed_at', 'raw').first()
    except DatabaseError:
        # Migrations not applied yet: no license, nothing else affected.
        logger.warning('Enterprise license table unavailable; Enterprise features are off')
        return None, None
    if row is None:
        return None, None
    key = (row.id, row.installed_at)
    if key not in _verified:
        _verified.clear()
        try:
            _verified[key] = (verify(row.raw), None)
        except LicenseError as exc:
            # Stored keys were verified on upload; this only happens if the
            # signing keys were rotated past it. Treat as no license.
            logger.warning('Installed Enterprise license is no longer valid: %s', exc)
            _verified[key] = (None, str(exc))
    return _verified[key]


def summary():
    lic, error = current()
    if lic is not None:
        info = lic.as_dict()
        info['feature_labels'] = {code: FEATURES[code] for code in info['features']}
        return info
    if error:
        return {'status': 'invalid', 'error': error}
    return {'status': 'none'}


class _Provider:
    """Registered with Utils.edition by ee/apps.py."""

    def licensed_features(self):
        lic, _ = current()
        if lic is None or lic.is_expired():
            return frozenset()
        return lic.features

    def license_summary(self):
        return summary()


provider = _Provider()
