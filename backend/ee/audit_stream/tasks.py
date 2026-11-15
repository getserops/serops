"""Celery tasks of audit streaming (queue ``normal``; see api/celery.py)."""
from celery import shared_task


@shared_task(ignore_result=True)
def deliver_destination(destination_id):
    from .service import deliver
    return deliver(destination_id)


@shared_task(ignore_result=True)
def deliver_due():
    from .service import deliver_due as run
    return run()
