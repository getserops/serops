"""OpsGenie Alert API sender.

We create a low-priority note-style alert on the OpsGenie side so
it appears on the on-call's timeline without paging anyone. The
``priority`` field defaults to P4 (info) so this is a passive
notification, not a fresh page.

Region: ``us`` (default) or ``eu`` — set on
``channel.extra_config.region``.

Docs:
  https://docs.opsgenie.com/docs/alert-api
"""

import logging

import requests
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)

_REGION_BASE = {
    'us': 'https://api.opsgenie.com',
    'eu': 'https://api.eu.opsgenie.com',
}
_TIMEOUT_SECONDS = 8


def _priority_from_severity(severity: str) -> str:
    return {
        'CRITICAL': 'P2',
        'HIGH': 'P3',
        'MEDIUM': 'P4',
        'LOW': 'P5',
        'INFO': 'P5',
    }.get((severity or '').upper(), 'P4')


def _build_body(payload: dict) -> dict:
    title = payload.get('title', 'SerOps analysis')
    project = payload.get('project_name') or 'unknown project'
    environment = payload.get('environment') or 'unknown env'
    severity = payload.get('top_severity') or 'INFO'
    issue_count = payload.get('issue_count', 0)
    root_cause = (payload.get('root_cause') or '')[:5000]
    recommendation = (payload.get('recommendation') or '')[:5000]
    incident_url = payload.get('incident_url') or ''

    description_parts = [
        f'Project: {project}',
        f'Environment: {environment}',
        f'Severity: {severity}',
        f'Issues: {issue_count}',
    ]
    if root_cause:
        description_parts.append('')
        description_parts.append(f'Root cause:\n{root_cause}')
    if recommendation:
        description_parts.append('')
        description_parts.append(f'Recommendation:\n{recommendation}')
    if incident_url:
        description_parts.append('')
        description_parts.append(f'Open in SerOps: {incident_url}')

    return {
        'message': title[:130],
        'description': '\n'.join(description_parts)[:15000],
        'source': 'serops',
        'priority': _priority_from_severity(severity),
        'tags': ['serops', 'ai-rca'] + ([project] if project else []),
    }


def send(channel, payload: dict):
    api_key = channel.get_api_key()
    if not api_key:
        return False, 'Missing OpsGenie API key'

    region = str((channel.extra_config or {}).get('region') or 'us').lower()
    base = _REGION_BASE.get(region)
    if base is None:
        return False, f'Unknown OpsGenie region "{region}" (allowed: us, eu)'

    try:
        resp = requests.post(
            f'{base}/v2/alerts',
            headers={
                'Authorization': f'GenieKey {api_key}',
                'Content-Type': 'application/json',
            },
            json=_build_body(payload),
            timeout=_TIMEOUT_SECONDS,
        )
    except RequestException as exc:
        return False, f'Network error: {exc}'

    if resp.status_code >= 300:
        return False, f'HTTP {resp.status_code}: {resp.text[:200]}'
    return True, ''
