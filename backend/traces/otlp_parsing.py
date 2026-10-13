"""Shared OTLP-format parsing helpers.

Used by two callers:

* ``traces.otlp_views.OTLPTracesReceiver`` — inbound push (writes to DB).
* ``integrations.adapters.tempo_traces.TempoTraceAdapter`` — outbound
  pull from Grafana Tempo, which returns spans in the same
  OTLP/HTTP JSON shape.

Keeping the parsing here means the two paths cannot drift on subtle
things like OTEL alias handling, kind normalisation, or status-code
mapping. Both callers get a stable canonical shape (dict for the
receiver, dataclass for the adapter — see ``parse_span_to_dict`` vs
``parse_span_to_entry``).
"""

from datetime import datetime, timezone
from typing import Optional

from integrations.field_aliases import SERVICE_NAME_ALIASES, first_present


def parse_attributes(attrs_list):
    """OTLP attributes are ``[{key, value: {stringValue|intValue|...}}]``.

    Flatten to a plain ``dict`` so downstream consumers don't have to
    know the OTEL type-union shape. Non-primitive values
    (arrayValue / kvlistValue / bytesValue) keep their wrapper — we
    don't try to interpret them.
    """
    out = {}
    for attr in attrs_list or []:
        if not isinstance(attr, dict):
            continue
        k = attr.get('key')
        if not k:
            continue
        v = attr.get('value') or {}
        if isinstance(v, dict):
            for type_key in ('stringValue', 'intValue', 'doubleValue', 'boolValue'):
                if type_key in v:
                    out[k] = v[type_key]
                    break
            else:
                out[k] = v
        else:
            out[k] = v
    return out


def parse_kind(raw) -> str:
    """OTLP kinds: SPAN_KIND_INTERNAL / _SERVER / _CLIENT / _PRODUCER / _CONSUMER."""
    raw = str(raw).upper()
    for k in ('INTERNAL', 'SERVER', 'CLIENT', 'PRODUCER', 'CONSUMER'):
        if k in raw:
            return k
    return 'INTERNAL'


def parse_status(status_obj):
    """Return (status_code, status_message).

    OTLP uses STATUS_CODE_OK / _ERROR / _UNSET; some SDKs send plain
    OK / ERROR. Accept both.
    """
    if not isinstance(status_obj, dict):
        return 'UNSET', ''
    raw = str(status_obj.get('code', '')).upper()
    if raw.endswith('OK') or raw == 'OK':
        code = 'OK'
    elif raw.endswith('ERROR') or raw == 'ERROR':
        code = 'ERROR'
    else:
        code = 'UNSET'
    return code, str(status_obj.get('message', ''))[:500]


def parse_events(events_list):
    """OTLP events: ``[{timeUnixNano, name, attributes}]``.

    Returns a JSON-friendly list of dicts with an ISO-8601 ``time``.
    """
    out = []
    for e in events_list or []:
        if not isinstance(e, dict):
            continue
        try:
            ts_ns = int(e.get('timeUnixNano', 0))
            ts = datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=timezone.utc).isoformat()
        except (TypeError, ValueError):
            ts = None
        out.append({
            'time': ts,
            'name': str(e.get('name', ''))[:255],
            'attributes': parse_attributes(e.get('attributes') or []),
        })
    return out


def _normalise_id(raw, expected_hex_len):
    """Accept OTLP-JSON's spec-compliant base64 IDs OR hex IDs.

    E18-1 (2026-09-12): the OTLP HTTP/JSON spec (opentelemetry-proto)
    encodes trace_id + span_id as base64. Some clients (custom scripts,
    older exporters) send hex instead. Both are seen in the wild —
    accept either and normalise to lowercase hex.

    Returns the 32/16-char lowercase hex ID, or '' on failure.
    Length-checked against ``expected_hex_len``.
    """
    import base64, binascii
    if not raw:
        return ''
    s = str(raw)
    # If already hex + right length, use as-is.
    if len(s) == expected_hex_len:
        try:
            bytes.fromhex(s)  # validate hex
            return s.lower()
        except ValueError:
            pass
    # Otherwise try base64 (with or without padding).
    try:
        # Pad to multiple of 4 for base64.decodebytes strict mode
        padded = s + '=' * (-len(s) % 4)
        decoded = base64.b64decode(padded, validate=False)
        return decoded.hex().lower() if len(decoded) * 2 == expected_hex_len else ''
    except (binascii.Error, ValueError):
        return ''


