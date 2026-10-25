"""ArgoCD native webhook handler — Items #15.

ArgoCD's ``argocd-notifications-controller`` sends webhooks on
Application events (sync succeeded / failed, health degraded /
recovered, deployment started, etc.). Users configure a
``notification`` resource that points at SerOps, and the controller
posts the ArgoCD-native payload.

Rather than force every ArgoCD user to author a custom notification
template that outputs SerOps' canonical
``{commit_sha, environment, ...}`` shape, this handler accepts the
default ArgoCD template and translates on our side.

Payload shape (ArgoCD Notifications v1.x default context)::

    {
      "app": {
        "metadata": {"name": "...", "namespace": "argocd"},
        "spec": {"source": {"targetRevision": "HEAD"}},
        "status": {
          "sync": {"status": "Synced", "revision": "<40 hex or git ref>"},
          "health": {"status": "Healthy"},
          "operationState": {
            "phase": "Succeeded",
            "finishedAt": "2026-10-25T14:25:00Z",
            "operation": {"initiatedBy": {"username": "..."}}
          }
        }
      },
      "context": {"argocdUrl": "..."}
    }

We only record a deployment when the *sync* is finished
successfully (``operationState.phase == "Succeeded"``) — health
transitions and in-progress syncs are ignored. That keeps the
"Recent Deployments" panel honest.

Environment resolution (in order):

1. ``metadata.annotations["serops.io/environment"]`` (explicit).
2. Application namespace (``metadata.namespace``) if it matches one
   of SerOps' known environment names.
3. Fallback: ``production`` — safer default than ``preview`` for a
   deployment that just happened.

Security: subclass reuses the parent's HMAC check + binding
resolution + rate-limit + logging — the only override is
``_parse_payload``.
"""

import logging
from datetime import datetime

from django.utils import timezone

from .deployment_webhook import GenericDeploymentWebhookHandler, _PayloadError, _VALID_ENVS

logger = logging.getLogger(__name__)


# ArgoCD reports sync status as one of these; only "Synced" means the
# desired state was applied. Everything else (OutOfSync, Unknown) is
# not a deployment event we should record.
_ARGO_SYNC_OK = 'Synced'

# Sync operation phases — only Succeeded counts as a deployment.
_ARGO_PHASE_OK = 'Succeeded'


class ArgoCDDeploymentWebhookHandler(GenericDeploymentWebhookHandler):
    """Accept ArgoCD's native Application payload; delegate the rest
    to :class:`GenericDeploymentWebhookHandler`."""

    def _parse_payload(self, request) -> dict:
        raw = self._read_json(request)
        app = raw.get('app') or {}
        if not isinstance(app, dict):
            raise _PayloadError('Payload missing "app" object')

        metadata = app.get('metadata') or {}
        spec = app.get('spec') or {}
        status = app.get('status') or {}
        sync = status.get('sync') or {}
        op_state = status.get('operationState') or {}

        # 1. Only record successful syncs.
        sync_status = str(sync.get('status') or '').strip()
        phase = str(op_state.get('phase') or '').strip()
        # Some ArgoCD event templates omit operationState (health-change
        # events, for example). We treat "Synced" alone as sufficient
        # when phase is absent, but reject explicit failures.
        # A succeeded operation is the deploy, whatever the app's sync status
        # reads by the time the notification is rendered: right after a sync
        # it can already be OutOfSync (live drift, a mutating webhook), and
        # with oncePer Argo CD never sends that revision again, so the deploy
        # was lost (found by the journey suite). The status only decides
        # when there is no operation state.
        if phase and phase != _ARGO_PHASE_OK:
            raise _PayloadError(f'Ignored: operation phase is "{phase}" (not Succeeded)')
        if not phase and sync_status and sync_status != _ARGO_SYNC_OK:
            raise _PayloadError(f'Ignored: sync status is "{sync_status}" (not Synced)')

        # 2. Extract commit SHA — ArgoCD's revision is the git sha for
        # git-tracked apps, or a chart version for Helm apps. We only
        # record git-sha deployments (7-64 hex); non-git sources
        # (Helm charts) fall through to the parent's validation and
        # 400 cleanly.
        # The revision the operation deployed, else the app's current one.
        op_revision = ((op_state.get('syncResult') or {}).get('revision')
                       or ((op_state.get('operation') or {}).get('sync') or {}).get('revision'))
        commit_sha = str(op_revision or sync.get('revision') or '').strip()
        if not commit_sha:
            raise _PayloadError('sync.revision is empty; nothing to record')

        # 3. Environment — annotation > namespace > default.
        environment = self._resolve_environment(metadata)

        # 4. Timestamp — finishedAt if present, else now.
        deployed_at = self._parse_iso(op_state.get('finishedAt')) or timezone.now()

        # 5. Actor — initiator username if provided, else "argocd".
        op = op_state.get('operation') or {}
        initiated_by = (op.get('initiatedBy') or {}).get('username', '') if isinstance(op, dict) else ''
        actor = initiated_by[:60] if initiated_by else 'argocd'

        # 6. Notes — app name + revision short + target for context.
        app_name = str(metadata.get('name') or '')
        target_rev = str((spec.get('source') or {}).get('targetRevision') or '')
        notes_parts = [f'argocd-app={app_name}']
        if target_rev and target_rev != commit_sha:
            notes_parts.append(f'target={target_rev}')
        notes = ' '.join(notes_parts)[:500]

        # Hand the canonicalised dict back through the parent's shape
        # so the rest of the pipeline (get_or_create CodeChange, create
        # Deployment, logging) is unchanged.
        return {
            'commit_sha': commit_sha,
            'environment': environment,
            'deployed_at': deployed_at,
            'actor': actor,
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
    def _resolve_environment(metadata: dict) -> str:
        annotations = metadata.get('annotations') or {}
        # Explicit annotation wins.
        explicit = str(annotations.get('serops.io/environment') or '').strip().lower()
        if explicit:
            return _map_env_alias(explicit)
        # Namespace fallback — many teams name namespaces after envs.
        ns = str(metadata.get('namespace') or '').strip().lower()
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


def _map_env_alias(name: str):
    """Return canonical env name for the input, or None if unrecognised."""
    if name in _VALID_ENVS:
        return name
    aliases = {
        'prod': 'production', 'prd': 'production', 'live': 'production',
        'stage': 'staging', 'stg': 'staging', 'preprod': 'staging',
        'dev': 'development', 'develop': 'development',
    }
    return aliases.get(name)
