"""Unified event timeline for a batch — Item #12 flagship.

Produces a single chronologically-sorted list of events spanning all
five data sources SerOps ingests:

* **log**              — error logs (level == ERROR)
* **metric_anomaly**   — CPU / memory spike windows
* **deploy**           — code changes (from batch.data.code_changes)
* **cicd**             — failed CI/CD jobs
* **span_error**       — top error spans from the trace summary

Each event has a compact common shape::

    {
        "time": "2026-09-04T12:34:56+00:00",
        "kind": "log" | "metric_anomaly" | "deploy" | "cicd" | "span_error",
        "service": "checkout",
        "severity": "ERROR" | "WARNING" | "INFO",
        "summary": "human-readable line",
        "detail": {...}   # kind-specific extras (trace_id, sha, ...)
    }

The timeline is meant for:

* Frontend rendering (chronological event list / future chart).
* The AI prompt — a compact temporal view is often more insight-dense
  than five parallel sections.
* Debugging / support — "show me everything that happened in the
  batch, in order".

Reads exclusively from ``batch.data`` — no live queries. Costs O(n)
in event count. Bounded by upstream limits (batch.data.logs is
already truncated at prompt time).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


# Q5-4: internal hard cap on how many events we even hold in memory
# per timeline build. A batch with 100k logs must not turn the
# timeline endpoint into an OOM vector; 2000 is comfortably above
# the biggest ``limit`` a client may ask for and small enough that
# the merged sort stays milliseconds.
_INTERNAL_TIMELINE_CAP = 2000


def build_unified_timeline(
    batch,
    max_events: int = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Return a chronologically-sorted event slice for ``batch``.

    ``max_events`` caps the slice length so a batch with 10k logs
    doesn't produce a 10k-row timeline. ``offset`` (Q5-4) supports
    pagination — combined with a per-page ``max_events`` a client
    can walk a large timeline without paying the full O(n) cost per
    request. Events are picked deterministically (most-recent-first
    per source, then merged + resorted ascending).

    Events without a source-provided timestamp get pinned to
    ``batch.timestamp`` (the batch window end) so the timeline chart
    can still plot them rather than silently dropping. Real-world
    example: trace summary spans historically didn't include
    start_time, and CI/CD job payloads sometimes lack finished_at.

    Use :func:`build_unified_timeline_with_total` when you also need
    the pre-slice total (for a ``total_events`` field in a paginated
    response).
    """
    slice_, _total = build_unified_timeline_with_total(
        batch, max_events=max_events, offset=offset,
    )
    return slice_


def build_unified_timeline_with_total(
    batch,
    max_events: int = 200,
    offset: int = 0,
) -> "tuple[List[Dict[str, Any]], int]":
    """
    Same as :func:`build_unified_timeline` but also returns the total
    number of events (before slicing). The total is bounded by
    ``_INTERNAL_TIMELINE_CAP`` — beyond that the timeline is best
    served by paginating instead of demanding a full-batch view.
    """
    if batch is None or not isinstance(getattr(batch, 'data', None), dict):
        return [], 0

    data = batch.data
    events: List[Dict[str, Any]] = []

    events.extend(_events_from_logs(data.get('logs') or []))
    events.extend(_events_from_metrics(data.get('metrics_summary') or {}))
    events.extend(_events_from_code_changes(data.get('code_changes') or []))
    events.extend(_events_from_cicd(data.get('cicd_logs') or []))
    events.extend(_events_from_traces(data.get('traces') or {}))

    # Backfill any missing timestamps to batch.timestamp so no event
    # is silently unplottable. batch.timestamp is the window end —
    # anchoring there is a defensible default ("this happened
    # somewhere in this batch's window; source didn't say when").
    batch_time = getattr(batch, 'timestamp', None)
    if batch_time is not None and hasattr(batch_time, 'isoformat'):
        fallback = batch_time.isoformat()
        for ev in events:
            if not ev.get('time'):
                ev['time'] = fallback
                ev.setdefault('detail', {})
                ev['detail']['time_estimated'] = True

    # Sort ascending; events without a parseable time (e.g. no batch
    # timestamp available) still go to the end via the U+FFFF sentinel.
    events.sort(key=lambda e: (e.get('time') or '￿'))

    # Hard internal cap — protects the endpoint from OOM on a
    # pathological batch.
    if len(events) > _INTERNAL_TIMELINE_CAP:
        events = events[:_INTERNAL_TIMELINE_CAP]

    total = len(events)
    # Coerce arguments defensively — the view layer already validates,
    # but this function is also called from tests and future code paths.
    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        offset = 0
    try:
        max_events = max(1, int(max_events))
    except (TypeError, ValueError):
        max_events = 200

    return events[offset:offset + max_events], total


# ---------------------------------------------------------------------------
# Per-source event builders
# ---------------------------------------------------------------------------


