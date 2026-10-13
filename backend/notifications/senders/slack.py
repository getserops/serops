"""Slack Incoming Webhook sender.

Slack Incoming Webhooks accept a POST with a JSON body describing
either a plain-text message or Block Kit blocks. We use Block Kit
for a formatted incident summary.

Docs: https://api.slack.com/messaging/webhooks
"""

import logging

import requests
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 8


def _format_severity_emoji(severity: str) -> str:
    """Emoji prefix so the summary is scan-able in a Slack channel."""
    return {
        'CRITICAL': ':rotating_light:',
        'HIGH': ':warning:',
        'MEDIUM': ':large_orange_diamond:',
        'LOW': ':large_blue_diamond:',
        'INFO': ':information_source:',
    }.get((severity or '').upper(), ':bell:')


def _build_blocks(payload: dict) -> list:
    """Convert the dispatcher payload into a Block Kit blocks list."""
    title = payload.get('title', 'SerOps analysis')
    project = payload.get('project_name') or 'unknown project'
    environment = payload.get('environment') or 'unknown env'
    severity = payload.get('top_severity') or ''
    issue_count = payload.get('issue_count', 0)
    root_cause = (payload.get('root_cause') or '')[:400]
    recommendation = (payload.get('recommendation') or '')[:400]
    incident_url = payload.get('incident_url') or ''

    blocks = [
        {
            'type': 'header',
            'text': {
                'type': 'plain_text',
                'text': f'{_format_severity_emoji(severity)}  {title}',
                'emoji': True,
            },
        },
        {
            'type': 'section',
            'fields': [
                {'type': 'mrkdwn', 'text': f'*Project*\n{project}'},
                {'type': 'mrkdwn', 'text': f'*Environment*\n{environment}'},
                {'type': 'mrkdwn', 'text': f'*Severity*\n{severity or "n/a"}'},
                {'type': 'mrkdwn', 'text': f'*Issues*\n{issue_count}'},
            ],
        },
    ]
    if root_cause:
        blocks.append({
            'type': 'section',
            'text': {'type': 'mrkdwn', 'text': f'*Root cause*\n{root_cause}'},
        })
    if recommendation:
        blocks.append({
            'type': 'section',
            'text': {'type': 'mrkdwn', 'text': f'*Recommendation*\n{recommendation}'},
        })
    if incident_url:
        blocks.append({
            'type': 'actions',
            'elements': [{
                'type': 'button',
                'text': {'type': 'plain_text', 'text': 'Open in SerOps'},
                'url': incident_url,
                'style': 'primary',
            }],
        })
    return blocks


def send(channel, payload: dict):
    """POST a Block Kit message to the channel's Slack webhook URL."""
    url = channel.get_webhook_url()
    if not url:
        return False, 'Missing Slack webhook URL'

    body = {
        'blocks': _build_blocks(payload),
        # Fallback text used by notifications / mobile previews.
        'text': payload.get('title', 'SerOps analysis'),
    }

    try:
        resp = requests.post(url, json=body, timeout=_TIMEOUT_SECONDS)
    except RequestException as exc:
        return False, f'Network error: {exc}'

    if resp.status_code >= 300:
        # Slack returns 200 + "ok" body on success; anything else is a fail.
        return False, f'HTTP {resp.status_code}: {resp.text[:200]}'
    return True, ''
