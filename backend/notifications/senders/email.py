"""Email sender for ``IncidentNotificationChannel(kind='email')``.

Uses Django's site-configured EMAIL_BACKEND (SMTP in prod). Recipient
addresses live on ``channel.extra_config['to']`` — either a single
string or a list of strings. Optional per-channel ``from`` / ``reply_to``
overrides fall through to ``DEFAULT_FROM_EMAIL``.

Never raises: notification failures cannot fail the batch analysis.
"""

from __future__ import annotations
import logging

from django.conf import settings
from django.core.mail import EmailMessage

logger = logging.getLogger(__name__)


def _normalise_to(raw) -> list[str]:
    """Accept a str, list, or comma-separated string; return a clean list."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        return [p.strip() for p in raw.split(',') if p.strip()]
    return []


def _format_subject(payload: dict) -> str:
    sev = (payload.get('top_severity') or '').upper() or 'INFO'
    project = payload.get('project_name') or 'unknown project'
    env = payload.get('environment') or 'unknown env'
    count = payload.get('issue_count', 0)
    return f'[SerOps · {sev}] {project} ({env}) — {count} issue(s)'


def _format_body(payload: dict) -> str:
    lines = [
        f"Project:     {payload.get('project_name') or 'unknown'}",
        f"Environment: {payload.get('environment') or 'unknown'}",
        f"Batch:       {payload.get('batch_id') or '?'}",
        f"Severity:    {(payload.get('top_severity') or 'INFO').upper()}",
        '',
        payload.get('title') or 'SerOps analysis',
        '',
    ]
    for issue in (payload.get('issues') or [])[:5]:
        lines.append(f"  • [{issue.get('severity', 'INFO')}] {issue.get('description', '')}")
    link = payload.get('batch_url')
    if link:
        lines += ['', f'View full analysis: {link}']
    return '\n'.join(lines)


def send(channel, payload) -> tuple[bool, str]:
    """Send one email. Returns (ok, message)."""
    extra = channel.extra_config or {}
    to = _normalise_to(extra.get('to'))
    if not to:
        return False, "channel.extra_config['to'] is empty — no recipients"

    subject = _format_subject(payload)
    body = _format_body(payload)
    from_email = extra.get('from') or getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@serops.ai')
    reply_to = extra.get('reply_to')

    try:
        msg = EmailMessage(
            subject=subject, body=body,
            from_email=from_email, to=to,
            reply_to=[reply_to] if reply_to else None,
        )
        sent_count = msg.send(fail_silently=False)
    except Exception as exc:
        return False, f'Email send failed: {type(exc).__name__}: {exc}'
    if sent_count == 0:
        return False, 'Email backend accepted the send but delivered 0 messages'
    return True, f'delivered to {len(to)} recipient(s)'
