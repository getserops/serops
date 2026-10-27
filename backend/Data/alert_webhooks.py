"""Alert webhook receivers for Prometheus Alertmanager, Grafana Alerts,
and Datadog Monitors (Items #13 + #14).

Each receiver:

1. Verifies a shared bearer secret in the ``Authorization`` header
   against ``settings.ALERT_WEBHOOK_SECRETS[<source>]``. Constant-time
   compare via ``hmac.compare_digest``. Missing / wrong secret → 401.
2. Parses the provider-specific payload into a common shape:
   (alertname, state, severity, service, environment, summary,
   external_id).
3. Deduplicates against ``AlertEvent`` — a retry within 5 minutes for
   the same (source, external_id) — or (source, alertname, service,
   environment) if no external_id — returns 200 without re-triggering.
4. Persists an ``AlertEvent`` row.
5. Enqueues the on-demand analysis task at high priority so the
   RCA batch lands within ~30s of the alert firing.

Security:

* No user input is interpolated into shell / SQL / templates.
* Payload bodies are treated as untrusted JSON — the parsers only
  read known keys, never eval / exec / template-render values.
* Rate-limited per-source via DRF's ``ScopedRateThrottle`` at
  ``alert_webhook`` (defined in ``api/settings.py``).
* Multi-tenancy: the URL path carries ``<org_id>`` so a leaked
  secret only affects that one tenant. Secret lookup uses the org's
  own hash (falls back to a global env secret only when the org has
  not set one — see ``_secret_for``).

Payload notes per provider:

* **Alertmanager** wraps alerts in ``{"alerts": [...]}``. We treat
  each alert in the list as its own AlertEvent so an alert group
  with 3 firing instances triggers 3 analyses (usually different
  services / hosts).
* **Grafana Alerts** (unified alerting v9+) sends the same shape as
  Alertmanager (they use the Alertmanager format). Parser is shared.
* **Datadog Monitors** sends one alert per webhook; ``event_type``
  tells us the state.
* **Sentry** (an internal integration) can't send a bearer token: it signs
  the body with HMAC-SHA256 under the integration's client secret, in the
  ``Sentry-Hook-Signature`` header, and names the payload kind in
  ``Sentry-Hook-Resource``. Issue alerts carry the event, so the summary
  holds the exception, culprit, release and top in-app frames.
"""

import hmac
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from Organisations.models import Organisations
from .models import AlertEvent

logger = logging.getLogger(__name__)


# Idempotency window — retries within this window are 200-no-op'd.
_DEDUP_WINDOW = timedelta(minutes=5)


# ---------------------------------------------------------------------------
# Secret lookup
# ---------------------------------------------------------------------------


def _secret_for(source: str, organisation) -> str:
    """
    Return the expected bearer secret for (source, org).

    Priority:
    1. Per-org secret in ``organisation.extra_config`` (future — not
       wired yet). Left as an extension point.
    2. Global env-backed secret in ``settings.ALERT_WEBHOOK_SECRETS``.

    Returns empty string when no secret is configured; caller must
    treat that as "reject all" — never allow un-authed webhooks.
    """
    secrets = getattr(settings, 'ALERT_WEBHOOK_SECRETS', {}) or {}
    return str(secrets.get(source, ''))


