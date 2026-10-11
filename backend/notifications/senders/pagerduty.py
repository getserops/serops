"""PagerDuty Events API v2 sender.

We use the **change event** endpoint (not the alert event endpoint) —
change events are visible on the PagerDuty service timeline but do
not create new incidents. When paired with an alert-triggered
analysis (Item #14), this attaches SerOps' AI RCA to the existing
incident timeline without duplicate incidents.

Docs:
  https://developer.pagerduty.com/api-reference/change-events
"""

import logging
from datetime import datetime, timezone

import requests
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)

_CHANGE_EVENTS_URL = 'https://events.pagerduty.com/v2/change/enqueue'
_TIMEOUT_SECONDS = 8


def _build_change_event(channel, payload: dict) -> dict:
    """Build the PagerDuty Events API v2 change event body."""
    title = payload.get('title', 'SerOps analysis')
    project = payload.get('project_name') or 'unknown project'
    environment = payload.get('environment') or 'unknown env'
    severity = payload.get('top_severity') or ''
    root_cause = (payload.get('root_cause') or '')[:1000]
    recommendation = (payload.get('recommendation') or '')[:1000]
    incident_url = payload.get('incident_url') or ''

    summary = (
        f'{title} — {project}/{environment}'
        + (f' [{severity}]' if severity else '')
    )
    custom_details = {
        'project': project,
        'environment': environment,
        'severity': severity,
        'issue_count': payload.get('issue_count', 0),
    }
    if root_cause:
        custom_details['root_cause'] = root_cause
    if recommendation:
        custom_details['recommendation'] = recommendation

    body = {
        'routing_key': channel.get_api_key(),
        'payload': {
            'summary': summary[:1024],
            'source': 'serops',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'custom_details': custom_details,
        },
    }
    if incident_url:
        body['links'] = [{'href': incident_url, 'text': 'View in SerOps'}]
    return body


def send(channel, payload: dict):
    integration_key = channel.get_api_key()
    if not integration_key:
        return False, 'Missing PagerDuty integration key'

    body = _build_change_event(channel, payload)

    try:
        resp = requests.post(_CHANGE_EVENTS_URL, json=body, timeout=_TIMEOUT_SECONDS)
    except RequestException as exc:
        return False, f'Network error: {exc}'

    # PagerDuty returns 202 Accepted on success.
    if resp.status_code >= 300:
        return False, f'HTTP {resp.status_code}: {resp.text[:200]}'
    return True, ''