def parse_span_dict(span_dict, resource_attrs, resource_service_name) -> Optional[dict]:
    """Convert one OTLP span dict → normalised dict, or ``None`` if malformed.

    Malformed = missing / wrong-length trace_id or span_id, or
    unparseable timestamps. Silent drop rather than raise — a single
    bad span in a batch of 500 must not fail the whole batch.

    Accepts both hex and base64 trace/span IDs. OTLP/JSON spec says
    base64 (opentelemetry-proto), but hex is widely seen in custom
    clients + hand-crafted test payloads. Normalised to lowercase hex.
    """
    trace_id = _normalise_id(span_dict.get('traceId'), 32)
    span_id = _normalise_id(span_dict.get('spanId'), 16)
    if not trace_id or not span_id:
        return None

    try:
        start_ns = int(span_dict.get('startTimeUnixNano', 0))
        end_ns = int(span_dict.get('endTimeUnixNano', 0))
        if end_ns < start_ns:
            end_ns = start_ns
        start_time = datetime.fromtimestamp(start_ns / 1_000_000_000, tz=timezone.utc)
        end_time = datetime.fromtimestamp(end_ns / 1_000_000_000, tz=timezone.utc)
    except (TypeError, ValueError):
        return None
    duration_ms = int((end_ns - start_ns) / 1_000_000)

    # parent_span_id — same base64/hex ambiguity. Empty is valid (root span).
    raw_parent = span_dict.get('parentSpanId', '') or ''
    parent_span_id = _normalise_id(raw_parent, 16) if raw_parent else ''
    kind = parse_kind(span_dict.get('kind', ''))

    span_attrs = parse_attributes(span_dict.get('attributes') or [])
    merged_attrs = {**(resource_attrs or {}), **span_attrs}

    service_name = first_present(
        merged_attrs, SERVICE_NAME_ALIASES, default=resource_service_name,
    )

    status_code, status_message = parse_status(span_dict.get('status') or {})
    events = parse_events(span_dict.get('events') or [])

    return {
        'trace_id': trace_id,
        'span_id': span_id,
        'parent_span_id': parent_span_id,
        'service_name': (service_name or '')[:255],
        'operation_name': str(span_dict.get('name', ''))[:255],
        'kind': kind,
        'start_time': start_time,
        'end_time': end_time,
        'duration_ms': duration_ms,
        'status_code': status_code,
        'status_message': status_message,
        'attributes': merged_attrs,
        'events': events,
    }


def iter_resource_spans(payload):
    """Yield ``(span_dict, resource_attrs, resource_service_name)`` triples
    for every span in an OTLP payload.

    Accepts the standard shape::

        {"resourceSpans": [
            {"resource": {"attributes": [...]},
             "scopeSpans": [{"spans": [...]}]}
        ]}
    """
    for rs in (payload or {}).get('resourceSpans') or []:
        if not isinstance(rs, dict):
            continue
        resource = rs.get('resource') or {}
        resource_attrs = parse_attributes(resource.get('attributes') or [])
        resource_service_name = first_present(
            resource_attrs, SERVICE_NAME_ALIASES, default='',
        )
        for scope in rs.get('scopeSpans') or []:
            if not isinstance(scope, dict):
                continue
            for span_dict in scope.get('spans') or []:
                if isinstance(span_dict, dict):
                    yield span_dict, resource_attrs, resource_service_name
