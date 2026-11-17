"""Generic deployment webhook — for tools without native CI/CD binding support.

Handles ArgoCD Notifications, Flux Notification Controller, Helm
post-install / post-upgrade hooks, Terraform apply post-hooks, kubectl
rollout wrappers, and any other tool that just needs to say "commit
X deployed to env Y at time Z."

Unlike the per-provider CI/CD webhooks (github_webhook, gitlab_webhook,
bitbucket_webhook, azure_devops_webhook, jenkins_webhook), this endpoint:

  * Doesn't build a ``Pipeline`` record — there's no pipeline concept
    for post-hook triggers.
  * Creates a ``Deployment`` directly from a minimal payload.
  * Uses the same ``CICDBinding.binding_id``-in-URL identity pattern.
  * Requires an HMAC-SHA256 signature made with the binding
    has a ``webhook_secret`` set (strongly recommended for any
    public-facing deploy webhook).

Payload (JSON):

    {
      "commit_sha":  "abc123def456...",       # required (7-64 chars)
      "environment": "production",             # required
      "version":     "v2.3.1",                 # optional
      "deployed_at": "2026-10-25T14:25:00Z",   # optional, defaults to now
      "actor":       "argocd",                 # optional (default 'external')
      "notes":       "auto-sync from main"     # optional (<= 500 chars)
    }

Response 200:

    {
      "message":       "deployment recorded",
      "deployment_id": 42,
      "commit_sha":    "abc123def456",
      "environment":   "production",
      "code_change_created": false        # true if we auto-created a stub
    }

Security:

  * Rate-limited via ``ScopedRateThrottle`` (scope: ``webhook_deployment``).
  * Signature verification uses ``hmac.compare_digest`` (constant-time).
    Signature header: ``X-SerOps-Signature: sha256=<hex>`` over raw body.
  * Payload validation clamps ``notes`` length and rejects malformed
    ``commit_sha`` / ``deployed_at`` / ``environment`` early.
  * If the commit is unknown (SCM webhook hasn't fired yet), a minimal
    stub ``CodeChange`` is created so the deployment can be linked —
    the real diff/message land later when the SCM webhook arrives.
"""

import hashlib
import hmac
import json
import logging
import re
from datetime import datetime

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


# Input-validation constants
_COMMIT_SHA_RE = re.compile(r'^[a-fA-F0-9]{7,64}$')
_ENV_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,49}$')
_NOTES_MAX_LEN = 500
_ACTOR_MAX_LEN = 60
_VERSION_MAX_LEN = 100


