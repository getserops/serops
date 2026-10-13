"""Verify SMTP config by sending a test email.

Replaces the "Send test email" button that used to live in
Settings → Email. Since SMTP is env-only (Grafana model), this is
now a CLI-only tool.

Usage:
    python manage.py check_smtp recipient@example.com
"""

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand, CommandError

from notifications.services import (
    get_email_connection,
    get_from_email,
    has_working_smtp_config,
)


class Command(BaseCommand):
    help = "Send a test email using the SMTP config from EMAIL_* env vars."

    def add_arguments(self, parser):
        parser.add_argument(
            'recipient',
            help='Address to send the test email to.',
        )

    def handle(self, *args, **opts):
        recipient = opts['recipient']

        self.stdout.write("=" * 60)
        self.stdout.write("SerOps SMTP check")
        self.stdout.write("=" * 60)
        self.stdout.write(f"EMAIL_HOST:         {getattr(settings, 'EMAIL_HOST', None) or '(unset)'}")
        self.stdout.write(f"EMAIL_PORT:         {getattr(settings, 'EMAIL_PORT', None) or '(unset)'}")
        self.stdout.write(f"EMAIL_HOST_USER:    {getattr(settings, 'EMAIL_HOST_USER', None) or '(unset)'}")
        self.stdout.write(f"EMAIL_HOST_PASSWORD:{' (set)' if getattr(settings, 'EMAIL_HOST_PASSWORD', None) else ' (unset)'}")
        self.stdout.write(f"EMAIL_USE_TLS:      {getattr(settings, 'EMAIL_USE_TLS', False)}")
        self.stdout.write(f"EMAIL_USE_SSL:      {getattr(settings, 'EMAIL_USE_SSL', False)}")
        self.stdout.write(f"DEFAULT_FROM_EMAIL: {getattr(settings, 'DEFAULT_FROM_EMAIL', None) or '(unset)'}")
        self.stdout.write("")

        if not has_working_smtp_config():
            raise CommandError(
                "EMAIL_HOST is not set. Configure EMAIL_HOST (and related "
                "EMAIL_* vars) in your .env file, then restart the backend."
            )

        try:
            connection = get_email_connection()
            from_email = get_from_email()
            EmailMessage(
                subject="SerOps SMTP test",
                body=(
                    "If you received this, your SerOps SMTP configuration "
                    "is working. It's safe to delete this message."
                ),
                from_email=from_email,
                to=[recipient],
                connection=connection,
            ).send(fail_silently=False)
        except Exception as e:
            raise CommandError(f"Send failed: {e}")

        self.stdout.write(self.style.SUCCESS(
            f"Test email sent to {recipient}"
        ))
