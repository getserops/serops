"""Datadog APM Trace Adapter for TraceProvider ABC.

Uses the Datadog Spans Search API:

  POST /api/v2/spans/events/search      — list spans matching a query
  GET  /api/v1/validate                 — health / API-key validation

Datadog requires both ``DD-API-KEY`` and ``DD-APPLICATION-KEY``
headers for the Spans API. Set in the integration config as
``extra_config.api_key`` and ``extra_config.app_key``.

Datadog's span shape (spans/events/search):

    {"data": [{
        "id": "span_id",
        "type": "spans",
        "attributes": {
            "trace_id": "...", "span_id": "...", "parent_id": "...",
            "service": "..", "resource_name": "..", "type": "web",
            "start_timestamp": "<iso>", "end_timestamp": "<iso>",
            "duration": <nanos>, "custom": {...}, "tags": [".."],
            "status": "ok"|"error"
        }
    }]}

We use the spans search (not the traces API) because it returns
canonical span-level data that maps cleanly to our SpanEntry.
For fetch_trace we do the same search filtered by trace_id.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import requests
from requests.exceptions import RequestException

from integrations.base import TraceProvider, TraceProviderCapabilities
from traces.schemas import SpanEntry, TraceEntry

logger = logging.getLogger(__name__)

_TRACE_ID_WIDTH = 32
_SPAN_ID_WIDTH = 16


def _pad_id(value: str, width: int) -> str:
    if not value:
        return ''
    # Datadog returns numeric IDs as strings; if they're already hex,
    # left-pad. If they're decimal, convert first.
    v = str(value)
    try:
        # Decimal → hex if all digits.
        if v.isdigit():
            v = format(int(v), 'x')
    except (TypeError, ValueError):
        pass
    return v.lower().rjust(width, '0')[:width]


def _parse_iso(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        # Datadog uses ISO 8601 with 'Z' or ±offset.
        if isinstance(value, str) and value.endswith('Z'):
            value = value[:-1] + '+00:00'
        return datetime.fromisoformat(str(value)).astimezone(timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


class DatadogTraceAdapter(TraceProvider):
    """Datadog APM adapter — pull via Spans Search API."""

    capabilities = TraceProviderCapabilities(
        spans=True,
        max_query_window_hours=24 * 15,   # DD retention: 15 days default
        fetch_by_id=True,
    )

    def __init__(self, config: dict = None):
        super().__init__(config)
        # DD site is configurable — US1, US3, US5, EU1, US1-FED.
        site = self._config.get('site') or self._config.get(
            'extra_config', {}
        ).get('site', 'datadoghq.com')
        self.base_url = f'https://api.{site}'
        self._session = requests.Session()

        extras = self._config.get('extra_config', {}) or {}
        api_key = self._config.get('api_key') or extras.get('api_key')
        app_key = self._config.get('app_key') or extras.get('app_key')
        if not api_key or not app_key:
            logger.warning(
                'DatadogTraceAdapter initialised without api_key + app_key '
                '— all calls will 403. Set extra_config.api_key and '
                'extra_config.app_key on the ObservabilityIntegration.'
            )
        self._session.headers.update({
            'DD-API-KEY': api_key or '',
            'DD-APPLICATION-KEY': app_key or '',
            'Content-Type': 'application/json',
        })

    def fetch_traces(self, service_name, since, until, limit=50):
        # Datadog query: `service:<name>`. Filter to root spans so we
        # get one row per trace, not one per span.
        query = f'service:{service_name} -_dd.origin:appsec'
        body = {
            'data': {
                'attributes': {
                    'filter': {
                        'query': query,
                        'from': since.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
                        'to': until.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    },
                    'page': {'limit': min(int(limit or 50), 1000)},
                    'sort': '-timestamp',
                }
            }
        }
        try:
            resp = self._session.post(
                f'{self.base_url}/api/v2/spans/events/search',
                json=body,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
        except RequestException as exc:
            logger.warning('Datadog fetch_traces failed: %s', exc)
            return []

        payload = resp.json() or {}
        # Group spans by trace_id → TraceEntry.
        by_trace: dict = {}
        for row in (payload.get('data') or []):
            span = self._parse_span(row)
            if not span or not span.trace_id:
                continue
            by_trace.setdefault(span.trace_id, []).append(span)

        return [self._assemble_trace(tid, spans) for tid, spans in by_trace.items()]

    def fetch_trace(self, trace_id):
        if not trace_id:
            return None
        body = {
            'data': {
                'attributes': {
                    'filter': {'query': f'trace_id:{trace_id}'},
                    'page': {'limit': 1000},
                }
            }
        }
        try:
            resp = self._session.post(
                f'{self.base_url}/api/v2/spans/events/search',
                json=body,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
        except RequestException as exc:
            logger.warning('Datadog fetch_trace(%s) failed: %s', trace_id, exc)
            return None

        payload = resp.json() or {}
        spans = [self._parse_span(row) for row in (payload.get('data') or [])]
        spans = [s for s in spans if s]
        if not spans:
            return None
        return self._assemble_trace(trace_id, spans)

    def health_check(self):
        try:
            resp = self._session.get(
                f'{self.base_url}/api/v1/validate',
                timeout=min(self.timeout_seconds, 5),
            )
            return resp.status_code == 200
        except RequestException:
            return False

    # ------------------------------------------------------------------

    def _parse_span(self, row: dict) -> Optional[SpanEntry]:
        if not isinstance(row, dict):
            return None
        attrs = row.get('attributes') or {}
        if not attrs:
            return None

        trace_id = _pad_id(attrs.get('trace_id') or attrs.get('traceId'), _TRACE_ID_WIDTH)
        span_id = _pad_id(attrs.get('span_id') or attrs.get('spanId') or row.get('id'), _SPAN_ID_WIDTH)
        if not (trace_id and span_id):
            return None

        parent = attrs.get('parent_id') or attrs.get('parentSpanId') or ''
        # Datadog "0" parent means root.
        if parent in ('0', '', 0, None):
            parent = ''
        else:
            parent = _pad_id(parent, _SPAN_ID_WIDTH)

        start = _parse_iso(attrs.get('start_timestamp') or attrs.get('start'))
        end = _parse_iso(attrs.get('end_timestamp') or attrs.get('end'))
        duration_ns = attrs.get('duration') or 0
        try:
            duration_ms = max(0, int(duration_ns) // 1_000_000)
        except (TypeError, ValueError):
            duration_ms = 0
        # If DD didn't give us end, derive from start + duration.
        if start and not end:
            from datetime import timedelta
            end = start + timedelta(milliseconds=duration_ms)

        status = str(attrs.get('status') or '').lower()
        status_code = 'ERROR' if status == 'error' else ('OK' if status == 'ok' else 'UNSET')

        custom = attrs.get('custom') or {}
        return SpanEntry(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent,
            service_name=str(attrs.get('service') or ''),
            operation_name=str(attrs.get('resource_name') or attrs.get('name') or ''),
            kind=str(attrs.get('type') or 'INTERNAL').upper(),
            start_time=start,
            end_time=end,
            duration_ms=duration_ms,
            status_code=status_code,
            status_message=str(custom.get('error.message') or ''),
            attributes=custom if isinstance(custom, dict) else {},
            events=[],
        )

    def _assemble_trace(self, trace_id: str, spans: list) -> TraceEntry:
        root = next((s for s in spans if not s.parent_span_id), spans[0] if spans else None)
        if root:
            start = min((s.start_time for s in spans if s.start_time), default=root.start_time)
            end = max((s.end_time for s in spans if s.end_time), default=root.end_time)
            duration_ms = int((end - start).total_seconds() * 1000) if (start and end) else root.duration_ms
        else:
            start = end = None
            duration_ms = 0

        error_count = sum(1 for s in spans if s.status_code == 'ERROR')
        trace_status = 'ERROR' if error_count > 0 else ('OK' if spans else 'UNSET')

        return TraceEntry(
            trace_id=trace_id,
            root_service_name=root.service_name if root else '',
            root_operation=root.operation_name if root else '',
            start_time=start,
            end_time=end,
            duration_ms=duration_ms,
            span_count=len(spans),
            error_span_count=error_count,
            status_code=trace_status,
            spans=spans,
        )