class GenericDeploymentWebhookHandler(APIView):
    """Accept a lightweight ``{commit_sha, environment, ...}`` payload
    and record a ``Deployment``.

    Same URL-binding pattern as the per-provider CI/CD webhooks:
    ``POST /api/providers/webhook/deployment/<binding_id>/``.
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'webhook_deployment'

    def post(self, request, binding_id):
        # 1. Resolve the binding and verify the signature. Every binding
        #    created through SerOps gets a secret, and unsigned events are
        #    refused. Unknown, inactive, secret-less and badly signed
        #    requests get the same answer, so binding ids (sequential)
        #    cannot be enumerated.
        binding = self._resolve_binding(binding_id)
        if binding is None or not binding.webhook_secret \
                or not self._verify_hmac(request, binding.webhook_secret):
            logger.warning('deployment webhook: refused request for binding %s', binding_id)
            return Response(
                {'error': 'Unknown binding or invalid signature'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # 3. Parse + validate payload
        try:
            payload = self._parse_payload(request)
        except _IgnoredEvent as e:
            # A well-formed event that is not a deploy (a reconcile that
            # changed nothing, a progress notice). 200, not 400: Flux and
            # Argo CD log every non-2xx answer as a failed notification and
            # retry it (client C4: an error line on every reconcile).
            return Response({'ignored': True, 'message': str(e)})
        except _PayloadError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        deploy_status = payload.get('status') or 'success'

        # 4. Get-or-create CodeChange for the commit
        code_change, created = self._get_or_create_code_change(payload, binding)

        # 5. Same revision already the newest deploy in this environment: Flux
        # sends an info event on every reconcile (and Argo CD can resend), so
        # without this one sync became a new "deployment" every 30 s (found by
        # the journey suite, launch plan 9.9). Rolling back and forward again
        # still records, because the newest deploy differs in between.
        from .models import Deployment
        org = getattr(getattr(binding.project_service, 'project', None), 'organisation', None)
        latest = (Deployment.objects
                  .filter(environment=payload['environment'], code_change__organisation=org,
                          project_service=binding.project_service)
                  .select_related('code_change').order_by('-deployed_at', '-pk').first())
        if latest is not None and latest.code_change_id == code_change.pk \
                and (latest.status or 'success') == deploy_status:
            return Response({
                'message': 'deployment already recorded',
                'deployment_id': latest.id,
                'commit_sha': code_change.commit_sha,
                'environment': latest.environment,
                'deduplicated': True,
            })

        # 6. Create Deployment via the shared service
        from .deployment_service import DeploymentService
        try:
            deployment = DeploymentService.create_deployment(
                code_change=code_change,
                environment=payload['environment'],
                deployed_at=payload['deployed_at'],
                pipeline=None,
                status=deploy_status,
                deployed_by=payload['actor'],
                notes=payload['notes'],
                project_service=binding.project_service,
            )
        except Exception as e:
            logger.exception(
                'deployment webhook: create_deployment failed for binding %s: %s',
                binding_id, e,
            )
            return Response(
                {'error': 'Failed to record deployment'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        logger.info(
            'deployment webhook: recorded deployment %s (commit=%s env=%s actor=%s binding=%s)',
            deployment.id, payload['commit_sha'][:8], payload['environment'],
            payload['actor'], binding_id,
        )

        return Response({
            'message': 'deployment recorded' if deploy_status == 'success' else 'failed deployment recorded',
            'deployment_id': deployment.id,
            'status': deploy_status,
            'commit_sha': code_change.commit_sha,
            'environment': deployment.environment,
            'code_change_created': created,
        })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_binding(self, binding_id):
        """Look up an active CICDBinding by id. Returns None on miss."""
        from Projects.models import CICDBinding
        try:
            return CICDBinding.objects.select_related(
                'project_service__project__organisation',
                'integration',
            ).get(pk=binding_id, is_active=True)
        except (CICDBinding.DoesNotExist, ValueError):
            # ValueError covers non-integer PKs — no need for a
            # separate error path.
            logger.warning(
                'deployment webhook: binding %s not found or inactive', binding_id,
            )
            return None

    @staticmethod
    def _verify_hmac(request, secret: str) -> bool:
        """Constant-time HMAC-SHA256 signature check.

        Expected header: ``X-SerOps-Signature: sha256=<hex>``.
        Signature is computed over the raw request body.
        """
        # Argo CD notifications cannot compute an HMAC of their own body,
        # but can send a fixed header read from argocd-notifications-secret:
        # ``Authorization: Bearer <binding secret>`` is accepted too.
        auth = request.META.get('HTTP_AUTHORIZATION', '')
        if auth.startswith('Bearer '):
            return hmac.compare_digest(auth[len('Bearer '):].strip(), secret)

        # Flux's ``generic-hmac`` provider signs the same way as SerOps but
        # sends the digest as ``X-Signature: sha256=<hex>``; accept either.
        header = (request.META.get('HTTP_X_SEROPS_SIGNATURE')
                  or request.META.get('HTTP_X_SIGNATURE') or '')
        if not header.startswith('sha256='):
            return False
        provided = header[len('sha256='):]

        body = request.body if isinstance(request.body, bytes) else str(request.body).encode()
        expected = hmac.new(
            secret.encode('utf-8'), body, hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(provided, expected)

    def _parse_payload(self, request) -> dict:
        """Parse + validate the JSON body. Raises _PayloadError on invalid input."""
        # DRF parses JSON into request.data; fall back to raw body only
        # if a client sends the wrong Content-Type by accident.
        try:
            raw = request.data if isinstance(request.data, dict) else json.loads(request.body)
        except (json.JSONDecodeError, TypeError, ValueError):
            raise _PayloadError('Body must be valid JSON')

        # Required fields
        commit_sha = str(raw.get('commit_sha', '')).strip()
        if not _COMMIT_SHA_RE.match(commit_sha):
            raise _PayloadError(
                'commit_sha is required and must be 7-64 hex characters'
            )

        environment = str(raw.get('environment', '')).strip().lower()
        if not environment:
            raise _PayloadError('environment is required')
        # Any environment name the project uses (qa, uat, preview, eu-prod);
        # prod / stage / dev spellings become production / staging /
        # development. Accepting preview and demo here and then refusing them
        # when recording was a 500 (phase 3 review SC-08).
        if not _ENV_NAME_RE.match(environment):
            raise _PayloadError('environment must be 1-50 letters, digits, ".", "_" or "-"')
        from .deployment_service import canonical_environment
        environment = canonical_environment(environment)

        # Optional fields — parse + clamp
        deployed_at_raw = raw.get('deployed_at')
        if deployed_at_raw:
            try:
                # Python 3.11+ accepts trailing Z natively.
                deployed_at = datetime.fromisoformat(str(deployed_at_raw).replace('Z', '+00:00'))
                if deployed_at.tzinfo is None:
                    deployed_at = timezone.make_aware(deployed_at, timezone.utc)
            except (ValueError, TypeError):
                raise _PayloadError(
                    'deployed_at must be an ISO 8601 timestamp (e.g. 2026-10-25T14:25:00Z)'
                )
        else:
            deployed_at = timezone.now()

        actor = str(raw.get('actor') or 'external').strip()[:_ACTOR_MAX_LEN]
        version = str(raw.get('version') or '').strip()[:_VERSION_MAX_LEN]
        notes = str(raw.get('notes') or '').strip()[:_NOTES_MAX_LEN]

        # If version is provided, prepend it to notes for visibility (notes are
        # what appear in the AI prompt as deploy context).
        if version and 'version' not in notes.lower():
            notes = f'version={version}' + (f' — {notes}' if notes else '')

        return {
            'commit_sha': commit_sha,
            'environment': environment,
            'deployed_at': deployed_at,
            'actor': actor,
            'notes': notes,
        }

    def _get_or_create_code_change(self, payload: dict, binding):
        """Find the CodeChange for this commit, or create a stub for later hydration.

        Returns ``(code_change, created)``. When the commit hasn't been
        seen yet (SCM webhook fires after the deploy webhook), we create
        a minimal stub with just what we know from the binding + payload
        so the deployment can be linked. The real message/diff hydrate
        when the SCM webhook eventually arrives (same commit_sha =
        update_or_create semantics — see providers.tasks).
        """
        from .models import CodeChange

        # Best-effort stub — pull org + provider from the binding chain.
        service = binding.project_service
        project = service.project
        organisation = getattr(project, 'organisation', None)

        # Within the binding's organisation: the SHA comes from the payload,
        # and another tenant's commit must not get this deployment
        # (security review 2026-11, finding 2).
        existing = CodeChange.objects.filter(
            commit_sha=payload['commit_sha'], organisation=organisation,
        ).first()
        if existing:
            return existing, False

        # Provider guess: use the integration's provider_type when it's one
        # of the SCM_PROVIDER_CHOICES; else default to 'gitlab' (the model's
        # own default). The stub is a placeholder — the real record with
        # correct provider metadata lands when the SCM webhook fires.
        _valid_scm = {'gitlab', 'github', 'bitbucket', 'azure_devops'}
        provider = 'gitlab'
        if binding.integration:
            candidate = getattr(binding.integration, 'provider_type', None)
            if candidate in _valid_scm:
                provider = candidate

        # external_project_id: SCM binding's repository_id if available, else
        # leave blank — a later SCM webhook will fill it via update.
        try:
            from Projects.models import SCMBinding
            scm = SCMBinding.objects.filter(project_service=service).first()
            external_project_id = scm.repository_id if scm else ''
        except Exception:
            external_project_id = ''

        stub = CodeChange.objects.create(
            organisation=organisation,
            provider=provider,
            project_id=str(external_project_id or ''),
            commit_sha=payload['commit_sha'],
            commit_message='',       # SCM webhook fills this when it arrives
            author_name='',
            timestamp=payload['deployed_at'],  # best guess until SCM webhook fires
            branch='',
        )
        logger.info(
            'deployment webhook: created stub CodeChange for unknown commit %s (binding %s)',
            payload['commit_sha'][:8], binding.pk,
        )
        return stub, True


class _PayloadError(ValueError):
    """Raised for malformed deployment webhook payloads."""


class _IgnoredEvent(Exception):
    """A valid controller event that records nothing (answered 200)."""
