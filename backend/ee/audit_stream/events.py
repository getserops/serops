"""What an audit event looks like on the wire (schema ``serops.audit.v1``).

One JSON object per event, the same for every transport:

    {"schema": "serops.audit.v1", "id": 4211, "time": "2026-11-14T09:30:12.123456Z",
     "organisation": {"id": 3, "name": "Acme"},
     "action": "LOGIN", "action_label": "User Login", "outcome": "success",
     "actor": {"type": "user", "id": 17, "email": "ana@acme.example"},
     "client": {"ip": "203.0.113.7", "user_agent": "Mozilla/5.0 ..."},
     "details": {...}, "source": {"product": "SerOps", "version": "1.4.0", "host": "serops.acme.example"}}

``id`` is the audit entry's id: unique per install and stable across
retries, so a SIEM can drop duplicates (delivery is at least once).
"""
import datetime
import json
import socket
from urllib.parse import urlsplit

from django.conf import settings

SCHEMA = 'serops.audit.v1'

# RFC 5424: facility 13 is "log audit"; severities notice (5) and warning (4).
FACILITY_LOG_AUDIT = 13
SEVERITY_NOTICE = 5
SEVERITY_WARNING = 4
_FAILURE_MARKERS = ('FAILED', 'DENIED', 'DEACTIVATE', 'REVOKE', 'DELETE')


def install_host():
    """The install's public host name (from API_URL), else the machine's."""
    host = urlsplit(getattr(settings, 'API_URL', '') or '').hostname
    return host or socket.gethostname()


def _source():
    from api.version import __version__
    return {'product': 'SerOps', 'version': __version__, 'host': install_host()}


def _time(dt):
    return dt.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _actor(entry):
    if entry.user_id:
        return {'type': 'user', 'id': entry.user_id, 'email': entry.user.email if entry.user else None}
    source = (entry.details or {}).get('source') if isinstance(entry.details, dict) else None
    return {'type': 'scim' if source == 'scim' else 'system'}


def outcome(action):
    return 'failure' if action.endswith('_FAILED') or action.endswith('_DENIED') else 'success'


def event(entry):
    """The wire form of an AuditLog entry."""
    from Data.models import AuditLog
    labels = dict(AuditLog.ACTION_TYPES)
    return {
        'schema': SCHEMA,
        'id': entry.pk,
        'time': _time(entry.created_at),
        'organisation': {'id': entry.organisation_id, 'name': entry.organisation.name},
        'action': entry.action,
        'action_label': labels.get(entry.action, entry.action),
        'outcome': outcome(entry.action),
        'actor': _actor(entry),
        'client': {'ip': entry.ip_address, 'user_agent': entry.user_agent or None},
        'details': entry.details or {},
        'source': _source(),
    }


def test_event(organisation, user):
    """A synthetic event for "Send a test event" (never stored in the audit log)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        'schema': SCHEMA, 'id': None, 'time': _time(now),
        'organisation': {'id': organisation.pk, 'name': organisation.name},
        'action': 'AUDIT_STREAM_TEST', 'action_label': 'Audit Stream Test', 'outcome': 'success',
        'actor': {'type': 'user', 'id': user.pk, 'email': user.email},
        'client': {'ip': None, 'user_agent': None},
        'details': {'message': 'Test event from SerOps: the destination is reachable.'},
        'source': _source(),
    }


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'), default=str)


# --- HTTP bodies --------------------------------------------------------------

def http_body(events, fmt):
    """(body bytes, content type) for a batch of events."""
    if fmt == 'ndjson':
        return ''.join(dumps(e) + '\n' for e in events).encode(), 'application/x-ndjson'
    if fmt == 'splunk_hec':
        # HEC's event endpoint takes events back to back, each with its own time.
        parts = []
        for e in events:
            ts = datetime.datetime.strptime(e['time'], '%Y-%m-%dT%H:%M:%S.%fZ').replace(
                tzinfo=datetime.timezone.utc).timestamp()
            parts.append(dumps({'time': round(ts, 3), 'host': e['source']['host'], 'source': 'serops',
                                'sourcetype': 'serops:audit', 'event': e}))
        return '\n'.join(parts).encode(), 'application/json'
    return dumps(events).encode(), 'application/json'


# --- Syslog (RFC 5424) --------------------------------------------------------

def _printable(value, limit):
    """RFC 5424 header fields: printable US-ASCII without spaces, or "-"."""
    cleaned = ''.join(c for c in str(value or '') if 33 <= ord(c) <= 126)[:limit]
    return cleaned or '-'


def syslog_message(e):
    """One RFC 5424 message, the JSON event as MSG.

    UTF-8 without the BOM (RFC 5424 MSG-ANY, as rsyslog sends): collectors
    such as Vector keep a BOM in the message, and a JSON parser downstream
    then fails on it.
    """
    severity = SEVERITY_WARNING if any(m in e['action'] for m in _FAILURE_MARKERS) else SEVERITY_NOTICE
    pri = FACILITY_LOG_AUDIT * 8 + severity
    header = (f"<{pri}>1 {e['time']} {_printable(e['source']['host'], 255)} serops - "
              f"{_printable(e['action'], 32)} -")
    return header.encode() + b' ' + dumps(e).encode()


def octet_counted(message):
    """RFC 5425 / RFC 6587 framing for TCP: "LEN SP MSG"."""
    return str(len(message)).encode() + b' ' + message
