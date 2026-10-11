"""Signal handlers wiring auto-creation of IntegrationScope rows.

Batch 48 — Deployment-model universal-topology rework. The one-shot
data migration seeds scopes from existing state; new integrations
created afterwards need their own scope row so ``_best_integration``
match-scoring works uniformly.

Fail-open: signal errors are logged, never propagated. A misbehaving
signal must not break integration creation.
"""

from __future__ import annotations

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import IntegrationScope, ObservabilityIntegration

logger = logging.getLogger(__name__)


@receiver(post_save, sender=ObservabilityIntegration)
def _create_scope_for_integration(sender, instance, created, **kwargs):
    """Auto-create scope row mirroring the integration's cluster on create.

    New integrations default to (cluster=integration.cluster, env='',
    region='', namespace='') — same shape the migration seeds for
    existing rows. UI edits (Batch 53) will let users add env / region
    / namespace tags later.
    """
    if not created:
        return
    try:
        IntegrationScope.objects.get_or_create(
            integration=instance,
            defaults={
                'cluster': instance.cluster,
                'environment': '',
                'region': '',
                'namespace': '',
            },
        )
    except Exception as exc:
        logger.warning(
            'Auto-create IntegrationScope failed for integration=%s: %s',
            instance.pk, exc,
        )