def _events_from_logs(logs) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    # Cap here so a batch with 10k logs contributes at most 60 timeline
    # rows — still leaves headroom for the other sources.
    for log in logs[:60]:
        if not isinstance(log, dict):
            continue
        # Batch logs come in the ES-style wrapper: {_source: {...}}.
        source = log.get('_source') if isinstance(log.get('_source'), dict) else log
        level = str(source.get('log_level') or source.get('level') or '').upper()
        # Only ERROR / WARN in the timeline — INFO/DEBUG are noise.
        if level and level not in ('ERROR', 'WARN', 'WARNING', 'CRITICAL', 'FATAL'):
            continue
        ts = source.get('@timestamp') or source.get('timestamp')
        service = _service_from_log(source)
        message = str(source.get('message', ''))[:180]
        out.append({
            'time': ts,
            'kind': 'log',
            'service': service,
            'severity': level or 'ERROR',
            'summary': message,
            'detail': {},
        })
    return out


def _events_from_metrics(metrics_summary) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for metric_type in ('memory', 'cpu'):
        anomalies = (metrics_summary.get(metric_type, {}) or {}).get('anomalies') or []
        for a in anomalies:
            out.append({
                'time': a.get('start_time'),
                'kind': 'metric_anomaly',
                'service': '',
                'severity': 'WARNING',
                'summary': f"{metric_type.upper()} spike to {a.get('peak_value', '?')}%",
                'detail': {
                    'metric_type': metric_type,
                    'peak_value': a.get('peak_value'),
                    'duration_seconds': a.get('duration_seconds'),
                },
            })
    return out


def _events_from_code_changes(code_changes) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for change in code_changes:
        if not isinstance(change, dict):
            continue
        stats = change.get('stats') or {}
        out.append({
            'time': change.get('timestamp'),
            'kind': 'deploy',
            'service': '',
            'severity': 'INFO',
            'summary': str(change.get('message', ''))[:150],
            'detail': {
                'sha': str(change.get('sha', ''))[:8],
                'author': change.get('author', ''),
                'branch': change.get('branch', ''),
                'files_changed': stats.get('files', 0),
            },
        })
    return out


def _events_from_cicd(cicd_logs) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for job in cicd_logs:
        if not isinstance(job, dict):
            continue
        status = str(job.get('status', '')).lower()
        # Only surface failures — successful builds are baseline noise.
        if status not in ('failed', 'failure', 'error'):
            continue
        out.append({
            'time': job.get('finished_at') or job.get('created_at') or job.get('started_at'),
            'kind': 'cicd',
            'service': job.get('job_name', ''),
            'severity': 'ERROR',
            'summary': f"CI/CD job '{job.get('job_name', 'unknown')}' failed on {job.get('branch', 'unknown')}",
            'detail': {
                'pipeline_id': job.get('pipeline_id'),
                'branch': job.get('branch'),
                'trace_errors': (job.get('trace_errors') or '')[:200],
            },
        })
    return out


def _events_from_traces(traces_summary) -> List[Dict[str, Any]]:
    """
    Trace summary carries only top-slow + top-error spans — that's
    enough to surface the notable spans on the timeline without
    replaying every span in the batch.

    ``start_time`` was added to the summary shape post-Batch 42 so
    span events can be positioned on the time axis. Legacy summaries
    without start_time get a None here; the caller
    (build_unified_timeline) backfills to batch.timestamp.
    """
    out: List[Dict[str, Any]] = []
    for span in (traces_summary.get('top_errors') or []):
        out.append({
            'time': span.get('start_time'),   # may be absent on legacy summaries
            'kind': 'span_error',
            'service': span.get('service_name') or '',
            'severity': 'ERROR',
            'summary': (
                f"Span error in {span.get('service_name') or '?'} :: "
                f"{span.get('operation_name') or '?'}"
            ),
            'detail': {
                'trace_id': span.get('trace_id'),
                'status_message': (span.get('status_message') or '')[:180],
                'duration_ms': span.get('duration_ms'),
            },
        })
    return out


def _service_from_log(source: Dict[str, Any]) -> str:
    """Extract a service label from an ES-style log source."""
    if not isinstance(source, dict):
        return ''
    svc_obj = source.get('service')
    if isinstance(svc_obj, dict):
        return svc_obj.get('name') or ''
    if isinstance(svc_obj, str):
        return svc_obj
    return source.get('component') or ''


# ---------------------------------------------------------------------------
# Causal pairs — engine-backed arrows for the timeline chart (Batch 42)
# ---------------------------------------------------------------------------


