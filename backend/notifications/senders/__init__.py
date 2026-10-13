"""Outbound notification senders (Items #22 + #23).

Each sender module exposes a single ``send(channel, payload) -> tuple[bool, str]``
function returning ``(ok, message)``. On success ``ok=True`` and
``message`` is empty or human-readable info. On failure ``ok=False``
and ``message`` is the error string (never a raw exception object —
callers write it to ``IncidentNotificationChannel.last_error``).

Senders MUST NEVER raise into their caller. Notification failures
cannot fail the batch analysis pipeline.
"""

from .slack import send as send_slack
from .teams import send as send_teams
from .pagerduty import send as send_pagerduty
from .opsgenie import send as send_opsgenie
from .email import send as send_email


SENDER_BY_KIND = {
    'slack': send_slack,
    'teams': send_teams,
    'pagerduty': send_pagerduty,
    'opsgenie': send_opsgenie,
    'email': send_email,
}

__all__ = ['SENDER_BY_KIND']
