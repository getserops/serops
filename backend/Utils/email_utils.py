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
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def _get_connection_and_from():
    """Lazy import to avoid circular import at module load."""
    from notifications.services import get_email_connection, get_from_email
    return get_email_connection(), get_from_email()


def send_activation_link(user, request):
    """Email the activation link; True when the mail server accepted it."""
    token = signing.dumps(user.id)
    activation_link = settings.API_URL + "/auth/activate/" + token

    subject = "Welcome to SerOps"
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
        return True
    except Exception as e:
        logger.error(f'Activation email error: {e}')
        return False


INVITATION_TTL_DAYS = int(os.getenv('INVITATION_TTL_DAYS', '7'))


def _password_fingerprint(user):
    """Changes whenever the user's password changes (set, reset, made unusable)."""
    return hashlib.sha256(f'{user.pk}:{user.password}'.encode()).hexdigest()[:16]


def make_invitation_token(user):
    """Signed invitation token: expires, and stops working once a password is set.

    It used to carry no expiry and stayed valid after use, so anyone holding an
    old invitation email could reset that account's password at any time
    (found by the journey suite, launch plan 9.9).
    """
    now = datetime.now(timezone.utc)
    token_data = {
        'user': user.id,
        'organisation': user.organisation_id,
        'role': user.role,
        'pwf': _password_fingerprint(user),
        'iat': int(now.timestamp()),
        'exp': int((now + timedelta(days=INVITATION_TTL_DAYS)).timestamp()),
    }
    return jwt.encode(token_data, settings.SECRET_KEY, algorithm='HS256')


def read_invitation_token(token):
    """The invited user, or raise jwt.InvalidTokenError (expired, tampered, used)."""
    from django.contrib.auth import get_user_model
    decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'], options={'require': ['exp']})
    user = get_user_model().objects.filter(pk=decoded.get('user')).first()
    if user is None:
        raise get_user_model().DoesNotExist
    if decoded.get('pwf') != _password_fingerprint(user):
        raise jwt.InvalidTokenError('invitation already used')
    return user


def send_invitation_link(user, invited_by=None):
    token = make_invitation_token(user)
    activation_link = settings.REACT_URL + "/accept_invitation/" + str(token)
    # Who invited them and to which organisation (journey suite, E3).
    organisation = getattr(getattr(user, 'organisation', None), 'name', '') or ''
    inviter = ''
    if invited_by is not None:
        inviter = invited_by.get_full_name().strip() or invited_by.email
    subject = (f"You're invited to join {organisation} on SerOps" if organisation
               else "You're invited to join your team on SerOps")

    html_message = render_to_string('acceptInvitationTemplate.html', {
        'user': user,
        'link': activation_link,
        'organisation': organisation,
        'inviter': inviter,
        'ttl_days': INVITATION_TTL_DAYS,
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
    subject = "Reset your SerOps password"
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
