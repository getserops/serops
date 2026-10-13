"""Flux CD native webhook handler — Item #16.

Flux's ``notification-controller`` fires webhooks on
``Kustomization`` / ``HelmRelease`` / ``GitRepository`` events. This
handler accepts the native Flux ``Provider webhook`` payload and
translates to SerOps' canonical deployment shape.

Payload shape (Flux notification-controller v1.x)::

    {
      "involvedObject": {
        "kind": "Kustomization",
        "name": "my-app",
        "namespace": "flux-system"
      },
      "severity": "info",
      "reason": "ReconciliationSucceeded",
      "message": "Reconciliation finished in 2.1s, next run in 10m0s",
      "metadata": {
        "revision": "main@sha1:abc123def456..."
      },
      "timestamp": "2026-10-25T14:25:00Z",
      "reportingController": "kustomize-controller"
    }

Recorded only when ``severity == "info"`` and ``reason`` names a
successful reconciliation. Errors / drift / dry-runs are ignored so
"Recent Deployments" stays clean.

Revision format is ``<branch|tag>@sha1:<sha>``. We extract the sha
after ``sha1:``.

Environment resolution mirrors the ArgoCD handler:

1. ``metadata["serops.io/environment"]`` label if the user
   annotates their Kustomization.
2. Namespace of the involved object.
3. Fallback: ``production``.
"""

import logging
import re
from datetime import datetime

from django.utils import timezone

from .argocd_webhook import _map_env_alias
from .deployment_webhook import GenericDeploymentWebhookHandler, _PayloadError

logger = logging.getLogger(__name__)


# Success reasons we treat as a deployment. Flux emits many others
# (Progressing, ValidationFailed, DependencyNotReady) — we ignore.
_FLUX_SUCCESS_REASONS = {
    'ReconciliationSucceeded',
    'ProgressingWithReconciliation',   # some templates use this
    'HealthCheckPassed',
}


# Flux revisions are ``<ref>@sha1:<sha>`` (older) or ``<ref>@<algo>:<sha>``
# (newer builds with SHA-256 support). Capture whichever hash comes last.
_REVISION_RE = re.compile(r'(?:[^@]+@)?[a-z0-9]+:([a-fA-F0-9]{7,64})')


class FluxDeploymentWebhookHandler(GenericDeploymentWebhookHandler):
    """Accept Flux's native notification-controller payload."""

    def _parse_payload(self, request) -> dict:
        raw = self._read_json(request)

        severity = str(raw.get('severity') or '').lower()
        reason = str(raw.get('reason') or '')

        if severity and severity != 'info':
            raise _PayloadError(f'Ignored: severity is "{severity}" (not info)')
        if reason and reason not in _FLUX_SUCCESS_REASONS:
            raise _PayloadError(f'Ignored: reason "{reason}" is not a success signal')

        metadata = raw.get('metadata') or {}
        revision = str(metadata.get('revision') or '').strip()
        commit_sha = self._extract_sha(revision)
        if not commit_sha:
            raise _PayloadError(
                f'metadata.revision "{revision[:60]}" contains no recognisable commit sha'
            )

        involved = raw.get('involvedObject') or {}
        environment = self._resolve_environment(involved, metadata)

        deployed_at = self._parse_iso(raw.get('timestamp')) or timezone.now()

        # Reporting controller identifies which Flux sub-controller
        # emitted this — useful audit trail (kustomize-controller vs.
        # helm-controller vs. source-controller).
        controller = str(raw.get('reportingController') or 'flux')[:60]

        kind = str(involved.get('kind') or '')
        name = str(involved.get('name') or '')
        notes_parts = [f'flux-{kind.lower()}={name}'] if kind and name else []
        if revision and revision != commit_sha:
            notes_parts.append(f'revision={revision[:80]}')
        notes = ' '.join(notes_parts)[:500]

        return {
            'commit_sha': commit_sha,
            'environment': environment,
            'deployed_at': deployed_at,
            'actor': controller,
            'notes': notes,
        }

    # ------------------------------------------------------------------

    @staticmethod
    def _read_json(request) -> dict:
        import json
        try:
            return request.data if isinstance(request.data, dict) else json.loads(request.body)
        except (json.JSONDecodeError, TypeError, ValueError):
            raise _PayloadError('Body must be valid JSON')

    @staticmethod
    def _extract_sha(revision: str) -> str:
        if not revision:
            return ''
        m = _REVISION_RE.search(revision)
        return m.group(1) if m else ''

    @staticmethod
    def _resolve_environment(involved: dict, metadata: dict) -> str:
        # Flux notification-controller doesn't currently forward labels
        # by default; metadata is the payload's own key/value map, which
        # some templates enrich with custom keys.
        explicit = str(metadata.get('serops.io/environment') or '').strip().lower()
        if explicit:
            mapped = _map_env_alias(explicit)
            if mapped:
                return mapped
        ns = str(involved.get('namespace') or '').strip().lower()
        if ns:
            mapped = _map_env_alias(ns)
            if mapped:
                return mapped
        return 'production'

    @staticmethod
    def _parse_iso(value):
        if not value:
            return None
        try:
            v = str(value)
            dt = datetime.fromisoformat(v.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = timezone.make_aware(dt, timezone.utc)
            return dt
        except (TypeError, ValueError):
            return None
