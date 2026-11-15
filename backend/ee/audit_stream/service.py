"""Audit streaming (Enterprise, feature ``audit_streaming``): queue and deliver.

Transactional outbox. When an audit entry is saved, one ``AuditStreamPending``
row per enabled destination of its organisation is written in the same
transaction (``on_audit_saved``), and delivery is kicked off once it
commits. An entry that rolls back is never sent; an entry that commits is
sent at least once, whatever the order transactions commit in.

Delivery (``deliver``) sends a destination's due events in id order, in
batches, one destination at a time (a row lock), and deletes them once the
destination accepted them. On failure the batch stays queued with an
exponential backoff (30 s, doubling, at most an hour), and the beat task
``ee.audit_stream.tasks.deliver_due`` retries every minute. Nothing is
dropped: an event leaves the queue when it is delivered, or when the audit
entry itself is deleted by the retention policy.

Without the license nothing is queued and nothing is sent; queued events
wait, and go out when a license with ``audit_streaming`` is installed.
"""
import datetime
import logging

from django.db import transaction
from django.utils import timezone

from Utils import crypto, edition

logger = logging.getLogger(__name__)

FEATURE = 'audit_streaming'
BATCH = 200
MAX_BATCHES_PER_RUN = 25
BACKOFF_START = 30
BACKOFF_MAX = 3600


def has_license():
    return edition.has_feature(FEATURE)


# --- secrets -------------------------------------------------------------------

def secret(value):
    """Decrypt a stored secret; '' when empty or unreadable (reported, never raised)."""
    if not value:
        return ''
    try:
        return crypto.decrypt(value)
    except crypto.DecryptionError:
        logger.error('Audit stream: a stored secret cannot be decrypted (wrong SEROPS_ENCRYPTION_KEY?)')
        return ''


# --- queueing ------------------------------------------------------------------

def on_audit_saved(sender, instance, created, raw=False, **kwargs):
    """post_save of Data.AuditLog: queue the entry for each enabled destination."""
    if not created or raw:
        return
    from ee.models import AuditStreamDestination, AuditStreamPending
    ids = list(AuditStreamDestination.objects.filter(organisation_id=instance.organisation_id, enabled=True)
               .values_list('pk', flat=True))
    if not ids or not has_license():
        return
    now = timezone.now()
    AuditStreamPending.objects.bulk_create(
        [AuditStreamPending(destination_id=d, audit_log_id=instance.pk, next_attempt_at=now) for d in ids],
        ignore_conflicts=True)
    transaction.on_commit(lambda: kick(ids))


def kick(destination_ids):
    """Ask a worker to deliver now; the beat task covers a broker that is down."""
    from .tasks import deliver_destination
    for pk in destination_ids:
        try:
            deliver_destination.delay(pk)
        except Exception as exc:  # broker unavailable: the next beat tick delivers
            logger.warning('Audit stream: could not queue delivery for destination %s (%s)', pk, exc)


# --- delivery ------------------------------------------------------------------

def send(destination, events):
    """Send events to a destination. Raises transports.DeliveryError."""
    from . import transports
    if destination.kind == destination.KIND_HTTP:
        header = None
        if destination.auth_header_name:
            header = (destination.auth_header_name, secret(destination.auth_header_value_encrypted))
        return transports.send_http(destination.url, events, fmt=destination.http_format, auth_header=header,
                                    signing_secret=secret(destination.signing_secret_encrypted) or None,
                                    ca_pem=destination.ca_certificate)
    return transports.send_syslog(destination.host, destination.port, destination.transport, events,
                                  ca_pem=destination.ca_certificate)


def backoff(attempts):
    return min(BACKOFF_START * 2 ** max(attempts - 1, 0), BACKOFF_MAX)


def deliver(destination_id, *, now=None):
    """Deliver the due events of one destination. Returns how many were delivered."""
    from ee.models import AuditStreamDestination, AuditStreamPending
    from . import events as wire
    from .transports import DeliveryError
    if not has_license():
        return 0
    delivered = 0
    for _ in range(MAX_BATCHES_PER_RUN):
        current = now or timezone.now()
        with transaction.atomic():
            # One delivery per destination at a time keeps events in order.
            # FOR NO KEY UPDATE: new outbox rows only take KEY SHARE on the
            # destination (their foreign key), so audit writes never wait
            # for a slow send.
            destination = (AuditStreamDestination.objects.select_for_update(skip_locked=True, no_key=True)
                           .filter(pk=destination_id, enabled=True).first())
            if destination is None:
                return delivered
            batch = list(AuditStreamPending.objects.filter(destination=destination, next_attempt_at__lte=current)
                         .select_related('audit_log__organisation', 'audit_log__user')
                         .order_by('audit_log_id')[:BATCH])
            if not batch:
                return delivered
            try:
                send(destination, [wire.event(p.audit_log) for p in batch])
            except DeliveryError as exc:
                attempts = max(p.attempts for p in batch) + 1
                retry_at = current + datetime.timedelta(seconds=backoff(attempts))
                AuditStreamPending.objects.filter(pk__in=[p.pk for p in batch]).update(
                    attempts=attempts, next_attempt_at=retry_at)
                AuditStreamDestination.objects.filter(pk=destination.pk).update(
                    last_failure_at=current, last_error=str(exc)[:500])
                logger.warning('Audit stream %s: %s (retry in %ss)', destination.pk, exc, backoff(attempts))
                return delivered
            AuditStreamPending.objects.filter(pk__in=[p.pk for p in batch]).delete()
            AuditStreamDestination.objects.filter(pk=destination.pk).update(
                last_success_at=current, last_error='', delivered_count=destination.delivered_count + len(batch))
            delivered += len(batch)
    return delivered


def deliver_due():
    """Every destination with something due (the beat task)."""
    from ee.models import AuditStreamPending
    if not has_license():
        return 0
    ids = (AuditStreamPending.objects.filter(next_attempt_at__lte=timezone.now(), destination__enabled=True)
           .values_list('destination_id', flat=True).distinct())
    return sum(deliver(pk) for pk in list(ids))


def status(destination):
    """Queue state shown in Settings: how many events wait, and since when."""
    from ee.models import AuditStreamPending
    pending = AuditStreamPending.objects.filter(destination=destination)
    oldest = pending.order_by('audit_log_id').select_related('audit_log').first()
    return {'pending': pending.count(),
            'oldest_pending_at': oldest.audit_log.created_at.isoformat() if oldest else None}
