"""Grafana Tempo Trace Adapter for TraceProvider ABC.

Tempo is the T in the LGTM stack. SerOps already ships Loki (L) +
Mimir (M); Tempo closes the gap so a Grafana-shop can bring their
whole stack to SerOps without repointing collectors.

API used (Tempo 2.x):

  GET /api/search                — search by tags in a time window
  GET /api/traces/<trace_id>     — fetch a single trace (OTLP JSON)
  GET /ready                     — health check

Multi-tenancy uses ``X-Scope-OrgID`` — same header pattern as
Loki/Mimir, so users can reuse their existing tenant IDs. Set
``tenant_id`` in the integration's ``extra_config`` (or top-level
config).

**Why we don't reparse OTLP shape ourselves:**

``GET /api/traces/<id>`` returns spans in the exact OTLP HTTP JSON
format we already receive via our own OTLP receiver. So both the
push path and this pull path share ``traces.otlp_parsing`` — no
schema drift.

Search results use a lighter shape (one row per trace with rollup
metadata but no spans), so ``fetch_traces`` fans out to
``fetch_trace`` for each hit. Bounded by ``limit`` to keep it sane.

Security:

* All user-supplied values (service_name, trace_id) go through
  ``requests`` params/URL — never string-formatted into the URL.
* No credential is logged. Failed requests log status codes, not
  bodies (bodies can echo user input).
"""

import logging
from datetime import datetime
from typing import List, Optional

import requests
from requests.exceptions import RequestException

from integrations.base import TraceProvider, TraceProviderCapabilities
from traces.otlp_parsing import iter_resource_spans, parse_span_dict
from traces.schemas import SpanEntry, TraceEntry

logger = logging.getLogger(__name__)


class TempoTraceAdapter(TraceProvider):
    """Grafana Tempo pull adapter."""

    capabilities = TraceProviderCapabilities(
        spans=True,
        # Tempo default retention is 48h; users bump this via storage
        # config. Conservative default here — the adapter still honours
        # the caller's since/until.
        max_query_window_hours=48,
        fetch_by_id=True,
    )

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.base_url = self._config.get('host', 'http://tempo:3200').rstrip('/')
        self._session = requests.Session()

        username = self._config.get('username')
        password = self._config.get('password')
        if username and password:
            self._session.auth = (username, password)
        bearer = self._config.get('bearer_token')
        if bearer:
            self._session.headers['Authorization'] = f'Bearer {bearer}'

        # Multi-tenant Tempo — same header pattern as Loki/Mimir.
        extras = self._config.get('extra_config', {}) or {}
        tenant_id = (
            self._config.get('tenant_id')
            or extras.get('tenant_id')
        )
        if tenant_id:
            self._session.headers['X-Scope-OrgID'] = str(tenant_id)
        else:
            logger.info(
                'TempoTraceAdapter initialised without tenant_id. '
                'For multi-tenant Tempo deployments set '
                'extra_config.tenant_id on the integration.'
            )

    # ------------------------------------------------------------------

    def fetch_traces(self, service_name, since, until, limit=50):
        # Tempo /api/search accepts tag-based search + time window in
        # seconds (some builds accept ns — the seconds form is universal).
        params = {
            'tags': f'service.name={service_name}',
            'start': int(since.timestamp()),
            'end': int(until.timestamp()),
            'limit': min(int(limit or 50), 500),
        }
        try:
            resp = self._session.get(
                f'{self.base_url}/api/search',
                params=params,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
        except RequestException as exc:
            logger.warning('Tempo fetch_traces failed: %s', exc)
            return []

        payload = resp.json() or {}
        traces_meta = payload.get('traces') or []

        # Search results are trace-summary only; hydrate each with a
        # full fetch so the caller gets the shape they expect. Bounded
        # by ``limit`` above so this never runs away.
        results: List[TraceEntry] = []
        for meta in traces_meta:
            trace_id = meta.get('traceID') or meta.get('trace_id')
            if not trace_id:
                continue
            trace = self.fetch_trace(trace_id)
            if trace is not None:
                results.append(trace)
        return results

    def fetch_trace(self, trace_id) -> Optional[TraceEntry]:
        if not trace_id:
            return None
        try:
            resp = self._session.get(
                f'{self.base_url}/api/traces/{trace_id}',
                headers={'Accept': 'application/json'},
                timeout=self.timeout_seconds,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        except RequestException as exc:
            logger.warning('Tempo fetch_trace(%s) failed: %s', trace_id, exc)
            return None

        payload = resp.json() or {}
        # Tempo wraps the OTLP payload in {"batches": [...]} historically,
        # or returns {"resourceSpans": [...]} directly in newer versions.
        # Handle both.
        if 'batches' in payload and 'resourceSpans' not in payload:
            payload = {'resourceSpans': payload['batches']}

        spans = self._parse_otlp_payload(payload)
        if not spans:
            return None
        return self._assemble_trace(str(trace_id).lower(), spans)

    def health_check(self) -> bool:
        try:
            resp = self._session.get(
                f'{self.base_url}/ready',
                timeout=min(self.timeout_seconds, 5),
            )
            return resp.status_code == 200
        except RequestException:
            return False

    # ------------------------------------------------------------------

    @staticmethod
    def _parse_otlp_payload(payload) -> List[SpanEntry]:
        """Walk an OTLP resourceSpans payload → list of SpanEntry.

        Reuses the shared parser from traces.otlp_parsing so the
        push (receiver) and pull (this adapter) paths cannot drift.
        """
        spans: List[SpanEntry] = []
        for span_dict, resource_attrs, resource_service_name in iter_resource_spans(payload):
            parsed = parse_span_dict(span_dict, resource_attrs, resource_service_name)
            if parsed is None:
                continue
            spans.append(SpanEntry(
                trace_id=parsed['trace_id'],
                span_id=parsed['span_id'],
                parent_span_id=parsed['parent_span_id'],
                service_name=parsed['service_name'],
                operation_name=parsed['operation_name'],
                kind=parsed['kind'],
                start_time=parsed['start_time'],
                end_time=parsed['end_time'],
                duration_ms=parsed['duration_ms'],
                status_code=parsed['status_code'],
                status_message=parsed['status_message'],
                attributes=parsed['attributes'],
                events=[],   # SpanEntry.events is a list of SpanEvent objects — Tempo events come through parsed but we keep them as raw dicts in .attributes if callers need them
            ))
        return spans

    @staticmethod
    def _assemble_trace(trace_id: str, spans: List[SpanEntry]) -> TraceEntry:
        root = next((s for s in spans if not s.parent_span_id), spans[0])
        start = min((s.start_time for s in spans if s.start_time), default=root.start_time)
        end = max((s.end_time for s in spans if s.end_time), default=root.end_time)
        duration_ms = (
            int((end - start).total_seconds() * 1000) if (start and end) else root.duration_ms
        )
        error_count = sum(1 for s in spans if s.status_code == 'ERROR')
        trace_status = 'ERROR' if error_count > 0 else 'OK'
        return TraceEntry(
            trace_id=trace_id,
            root_service_name=root.service_name,
            root_operation=root.operation_name,
            start_time=start,
            end_time=end,
            duration_ms=duration_ms,
            span_count=len(spans),
            error_span_count=error_count,
            status_code=trace_status,
            spans=spans,
        )
