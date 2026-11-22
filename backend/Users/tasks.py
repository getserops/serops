"""Periodic account housekeeping."""
import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def delete_expired_auth_tokens():
    """Delete Knox tokens past their expiry (audit 2026-11-20, item 15).

    Authentication skips expired tokens without deleting them, so every
    expired session, including each visit to the public demo, stayed in the
    table. Returns the number deleted.
    """
    from knox.models import AuthToken
    deleted, _ = AuthToken.objects.filter(expiry__lt=timezone.now()).delete()
    if deleted:
        logger.info("Deleted %d expired sign-in tokens", deleted)
    return deleted
