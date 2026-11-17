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
import re
from datetime import datetime

from django.utils import timezone

from .deployment_webhook import GenericDeploymentWebhookHandler, _IgnoredEvent, _PayloadError

logger = logging.getLogger(__name__)


# ArgoCD reports sync status as one of these; only "Synced" means the
# desired state was applied. Everything else (OutOfSync, Unknown) is
# not a deployment event we should record.
_ARGO_SYNC_OK = 'Synced'

# Sync operation phases — only Succeeded counts as a deployment.
_ARGO_PHASE_OK = 'Succeeded'
_ARGO_PHASE_FAILED = {'Failed', 'Error'}


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
        # A sync that failed is a deploy attempted and rejected: recorded as
        # failed so the analysis knows the change did not land. Anything
        # else that is not a deploy is answered 200 "ignored": Argo CD logs
        # a non-2xx answer as a failed notification and retries it.
        deploy_status = 'success'
        if phase in _ARGO_PHASE_FAILED:
            deploy_status = 'failed'
        elif phase and phase != _ARGO_PHASE_OK:
            raise _IgnoredEvent(f'Ignored: operation phase is "{phase}" (not Succeeded)')
        elif not phase and sync_status and sync_status != _ARGO_SYNC_OK:
            raise _IgnoredEvent(f'Ignored: sync status is "{sync_status}" (not Synced)')

        # 2. Extract commit SHA — ArgoCD's revision is the git sha for
        # git-tracked apps, or a chart version for Helm apps. We only
        # record git-sha deployments (7-64 hex); non-git sources
        # (Helm charts) fall through to the parent's validation and
        # 400 cleanly.
        # The revision the operation deployed, else the app's current one.
        # A multi-source Application (a Helm chart plus a values repo, common
        # since Argo CD 2.6) has ``revisions`` lists instead: the Git entry
        # is the commit, the chart version is not (C2 found every such
        # deploy answered 400).
        sync_result = op_state.get('syncResult') or {}
        op_sync = (op_state.get('operation') or {}).get('sync') or {}
        op_revision = (sync_result.get('revision') or op_sync.get('revision')
                       or sync.get('revision'))
        if not op_revision:
            op_revision = (_git_revision(sync_result.get('revisions'))
                           or _git_revision(op_sync.get('revisions'))
                           or _git_revision(sync.get('revisions')))
        commit_sha = str(op_revision or '').strip()
        if not commit_sha:
            raise _PayloadError('sync.revision is empty; nothing to record')

        # 3. Environment: annotation > destination namespace > app name >
        # the Application's own namespace > production (flagged in notes).
        environment, env_source = self._resolve_environment(metadata, spec)

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
        if env_source == 'default':
            notes_parts.append('environment=assumed-production')
        if deploy_status == 'failed':
            notes_parts.append(f'failed ({phase}): ' + ' '.join(str(op_state.get('message') or '').split())[:300])
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
    def _resolve_environment(metadata: dict, spec: dict = None):
        """``(environment, source)``. ``metadata.namespace`` is where the
        Application resource lives (usually ``argocd``), not where it deploys,
        so the destination namespace and the app name are read first (SC-09:
        every staging deploy was recorded as production)."""
        annotations = metadata.get('annotations') or {}
        # Explicit annotation wins.
        explicit = str(annotations.get('serops.io/environment') or '').strip().lower()
        if explicit:
            # An environment the alias map does not know (qa, uat) is kept
            # as named, not None: None made the deploy a 500 (SC-08).
            from .deployment_service import canonical_environment
            return _map_env_alias(explicit) or canonical_environment(explicit), 'annotation'
        destination = (spec or {}).get('destination') or {}
        for source, value in (
            ('destination', _map_env_alias(str(destination.get('namespace') or '').strip().lower())),
            ('name', _env_from_name(metadata.get('name'))),
            ('destination', _env_from_name(destination.get('namespace'))),
            ('namespace', _map_env_alias(str(metadata.get('namespace') or '').strip().lower())),
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


# Namespace names read as an environment when nothing explicit is set.
_NAMESPACE_ENVS = {'production', 'staging', 'development', 'preview', 'demo'}


_GIT_SHA_RE = re.compile(r'^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$')


def _git_revision(revisions):
    """The Git commit in a multi-source ``revisions`` list (a full SHA-1 or
    SHA-256), skipping chart versions; None when there is none."""
    if not isinstance(revisions, list):
        return None
    for rev in revisions:
        rev = str(rev or '').strip()
        if _GIT_SHA_RE.match(rev):
            return rev
    return None


def _env_from_name(name):
    """The environment a resource name spells as its first or last part
    (``payments-staging``, ``prod.checkout``, ``staging_api``), or None."""
    parts = [p for p in re.split(r'[-_.]', str(name or '').strip().lower()) if p]
    for part in dict.fromkeys(parts[-1:] + parts[:1]):
        mapped = _map_env_alias(part)
        if mapped:
            return mapped
    return None


def _map_env_alias(name: str):
    """Return canonical env name for the input, or None if unrecognised.

    Used for namespaces (a namespace named ``payments`` is not an
    environment), so only the usual names and their spellings count.
    """
    from .deployment_service import canonical_environment
    canonical = canonical_environment(name)
    return canonical if canonical in _NAMESPACE_ENVS else None
