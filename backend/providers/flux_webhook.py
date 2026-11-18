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

Recorded as a deploy only when the event shows the apply changed
something: kustomize-controller's change set ("Deployment/ns/x
configured") or a helm-controller install/upgrade/rollback. A reconcile
that changed nothing ("Reconciliation finished …"), progress and
dependency notices are answered 200 "ignored". An error event (a
rejected apply) is recorded as a failed deployment.

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

from .argocd_webhook import _env_from_name, _map_env_alias
from .deployment_webhook import GenericDeploymentWebhookHandler, _IgnoredEvent, _PayloadError

logger = logging.getLogger(__name__)


# What counts as a deploy (client C4, Flux 2.7 monorepo):
# - kustomize-controller lists what an apply changed, one object per line
#   ("Deployment/studio/pricing configured", "Namespace/studio created"), in
#   an info event whose reason is the Ready reason at the time (usually
#   "Progressing"). Every Kustomization of a monorepo also reports
#   "Reconciliation finished in 2.1s, next run in 10m0s" with the new
#   revision on ANY commit: that is not a deploy, or a pricing-only commit
#   is recorded as a deploy of every service.
# - helm-controller reports InstallSucceeded / UpgradeSucceeded /
#   RollbackSucceeded for a release it changed.
_CHANGESET_RE = re.compile(r'^\s*[\w.-]+/(?:[\w.-]+/)?[\w.:-]+\s+(?:created|configured|deleted)\b',
                           re.MULTILINE)
_HELM_DEPLOY_REASONS = {'InstallSucceeded', 'UpgradeSucceeded', 'RollbackSucceeded'}

# Flux revisions are ``<ref>@sha1:<sha>`` (older) or ``<ref>@<algo>:<sha>``
# (newer builds with SHA-256 support). Capture whichever hash comes last.
# Applied to the part after the last '@', anchored: no backtracking on a
# hostile body (CodeQL py/polynomial-redos).
_REVISION_RE = re.compile(r'[a-z0-9]+:([a-fA-F0-9]{7,64})')


class FluxDeploymentWebhookHandler(GenericDeploymentWebhookHandler):
    """Accept Flux's native notification-controller payload."""

    def _parse_payload(self, request) -> dict:
        raw = self._read_json(request)

        severity = str(raw.get('severity') or '').lower()
        reason = str(raw.get('reason') or '')
        message = str(raw.get('message') or '')
        metadata = raw.get('metadata') or {}
        if not isinstance(metadata, dict):
            raise _PayloadError('metadata must be an object')

        # A failed apply is recorded as a failed deployment, so the analysis
        # learns a change was attempted and rejected (client C4 L9: "dry-run
        # failed (Invalid)" answered 400 and recorded nowhere).
        if severity == 'error':
            deploy_status = 'failed'
        elif severity and severity != 'info':
            raise _IgnoredEvent(f'Ignored: severity "{severity}"')
        elif _CHANGESET_RE.search(message) or reason in _HELM_DEPLOY_REASONS:
            deploy_status = 'success'
        else:
            # "Reconciliation finished … next run in …", DependencyNotReady,
            # Progressing without a change set, health checks: not a deploy.
            raise _IgnoredEvent(f'Ignored: no change applied (reason "{reason[:60]}")')

        # A HelmRelease's revision is its chart version; the Git commit is
        # in originRevision (Flux 2.2+) when the chart comes from Git.
        revision = str(metadata.get('revision') or '').strip()
        commit_sha = self._extract_sha(revision)
        if not commit_sha:
            origin = str(metadata.get('originRevision') or '').strip()
            commit_sha = self._extract_sha(origin)
            if commit_sha:
                revision = origin
        if not commit_sha:
            raise _IgnoredEvent(
                f'Ignored: revision "{revision[:60]}" names no Git commit'
            )

        involved = raw.get('involvedObject') or {}
        environment, env_source = self._resolve_environment(involved, metadata)

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
        if env_source == 'default':
            notes_parts.append('environment=assumed-production')
        if deploy_status == 'failed':
            # What the controller said, so the analysis can quote it.
            notes_parts.append(f'failed ({reason[:40] or "error"}): ' + ' '.join(message.split())[:300])
        notes = ' '.join(notes_parts)[:500]

        return {
            'commit_sha': commit_sha,
            'environment': environment,
            'deployed_at': deployed_at,
            'actor': controller,
            'notes': notes,
            'status': deploy_status,
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
        m = _REVISION_RE.match(revision.rsplit('@', 1)[-1])
        return m.group(1) if m else ''

    @staticmethod
    def _resolve_environment(involved: dict, metadata: dict):
        """``(environment, source)``. ``involvedObject.namespace`` is usually
        ``flux-system``, so the Kustomization or HelmRelease name is read
        before it (SC-09)."""
        # Flux notification-controller doesn't currently forward labels
        # by default; metadata is the payload's own key/value map, which
        # some templates enrich with custom keys.
        explicit = str(metadata.get('serops.io/environment') or '').strip().lower()
        if explicit:
            # Kept as named when the alias map does not know it (SC-08): an
            # explicit environment is not overridden by the namespace.
            from .deployment_service import canonical_environment
            return _map_env_alias(explicit) or canonical_environment(explicit), 'annotation'
        for source, value in (
            ('name', _env_from_name(involved.get('name'))),
            ('namespace', _map_env_alias(str(involved.get('namespace') or '').strip().lower())),
        ):
            if value:
                return value, source
        return 'production', 'default'

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
