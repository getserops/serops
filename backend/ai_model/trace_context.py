"""Build trace-summary context for RCA prompt enrichment.

Given a batch's time window and its project services, this helper
assembles a compact summary of the most interesting distributed-trace
spans for the AI to reason over. Two sources, in order of preference:

1. **Native OTLP store** (``traces.models.Trace`` / ``Span``) — fast,
   already normalised, always current for orgs that pointed their
   OTEL Collector at SerOps. Queried first.
2. **External trace provider** (Jaeger, Zipkin, Datadog APM) —
   configured per-org via ``ObservabilityIntegration``. Queried only
   if the native store returned nothing for the relevant services in
   the window. Bounded to a small fetch; adapters have their own
   timeouts and never block RCA on failure.

The output is a small dict shaped for the prompt builder:

    {
        'span_count': int,
        'error_span_count': int,
        'top_slow': [{'service':.., 'operation':.., 'duration_ms':.., 'trace_id':..}, ...],
        'top_errors': [{'service':.., 'operation':.., 'status_message':.., 'trace_id':..}, ...],
        'services_touched': ['api', 'checkout', ...],
    }

Failures are always swallowed and logged — trace context is an
enrichment, never a hard dependency for RCA.
"""

import logging
from collections import defaultdict
from datetime import timedelta
from types import SimpleNamespace

logger = logging.getLogger(__name__)

# Compact caps — RCA prompts are token-budgeted.
_TOP_SLOW = 5
_TOP_ERRORS = 5
_MAX_TRACES_PER_SERVICE = 20    # bounded external-provider fetch
_PER_SERVICE = 8                # services listed with their own timings
_MAX_TIMING_SPANS = 20000       # spans read to compute them


def build_trace_context(batch):
    """
    Return a dict of trace summary for the batch's window, or ``None``
    if no data is available.

    ``batch`` must have ``.timestamp`` (window end) and ``.project``.
    Window start is derived from the project's batch interval, falling
    back to 15 minutes.

    **Read order:**

    1. ``batch.data['traces']`` — snapshot written at batch creation
       (see ``snapshot_trace_context``). Same shape returned here, so
       downstream is source-agnostic.
    2. Live query against native OTLP store (``traces.Trace/Span``).
    3. Live query against a configured external adapter (Jaeger /
       Zipkin / Datadog APM).

    The snapshot path is preferred so that reanalysis of an old batch
    reasons over the traces that existed *when the batch was created* —
    not whatever is left after retention purges or provider outages.
    """
    if batch is None or not getattr(batch, 'timestamp', None):
        return None

    # 1. Snapshot fast-path — reproducible, immune to retention purges.
    #    Snapshot is already redacted at write time (Q1.5).
    snapshot = _read_snapshot(batch)
    if snapshot is not None:
        return snapshot

    # 2 + 3. Live compute (native OTLP first, then adapter fallback).
    #    Redact defensively — the live path fires only for pre-#10.5
    #    batches without a snapshot, but the AI-egress risk is identical.
    try:
        summary = _compute_live(batch)
        from Utils.redaction_helpers import redact_span_summary
        return redact_span_summary(summary)
    except Exception as exc:
        logger.warning('build_trace_context failed: %s', exc)
        return None


# ---------------------------------------------------------------------------
# Snapshot persistence (write at batch creation, read at analysis time)
# ---------------------------------------------------------------------------


def snapshot_trace_context(batch):
    """
    Compute the trace summary for a batch and persist it to
    ``batch.data['traces']`` for reproducibility. Idempotent — safe to
    call multiple times on the same batch.

    Called by ``Data.tasks.create_log_batch_with_project_name`` right
    after the batch row is created and its ``project`` FK is set.

    **PII redaction (Q1.5):** trace summary fields (operation_name,
    status_message, service_name, services_touched) are redacted
    BEFORE persistence — the raw text never lands on ``batch.data``
    or in an AI prompt.

    Failures are always swallowed and logged — batch creation must
    never fail because of a trace-snapshot problem.
    """
    if batch is None:
        return None
    try:
        summary = _compute_live(batch)
        # Redact before persistence. redact_span_summary is a no-op on
        # None so we can safely chain.
        from Utils.redaction_helpers import redact_span_summary
        summary = redact_span_summary(summary)
        if not isinstance(batch.data, dict):
            batch.data = {}
        batch.data['traces'] = summary
        batch.save(update_fields=['data'])
        return summary
    except Exception as exc:
        logger.warning('snapshot_trace_context failed: %s', exc)
        return None


