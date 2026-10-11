"""Zipkin Trace Adapter for TraceProvider ABC.

Uses the Zipkin HTTP query API (v2):

  GET /api/v2/services                                    — health / service list
  GET /api/v2/traces?serviceName=X&endTs=<ms>&lookback=<ms>&limit=N — recent traces
  GET /api/v2/trace/<trace_id>                            — single trace

Zipkin v2 span shape:

    {"traceId": "abc", "id": "span_id", "parentId": "..",
     "name": "op", "kind": "SERVER",
     "timestamp": <micros>, "duration": <micros>,
     "localEndpoint": {"serviceName": ".."},
     "tags": {"error": "..."},
     "annotations": [{"timestamp": .., "value": ".."}]}

Zipkin returns a list-of-lists: outer = one entry per trace, inner =
spans in that trace.
"""

import logging
from datetime import datetime
from typing import Optional

import requests
from requests.exceptions import RequestException

from integrations.base import TraceProvider, TraceProviderCapabilities
from traces.schemas import SpanEntry, SpanEvent, TraceEntry

logger = logging.getLogger(__name__)

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


def _status_from_tags(tags: dict) -> str:
    if not isinstance(tags, dict):
        return 'UNSET'
    if tags.get('error') is not None:
        return 'ERROR'
    otel_status = tags.get('otel.status_code')
    if isinstance(otel_status, str) and otel_status.upper() in ('OK', 'ERROR'):
        return otel_status.upper()
    return 'UNSET'


class ZipkinTraceAdapter(TraceProvider):
    """Zipkin v2 API adapter — pull-only."""

    capabilities = TraceProviderCapabilities(
        spans=True,
        max_query_window_hours=168,   # Zipkin ES default retention: 7d
        fetch_by_id=True,
    )

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.base_url = self._config.get('host', 'http://zipkin:9411').rstrip('/')
        self._session = requests.Session()
        username = self._config.get('username')
        password = self._config.get('password')
        if username and password:
            self._session.auth = (username, password)
        bearer = self._config.get('bearer_token')
        if bearer:
            self._session.headers['Authorization'] = f'Bearer {bearer}'

    def fetch_traces(self, service_name, since, until, limit=50):
        end_ms = int(until.timestamp() * 1000)
        lookback_ms = max(0, int((until - since).total_seconds() * 1000))
        params = {
            'serviceName': service_name,
            'endTs': end_ms,
            'lookback': lookback_ms,
            'limit': min(int(limit or 50), 1000),
        }
        try:
            resp = self._session.get(
                f'{self.base_url}/api/v2/traces',
                params=params,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
        except RequestException as exc:
            logger.warning('Zipkin fetch_traces failed: %s', exc)
            return []

        payload = resp.json() or []
        return [self._parse_trace(spans) for spans in payload if spans]

    def fetch_trace(self, trace_id):
        if not trace_id:
            return None
        try:
            resp = self._session.get(
                f'{self.base_url}/api/v2/trace/{trace_id}',
                timeout=self.timeout_seconds,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        except RequestException as exc:
            logger.warning('Zipkin fetch_trace(%s) failed: %s', trace_id, exc)
            return None

        spans = resp.json() or []
        if not spans:
            return None
        return self._parse_trace(spans)

    def health_check(self):
        try:
            resp = self._session.get(
                f'{self.base_url}/api/v2/services',
                timeout=min(self.timeout_seconds, 5),
            )
            return resp.status_code == 200
        except RequestException:
            return False

    # ------------------------------------------------------------------

    def _parse_trace(self, zipkin_spans: list) -> TraceEntry:
        trace_id = ''
        spans = []
        for raw in zipkin_spans:
            if not isinstance(raw, dict):
                continue
            if not trace_id:
                trace_id = _pad_id(raw.get('traceId', ''), _TRACE_ID_WIDTH)

            tags = raw.get('tags') or {}
            local_ep = raw.get('localEndpoint') or {}
            start_dt = _from_unix_micros(raw.get('timestamp'))
            duration_us = raw.get('duration') or 0
            end_dt = _from_unix_micros(
                (raw.get('timestamp') or 0) + duration_us
            )

            events = []
            for anno in raw.get('annotations') or []:
                if not isinstance(anno, dict):
                    continue
                anno_ts = _from_unix_micros(anno.get('timestamp'))
                if anno_ts is not None:
                    events.append(SpanEvent(
                        time=anno_ts,
                        name=str(anno.get('value', '')),
                        attributes={},
                    ))

            spans.append(SpanEntry(
                trace_id=trace_id,
                span_id=_pad_id(raw.get('id', ''), _SPAN_ID_WIDTH),
                parent_span_id=_pad_id(raw.get('parentId', ''), _SPAN_ID_WIDTH),
                service_name=str(local_ep.get('serviceName') or ''),
                operation_name=str(raw.get('name') or ''),
                kind=str(raw.get('kind') or 'INTERNAL').upper(),
                start_time=start_dt,
                end_time=end_dt,
                duration_ms=max(0, int(duration_us / 1000)),
                status_code=_status_from_tags(tags),
                status_message=str(tags.get('error') or ''),
                attributes=tags if isinstance(tags, dict) else {},
                events=events,
            ))

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
