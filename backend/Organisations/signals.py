"""Onboarding + capability-cache signal handlers.

Wired up in :meth:`OrganisationsConfig.ready`. Kept out of models.py
to avoid the AppConfig import-time cycle (signal receivers reference
models from other apps).
"""

import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from . import capability_registry

logger = logging.getLogger(__name__)


@receiver(post_save, sender='Projects.ProjectService')
def dispatch_first_analysis_on_service_link(sender, instance, created, **kwargs):
    """Fire the first batch analysis as soon as an org links its first service.

    Rationale (Sentry / Datadog onboarding pattern): the wizard's
    "waiting for first analysis" step is the aha moment. Waiting for
    the normal 10-min Celery beat pushes TTV past the 30-min
    abandonment cliff. Dispatching immediately on ``ProjectService``
    create drops it to seconds.

    Guarantees:

    - Only fires when the ``ProjectService`` is newly created (not on
      subsequent saves).
    - Only fires once per org during onboarding — the
      ``first_analysis_dispatched_at`` marker in ``onboarding_data``
      is our idempotency key. If the user creates a second service
      before the first analysis returns, we don't queue a duplicate.
    - Skipped once the org's onboarding is fully complete — post-
      onboarding, batches are scheduled by the normal beat.
    - Best-effort — any exception is logged and swallowed. A failed
      dispatch must not roll back the ProjectService.save() the user
      just made.
    """
    if not created:
        return

    try:
        from .models import OnboardingStatus

        project = getattr(instance, 'project', None)
        organisation = getattr(project, 'organisation', None) if project else None
        if organisation is None:
            return

        onboarding = OnboardingStatus.get_or_create_for_org(organisation)
        if onboarding.is_completed:
            # Post-onboarding — normal beat handles it.
            return

        data = onboarding.onboarding_data or {}
        if data.get('first_analysis_dispatched_at'):
            # Already fired this run; don't queue another.
            return

        # Pick an environment: prefer the project's first active env,
        # fall back to whatever the batch task's env-detection can
        # figure out from the logs themselves.
        env = None
        try:
            env_qs = project.environments.filter(is_active=True).order_by('id')
            env = env_qs.first()
        except Exception:
            env = None

        # Dispatch async so the caller (a ProjectService POST view)
        # returns immediately and the user's browser stays snappy.
        from Data.tasks import create_log_batch_with_project_name
        create_log_batch_with_project_name.delay(
            project_name=project.name,
            project=project.id,
            environment=env.id if env else None,
        )

        # Mark dispatched — idempotency guard for future post_saves.
        data['first_analysis_dispatched_at'] = timezone.now().isoformat()
        data['first_analysis_project_id'] = project.id
        data['first_analysis_service_id'] = instance.id
        onboarding.store_data(data)

        logger.info(
            f"First-analysis dispatch: org={organisation.id} "
            f"project={project.id} service={instance.id}"
        )
    except Exception as exc:
        # Never let a signal-handler bug block ProjectService creation.
        logger.warning(f"First-analysis dispatch failed: {exc}", exc_info=True)


# ---------------------------------------------------------------------------
# Capability-cache invalidation (Q2.3)
# ---------------------------------------------------------------------------
#
# Four model classes drive what capabilities an org has: ``ObservabilityIntegration``
# (logs/metrics/traces adapters), ``IngestKey`` (OTLP trace receiver),
# ``SCMBinding`` (code capability), ``CICDBinding`` (cicd capability).
# Every create / update / delete on those tables must invalidate the
# cached result so the next capability lookup rebuilds against reality.
#
# The receivers dispatch on lazy string senders (``'app.Model'``) so
# this module never imports the target models directly — keeps the
# AppConfig import graph acyclic and lets Organisations.apps.ready()
# hook them in early without waiting for the referenced apps.


def _invalidate_from_org_sender(instance):
    """Invalidate for any model whose row has an ``organisation`` FK.

    Covers ``ObservabilityIntegration`` and ``IngestKey`` — both carry
    the org directly and flip org-wide capabilities.
    """
    org_id = getattr(instance, 'organisation_id', None)
    if org_id is not None:
        capability_registry.invalidate_org(org_id)


def _invalidate_from_binding_sender(instance):
    """Invalidate for a binding — resolves project + org from the FK chain.

    Covers ``SCMBinding`` and ``CICDBinding``. Both hang off
    ``ProjectService`` which points at ``Project`` which points at
    ``Organisations``; either level can move a capability. The lookup
    is a best-effort resolve — if the chain is already partially
    torn down (post_delete on a cascade), we fall back to blowing the
    org cache only.
    """
    project_id = None
    org_id = None
    service = getattr(instance, 'project_service', None)
    if service is not None:
        project = getattr(service, 'project', None)
        if project is not None:
            project_id = getattr(project, 'id', None)
            org_id = getattr(project, 'organisation_id', None)
    if project_id is not None:
        capability_registry.invalidate_project(project_id, org_id=org_id)
    elif org_id is not None:
        capability_registry.invalidate_org(org_id)


@receiver(post_save, sender='integrations.ObservabilityIntegration')
@receiver(post_delete, sender='integrations.ObservabilityIntegration')
def _cap_invalidate_observability(sender, instance, **kwargs):
    _invalidate_from_org_sender(instance)


@receiver(post_save, sender='traces.IngestKey')
@receiver(post_delete, sender='traces.IngestKey')
def _cap_invalidate_ingest_key(sender, instance, **kwargs):
    _invalidate_from_org_sender(instance)


@receiver(post_save, sender='Projects.SCMBinding')
@receiver(post_delete, sender='Projects.SCMBinding')
def _cap_invalidate_scm_binding(sender, instance, **kwargs):
    _invalidate_from_binding_sender(instance)


@receiver(post_save, sender='Projects.CICDBinding')
@receiver(post_delete, sender='Projects.CICDBinding')
def _cap_invalidate_cicd_binding(sender, instance, **kwargs):
    _invalidate_from_binding_sender(instance)