def count_spans_in_window(project, start, end):
    """Cheap span count for a project's window — no batch row required.

    Batch creation gates on "is there anything to analyse?", and that gate
    predates trace ingestion: it counted logs and metrics only. A pure
    latency regression — slow spans, HTTP 200 throughout, no error logs and
    no metric movement — therefore produced NO BATCH AT ALL, so the incident
    never entered the pipeline. That is precisely the failure mode
    distributed tracing exists to catch. Measured on the chaos suite: the
    latency scenario returned "No new logs or metrics found" with thousands
    of spans already stored.

    ``snapshot_trace_context`` cannot serve this — it needs a persisted
    batch, which is what we are deciding whether to create. This is two
    COUNT queries against the native OTLP store; the external adapters are
    deliberately not consulted, because a gate must not make a network call
    on every scheduled tick.

    Returns 0 on any failure: traces may add a reason to create a batch,
    never a reason to fail one.
    """
    if project is None or start is None or end is None:
        return 0
    try:
        from traces.models import Span, Trace
    except ImportError:
        return 0
    try:
        organisation = getattr(project, 'organisation', None)
        if organisation is None:
            return 0
        trace_qs = Trace.objects.filter(
            organisation=organisation,
            start_time__gte=start,
            start_time__lte=end,
        )
        service_names = _service_names(project)
        if service_names:
            from django.db.models import Exists, OuterRef, Q
            trace_qs = trace_qs.filter(Q(root_service_name__in=service_names) | Exists(
                Span.objects.filter(trace=OuterRef('pk'), service_name__in=service_names)))
        # Primary keys, not OTEL trace ids: a trace id is unique only within
        # an organisation (security review 2026-11, finding 1).
        trace_pks = list(trace_qs.values_list('pk', flat=True)[:500])
        if not trace_pks:
            return 0
        return Span.objects.filter(trace__in=trace_pks).count()
    except Exception as exc:                                    # noqa: BLE001
        logger.warning('count_spans_in_window failed: %s', exc)
        return 0


def _read_snapshot(batch):
    """Return the persisted snapshot on batch.data, or None if absent.

    Snapshot MUST be a dict with the shape produced by ``_from_native``
    (span_count, error_span_count, top_slow, top_errors,
    services_touched). If we find anything else on ``batch.data['traces']``
    (e.g. a raw list of trace summaries from an old ingest path, or a
    bare integer), we log and return ``None`` so the caller falls
    through to a live query — prevents the prompt formatter silently
    dropping traces because it couldn't ``.get('top_slow')`` on a list.
    """
    data = getattr(batch, 'data', None)
    if not isinstance(data, dict):
        return None
    if 'traces' not in data:
        # Never snapshotted (pre-#10.5 batch, or snapshot skipped) —
        # let the caller fall through to a live query.
        return None
    snapshot = data['traces']
    if snapshot is None:
        # Snapshot was taken but yielded no data. Honour that:
        # the batch's window genuinely had no traces.
        return None
    if not isinstance(snapshot, dict):
        # Wrong shape from an old ingest / test generator. Warn once
        # per batch and fall through to a live query so the AI still
        # sees traces if any exist in the window.
        logger.warning(
            'batch %s has non-dict trace snapshot (type=%s) — falling through '
            'to live query. Fix the ingest that produced this shape.',
            getattr(batch, 'batch_id', '?'), type(snapshot).__name__,
        )
        return None
    if 'top_slow' not in snapshot and 'top_errors' not in snapshot and 'span_count' not in snapshot:
        # Dict but wrong keys — same treatment as above.
        logger.warning(
            'batch %s has trace snapshot dict without expected keys — '
            'falling through to live query. Keys: %s',
            getattr(batch, 'batch_id', '?'), sorted(snapshot.keys())[:10],
        )
        return None
    return snapshot


