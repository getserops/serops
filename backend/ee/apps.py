from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured


class EnterpriseConfig(AppConfig):
    name = 'ee'
    label = 'ee'
    verbose_name = 'SerOps Enterprise'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        from Utils import edition
        from ee.licensing.store import provider
        edition.register(provider)
        edition.register_sso_protocol('saml', load_saml_protocol())
        load_scim()
        load_audit_streaming()
        from ee import checks  # noqa: F401  (registers the system checks)


def load_saml_protocol():
    """The SAML handler, or a startup failure that says what is missing.

    Never skipped: without python3-saml and its xmlsec/lxml wheels (both in
    requirements.txt) the backend refuses to start rather than run with the
    SAML routes answering 404. The licence is read after startup, so this
    fails whether or not the licence includes ``saml``.
    """
    try:
        from ee.saml.service import SamlProtocol
    except Exception as exc:  # ImportError, or xmlsec.Error on a libxml2 mismatch
        raise ImproperlyConfigured(
            'SerOps Enterprise SAML cannot load python3-saml/xmlsec '
            f'({exc.__class__.__name__}: {exc}). Install backend/requirements.txt '
            '(xmlsec and lxml must share one libxml2 version).') from exc
    return SamlProtocol()


def load_scim():
    """Import the SCIM endpoints at startup, or stop with what is missing.

    SCIM needs nothing outside requirements.txt; this makes a broken install
    fail when the backend starts, not as a 404 or 500 during the identity
    provider's next sync.
    """
    try:
        from ee.scim import protocol, service, views  # noqa: F401
    except Exception as exc:
        raise ImproperlyConfigured(
            f'SerOps Enterprise SCIM cannot load ({exc.__class__.__name__}: {exc}). '
            'Install backend/requirements.txt.') from exc


def load_audit_streaming():
    """Connect audit streaming to the audit log, or stop with what is missing.

    The receiver queues each new audit entry for the organisation's
    destinations in the same transaction (see ee.audit_stream.service); the
    tasks module is imported so workers know the delivery tasks.
    """
    try:
        from django.db.models.signals import post_save

        from Data.models import AuditLog
        from ee.audit_stream import service, tasks, transports, views  # noqa: F401
    except Exception as exc:
        raise ImproperlyConfigured(
            f'SerOps Enterprise audit streaming cannot load ({exc.__class__.__name__}: {exc}). '
            'Install backend/requirements.txt.') from exc
    post_save.connect(service.on_audit_saved, sender=AuditLog, dispatch_uid='ee.audit_stream')
