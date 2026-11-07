"""Deleting an organisation that is still receiving telemetry.

Its collectors keep sending traces with its ingest key, and the scheduler
keeps writing batches: a row inserted after Django collected what to cascade
made the final DELETE fail on a foreign key, and "Delete organisation" and
"Delete my account" answered 500 for as long as the apps kept sending.
"""
import logging
import time

from django.db import IntegrityError, transaction

logger = logging.getLogger(__name__)


# Traces (with their spans) deleted per round when purging an organisation.
TELEMETRY_CHUNK = 5000


def _purge_telemetry(organisation, chunk: int = TELEMETRY_CHUNK) -> None:
    """Delete the organisation's spans and traces in chunks, in the database.

    A few days of OTLP ingestion is millions of rows; Django's cascade
    loaded them all into the process, which the backend's memory limit
    killed (1.5 M traces and 4.5 M spans in the journey suite), so the
    deletion never finished. Nothing references spans or traces, so they
    are removed with raw DELETEs before the cascade runs.
    """
    from traces.models import Span, Trace

    # One round per chunk of trace ids (organisation index), their spans
    # through the trace foreign key index, then the traces: a span query
    # joined to traces scanned millions of rows each round.
    while True:
        ids = list(Trace.objects.filter(organisation=organisation).values_list('pk', flat=True)[:chunk])
        if not ids:
            break
        Span.objects.filter(trace_id__in=ids)._raw_delete(Span.objects.db)
        Trace.objects.filter(pk__in=ids)._raw_delete(Trace.objects.db)


def delete_organisation(organisation, attempts: int = 5) -> None:
    """Stop accepting the organisation's telemetry, then delete it.

    The ingest keys are deactivated, then the organisation and its projects
    are locked (SELECT ... FOR UPDATE): an insert that references them waits
    for the lock and then fails on the deleted row, instead of slipping in
    between Django's collection and the DELETE. When this is the outermost
    transaction, a late row is also retried.
    """
    from Organisations.models import Organisations
    from Projects.models import Project
    from traces.models import IngestKey

    IngestKey.objects.filter(organisation=organisation).update(is_active=False)
    _purge_telemetry(organisation)
    for attempt in range(1, attempts + 1):
        try:
            with transaction.atomic():
                list(Organisations.objects.select_for_update().filter(pk=organisation.pk).values_list('pk'))
                list(Project.objects.select_for_update().filter(organisation=organisation).values_list('pk'))
                organisation.delete()
            return
        except IntegrityError as exc:
            if attempt == attempts:
                raise
            logger.warning("Organisation %s: a row arrived during deletion (%s); retrying",
                           organisation.pk, str(exc).splitlines()[0])
            time.sleep(0.5 * attempt)