def native_trace_summary(project, data, window_end):
    """Redacted trace summary from the native OTLP store, before a batch exists.

    Sentinel decides whether a window is worth an analysis BEFORE the batch
    row is written (the pre-creation gate), so it never saw the trace
    snapshot: a dependency going from 20 ms to 900 ms with no errors read as
    a quiet window until the forced review hours later (external review of
    v1.2.13). The batch task calls this first, hands the result to Sentinel
    inside the batch data, and keeps it as the batch's snapshot — one query
    either way.

    Native store only: a gate runs on every scheduled tick and must not make
    a network call to an external trace provider each time. When the native
    store has nothing, this returns ``None`` and the post-creation snapshot
    still tries the external provider. Never raises.
    """
    if project is None or window_end is None:
        return None
    try:
        window = _window(SimpleNamespace(timestamp=window_end, project=project, data=data))
        if window is None:
            return None
        summary = _from_native(*window)
        if not summary or not summary.get('span_count'):
            return None
        from Utils.redaction_helpers import redact_span_summary
        return redact_span_summary(summary)
    except Exception as exc:                                    # noqa: BLE001
        logger.warning('native_trace_summary failed: %s', exc)
        return None


def _compute_live(batch):
    """The pre-#10.5 code path — query the DB / adapter directly.

    Extracted so ``build_trace_context`` and ``snapshot_trace_context``
    share exactly one query implementation.
    """
    window = _window(batch)
    if window is None:
        return None
    summary = _from_native(*window)
    if summary and summary.get('span_count', 0) > 0:
        return summary
    return _from_external(*window)


def _window(batch):
    """(organisation, service_names, start, end) for a batch, or None."""
    if not getattr(batch, 'timestamp', None):
        return None

    window_end = batch.timestamp
    organisation = _resolve_org(batch)
    if organisation is None:
        return None

    interval_min = 15
    try:
        from Data.batch_config import get_batch_interval_for_org
        interval_min = get_batch_interval_for_org(organisation) or 15
    except Exception:
        pass
    window_start = window_end - timedelta(minutes=interval_min)

    # The batch's own window when it has one (an investigation over the last
    # 15 minutes, an alert's window): traces used to cover only the org's
    # batch interval before the batch, so an investigation showed fewer
    # traces than the window it named (found by the journey suite).
    time_range = ((getattr(batch, 'data', None) or {}).get('statistics') or {}).get('time_range') or {}
    try:
        from datetime import datetime, timezone
        if time_range.get('start') and time_range.get('end'):
            window_start = datetime.fromisoformat(time_range['start'].replace('Z', '+00:00'))
            window_end = datetime.fromisoformat(time_range['end'].replace('Z', '+00:00'))
            if window_start.tzinfo is None:
                window_start = window_start.replace(tzinfo=timezone.utc)
            if window_end.tzinfo is None:
                window_end = window_end.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass

    service_names = _service_names(getattr(batch, 'project', None))
    return organisation, service_names, window_start, window_end


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_org(batch):
    project = getattr(batch, 'project', None)
    if project and getattr(project, 'organisation', None):
        return project.organisation
    # Batch.data may carry organisation_id as a fallback.
    org_id = None
    if hasattr(batch, 'data') and isinstance(batch.data, dict):
        org_id = batch.data.get('organisation_id')
    if org_id:
        from Organisations.models import Organisations
        return Organisations.objects.filter(id=org_id).first()
    return None


def _service_names(project):
    """Return the set of service names attached to the project."""
    if project is None:
        return set()
    try:
        return {s.name for s in project.services.all() if getattr(s, 'name', '')}
    except Exception:
        return set()


