"""Email dispatch helpers.

SMTP configuration is env-var-only (Grafana model): set ``EMAIL_HOST``
and friends in ``.env`` and restart. There is no UI-editable SMTP
config — the ``SystemMailSettings`` model + views + DB-based fallback
were removed 2026-09-01. Verify config with
``python manage.py check_smtp <recipient>``.
"""

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def has_working_smtp_config() -> bool:
    """Return True when ``EMAIL_HOST`` is set.

    Used by ``Users.views.RegisterView`` to decide whether the first
    user should auto-activate (no SMTP) or receive a verification email
    (SMTP configured).
    """
    return bool(getattr(settings, 'EMAIL_HOST', None))


def get_email_connection():
    """Django's env-backed SMTP connection.

    Kept as a helper so callers stay one call away from the connection
    without importing Django internals directly — this is where any
    future connection-level customisation (retries, backends, etc.)
    would land.
    """
    return get_connection()


def get_from_email(organisation=None):
    """Build the From address, optionally with a per-org sender name.

    Returns RFC 5322 format (``"Sender Name" <email>``) when a name is
    available; otherwise the raw ``DEFAULT_FROM_EMAIL``.

    The per-org sender name is a NotificationSettings display label,
    not an SMTP account — it's safe to keep customer-configurable
    even in multi-tenant deployments (the actual From-address host
    is always the platform's).
    """
    base_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@serops.ai')

    sender_name = ''
    if organisation:
        try:
            from org_settings.models import NotificationSettings
            ns = NotificationSettings.objects.filter(
                organisation=organisation
            ).values_list('sender_name', flat=True).first()
            if ns:
                sender_name = ns
        except Exception:
            pass

    if sender_name:
        return f'"{sender_name}" <{base_email}>'
    return base_email


def send_notification_email(user_email, subject, context, template_name, organisation=None):
    """Send an HTML+text email using env-configured SMTP.

    Returns True on success, False on failure (logged but not raised —
    notification pipelines shouldn't crash the caller).
    """
    try:
        html_content = render_to_string(template_name, context)
        text_content = strip_tags(html_content)

        from_email = get_from_email(organisation)
        connection = get_email_connection()

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=from_email,
            to=[user_email],
            reply_to=[from_email],
            connection=connection,
        )
        email.attach_alternative(html_content, "text/html")

        email.send(fail_silently=False)
        logger.debug(f"Email sent to {user_email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email to {user_email}: {str(e)}", exc_info=True)
        return False
