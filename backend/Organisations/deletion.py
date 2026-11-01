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