def _from_native(organisation, service_names, start, end):
    """Pull top-slow + top-error spans from our own Trace/Span store."""
    try:
        from traces.models import Span
    except ImportError:
        return None

    trace_pks = _project_trace_pks(organisation, service_names, start, end)
    if not trace_pks:
        return None

    span_qs = Span.objects.filter(trace__in=trace_pks)
    total_spans = span_qs.count()
    if total_spans == 0:
        return None

    error_spans = span_qs.filter(status_code='ERROR')

    # start_time is included so the unified timeline can plot span
    # events on the time axis. Without it, _events_from_traces produces
    # time=None events and the timeline chart silently drops them.
    top_slow = list(
        span_qs.order_by('-duration_ms')[:_TOP_SLOW]
        .values('service_name', 'operation_name',
                'duration_ms', 'status_code', 'start_time', 'trace__trace_id')
    )
    top_errors = list(
        error_spans.order_by('-start_time')[:_TOP_ERRORS]
        .values('service_name', 'operation_name',
                'status_message', 'duration_ms', 'start_time', 'trace__trace_id')
    )
    # Django's `.values()` returns datetime objects for DateTimeField;
    # ensure they serialise as ISO strings in the JSON payload the
    # frontend + AI both consume.
    for row in top_slow + top_errors:
        # The OTEL trace id lives on the trace row; Span.trace_id is the FK.
        row['trace_id'] = row.pop('trace__trace_id')
        st = row.get('start_time')
        if st is not None and hasattr(st, 'isoformat'):
            row['start_time'] = st.isoformat()

    services_touched = sorted(
        {s for s in span_qs.values_list('service_name', flat=True).distinct() if s}
    )

    # The window before, same length, as the baseline each service's timings
    # are compared to: "p95 3004ms" means little without "it was 5ms".
    baseline_pks = _project_trace_pks(organisation, service_names, start - (end - start), start)
    per_service = _service_timings(_span_rows(Span.objects.filter(trace__in=trace_pks)))
    baseline = _service_timings(_span_rows(Span.objects.filter(trace__in=baseline_pks))) if baseline_pks else {}
    for name, row in per_service.items():
        before = baseline.get(name)
        if before:
            row['baseline'] = {k: before[k] for k in ('spans', 'p95_ms', 'self_p95_ms', 'errors')}

    # Traffic, counted in full: the timings above come from at most 500
    # traces per window, so in a surge both windows hit the cap and look
    # alike. Without the change in volume, "every service slowed down at
    # once" read as a code problem (Online Boutique on AKS, scenario R9: a
    # 5x load-generator surge blamed on recommendationservice's client code).
    traffic = _traffic(organisation, list(per_service), start, end)
    for name, row in per_service.items():
        if name in traffic['per_service']:
            row['traffic'] = traffic['per_service'][name]

    return {
        'source': 'otlp',
        'span_count': total_spans,
        'error_span_count': error_spans.count(),
        'trace_count': len(trace_pks),
        'top_slow': top_slow,
        'top_errors': top_errors,
        'services_touched': services_touched,
        'per_service': _top_services(per_service),
        'traffic': {'spans': traffic['spans'], 'before': traffic['before']},
    }


def _traffic(organisation, service_names, start, end):
    """Spans per service in the window and in the window before, uncapped.

    ``{'spans': N, 'before': M, 'per_service': {name: {'spans': n, 'before': m}}}``.
    One grouped count per window, on the (service_name, start_time) index.
    """
    from django.db.models import Count
    from traces.models import Span
    result = {'spans': 0, 'before': 0, 'per_service': {}}
    if not service_names:
        return result
    length = end - start
    for key, (lo, hi) in (('spans', (start, end)), ('before', (start - length, start))):
        rows = (Span.objects.filter(trace__organisation=organisation, service_name__in=service_names,
                                    start_time__gte=lo, start_time__lt=hi)
                .values('service_name').annotate(n=Count('id')))
        for row in rows:
            entry = result['per_service'].setdefault(row['service_name'], {'spans': 0, 'before': 0})
            entry[key] = row['n']
            result[key] += row['n']
    return result


def _volume_change(now, before):
    """' (x5.2)' / ' (x0.3)' when the volume moved markedly, else ''."""
    if not before:
        return ' (none before)' if now else ''
    ratio = now / before
    if 0.67 <= ratio <= 1.5:
        return ''
    return f' (x{ratio:.1f})'


def _project_trace_pks(organisation, service_names, start, end):
    """Primary keys of the organisation's traces in the window.

    Primary keys rather than OTEL trace ids: a trace id is unique only within
    an organisation, so filtering spans by trace id could pull in another
    tenant's spans (security review 2026-11, finding 1).
    """
    from traces.models import Span, Trace
    trace_qs = Trace.objects.filter(
        organisation=organisation,
        start_time__gte=start,
        start_time__lte=end,
    )
    if service_names:
        # Traces the project's services take part in, not only those they
        # start: a backend called by another project's frontend never roots
        # a trace, and its analyses had no trace context (journey suite).
        from django.db.models import Exists, OuterRef, Q
        trace_qs = trace_qs.filter(Q(root_service_name__in=service_names) | Exists(
            Span.objects.filter(trace=OuterRef('pk'), service_name__in=service_names)))
    return list(trace_qs.values_list('pk', flat=True)[:500])


