"""Lifecycle-email helpers (activation, invitation, password reset).

All three functions route through :func:`notifications.services.get_email_connection`
and :func:`notifications.services.get_from_email` so they honor the same
SMTP resolution rules as notification emails — including
``PLATFORM_SMTP_ENFORCED``, which forces env-var-only SMTP on
multi-tenant SaaS hosts (prevents lifecycle-email hijack via
UI-configured SMTP).
"""

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.core import signing
import jwt
import logging

logger = logging.getLogger(__name__)


def _get_connection_and_from():
    """Lazy import to avoid circular import at module load."""
    from notifications.services import get_email_connection, get_from_email
    return get_email_connection(), get_from_email()


def send_activation_link(user, request):
    token = signing.dumps(user.id)
    activation_link = settings.API_URL + "/auth/activate/" + token

    subject = "Welcome to Serops!"
    html_message = render_to_string('accountActivationTemplate.html', {
        'user': user,
        'link': activation_link,
    })

    try:
        connection, from_email = _get_connection_and_from()
        email = EmailMessage(
            subject=subject,
            body=html_message,
            from_email=from_email,
            to=[user.email],
            connection=connection,
        )
        email.content_subtype = "html"
        email.send(fail_silently=False)
        logger.info('Activation email sent successfully')
    except Exception as e:
        logger.error(f'Activation email error: {e}')


def send_invitation_link(user):
    token_data = {
        'user': user.id,
        'organisation': user.organisation_id,
        'role': user.role,
    }
    token = jwt.encode(token_data, settings.SECRET_KEY, algorithm='HS256')
    activation_link = settings.REACT_URL + "/accept_invitation/" + str(token)
    subject = "Invitation to join your team on Serops!"

    html_message = render_to_string('acceptInvitationTemplate.html', {
        'user': user,
        'link': activation_link,
    })

    try:
        connection, from_email = _get_connection_and_from()
        email = EmailMessage(
            subject=subject,
            body=html_message,
            from_email=from_email,
            to=[user.email],
            connection=connection,
        )
        email.content_subtype = "html"
        email.send(fail_silently=False)
        logger.info('Invitation email sent successfully')
    except Exception as e:
        logger.error(f'Invitation email error: {e}')


def send_reset_password_link(email_addr, url):
    subject = "Password Reset Request Serops"
    body = f'Click the link below to reset password on your account: {url}'

    try:
        connection, from_email = _get_connection_and_from()
        email = EmailMessage(
            subject=subject,
            body=body,
            from_email=from_email,
            to=[email_addr],
            connection=connection,
        )
        # Default content_subtype is plain text, which matches the body
        email.send(fail_silently=False)
        logger.info('Password reset email sent successfully')
    except Exception as e:
        logger.error(f'Password reset email error: {e}')


def generate_token(user):
    return {
        'user': user.id,
        'organisation': user.organisation.id,
        'role': user.role,
    }
