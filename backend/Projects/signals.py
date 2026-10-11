"""Signal handlers wiring auto-creation of ProjectDeployment rows.

Batch 48 (Deployment-model universal-topology rework). The one-shot
data migration seeds deployments from existing state, but new envs +
new projects created AFTER migration need their own deployments.
Signals close that loop so the "batches run per deployment" invariant
holds regardless of creation path.

Two triggers:

* ``post_save(ProjectEnvironment)`` with created=True — the common
  case. Auto-creates a deployment matching (project × env ×
  project.cluster). Runs for envs made via the API, the onboarding
  wizard, ``create_default_environments``, and direct ORM (tests,
  seed scripts).

* ``post_save(Project)`` with created=True — fallback for projects
  created without any envs (rare — legacy shape). Creates a single
  deployment with env=None so the batch pipeline still routes.

Fail-open: signal errors are logged, never propagated. A misbehaving
signal must not break project creation.
"""

from __future__ import annotations

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Project, ProjectDeployment, ProjectEnvironment

logger = logging.getLogger(__name__)


@receiver(post_save, sender=ProjectEnvironment)
def _create_deployment_for_env(sender, instance, created, **kwargs):
    """Auto-create the matching deployment when a new env is added."""
    if not created:
        return
    if not instance.is_active:
        # Inactive envs don't produce batches, so no deployment needed.
        # If the env is later activated the caller must create the
        # deployment explicitly (UI flow, Batch 52).
        return
    try:
        ProjectDeployment.objects.get_or_create(
            project=instance.project,
            environment=instance,
            cluster=instance.project.cluster,
            region='',
            namespace='',
            defaults={'is_active': True},
        )
    except Exception as exc:
        logger.warning(
            'Auto-create ProjectDeployment failed for env=%s: %s',
            instance.pk, exc,
        )


# Project.post_save was tempting for "auto-create default deployment"
# but fires BEFORE any env-creation callers add envs, so we ended up
# with 2 deployments per project (one env=None from this handler +
# one env-scoped from the env handler). The batch pipeline's own
# fallback path (create_batches_for_all_projects logs a warning +
# creates a legacy env-less batch when deployments.count() == 0)
# already covers the "project without envs" case correctly. Removed.
