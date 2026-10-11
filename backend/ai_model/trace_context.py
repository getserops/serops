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
from datetime import timedelta

logger = logging.getLogger(__name__)

# Compact caps — RCA prompts are token-budgeted.
_TOP_SLOW = 5
_TOP_ERRORS = 5
_MAX_TRACES_PER_SERVICE = 20    # bounded external-provider fetch


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
            trace_qs = trace_qs.filter(root_service_name__in=service_names)
        trace_ids = list(trace_qs.values_list('trace_id', flat=True)[:500])
        if not trace_ids:
            return 0
        return Span.objects.filter(trace_id__in=trace_ids).count()
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


def _compute_live(batch):
    """The pre-#10.5 code path — query the DB / adapter directly.

    Extracted so ``build_trace_context`` and ``snapshot_trace_context``
    share exactly one query implementation.
    """
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

    service_names = _service_names(getattr(batch, 'project', None))

    summary = _from_native(organisation, service_names, window_start, window_end)
    if summary and summary.get('span_count', 0) > 0:
        return summary
    return _from_external(organisation, service_names, window_start, window_end)


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
        from traces.models import Span, Trace
    except ImportError:
        return None

    trace_qs = Trace.objects.filter(
        organisation=organisation,
        start_time__gte=start,
        start_time__lte=end,
    )
    if service_names:
        trace_qs = trace_qs.filter(root_service_name__in=service_names)

    trace_ids = list(trace_qs.values_list('trace_id', flat=True)[:500])
    if not trace_ids:
        return None

    span_qs = Span.objects.filter(trace_id__in=trace_ids)
    total_spans = span_qs.count()
    if total_spans == 0:
        return None

    error_spans = span_qs.filter(status_code='ERROR')

    # start_time is included so the unified timeline can plot span
    # events on the time axis. Without it, _events_from_traces produces
    # time=None events and the timeline chart silently drops them.
    top_slow = list(
        span_qs.order_by('-duration_ms')[:_TOP_SLOW]
        .values('trace_id', 'service_name', 'operation_name',
                'duration_ms', 'status_code', 'start_time')
    )
    top_errors = list(
        error_spans.order_by('-start_time')[:_TOP_ERRORS]
        .values('trace_id', 'service_name', 'operation_name',
                'status_message', 'duration_ms', 'start_time')
    )
    # Django's `.values()` returns datetime objects for DateTimeField;
    # ensure they serialise as ISO strings in the JSON payload the
    # frontend + AI both consume.
    for row in top_slow + top_errors:
        st = row.get('start_time')
        if st is not None and hasattr(st, 'isoformat'):
            row['start_time'] = st.isoformat()

    services_touched = sorted(
        {s for s in span_qs.values_list('service_name', flat=True).distinct() if s}
    )

    return {
        'source': 'otlp',
        'span_count': total_spans,
        'error_span_count': error_spans.count(),
        'trace_count': len(trace_ids),
        'top_slow': top_slow,
        'top_errors': top_errors,
        'services_touched': services_touched,
    }


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

    return {
        'source': 'external',
        'span_count': len(all_spans),
        'error_span_count': len(error_spans),
        'trace_count': len({s['trace_id'] for s in all_spans}),
        'top_slow': top_slow,
        'top_errors': top_errors,
        'services_touched': sorted(services_seen),
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