def _span_rows(span_qs):
    return span_qs.values_list(
        'trace_id', 'span_id', 'parent_span_id', 'service_name',
        'operation_name', 'duration_ms', 'status_code')[:_MAX_TIMING_SPANS]


def _percentile(values, pct):
    """Nearest-rank percentile of a non-empty list."""
    ordered = sorted(values)
    return ordered[max(0, -(-len(ordered) * pct // 100) - 1)]


def _service_timings(rows):
    """Timings per service: span count, p50/p95 duration, errors, and SELF time.

    ``rows`` are (trace_id, span_id, parent_span_id, service_name,
    operation_name, duration_ms, status_code). Self time is a span's duration
    minus its children's: the time spent in the service itself rather than
    waiting on the services it called. The top-5 slowest spans could not
    tell those apart — a frontend waiting 3s on a slow catalogue filled the
    whole list, and the analysis blamed the frontend (production scenario B4
    on Online Boutique). Self time puts the 3s on the catalogue.

    Children running in parallel can add up to more than their parent; self
    time is floored at 0 rather than going negative.
    """
    rows = list(rows)
    child_ms = defaultdict(int)
    for trace_id, _span, parent, _svc, _op, duration, _status in rows:
        if parent:
            child_ms[(trace_id, parent)] += duration or 0
    acc = defaultdict(lambda: {'durations': [], 'self': [], 'errors': 0, 'slowest': ('', -1)})
    for trace_id, span_id, _parent, service, operation, duration, status in rows:
        if not service:
            continue
        duration = duration or 0
        own = max(0, duration - child_ms.get((trace_id, span_id), 0)) if span_id else duration
        a = acc[service]
        a['durations'].append(duration)
        a['self'].append(own)
        if status == 'ERROR':
            a['errors'] += 1
        if own > a['slowest'][1]:
            a['slowest'] = (operation or '', own)
    return {
        service: {
            'spans': len(a['durations']),
            'p50_ms': _percentile(a['durations'], 50),
            'p95_ms': _percentile(a['durations'], 95),
            'self_p95_ms': _percentile(a['self'], 95),
            'errors': a['errors'],
            'slowest_operation': a['slowest'][0],
            'slowest_self_ms': a['slowest'][1],
        }
        for service, a in acc.items()
    }


def _top_services(per_service):
    """The services worth the prompt's tokens: highest self time first, then errors."""
    ranked = sorted(per_service.items(),
                    key=lambda kv: (kv[1]['self_p95_ms'], kv[1]['errors']), reverse=True)
    top = ranked[:_PER_SERVICE]
    # A failing service is listed even when it is fast.
    top += [kv for kv in ranked[_PER_SERVICE:] if kv[1]['errors']][:3]
    return [{'service_name': name, **row} for name, row in top]


def _from_external(organisation, service_names, start, end):
    """Pull traces from a configured Jaeger/Zipkin/DD APM adapter."""
    from integrations.registry import IntegrationRegistry
    provider = IntegrationRegistry.get_trace_provider_for_org(organisation)
    if provider is None or not service_names:
        return None

    all_spans = []
    services_seen = set()
    for svc_name in sorted(service_names):
        try:
            traces = provider.fetch_traces(
                service_name=svc_name,
                since=start,
                until=end,
                limit=_MAX_TRACES_PER_SERVICE,
            ) or []
        except Exception as exc:
            logger.warning(
                'Trace provider fetch failed for service=%s: %s', svc_name, exc,
            )
            continue

        for trace in traces:
            for span in (trace.spans or []):
                if span.service_name:
                    services_seen.add(span.service_name)
                # start_time serialised as ISO so it works both in the
                # AI-prompt path and the unified-timeline path. Missing
                # start_time falls back to None — timeline handles that
                # gracefully by anchoring to batch.timestamp.
                start_time = getattr(span, 'start_time', None)
                if start_time is not None and hasattr(start_time, 'isoformat'):
                    start_time = start_time.isoformat()
                all_spans.append({
                    'trace_id': trace.trace_id,
                    'span_id': getattr(span, 'span_id', '') or '',
                    'parent_span_id': getattr(span, 'parent_span_id', '') or '',
                    'service_name': span.service_name,
                    'operation_name': span.operation_name,
                    'duration_ms': span.duration_ms,
                    'status_code': span.status_code,
                    'status_message': span.status_message,
                    'start_time': start_time,
                })

    if not all_spans:
        return None

    top_slow = sorted(all_spans, key=lambda s: s.get('duration_ms', 0), reverse=True)[:_TOP_SLOW]
    error_spans = [s for s in all_spans if s.get('status_code') == 'ERROR']
    top_errors = error_spans[:_TOP_ERRORS]
    per_service = _service_timings(
        (s['trace_id'], s['span_id'], s['parent_span_id'], s['service_name'],
         s['operation_name'], s['duration_ms'], s['status_code']) for s in all_spans)
    # The prompt and the timeline read only these keys of each span.
    for s in all_spans:
        s.pop('span_id', None)
        s.pop('parent_span_id', None)

    return {
        'source': 'external',
        'span_count': len(all_spans),
        'error_span_count': len(error_spans),
        'trace_count': len({s['trace_id'] for s in all_spans}),
        'top_slow': top_slow,
        'top_errors': top_errors,
        'services_touched': sorted(services_seen),
        'per_service': _top_services(per_service),
    }


# ---------------------------------------------------------------------------
# Prompt formatter
# ---------------------------------------------------------------------------


def format_trace_context_for_prompt(traces_summary):
    """Render a compact prompt section from build_trace_context output.

    Returns an empty string if the summary is None/empty. Otherwise
    returns a `\\nDistributed Traces:\\n...` block suitable for
    concatenation into the RCA user prompt.
    """
    if not traces_summary or not isinstance(traces_summary, dict):
        return ''
    if traces_summary.get('span_count', 0) == 0:
        return ''

    parts = ['\nDistributed Traces:', '-------------']
    source = traces_summary.get('source', 'otlp')
    parts.append(
        f"Source: {source}  Traces: {traces_summary.get('trace_count', 0)}  "
        f"Spans: {traces_summary.get('span_count', 0)}  "
        f"Errors: {traces_summary.get('error_span_count', 0)}"
    )

    services = traces_summary.get('services_touched') or []
    if services:
        parts.append(f"Services in window: {', '.join(services[:10])}")

    top_slow = traces_summary.get('top_slow') or []
    if top_slow:
        parts.append(f"\nTop {len(top_slow)} slowest spans:")
        for span in top_slow:
            parts.append(
                f"  [{span.get('duration_ms', 0)}ms] "
                f"{span.get('service_name', '?')} :: {span.get('operation_name', '?')} "
                f"(trace {str(span.get('trace_id', ''))[:16]}…)"
            )

    traffic = traces_summary.get('traffic') or {}
    if traffic.get('spans') or traffic.get('before'):
        parts.append(f"Traffic: {traffic.get('spans', 0)} spans in this window, "
                     f"{traffic.get('before', 0)} in the window before"
                     f"{_volume_change(traffic.get('spans', 0), traffic.get('before', 0))}")

    per_service = traces_summary.get('per_service') or []
    if per_service:
        parts.append("\nPer-service timings (self = time inside the service itself, "
                     "not waiting on the services it called):")
        for row in per_service:
            volume = row.get('traffic')
            spans = (f"{volume['spans']} spans (window before: {volume['before']})"
                     f"{_volume_change(volume['spans'], volume['before'])}"
                     if volume else f"{row.get('spans', 0)} spans")
            line = (f"  {row.get('service_name', '?')}: {spans}, "
                    f"p50 {row.get('p50_ms', 0)}ms, p95 {row.get('p95_ms', 0)}ms, "
                    f"self p95 {row.get('self_p95_ms', 0)}ms, {row.get('errors', 0)} errors")
            before = row.get('baseline')
            if before:
                line += (f" (window before: p95 {before.get('p95_ms', 0)}ms, "
                         f"self p95 {before.get('self_p95_ms', 0)}ms)")
            if row.get('slowest_operation'):
                line += (f"; slowest own time: {row['slowest_operation']} "
                         f"{row.get('slowest_self_ms', 0)}ms")
            parts.append(line)

    top_errors = traces_summary.get('top_errors') or []
    if top_errors:
        parts.append(f"\nTop {len(top_errors)} error spans:")
        for span in top_errors:
            msg = (span.get('status_message') or '')[:120]
            suffix = f" — {msg}" if msg else ''
            parts.append(
                f"  {span.get('service_name', '?')} :: {span.get('operation_name', '?')}"
                f"{suffix} (trace {str(span.get('trace_id', ''))[:16]}…)"
            )

    return '\n'.join(parts) + '\n'
