"""Post-RCA outbound notification dispatcher (Items #22 + #23).

Called at two points in the batch pipeline:

* After every batch analysis completes (``ai_model/tasks.py`` — the
  ``analyze_batch_with_ai`` entry point).
* After alert-triggered analyses specifically
  (``Data.tasks.analyze_alert_ondemand``).

For each active ``IncidentNotificationChannel`` in the batch's org
that matches the event + severity filter, fan-out sends via the
appropriate ``notifications.senders`` module. All failures are
logged + swallowed — a broken Slack workspace must not fail the
batch pipeline.

Auto-disable on permanent 4xx: senders return ``err_msg`` strings
that begin with ``HTTP 4xx:``. When we see one, we flip the channel
to ``is_active=False`` — a 400 "Invalid routing key" from PagerDuty
(E31-7) will never succeed on retry and repeated attempts just spam
the logs once per batch. User sees the last_error in the UI + can
re-enable after fixing the config.

Rate-limiting: the sender modules have per-call timeouts (8s); the
dispatcher does not itself rate-limit — most orgs have < 5 channels.
"""

import logging
import re
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)

# Match "HTTP <status>:" prefix from sender error messages. 4xx is
# permanent (bad config); 5xx / network / auth are transient or
# retryable so we leave the channel active.
_HTTP_STATUS_RE = re.compile(r'^HTTP (\d{3}):')

# The seed_demo_org command writes this placeholder as api_key /
# webhook_url secret for all incident channels so the UI has
# representative rows to show. Actually sending to the upstream would
# fail with 4xx ("Invalid routing key" from PagerDuty, etc.) — E31-7.
# Short-circuit here so the demo channels behave like they're active
# without ever burning real quota on placeholder secrets.
_DEMO_PLACEHOLDER = 'SEED_DEMO_PLACEHOLDER_NOT_A_REAL_SECRET'


def _is_demo_placeholder(channel) -> bool:
    """True when the channel's secret is the seed-demo sentinel."""
    for accessor in ('get_api_key', 'get_webhook_url'):
        fn = getattr(channel, accessor, None)
        if not fn:
            continue
        try:
            val = fn() or ''
        except Exception:
            val = ''
        if _DEMO_PLACEHOLDER in val:
            return True
    return False


def _is_permanent_failure(err_msg: str) -> bool:
    """Return True when the error indicates the channel config is bad
    (4xx from the upstream) and further retries will fail identically."""
    if not err_msg:
        return False
    m = _HTTP_STATUS_RE.match(err_msg)
    if not m:
        return False
    code = int(m.group(1))
    # 401/403/404 = auth / channel-not-found — those may recover if
    # the user rotates the key on their side without touching SerOps.
    # Only auto-disable on 400 (malformed request — the payload we
    # sent is provably wrong) and 422 (validation error).
    return code in (400, 422)


def dispatch(
    batch,
    event: str = 'batch_analyzed',
    alert_event=None,
) -> dict:
    """
    Send post-RCA notifications for ``batch`` to matching channels.

    Args:
        batch: AIAnalyzedBatch (already analyzed).
        event: One of IncidentNotificationChannel.TRIGGER_CHOICES codes.
        alert_event: Optional AlertEvent (populated for
            alert-triggered analyses so the payload can link back
            to the originating alert).

    Returns:
        Summary dict: {sent, failed, skipped}.

    Never raises.
    """
    if batch is None:
        return {'sent': 0, 'failed': 0, 'skipped': 0}

    try:
        return _dispatch(batch, event, alert_event)
    except Exception as exc:
        logger.exception('incident_dispatcher failed for batch=%s: %s',
                         getattr(batch, 'batch_id', '?'), exc)
        return {'sent': 0, 'failed': 0, 'skipped': 0, 'error': str(exc)}


