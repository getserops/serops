"""Microsoft Teams Incoming Webhook sender.

Teams webhook accepts either legacy MessageCard JSON or the newer
Adaptive Card via workflows. We use MessageCard (still widely
supported and simpler — no schema version dance).

Docs: https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/connectors-using
"""

import logging

import requests
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 8


def _severity_color(severity: str) -> str:
    return {
        'CRITICAL': 'D9534F',
        'HIGH': 'F0AD4E',
        'MEDIUM': 'FFB84D',
        'LOW': '5BC0DE',
        'INFO': '5CB85C',
    }.get((severity or '').upper(), '777777')


def _build_message_card(payload: dict) -> dict:
    title = payload.get('title', 'SerOps analysis')
    project = payload.get('project_name') or 'unknown project'
    environment = payload.get('environment') or 'unknown env'
    severity = payload.get('top_severity') or 'INFO'
    issue_count = payload.get('issue_count', 0)
    root_cause = (payload.get('root_cause') or '')[:400]
    recommendation = (payload.get('recommendation') or '')[:400]
    incident_url = payload.get('incident_url') or ''

    facts = [
        {'name': 'Project', 'value': project},
        {'name': 'Environment', 'value': environment},
        {'name': 'Severity', 'value': severity},
        {'name': 'Issues', 'value': str(issue_count)},
    ]
    if root_cause:
        facts.append({'name': 'Root cause', 'value': root_cause})
    if recommendation:
        facts.append({'name': 'Recommendation', 'value': recommendation})

    card = {
        '@type': 'MessageCard',
        '@context': 'https://schema.org/extensions',
        'summary': title,
        'themeColor': _severity_color(severity),
        'title': title,
        'sections': [{'facts': facts}],
    }
    if incident_url:
        card['potentialAction'] = [{
            '@type': 'OpenUri',
            'name': 'Open in SerOps',
            'targets': [{'os': 'default', 'uri': incident_url}],
        }]
    return card


def send(channel, payload: dict):
    url = channel.get_webhook_url()
    if not url:
        return False, 'Missing Teams webhook URL'

    try:
        resp = requests.post(
            url, json=_build_message_card(payload), timeout=_TIMEOUT_SECONDS,
        )
    except RequestException as exc:
        return False, f'Network error: {exc}'

    if resp.status_code >= 300:
        return False, f'HTTP {resp.status_code}: {resp.text[:200]}'
    return True, ''
