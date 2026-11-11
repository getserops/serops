"""
Which Enterprise features this install may use.

Community code asks this module and never imports ``ee``. When the
Enterprise directory (``backend/ee/``) is present, its Django app registers a
provider at startup; without it, or without a valid license key, no
Enterprise feature is licensed and SerOps runs as the complete Community
edition.

    from Utils import edition
    if edition.has_feature('saml'):
        ...

A provider is any object with ``licensed_features()`` (an iterable of feature
codes) and ``license_summary()`` (a dict for the UI, never the key itself).
"""

import logging

logger = logging.getLogger(__name__)

_provider = None


def register(provider):
    """Called once by the Enterprise app (ee/apps.py) at startup."""
    global _provider
    _provider = provider


def enterprise_available():
    """True when the Enterprise code is installed (licensed or not)."""
    return _provider is not None


def licensed_features():
    """The Enterprise features the installed license enables (empty without one).

    A failure in the provider never reaches Community code: it means no
    Enterprise feature, logged, and everything else keeps working.
    """
    if _provider is None:
        return frozenset()
    try:
        return frozenset(_provider.licensed_features())
    except Exception:
        logger.exception('Enterprise license check failed; Enterprise features are off')
        return frozenset()


def has_feature(code):
    """True when the Enterprise feature ``code`` is licensed on this install."""
    return code in licensed_features()


def summary():
    """What the UI shows about the edition (GET /api/organisation/edition/)."""
    license_info = None
    if _provider is not None:
        try:
            license_info = _provider.license_summary()
        except Exception:
            logger.exception('Enterprise license summary failed')
    return {
        'enterprise_available': enterprise_available(),
        'features': sorted(licensed_features()),
        'license': license_info,
    }


LICENSE_REQUIRED = 'enterprise_license_required'


class LicenseRequired(PermissionError):
    """Raised where Community code meets an Enterprise-only action."""

    def __init__(self, feature):
        self.feature = feature
        super().__init__(f'This needs a SerOps Enterprise license with "{feature}".')


def license_error(feature):
    """The 403 body for an Enterprise-only action (the app shows an upgrade note)."""
    return {
        'error': f'This needs a SerOps Enterprise license with "{feature}". '
                 'What already exists keeps working and can be removed.',
        'code': LICENSE_REQUIRED,
        'feature': feature,
    }


def require(feature):
    """Raise ``LicenseRequired`` unless ``feature`` is licensed."""
    if not has_feature(feature):
        raise LicenseRequired(feature)