def _authenticate_sentry(request) -> bool:
    """Sentry-Hook-Signature = hex HMAC-SHA256(client secret, raw body)."""
    import hashlib
    secret = _secret_for('sentry', None)
    signature = request.META.get('HTTP_SENTRY_HOOK_SIGNATURE', '')
    if not secret or not signature:
        if not secret:
            logger.warning('Sentry webhook rejected: SEROPS_SENTRY_CLIENT_SECRET is not set.')
        return False
    expected = hmac.new(secret.encode('utf-8'), request.body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def _authenticate(request, source: str, organisation) -> bool:
    """Constant-time bearer auth. False on any mismatch.

    Q5-5 (2026-09-21): if the org has a per-org ``alert_ingest_secret_hash``
    set, that takes precedence over the global
    ``settings.ALERT_WEBHOOK_SECRETS``. Presented bearer is SHA-256
    hashed and compared constant-time against the stored hash.
    Per-org secrets rotate via the ``AlertSecretRotateView`` endpoint;
    they can be revoked by rotating without redistributing the new
    plaintext.
    """
    header = request.META.get('HTTP_AUTHORIZATION', '')
    if not header.startswith('Bearer '):
        return False
    provided = header[len('Bearer '):].strip()
    if not provided:
        return False

    # Per-org secret takes precedence when set.
    org_hash = getattr(organisation, 'alert_ingest_secret_hash', '') or ''
    if org_hash:
        import hashlib
        candidate = hashlib.sha256(provided.encode('utf-8')).hexdigest()
        return hmac.compare_digest(candidate, org_hash)

    # Fallback: legacy global-per-source secret.
    expected = _secret_for(source, organisation)
    if not expected:
        logger.warning(
            'Alert webhook rejected: no per-org secret and no global secret '
            'for source=%s. Rotate via POST /api/organisation/alert-secret/rotate/ '
            'or set settings.ALERT_WEBHOOK_SECRETS["%s"] via env.',
            source, source,
        )
        return False
    return hmac.compare_digest(str(provided), str(expected))


# ---------------------------------------------------------------------------
# Provider parsers — untrusted input → common shape
# ---------------------------------------------------------------------------


def _parse_alertmanager(payload: dict) -> list:
    """Alertmanager (also Grafana unified alerting v9+) format.

    Yields one dict per alert in the ``alerts`` list.
    """
    out = []
    for alert in (payload.get('alerts') or []):
        if not isinstance(alert, dict):
            continue
        labels = alert.get('labels') or {}
        annotations = alert.get('annotations') or {}
        out.append({
            'alertname': str(labels.get('alertname') or 'unknown'),
            'state': str(alert.get('status') or 'firing'),
            'severity': str(labels.get('severity') or ''),
            # service_name / environment are the canonical labels our metrics
            # docs put on every series; rules usually copy them into alerts.
            'service': str(labels.get('service') or labels.get('service_name') or labels.get('job') or ''),
            'environment': str(labels.get('environment') or labels.get('env') or ''),
            'summary': str(annotations.get('summary') or annotations.get('description') or '')[:2000],
            'external_id': str(alert.get('fingerprint') or ''),
        })
    return out


def _parse_datadog(payload: dict) -> list:
    """Datadog Monitor webhook format — one alert per POST."""
    # Datadog wraps user's message under different keys depending on
    # setup; accept the common ones.
    event_type = str(payload.get('event_type') or payload.get('alert_type') or 'firing').lower()
    state = 'resolved' if 'recover' in event_type else 'firing'

    tags = payload.get('tags') or ''
    if isinstance(tags, str):
        tag_pairs = [t.strip() for t in tags.split(',') if t.strip()]
    elif isinstance(tags, list):
        tag_pairs = [str(t) for t in tags]
    else:
        tag_pairs = []
    tag_dict = {}
    for pair in tag_pairs:
        if ':' in pair:
            k, v = pair.split(':', 1)
            tag_dict[k.strip()] = v.strip()

    return [{
        'alertname': str(payload.get('alert_title') or payload.get('title') or 'datadog-alert'),
        'state': state,
        'severity': str(payload.get('priority') or ''),
        'service': tag_dict.get('service', ''),
        'environment': tag_dict.get('env', tag_dict.get('environment', '')),
        'summary': str(payload.get('body') or payload.get('message') or '')[:2000],
        'external_id': str(payload.get('id') or payload.get('alert_transition_id') or ''),
    }]


def _sentry_tag(tags, key):
    """Sentry sends tags as [[key, value], …] or [{key, value}, …]."""
    for t in tags or []:
        if isinstance(t, (list, tuple)) and len(t) == 2 and t[0] == key:
            return str(t[1])
        if isinstance(t, dict) and t.get('key') == key:
            return str(t.get('value') or '')
    return ''


def _sentry_frames(event):
    """'Type: value' plus the innermost in-app frames, innermost first."""
    lines = []
    for exc in ((event.get('exception') or {}).get('values') or [])[-2:]:
        if not isinstance(exc, dict):
            continue
        lines.append(f"{exc.get('type') or 'Error'}: {str(exc.get('value') or '')[:300]}")
        frames = [f for f in ((exc.get('stacktrace') or {}).get('frames') or []) if isinstance(f, dict)]
        in_app = [f for f in frames if f.get('in_app')] or frames
        for f in reversed(in_app[-5:]):
            lines.append(f"  at {f.get('function') or '?'} ({f.get('filename') or f.get('module') or '?'}"
                         f":{f.get('lineno') or '?'})")
    return lines


def _parse_sentry(payload: dict, resource: str = '') -> list:
    """Sentry internal-integration webhooks: issue alerts (event_alert),
    metric alerts, and new issues. Other resources are acknowledged and
    ignored."""
    data = payload.get('data') or {}
    action = str(payload.get('action') or '')
    if resource == 'event_alert' or 'event' in data:
        event = data.get('event') or {}
        tags = event.get('tags') or []
        lines = [str(event.get('title') or '')[:300]]
        if event.get('culprit'):
            lines.append(f"Culprit: {str(event['culprit'])[:200]}")
        release = event.get('release') or _sentry_tag(tags, 'release')
        if release:
            lines.append(f"Release: {str(release)[:100]}")
        lines += _sentry_frames(event)
        if data.get('triggered_rule'):
            lines.append(f"Alert rule: {str(data['triggered_rule'])[:200]}")
        if event.get('web_url'):
            lines.append(f"Sentry: {str(event['web_url'])[:300]}")
        return [{
            'alertname': str(event.get('title') or data.get('triggered_rule') or 'sentry-alert')[:250],
            'state': 'firing',
            'severity': str(event.get('level') or ''),
            'service': _sentry_tag(tags, 'service') or str(event.get('project_slug') or ''),
            'environment': str(event.get('environment') or _sentry_tag(tags, 'environment')),
            'summary': '\n'.join(lines)[:2000],
            'external_id': str(event.get('event_id') or event.get('id') or ''),
        }]
    if resource == 'metric_alert' or 'metric_alert' in data:
        alert = data.get('metric_alert') or {}
        rule = alert.get('alert_rule') or {}
        desc = data.get('description_text') or data.get('description_title') or ''
        return [{
            'alertname': str(rule.get('name') or data.get('description_title') or 'sentry-metric-alert')[:250],
            'state': 'resolved' if action == 'resolved' else 'firing',
            'severity': action if action in ('critical', 'warning') else '',
            'service': '',
            'environment': str(rule.get('environment') or ''),
            'summary': str(desc)[:2000],
            'external_id': str(alert.get('id') or ''),
        }]
    if (resource == 'issue' or 'issue' in data) and action == 'created':
        issue = data.get('issue') or {}
        project = issue.get('project') or {}
        meta = issue.get('metadata') or {}
        lines = [str(issue.get('title') or '')[:300]]
        if issue.get('culprit'):
            lines.append(f"Culprit: {str(issue['culprit'])[:200]}")
        if meta.get('filename'):
            lines.append(f"File: {str(meta['filename'])[:200]}")
        if issue.get('web_url') or issue.get('permalink'):
            lines.append(f"Sentry: {str(issue.get('web_url') or issue.get('permalink'))[:300]}")
        return [{
            'alertname': str(issue.get('title') or 'sentry-issue')[:250],
            'state': 'firing',
            'severity': str(issue.get('level') or ''),
            'service': str(project.get('slug') or ''),
            'environment': '',
            'summary': '\n'.join(lines)[:2000],
            'external_id': str(issue.get('id') or ''),
        }]
    return []


PARSER_BY_SOURCE = {
    'alertmanager': _parse_alertmanager,
    'grafana': _parse_alertmanager,   # same format
    'datadog': _parse_datadog,
    'sentry': _parse_sentry,
}


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def _is_duplicate(source: str, organisation, parsed: dict) -> bool:
    """
    True if the same alert (retry) landed within the dedup window.

    Uses external_id when present (Alertmanager fingerprint, Datadog
    event id); falls back to a synthetic key otherwise so a
    fingerprint-less provider still can't spam-retry us into 100
    duplicate analyses.
    """
    cutoff = timezone.now() - _DEDUP_WINDOW
    qs = AlertEvent.objects.filter(
        organisation=organisation, source=source, received_at__gte=cutoff,
    )
    ext_id = parsed.get('external_id')
    if ext_id:
        return qs.filter(external_id=ext_id).exists()
    return qs.filter(
        alertname=parsed['alertname'],
        service=parsed.get('service', ''),
        environment=parsed.get('environment', ''),
    ).exists()


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------


class AlertWebhookView(APIView):
    """
    POST /api/webhooks/alerts/<source>/<org_id>/

    ``source`` ∈ {alertmanager, grafana, datadog, sentry}. Any other value
    returns 400 without hitting the parser — safe URL routing.
    """

    permission_classes = [AllowAny]   # bearer secret, not Django auth
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'alert_webhook'

    def post(self, request, source, org_id):
        if source not in PARSER_BY_SOURCE:
            return Response(
                {'error': f'Unknown source: {source}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        organisation = Organisations.objects.filter(pk=org_id).first()
        if organisation is None:
            # Same 404 as if the source were wrong — no cross-org enum.
            return Response(
                {'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND,
            )

        authenticated = (_authenticate_sentry(request) if source == 'sentry'
                         else _authenticate(request, source, organisation))
        if not authenticated:
            return Response(
                {'error': 'Missing or invalid Authorization: Bearer <secret>'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        payload = request.data if isinstance(request.data, dict) else {}
        try:
            if source == 'sentry':
                alerts = _parse_sentry(payload, request.META.get('HTTP_SENTRY_HOOK_RESOURCE', ''))
            else:
                alerts = PARSER_BY_SOURCE[source](payload)
        except Exception as exc:
            logger.warning('Alert parse failed source=%s: %s', source, exc)
            return Response(
                {'error': 'Malformed payload'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not alerts:
            return Response({'accepted': 0, 'deduplicated': 0}, status=status.HTTP_200_OK)

        # PII redaction (Q1.5) — apply the same policy as logs to the
        # parsed alert fields + raw_payload BEFORE persistence. The
        # alert summary flows into the RCA prompt via
        # notifications.incident_dispatcher; the raw_payload sits on
        # the row for support debugging. Both are subject to enterprise
        # data-governance.
        from Utils.redaction_helpers import redact_alert_parsed, redact_raw_payload
        redacted_payload = redact_raw_payload(payload)

        accepted = 0
        deduped = 0
        events = []
        for parsed in alerts:
            if _is_duplicate(source, organisation, parsed):
                deduped += 1
                continue
            safe_parsed = redact_alert_parsed(parsed) or parsed
            event = AlertEvent.objects.create(
                organisation=organisation,
                source=source,
                external_id=safe_parsed.get('external_id', ''),
                alertname=safe_parsed['alertname'],
                state=safe_parsed['state'],
                severity=safe_parsed.get('severity', ''),
                service=safe_parsed.get('service', ''),
                environment=safe_parsed.get('environment', ''),
                summary=safe_parsed.get('summary', ''),
                raw_payload=redacted_payload,
            )
            events.append(event)
            accepted += 1

        # Fire the on-demand analysis task (Item #14) — one per new alert.
        # Wrapped so a Celery / broker outage doesn't turn 200 into 500.
        for event in events:
            try:
                from Data.tasks import analyze_alert_ondemand
                analyze_alert_ondemand.delay(event.pk)
            except Exception as exc:
                logger.warning(
                    'analyze_alert_ondemand enqueue failed for event=%s: %s',
                    event.pk, exc,
                )

        # Self-metrics (Item #24) — one bump per accepted / deduped alert.
        try:
            from Data.self_metrics import ALERT_RECEIVED
            if accepted:
                ALERT_RECEIVED.labels(source=source, outcome='accepted').inc(accepted)
            if deduped:
                ALERT_RECEIVED.labels(source=source, outcome='deduplicated').inc(deduped)
        except Exception:
            pass

        return Response({
            'accepted': accepted,
            'deduplicated': deduped,
        }, status=status.HTTP_200_OK)