def _dispatch(batch, event: str, alert_event) -> dict:
    from notifications.models import (
        IncidentNotificationChannel,
        NotificationRoutingRule,
    )
    from notifications.senders import SENDER_BY_KIND

    org = getattr(batch, 'organisation', None)
    if org is None and hasattr(batch, 'project') and batch.project is not None:
        org = batch.project.organisation
    if org is None:
        return {'sent': 0, 'failed': 0, 'skipped': 0, 'reason': 'no_org'}

    # Build the payload once — same across channels; each sender formats.
    payload = _build_payload(batch, alert_event)
    top_severity = payload['top_severity']
    project_name = payload.get('project_name') or ''
    environment = payload.get('environment') or ''

    # PR-N phase 2 (2026-09-26): walk routing rules → union of
    # target channels. Each active rule that matches the incident
    # contributes its ``targets`` to the send set. A channel is
    # notified at most once per dispatch even when multiple rules
    # target it (dedup below).
    rules = (
        NotificationRoutingRule.objects
        .filter(organisation=org, is_active=True)
        .prefetch_related('targets')
        .order_by('priority', 'name')
    )
    matched_channel_ids: set[int] = set()
    for rule in rules:
        if rule.matches(
            event=event, severity=top_severity,
            environment=environment, service=project_name,
        ):
            matched_channel_ids.update(rule.targets.values_list('pk', flat=True))

    if not matched_channel_ids:
        return {'sent': 0, 'failed': 0, 'skipped': 0}

    channels = list(
        IncidentNotificationChannel.objects.filter(
            pk__in=matched_channel_ids, is_active=True,
        ),
    )
    if not channels:
        return {'sent': 0, 'failed': 0, 'skipped': 0}

    sent = failed = skipped = 0
    for channel in channels:
        # The rule already gated on event/severity, but preserve the
        # per-channel ``min_severity`` floor as a belt-and-braces.
        if not channel.meets_severity(top_severity):
            skipped += 1
            continue
        sender = SENDER_BY_KIND.get(channel.kind)
        if sender is None:
            logger.warning('No sender registered for kind=%s (channel=%s)',
                           channel.kind, channel.pk)
            failed += 1
            continue

        # Demo-seed placeholder short-circuit: never contact real
        # upstream with a placeholder secret. Counts as skipped so
        # metrics don't record a fake success.
        if _is_demo_placeholder(channel):
            skipped += 1
            logger.debug(
                'Notification channel=%s (%s) uses SEED_DEMO_PLACEHOLDER '
                '— skipping upstream send.',
                channel.pk, channel.kind,
            )
            continue

        try:
            ok, err_msg = sender(channel, payload)
        except Exception as exc:
            # Belt-and-braces — senders shouldn't raise but if they do,
            # catch here so one broken sender can't hurt the others.
            ok, err_msg = False, f'Sender raised: {exc}'

        update_fields = ['last_sent_at', 'last_error']
        if ok:
            sent += 1
            channel.last_sent_at = timezone.now()
            channel.last_error = ''
        else:
            failed += 1
            channel.last_error = err_msg[:1000]
            # Auto-disable on permanent 4xx — same bad config will
            # produce the same error every time, and the user sees
            # `last_error` in the UI so they can fix + re-enable.
            if _is_permanent_failure(err_msg):
                channel.is_active = False
                update_fields.append('is_active')
                logger.warning(
                    'Notification channel=%s auto-disabled (permanent): %s. '
                    'Fix the config in Settings → Incident Channels and '
                    're-enable.',
                    channel.pk, err_msg,
                )
            else:
                logger.warning('Notification send failed channel=%s: %s',
                               channel.pk, err_msg)
        channel.save(update_fields=update_fields)

    return {'sent': sent, 'failed': failed, 'skipped': skipped}


# ---------------------------------------------------------------------------
# Payload assembly
# ---------------------------------------------------------------------------


def _build_payload(batch, alert_event) -> dict:
    """Shape the analysis into a sender-friendly dict."""
    project_name = ''
    environment = getattr(batch, 'environment', '') or ''
    if getattr(batch, 'project', None) is not None:
        project_name = batch.project.name
        if not environment:
            # Fall back to any project-level default (rare).
            environment = getattr(batch.project, 'default_environment', '') or ''

    # Pick the top issue for the summary — highest severity + newest.
    top_issue = _top_issue(batch)
    top_severity = getattr(top_issue, 'severity', '') if top_issue else ''
    issue_count = _issue_count(batch)

    root_cause = getattr(top_issue, 'root_cause', '') if top_issue else ''
    recommendation = getattr(top_issue, 'recommendation', '') if top_issue else ''

    if alert_event is not None:
        title = f'Alert analyzed — {alert_event.alertname}'
    else:
        title = f'RCA — {project_name or "batch"} {environment or ""}'.strip()

    incident_url = _incident_url(batch)

    return {
        'title': title,
        'batch_id': getattr(batch, 'batch_id', ''),
        'project_name': project_name,
        'environment': environment,
        'top_severity': (top_severity or '').upper(),
        'issue_count': issue_count,
        'root_cause': root_cause,
        'recommendation': recommendation,
        'incident_url': incident_url,
        'alert_event_id': getattr(alert_event, 'pk', None) if alert_event else None,
    }


def _top_issue(batch):
    try:
        # Severity CRITICAL > HIGH > MEDIUM > LOW; then newest first.
        return batch.issues.order_by('severity', '-created_at').first()
    except Exception:
        return None


def _issue_count(batch) -> int:
    try:
        return batch.issues.count()
    except Exception:
        return 0


def _incident_url(batch) -> str:
    """Build a UI deep-link if PUBLIC_BASE_URL is set; else empty."""
    import os
    base = os.getenv('SEROPS_PUBLIC_BASE_URL', '').rstrip('/')
    if not base or not getattr(batch, 'batch_id', None):
        return ''
    return f'{base}/dash/issues/{batch.batch_id}'
