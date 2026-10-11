"""Jaeger Trace Adapter for TraceProvider ABC.

Uses the Jaeger HTTP query API (v1):

  GET /api/services                        — health / service list
  GET /api/traces?service=X&start=...      — recent traces for a service
  GET /api/traces/<trace_id>               — single trace

Jaeger's trace shape (as of Jaeger v1.42+):

    {"data": [{"traceID": "abc", "spans": [{"spanID":"..","operationName":"..",
               "startTime": <micro>, "duration": <micro>, "tags":[...], ...}]}]}

trace/span IDs are hex strings but Jaeger uses variable-length (up to
32 for trace, up to 16 for span) — we left-pad to canonical length so
they match OTLP-ingested traces if the same trace shows up in both
stores.

Security notes:

* ``service_name`` and ``trace_id`` are user-provided and go into
  query params; requests handles URL-encoding, and we never string-
  format them into the URL path.
* All HTTP responses are treated as untrusted JSON — we only pull
  known keys, never eval or template-inject.
"""

import logging
from datetime import datetime
from typing import List, Optional

import requests
from requests.exceptions import RequestException

from integrations.base import TraceProvider, TraceProviderCapabilities
from traces.schemas import SpanEntry, TraceEntry

logger = logging.getLogger(__name__)

# Canonical widths (OTEL): trace_id = 32 hex, span_id = 16 hex.
_TRACE_ID_WIDTH = 32
_SPAN_ID_WIDTH = 16


def _pad_id(value: str, width: int) -> str:
    if not value:
        return ''
    return value.lower().rjust(width, '0')[:width]


def _from_unix_micros(micros) -> Optional[datetime]:
    try:
        return datetime.utcfromtimestamp(int(micros) / 1_000_000)
    except (TypeError, ValueError):
        return None


def _tag_dict(tags) -> dict:
    """Convert Jaeger's [{key, type, value}] tag list to a flat dict."""
    if not isinstance(tags, list):
        return {}
    out = {}
    for tag in tags:
        if isinstance(tag, dict) and 'key' in tag:
            out[str(tag['key'])] = tag.get('value')
    return out


def _status_from_tags(tag_dict: dict) -> str:
    """
    Jaeger encodes span status in tags:
    - {'error': True}     → ERROR
    - {'otel.status_code': 'ERROR'|'OK'}
    Default: UNSET (Jaeger doesn't force a status).
    """
    if tag_dict.get('error') is True or tag_dict.get('error') == 'true':
        return 'ERROR'
    otel_status = tag_dict.get('otel.status_code')
    if isinstance(otel_status, str) and otel_status.upper() in ('OK', 'ERROR'):
        return otel_status.upper()
    return 'UNSET'


class JaegerTraceAdapter(TraceProvider):
    """Jaeger v1.x adapter — pull-only."""

    capabilities = TraceProviderCapabilities(
        spans=True,
        max_query_window_hours=72,   # Jaeger memory backend defaults to 72h
        fetch_by_id=True,
    )

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.base_url = self._config.get('host', 'http://jaeger:16686').rstrip('/')
        self._session = requests.Session()
        # Optional basic auth for gateway-fronted Jaeger.
        username = self._config.get('username')
        password = self._config.get('password')
        if username and password:
            self._session.auth = (username, password)
        bearer = self._config.get('bearer_token')
        if bearer:
            self._session.headers['Authorization'] = f'Bearer {bearer}'

    # ------------------------------------------------------------------

    def fetch_traces(self, service_name, since, until, limit=50):
        # Jaeger expects microseconds since epoch.
        params = {
            'service': service_name,
            'start': int(since.timestamp() * 1_000_000),
            'end': int(until.timestamp() * 1_000_000),
            'limit': min(int(limit or 50), 1500),
        }
        try:
            resp = self._session.get(
                f'{self.base_url}/api/traces',
                params=params,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
        except RequestException as exc:
            logger.warning('Jaeger fetch_traces failed: %s', exc)
            return []

        payload = resp.json() or {}
        return [self._parse_trace(t) for t in (payload.get('data') or [])]

    def fetch_trace(self, trace_id):
        if not trace_id:
            return None
        try:
            resp = self._session.get(
                f'{self.base_url}/api/traces/{trace_id}',
                timeout=self.timeout_seconds,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        except RequestException as exc:
            logger.warning('Jaeger fetch_trace(%s) failed: %s', trace_id, exc)
            return None

        payload = resp.json() or {}
        data = payload.get('data') or []
        if not data:
            return None
        return self._parse_trace(data[0])

    def health_check(self):
        try:
            resp = self._session.get(
                f'{self.base_url}/api/services',
                timeout=min(self.timeout_seconds, 5),
            )
            return resp.status_code == 200
        except RequestException:
            return False

    # ------------------------------------------------------------------

    def _parse_trace(self, jaeger_trace: dict) -> TraceEntry:
        trace_id = _pad_id(jaeger_trace.get('traceID', ''), _TRACE_ID_WIDTH)
        raw_spans = jaeger_trace.get('spans') or []
        processes = jaeger_trace.get('processes') or {}

        spans = []
        for raw in raw_spans:
            tag_dict = _tag_dict(raw.get('tags'))
            process_id = raw.get('processID')
            service_name = ''
            if process_id and isinstance(processes.get(process_id), dict):
                service_name = processes[process_id].get('serviceName', '') or ''

            start_dt = _from_unix_micros(raw.get('startTime'))
            duration_us = raw.get('duration') or 0
            end_dt = _from_unix_micros(
                (raw.get('startTime') or 0) + duration_us
            )

            parent_span = ''
            refs = raw.get('references') or []
            for ref in refs:
                if ref.get('refType') == 'CHILD_OF' and ref.get('spanID'):
                    parent_span = _pad_id(ref['spanID'], _SPAN_ID_WIDTH)
                    break

            spans.append(SpanEntry(
                trace_id=trace_id,
                span_id=_pad_id(raw.get('spanID', ''), _SPAN_ID_WIDTH),
                parent_span_id=parent_span,
                service_name=service_name,
                operation_name=raw.get('operationName', '') or '',
                kind=str(tag_dict.get('span.kind', 'INTERNAL')).upper(),
                start_time=start_dt,
                end_time=end_dt,
                duration_ms=max(0, int(duration_us / 1000)),
                status_code=_status_from_tags(tag_dict),
                status_message=str(tag_dict.get('error.message') or ''),
                attributes=tag_dict,
                events=[],
            ))

        # Rollup: first span with no parent is the root.
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
