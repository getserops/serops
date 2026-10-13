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
  * Uses optional HMAC-SHA256 signature verification when the binding
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
_VALID_ENVS = {'production', 'staging', 'development', 'preview', 'demo'}
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
        # 1. Resolve binding
        binding = self._resolve_binding(binding_id)
        if binding is None:
            return Response(
                {'error': 'Unknown or inactive binding'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # 2. Verify HMAC signature if the binding has a secret configured.
        #    We ONLY verify when a secret is set — otherwise the binding
        #    is opt-out unsigned (backward-compat + convenience for
        #    private-network ArgoCD → SerOps installs).
        if binding.webhook_secret:
            if not self._verify_hmac(request, binding.webhook_secret):
                logger.warning(
                    'deployment webhook: HMAC verification failed for binding %s',
                    binding_id,
                )
                return Response(
                    {'error': 'Invalid signature'},
                    status=status.HTTP_403_FORBIDDEN,
                )

        # 3. Parse + validate payload
        try:
            payload = self._parse_payload(request)
        except _PayloadError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # 4. Get-or-create CodeChange for the commit
        code_change, created = self._get_or_create_code_change(payload, binding)

        # 5. Create Deployment via the shared service
        from .deployment_service import DeploymentService
        try:
            deployment = DeploymentService.create_deployment(
                code_change=code_change,
                environment=payload['environment'],
                deployed_at=payload['deployed_at'],
                pipeline=None,
                status='success',
                deployed_by=payload['actor'],
                notes=payload['notes'],
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
            'message': 'deployment recorded',
            'deployment_id': deployment.id,
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
        header = request.META.get('HTTP_X_SEROPS_SIGNATURE', '')
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
        if environment not in _VALID_ENVS:
            # Accept aliases (prod → production, stage → staging, dev → development).
            aliases = {
                'prod': 'production', 'prd': 'production',
                'stage': 'staging', 'stg': 'staging', 'preprod': 'staging',
                'dev': 'development', 'develop': 'development',
            }
            environment = aliases.get(environment)
            if not environment:
                raise _PayloadError(
                    f'environment must be one of {sorted(_VALID_ENVS)} (aliases: prod/dev/stage/...)'
                )

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

        existing = CodeChange.objects.filter(commit_sha=payload['commit_sha']).first()
        if existing:
            return existing, False

        # Best-effort stub — pull org + provider from the binding chain.
        service = binding.project_service
        project = service.project
        organisation = getattr(project, 'organisation', None)

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