def build_causal_pairs(batch, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return frontend-ready causal pairs sourced from the correlation engine.

    Prior timeline chart drew arrows using a naive heuristic (same
    service + 15-min window). That drifts from what the correlation
    engine actually decides — the engine could label a pair LOW-
    confidence while the timeline drew a bold arrow, or vice versa.

    This helper reads ``batch.data['correlation_results']`` (produced
    by ``Data.correlation_engine.build_comprehensive_correlations``)
    and maps each correlation entry to a pair of INDEXES into the
    events list. Frontend renders the arrow purely from the indexes
    plus confidence — no matching / fuzzy time-window logic there.

    Returned shape::

        {
            "from_index": <int>,        # index into events[]
            "to_index":   <int>,        # index into events[]
            "confidence": "HIGH" | "MEDIUM" | "LOW",
            "type":       "file_to_error" | "deployment_to_metric_spike" | ...,
            "note":       "short human-readable justification",
        }

    Pairs whose endpoints can't be resolved to timeline events (e.g.
    a metric_spike_to_errors correlation on a batch whose logs got
    truncated below the referenced entry) are silently skipped —
    partial visibility is better than a broken arrow.
    """
    if batch is None or not isinstance(getattr(batch, 'data', None), dict):
        return []
    corr = batch.data.get('correlation_results')
    if not isinstance(corr, dict):
        return []
    corr = corr.get('correlations') or corr  # accept both {correlations: {...}} + flat

    # Index events by kind for fast lookup. Deploy events are the
    # anchor for most correlations, so we key them by short sha too.
    by_kind: Dict[str, List[int]] = {}
    deploys_by_sha: Dict[str, int] = {}
    for i, e in enumerate(events):
        by_kind.setdefault(e.get('kind'), []).append(i)
        if e.get('kind') == 'deploy':
            sha = (e.get('detail') or {}).get('sha')
            if sha:
                deploys_by_sha[str(sha)[:8]] = i

    pairs: List[Dict[str, Any]] = []

    def _first_error_after(deploy_idx: int, service: str = '') -> int | None:
        """Find the earliest span_error/log ERROR event that follows a deploy."""
        deploy_time = events[deploy_idx].get('time') or ''
        best: int | None = None
        for j in by_kind.get('span_error', []) + by_kind.get('log', []):
            ev = events[j]
            if (ev.get('time') or '') <= deploy_time:
                continue
            if ev.get('kind') == 'log' and str(ev.get('severity', '')).upper() not in (
                'ERROR', 'CRITICAL', 'FATAL'
            ):
                continue
            if service and ev.get('service') and ev.get('service') != service:
                continue
            best = j if best is None else min(best, j)
        return best

    def _first_metric_after(deploy_idx: int) -> int | None:
        deploy_time = events[deploy_idx].get('time') or ''
        for j in by_kind.get('metric_anomaly', []):
            if (events[j].get('time') or '') > deploy_time:
                return j
        return None

    # file_to_error: commit sha → error log(s).
    for entry in (corr.get('file_to_error') or []):
        sha = str(entry.get('commit_sha') or '')[:8]
        if not sha or sha not in deploys_by_sha:
            continue
        deploy_idx = deploys_by_sha[sha]
        target = _first_error_after(deploy_idx)
        if target is None:
            continue
        matching = ', '.join((entry.get('matching_files') or [])[:3])
        pairs.append({
            'from_index': deploy_idx,
            'to_index': target,
            'confidence': entry.get('confidence', 'MEDIUM'),
            'type': 'file_to_error',
            'note': f'Files changed: {matching}' if matching else 'Files match error trace',
        })

    # deployment_to_metric_spike: commit sha → metric anomaly.
    for entry in (corr.get('deployment_to_metric_spike') or []):
        sha = str(entry.get('commit_sha') or '')[:8]
        if not sha or sha not in deploys_by_sha:
            continue
        deploy_idx = deploys_by_sha[sha]
        target = _first_metric_after(deploy_idx)
        if target is None:
            continue
        peak = entry.get('anomaly_peak', '?')
        metric = str(entry.get('metric_type', '')).upper()
        pairs.append({
            'from_index': deploy_idx,
            'to_index': target,
            'confidence': entry.get('confidence', 'MEDIUM'),
            'type': 'deployment_to_metric_spike',
            'note': f'{metric} spike to {peak}',
        })

    # slow_span_after_deploy: commit sha → span_error.
    for entry in (corr.get('slow_span_after_deploy') or []):
        sha = str(entry.get('commit_sha') or '')[:8]
        if not sha or sha not in deploys_by_sha:
            continue
        deploy_idx = deploys_by_sha[sha]
        # Prefer the exact trace_id if present in a span_error event.
        trace_id = entry.get('trace_id')
        target = None
        if trace_id:
            for j in by_kind.get('span_error', []):
                if (events[j].get('detail') or {}).get('trace_id') == trace_id:
                    target = j
                    break
        if target is None:
            target = _first_error_after(deploy_idx)
        if target is None:
            continue
        top_op = entry.get('top_slow_operation', '')
        top_ms = entry.get('top_slow_duration_ms', 0)
        pairs.append({
            'from_index': deploy_idx,
            'to_index': target,
            'confidence': entry.get('confidence', 'MEDIUM'),
            'type': 'slow_span_after_deploy',
            'note': f'Slow span: {top_op} at {top_ms}ms',
        })

    # De-dup pairs that resolved to the same (from, to). Keep the highest
    # confidence one — the arrow renders best when there's a single
    # unambiguous winner per endpoint pair.
    dedup: Dict[tuple, Dict[str, Any]] = {}
    _conf_rank = {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1}
    for p in pairs:
        k = (p['from_index'], p['to_index'])
        prev = dedup.get(k)
        if prev is None or _conf_rank.get(p['confidence'], 0) > _conf_rank.get(prev['confidence'], 0):
            dedup[k] = p
    return list(dedup.values())
