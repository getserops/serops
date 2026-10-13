"""
Correlation Engine for intelligent data source linking.

Provides 4-way correlation between:
1. Logs ↔ Code Changes (file-to-error)
2. Metrics ↔ Code Changes (deployment impact)
3. Logs ↔ Metrics (temporal alignment)
4. CI/CD ↔ Code Changes (build verification)

**Complexity bounds** (Q2.2)

Every correlation function has nested loops over untrusted-length
inputs — logs, code changes, spans, CI/CD jobs — that arrive from
Elasticsearch / OTLP / SCM adapters and can be arbitrarily large
under a noisy incident (10K logs × 500 spans × 50 commits).
Without caps this becomes ~5M inner-loop iterations per batch,
holding a Celery worker for seconds and starving other batches.

Two protections applied here:

1. **Input caps** — each function takes the first ``_MAX_*`` items of
   its untrusted input and logs a truncation warning. The AI prompt
   already caps ``logs`` at ~500 severity-filtered entries and
   ``code_changes`` at 10 commits; the correlation engine's caps
   sit at the same order of magnitude so we never process more
   than the AI eventually reads. Real batches almost never touch
   these caps; noisy-incident batches do, and truncating there is
   cheaper than blocking the whole pipeline.

2. **Per-log early exit** — the file-to-error loop looks for *any*
   commit that touched a file the log mentioned. It doesn't need
   to try every commit; the first hit is the interesting one.
   Same principle in ``correlate_cicd_with_code_changes``:
   the earliest commit-in-window on the matching branch is the
   candidate; later commits are already ranked lower by the
   confidence helper.

The caps are named module-level constants below so an operator
tuning them in production can grep once, not seven times.
"""

import re
from datetime import datetime,timedelta
from typing import List, Dict, Any, Optional
import logging

from Data.correlation_confidence import (
    HIGH,
    LOW,
    MEDIUM,
    SCORE_HIGH,
    SCORE_LOW,
    SCORE_MEDIUM,
    SCORE_MISSING_FALLBACK_MEDIUM,
    SCORE_MISSING_FALLBACK_OTHER,
    confidence_from_deploy_metric_lag,
    confidence_from_time_proximity,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input caps (Q2.2)
# ---------------------------------------------------------------------------
#
# Same order-of-magnitude as the AI prompt caps in prompts.py — we
# never correlate more signal than the prompt eventually reads. Real
# batches sit far below these; noisy-incident batches hit the ceiling
# and we truncate + log rather than block the pipeline.

_MAX_LOGS = 500
_MAX_CODE_CHANGES = 50
_MAX_CICD_JOBS = 50
_MAX_TRACE_ERROR_SPANS = 50
_MAX_TRACE_SLOW_SPANS = 50
_MAX_FILE_MENTIONS_PER_LOG = 20

# Output cap per correlation type (RCA audit finding #13, 2026-09-19).
# PR-PERF1 capped INPUTS but the output list is O(N × M) in the worst
# case — a batch with 500 logs × 50 code_changes matching everything
# produces 25 000 correlation dicts. That bloats ``batch.data`` JSONB,
# stresses Postgres, and clobbers the Batch Detail render. Downstream
# only ever reads the top ~5 per type (see prompts.py section render),
# so keeping the top-100 by score is comfortable headroom while
# bounding memory + storage.
_MAX_CORRELATIONS_PER_TYPE = 100

# Trace-id length in correlation output (RCA audit finding #9). OTEL
# trace_ids are 32 hex chars — anything shorter fails when the
# operator tries to look up the trace in Tempo / Jaeger / DD APM.
# Frontend can truncate for display; backend must emit the full id.
_TRACE_ID_LEN = 32


# ---------------------------------------------------------------------------
# Span↔log fuzzy match (RCA audit finding #12)
# ---------------------------------------------------------------------------
#
# Real client libraries decorate the raw exception before it lands in
# a log line:
#   * pymongo   — inserts ``mongodb://`` between the exception name
#     and the host, breaking a plain substring test.
#   * urllib3   — wraps a ``ConnectionError()`` around the payload.
#   * stripe    — prepends module paths (``stripe.error.APIConnectionError``).
# The old ``span_msg[:40] in log_msg`` check refused to match when
# any of those decorations appeared between the substring's tokens,
# demoting the correlation from HIGH to MEDIUM even though span and
# log clearly described the same event. Token-overlap resolves this.

# Minimum share of the span's significant tokens that must appear in
# the log line for the two to count as the same event. 0.6 keeps the
# bar meaningful — a stray "connection refused" won't match — while
# tolerating one or two client-library decorations.
_SPAN_LOG_TOKEN_OVERLAP_MIN = 0.6

# Tokens shorter than this are usually filler (``is``, ``at``, ``the``)
# and drag the ratio down without signal.
_SPAN_LOG_MIN_TOKEN_LEN = 4


def _significant_tokens(text: str) -> set:
    """Return the set of alphanumeric tokens of at least four chars,
    lowercased. Used for span↔log token-overlap comparison."""
    if not text:
        return set()
    return set(re.findall(r'[a-z0-9]{' + str(_SPAN_LOG_MIN_TOKEN_LEN) + r',}', text.lower()))


def _span_log_equivalent(span_msg: str, log_msg: str) -> bool:
    """True when a span error message and a log line likely describe
    the same event.

    Two signals — either satisfies:
      1. The first 40 chars of the span message appear verbatim in the
         log line (the pre-fix behaviour — cheap when it works).
      2. At least ``_SPAN_LOG_TOKEN_OVERLAP_MIN`` of the span's
         four-plus-char alphanumeric tokens also appear in the log.

    Signal 1 handles clean cases where no decoration was inserted.
    Signal 2 handles the pymongo / urllib3 / stripe wrapping cases.
    """
    if not span_msg or not log_msg:
        return False
    span_lower = span_msg.lower()
    log_lower = log_msg.lower()
    if span_lower[:40] in log_lower:
        return True
    span_tokens = _significant_tokens(span_lower)
    if not span_tokens:
        return False
    overlap = span_tokens & _significant_tokens(log_lower)
    return len(overlap) / len(span_tokens) >= _SPAN_LOG_TOKEN_OVERLAP_MIN


def _cap(items, limit: int, kind: str) -> List:
    """Return the first ``limit`` items and log if we truncated.

    The warning is one line per batch — noisy enough to spot in the
    logs, quiet enough not to spam under a real incident. The
    correlation results already carry high-signal ranking, so
    dropping the tail rarely changes the ``primary_correlation``
    outcome.
    """
    if not items:
        return items
    if len(items) <= limit:
        return items
    logger.warning(
        'correlation_engine: truncating %s from %d to %d for bounded processing',
        kind, len(items), limit,
    )
    return items[:limit]


def correlate_logs_with_code_changes(logs: List[Dict], code_changes: List[Dict]) -> List[Dict]:
    """
    Find explicit connections between error logs and code changes.
    
    Extracts file paths from stack traces and matches them to recently modified files.
    
    Args:
        logs: List of log entries
        code_changes: List of code change dictionaries
        
    Returns:
        List of correlations with confidence scoring
    """
    correlations = []

    if not logs or not code_changes:
        return correlations

    logs = _cap(logs, _MAX_LOGS, 'logs')
    code_changes = _cap(code_changes, _MAX_CODE_CHANGES, 'code_changes')

    # File path patterns for different languages
    file_patterns = [
        r'(?:/[\w/]+/)?([\w/]+\.(?:py|js|jsx|ts|tsx|java|go|rb|php|cs))',  # Common languages
        r'File "([^"]+)"',  # Python traceback
        r'at ([^\s]+\.(?:js|ts))',  # JavaScript stack
        r'in ([\w/]+\.\w+)',  # Generic
    ]

    for log in logs:
        message = log.get('message', '')
        timestamp_str = log.get('timestamp', '')
        
        if not message:
            continue
        
        # Extract all file mentions from the log. Cap the mention
        # set per-log — a stack trace with a hundred frames still
        # gives us plenty of signal from the first 20, and the
        # inner-loop file-matching is O(mentions × changed_files).
        file_mentions = set()
        for pattern in file_patterns:
            matches = re.findall(pattern, message)
            file_mentions.update(matches)
            if len(file_mentions) >= _MAX_FILE_MENTIONS_PER_LOG:
                break

        if not file_mentions:
            continue
        
        # Try to parse log timestamp
        try:
            log_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except Exception:
            log_time = datetime.now()
        
        # Check each code change
        for change in code_changes:
            changed_files = change.get('files', [])
            if not changed_files:
                continue
            
            # Find matching files
            matching_files = []
            for mentioned_file in file_mentions:
                for changed_file in changed_files:
                    # Match if the file path ends with the mentioned file
                    if changed_file.endswith(mentioned_file) or mentioned_file in changed_file:
                        matching_files.append(mentioned_file)
                        break
            
            if not matching_files:
                continue
            
            # Time-proximity confidence — see Data.correlation_confidence
            # for the threshold rationale. Drop the correlation on either
            # a parse failure or an out-of-window gap: we don't want to
            # emit a low-signal LOW when the timestamps are unusable.
            try:
                commit_time = datetime.fromisoformat(change['timestamp'].replace('Z', '+00:00'))
                time_diff_seconds = (log_time - commit_time).total_seconds()
            except Exception:
                continue
            outcome = confidence_from_time_proximity(time_diff_seconds)
            if outcome is None:
                continue
            confidence, score = outcome
            
            correlations.append({
                'type': 'file_to_error',
                'log_timestamp': timestamp_str,
                'log_message': message[:200],
                'commit_sha': change.get('sha', 'unknown')[:8],
                'commit_message': change.get('message', '')[:100],
                'matching_files': matching_files,
                'time_since_commit_minutes': round(time_diff_seconds / 60, 1),
                'confidence': confidence,
                'score': score
            })
    
    # Sort by confidence score (highest first)
    correlations.sort(key=lambda x: x['score'], reverse=True)
    
    logger.info(f"File-to-Error correlations: {len(correlations)} found")
    return correlations


def correlate_metrics_with_code_changes(metrics_summary: Dict, code_changes: List[Dict]) -> List[Dict]:
    """
    Correlate metric anomalies with recent deployments.
    
    Args:
        metrics_summary: Processed metrics summary from preprocess_metrics_for_ai
        code_changes: List of code change dictionaries
        
    Returns:
        List of deployment impact correlations
    """
    correlations = []

    if not metrics_summary or not code_changes:
        return correlations

    code_changes = _cap(code_changes, _MAX_CODE_CHANGES, 'code_changes')

    # Check memory anomalies
    memory_anomalies = metrics_summary.get('memory', {}).get('anomalies', [])
    cpu_anomalies = metrics_summary.get('cpu', {}).get('anomalies', [])
    
    all_anomalies = [
        {'type': 'memory', **anomaly} for anomaly in memory_anomalies
    ] + [
        {'type': 'cpu', **anomaly} for anomaly in cpu_anomalies
    ]
    
    for anomaly in all_anomalies:
        anomaly_start_str = anomaly.get('start_time', '')
        if not anomaly_start_str:
            continue
        
        try:
            anomaly_time = datetime.fromisoformat(anomaly_start_str.replace('Z', '+00:00'))
        except Exception:
            continue
        
        # Find commits deployed shortly before the anomaly
        for change in code_changes:
            try:
                commit_time = datetime.fromisoformat(change['timestamp'].replace('Z', '+00:00'))
                time_diff = anomaly_time - commit_time
                time_diff_minutes = time_diff.total_seconds() / 60
                
                # Deploy → resource anomaly — see correlation_confidence
                # for the 15-60-120 min band rationale. Drop the entry
                # on out-of-window (< 15 min = noise, > 120 min = stale).
                outcome = confidence_from_deploy_metric_lag(time_diff_minutes)
                if outcome is None:
                    continue
                confidence, score = outcome

                correlations.append({
                    'type': 'deployment_to_metric_spike',
                    'metric_type': anomaly['type'],
                    'anomaly_peak': f"{anomaly.get('peak_value', 0)}%",
                    'anomaly_start': anomaly_start_str,
                    'commit_sha': change.get('sha', 'unknown')[:8],
                    'commit_message': change.get('message', '')[:100],
                    'time_after_deploy_minutes': round(time_diff_minutes, 1),
                    'confidence': confidence,
                    'score': score,
                    'files_changed': change.get('files', [])[:5],
                })
            except Exception:
                continue
    
    logger.info(f"Deployment-to-Metric correlations: {len(correlations)} found")
    return correlations


def correlate_logs_with_metrics(logs: List[Dict], metrics_summary: Dict) -> List[Dict]:
    """
    Link error logs that occurred during metric spikes.
    
    Args:
        logs: List of log entries
        metrics_summary: Processed metrics summary
        
    Returns:
        List of temporal correlations
    """
    correlations = []

    if not logs or not metrics_summary:
        return correlations

    logs = _cap(logs, _MAX_LOGS, 'logs')

    # Get all anomalies with their correlation windows
    memory_anomalies = metrics_summary.get('memory', {}).get('anomalies', [])
    cpu_anomalies = metrics_summary.get('cpu', {}).get('anomalies', [])

    for anomaly in memory_anomalies + cpu_anomalies:
        correlation_window = anomaly.get('correlation_window', {})
        if not correlation_window:
            continue
        
        try:
            window_start = datetime.fromisoformat(correlation_window['start'].replace('Z', '+00:00'))
            window_end = datetime.fromisoformat(correlation_window['end'].replace('Z', '+00:00'))
        except Exception:
            continue
        
        # Find logs within this window
        correlated_logs = []
        for log in logs:
            try:
                log_time = datetime.fromisoformat(log['timestamp'].replace('Z', '+00:00'))
                # Include logs during spike + 2 min buffer after
                if window_start <= log_time <= (window_end + timedelta(minutes=2)):
                    correlated_logs.append({
                        'timestamp': log['timestamp'],
                        'message': log['message'][:150],
                        'level': log.get('level', 'UNKNOWN')
                    })
            except Exception:
                continue
        
        if correlated_logs:
            metric_type = 'Memory' if 'memory' in anomaly.get('type', '').lower() else 'CPU'
            # RCA audit finding #6 (PR-AUDIT3): assign a confidence
            # label so ``high_confidence_count`` reports honestly and
            # ``primary_correlation`` ranking uses the calibrated scale
            # instead of the legacy no-score fallback. Threshold:
            # 3+ error logs during the spike window is a strong
            # co-occurrence signal (HIGH); 1-2 is suggestive but the
            # base rate of concurrent errors during a batch window
            # keeps the confidence at MEDIUM.
            if len(correlated_logs) >= 3:
                label, score = HIGH, SCORE_HIGH
            else:
                label, score = MEDIUM, SCORE_MEDIUM
            correlations.append({
                'type': 'logs_during_metric_spike',
                'metric': metric_type,
                'peak_value': f"{anomaly.get('peak_value', 0)}%",
                'spike_start': correlation_window.get('start'),
                'spike_duration_seconds': anomaly.get('duration_seconds', 0),
                'correlated_log_count': len(correlated_logs),
                'sample_logs': correlated_logs[:5],  # First 5 logs
                'suggestion': f"These errors may be caused by or causing the {metric_type} spike",
                'confidence': label,
                'score': score,
            })

    correlations.sort(key=lambda c: c.get('score', 0), reverse=True)
    logger.info(f"Log-to-Metric correlations: {len(correlations)} found")
    return correlations


def correlate_cicd_with_code_changes(cicd_logs: List[Dict], code_changes: List[Dict]) -> List[Dict]:
    """
    Correlate failed CI/CD jobs with recent code changes.

    Matching logic:
    1. Branch match: cicd_log.branch == code_change.branch
    2. Temporal proximity: commit before CI/CD job, within 4-hour window
    3. Confidence: <1h = HIGH (0.9), <2h = MEDIUM (0.7), <4h = LOW (0.5)

    Only processes failed jobs (status == 'failed').

    Args:
        cicd_logs: List of CI/CD log entries from batch data
        code_changes: List of code change dictionaries

    Returns:
        List of cicd_failure_to_commit correlations
    """
    correlations = []

    if not cicd_logs or not code_changes:
        return correlations

    # Only process failed jobs
    failed_jobs = [j for j in cicd_logs if j.get('status') == 'failed']
    if not failed_jobs:
        return correlations

    failed_jobs = _cap(failed_jobs, _MAX_CICD_JOBS, 'failed_cicd_jobs')
    code_changes = _cap(code_changes, _MAX_CODE_CHANGES, 'code_changes')

    for job in failed_jobs:
        job_branch = job.get('branch', '')
        if not job_branch:
            continue

        # Parse job timestamp
        job_time_str = job.get('timestamp') or job.get('created_at', '')
        if not job_time_str:
            continue
        try:
            job_time = datetime.fromisoformat(str(job_time_str).replace('Z', '+00:00'))
        except (ValueError, TypeError):
            continue

        for change in code_changes:
            change_branch = change.get('branch', '')
            if not change_branch or change_branch != job_branch:
                continue

            # Parse commit timestamp
            try:
                commit_time = datetime.fromisoformat(
                    str(change.get('timestamp', '')).replace('Z', '+00:00')
                )
            except (ValueError, TypeError):
                continue

            # Commit must be before the CI/CD job — the confidence
            # helper handles the negative-lag case (returns None) so the
            # ordering guard is implicit.
            time_diff_seconds = (job_time - commit_time).total_seconds()
            outcome = confidence_from_time_proximity(time_diff_seconds)
            if outcome is None:
                continue
            confidence, score = outcome

            trace_errors = job.get('trace_errors', '') or ''

            correlations.append({
                'type': 'cicd_failure_to_commit',
                'pipeline_id': str(job.get('pipeline_id', '')),
                'job_name': job.get('job_name', ''),
                'job_status': 'failed',
                'branch': job_branch,
                'trace_errors': trace_errors[:300],
                'commit_sha': change.get('sha', 'unknown')[:8],
                'commit_message': change.get('message', '')[:100],
                'commit_author': change.get('author', ''),
                'time_between_minutes': round(time_diff_seconds / 60, 1),
                'confidence': confidence,
                'score': score,
                'files_changed': change.get('files', [])[:5],
            })

    # Sort by confidence score (highest first)
    correlations.sort(key=lambda x: x['score'], reverse=True)

    logger.info(f"CI/CD-to-CodeChange correlations: {len(correlations)} found")
    return correlations


def _parse_iso(value):
    """Tolerant ISO parser used by trace correlations. Returns None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


def correlate_spans_with_logs(traces_summary: Dict, logs: List[Dict]) -> List[Dict]:
    """
    Cross-service causality: an error span in trace X coincides with an
    error log in the same service around the same time.

    Distinguishes "logs and traces both saw something" (weak) from
    "the trace's error span is the same event as the log error"
    (strong — the span gives us the service + operation the log line
    lacked).
    """
    correlations: List[Dict] = []
    if not traces_summary or not logs:
        return correlations

    logs = _cap(logs, _MAX_LOGS, 'logs')
    top_errors = _cap(
        traces_summary.get('top_errors') or [],
        _MAX_TRACE_ERROR_SPANS, 'trace_error_spans',
    )
    if not top_errors:
        return correlations

    # Build a small index of error logs by (service, roughly bucketed time).
    log_index: List[Dict] = []
    for log in logs:
        message = log.get('message', '') or ''
        # Only ERROR-level logs are worth correlating with error spans.
        level = str(log.get('level', '')).upper()
        if level and level != 'ERROR':
            continue
        ts = _parse_iso(log.get('timestamp'))
        if ts is None:
            continue
        log_index.append({
            'timestamp': ts,
            'service': log.get('component') or log.get('service') or '',
            'message': message,
        })

    for span in top_errors:
        span_service = str(span.get('service_name') or '')
        span_msg = str(span.get('status_message') or '')
        # Spans don't always have a wall-clock — top_errors is ranked
        # by recency so we don't have per-span time. Use service as
        # the join key; time correlation is via the batch window
        # (already narrow — 15 min).
        matching_logs = []
        for log in log_index:
            if span_service and log['service'] and span_service.lower() != str(log['service']).lower():
                continue
            matching_logs.append(log)
        if not matching_logs:
            continue

        # Highest confidence if the span error message shows up in a
        # log line — same event surfaced from two sources. RCA audit
        # finding #12 (PR-AUDIT4): the old exact-substring test broke
        # on real client libraries that decorate the raw exception
        # message before it lands in logs (pymongo prepends
        # ``mongodb://`` between the exception name and host, urllib3
        # wraps ``ConnectionError()`` around the message, stripe
        # prepends module paths). Fall back to token overlap when the
        # exact-substring check misses, so real ``span_error → log_error``
        # matches keep their HIGH label instead of demoting to MEDIUM.
        exact_hit = any(
            span_msg and _span_log_equivalent(span_msg, m['message'] or '')
            for m in matching_logs
        )
        # Exact message overlap = same event surfaced by two paths (span
        # + log). Service-only match = suggestive coincidence. Both
        # scores follow the shared HIGH/MEDIUM scale so
        # ``primary_correlation`` ranks correlation types uniformly.
        confidence = HIGH if exact_hit else MEDIUM
        score = SCORE_HIGH if exact_hit else SCORE_MEDIUM

        correlations.append({
            'type': 'span_error_to_log_error',
            'service': span_service,
            'operation': span.get('operation_name', ''),
            'trace_id': str(span.get('trace_id', ''))[:_TRACE_ID_LEN],
            'span_message': span_msg[:200],
            'matching_log_count': len(matching_logs),
            'sample_log_message': (matching_logs[0]['message'] or '')[:200] if matching_logs else '',
            'confidence': confidence,
            'score': score,
        })

    correlations.sort(key=lambda c: c['score'], reverse=True)
    logger.info(f"Span-error-to-log-error correlations: {len(correlations)} found")
    return correlations


def correlate_spans_with_code_changes(
    traces_summary: Dict,
    code_changes: List[Dict],
    service_paths_by_name: Optional[Dict[str, List[str]]] = None,
) -> List[Dict]:
    """
    Perf-regression heuristic: slow spans appearing shortly after a
    code deploy suggest the deploy introduced latency.

    We can't do exact per-span timing without wall clocks in the
    summary — so we correlate at the *trace summary* level: if the
    summary says services touched include something a recent commit
    modified, that's a candidate.

    Q5-3: the directory heuristic ``/{svc}/`` in a file path is fragile
    across monorepos (packages/foo/src/services/checkout/...) and
    package-style repos (pkg-checkout/api.py doesn't contain
    /checkout/). An owner can now declare authoritative service→path
    globs via ``ProjectService.provider_config['service_paths']``;
    the caller threads them here as ``service_paths_by_name``. When
    a service has explicit globs, they're the source of truth; the
    directory heuristic remains a fallback for services with no
    declared paths.
    """
    correlations: List[Dict] = []
    if not traces_summary or not code_changes:
        return correlations

    code_changes = _cap(code_changes, _MAX_CODE_CHANGES, 'code_changes')
    top_slow = _cap(
        traces_summary.get('top_slow') or [],
        _MAX_TRACE_SLOW_SPANS, 'trace_slow_spans',
    )
    services_touched = set(traces_summary.get('services_touched') or [])
    if not top_slow or not services_touched:
        return correlations

    # Normalise the owner-declared overrides so matching is
    # case-insensitive on service names.
    owner_overrides: Dict[str, List[str]] = {}
    if service_paths_by_name:
        for svc, globs in service_paths_by_name.items():
            if not svc or not globs:
                continue
            owner_overrides[svc.lower()] = [
                g for g in globs if isinstance(g, str) and g
            ]

    import fnmatch

    for change in code_changes:
        commit_files = change.get('files') or []
        file_paths = []
        for f in commit_files:
            if isinstance(f, dict):
                file_paths.append(f.get('path', ''))
            elif isinstance(f, str):
                file_paths.append(f)
        matching_services = set()
        for svc in services_touched:
            svc_low = svc.lower()
            svc_globs = owner_overrides.get(svc_low)
            if svc_globs:
                # Authoritative override — any glob match wins;
                # skip the directory heuristic entirely.
                if any(
                    fnmatch.fnmatch(str(path), glob)
                    for path in file_paths
                    for glob in svc_globs
                ):
                    matching_services.add(svc)
                continue
            # No override for this service — fall back to the
            # directory heuristic (services/<name>/ or <name>/).
            for path in file_paths:
                path_low = str(path).lower()
                if f'/{svc_low}/' in path_low or path_low.startswith(f'{svc_low}/'):
                    matching_services.add(svc)
                    break
        if not matching_services:
            continue

        # Slowest spans in the matched services.
        service_spans = [
            s for s in top_slow
            if s.get('service_name') and s['service_name'] in matching_services
        ]
        if not service_spans:
            continue

        top_span = max(service_spans, key=lambda s: s.get('duration_ms', 0))
        # Deploy → span timing is per-batch, not per-second — we can't
        # tell whether the slow span came before or after the code
        # change within the batch window. MEDIUM by construction,
        # scored on the shared scale so ranking behaves.
        correlations.append({
            'type': 'slow_span_after_deploy',
            'commit_sha': str(change.get('sha', ''))[:8],
            'commit_message': str(change.get('message', ''))[:100],
            'commit_author': change.get('author', ''),
            'services_affected': sorted(matching_services),
            'top_slow_operation': top_span.get('operation_name', ''),
            'top_slow_duration_ms': top_span.get('duration_ms', 0),
            'trace_id': str(top_span.get('trace_id', ''))[:_TRACE_ID_LEN],
            'confidence': MEDIUM,
            'score': SCORE_MEDIUM,
        })

    correlations.sort(key=lambda c: c['score'], reverse=True)
    logger.info(f"Slow-span-after-deploy correlations: {len(correlations)} found")
    return correlations


def correlate_spans_with_metrics(traces_summary: Dict, metrics_summary: Dict) -> List[Dict]:
    """
    Resource-contention heuristic: slow spans coincide with a CPU or
    memory anomaly in the same batch window. Suggests the latency
    is driven by resource pressure, not code.
    """
    correlations: List[Dict] = []
    if not traces_summary or not metrics_summary:
        return correlations

    top_slow = _cap(
        traces_summary.get('top_slow') or [],
        _MAX_TRACE_SLOW_SPANS, 'trace_slow_spans',
    )
    if not top_slow:
        return correlations

    memory_anomalies = metrics_summary.get('memory', {}).get('anomalies', []) or []
    cpu_anomalies = metrics_summary.get('cpu', {}).get('anomalies', []) or []
    all_anomalies = (
        [{'type': 'memory', **a} for a in memory_anomalies] +
        [{'type': 'cpu', **a} for a in cpu_anomalies]
    )
    if not all_anomalies:
        return correlations

    # One correlation entry per anomaly — attaches the slowest span for
    # context. Since spans + metrics are already batch-scoped, this
    # temporal join is implicit.
    top_span = max(top_slow, key=lambda s: s.get('duration_ms', 0))
    # Resource-contention is a hypothesis, not a certainty — the batch
    # window makes co-occurrence plausible, but doesn't prove the
    # anomaly caused the slow span. MEDIUM.
    for anomaly in all_anomalies:
        correlations.append({
            'type': 'slow_span_during_metric_spike',
            'metric_type': anomaly.get('type'),
            'anomaly_peak': f"{anomaly.get('peak_value', 0)}%",
            'anomaly_start': anomaly.get('start_time', ''),
            'top_slow_service': top_span.get('service_name', ''),
            'top_slow_operation': top_span.get('operation_name', ''),
            'top_slow_duration_ms': top_span.get('duration_ms', 0),
            'trace_id': str(top_span.get('trace_id', ''))[:_TRACE_ID_LEN],
            'confidence': MEDIUM,
            'score': SCORE_MEDIUM,
        })

    correlations.sort(key=lambda c: c['score'], reverse=True)
    logger.info(f"Slow-span-during-metric-spike correlations: {len(correlations)} found")
    return correlations


def build_comprehensive_correlations(
    logs: List[Dict],
    metrics_summary: Dict,
    code_changes: List[Dict],
    cicd_logs: Optional[List[Dict]] = None,
    traces_summary: Optional[Dict] = None,
    service_paths_by_name: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """
    Generate all possible correlations between data sources.

    Args:
        logs: Formatted log entries from AI analysis
        metrics_summary: Preprocessed metrics summary
        code_changes: Recent code changes
        cicd_logs: CI/CD job logs (failed pipelines, etc.)
        traces_summary: Trace summary from ai_model.trace_context
            (top_slow, top_errors, services_touched). Optional —
            callers without trace data pass None.
        service_paths_by_name: Q5-3. Optional owner-declared globs
            keyed by service name (from ``ProjectService.provider_config['service_paths']``).
            Threaded to ``correlate_spans_with_code_changes`` where
            it overrides the fragile directory heuristic.

    Returns:
        Comprehensive correlation map with summary
    """
    all_correlations = {
        'file_to_error': correlate_logs_with_code_changes(logs, code_changes),
        'deployment_to_metric_spike': correlate_metrics_with_code_changes(metrics_summary, code_changes),
        'metric_spike_to_errors': correlate_logs_with_metrics(logs, metrics_summary),
        'cicd_failure_to_commit': correlate_cicd_with_code_changes(cicd_logs or [], code_changes),
        # Trace-based correlations (Item #12) — empty lists when
        # traces_summary is None, so downstream doesn't need to guard.
        'span_error_to_log_error': correlate_spans_with_logs(traces_summary or {}, logs),
        'slow_span_after_deploy': correlate_spans_with_code_changes(
            traces_summary or {}, code_changes,
            service_paths_by_name=service_paths_by_name,
        ),
        'slow_span_during_metric_spike': correlate_spans_with_metrics(
            traces_summary or {}, metrics_summary,
        ),
    }

    # Output cap per correlation type (RCA audit finding #13). Each
    # correlation function already sorts its own list by score
    # descending; keeping the top-N by that ranking preserves the
    # highest-signal correlations for both AI prompt inclusion (already
    # top-5 per section) and the Batch Detail UI. A batch where every
    # log matches every code change (500 × 50 = 25 000 pairs) used to
    # persist all of them into ``batch.data['correlation_results']``,
    # bloating the JSONB blob and slowing the Batch Detail render.
    for _corr_type, _corr_list in all_correlations.items():
        if len(_corr_list) > _MAX_CORRELATIONS_PER_TYPE:
            logger.warning(
                'correlation_engine: %s produced %d correlations; '
                'truncating to top %d by score.',
                _corr_type, len(_corr_list), _MAX_CORRELATIONS_PER_TYPE,
            )
            all_correlations[_corr_type] = _corr_list[:_MAX_CORRELATIONS_PER_TYPE]

    # Calculate statistics. Per RCA audit finding #10 (PR-AUDIT3),
    # also emit the MEDIUM count — several correlation types are
    # MEDIUM by construction (span-based correlations under PR-CONF1,
    # single-signal metric coincidences under finding #6), so
    # reporting only ``high_confidence_count`` under-represents the
    # analysis to the operator on the Dashboard.
    total_correlations = sum(len(c) for c in all_correlations.values())
    high_confidence_count = sum(
        len([item for item in correlations if item.get('confidence') == HIGH])
        for correlations in all_correlations.values()
    )
    medium_confidence_count = sum(
        len([item for item in correlations if item.get('confidence') == MEDIUM])
        for correlations in all_correlations.values()
    )
    low_confidence_count = sum(
        len([item for item in correlations if item.get('confidence') == LOW])
        for correlations in all_correlations.values()
    )

    # Determine primary root cause (highest confidence correlation).
    # Fallback for legacy entries with no explicit ``score``: named
    # constants keep the two fallback ranks (unlabelled MEDIUM vs.
    # everything else) strictly BELOW any scored MEDIUM so a scored
    # MEDIUM always wins the ranking against a legacy shape.
    primary_correlation = None
    max_score = 0
    for corr_type, correlations in all_correlations.items():
        for corr in correlations:
            score = corr.get(
                'score',
                SCORE_MISSING_FALLBACK_MEDIUM
                if corr.get('confidence') == MEDIUM
                else SCORE_MISSING_FALLBACK_OTHER,
            )
            if score > max_score:
                max_score = score
                primary_correlation = {
                    'type': corr_type,
                    'details': corr,
                }
    
    return {
        'correlations': all_correlations,
        'summary': {
            'total_correlations': total_correlations,
            'high_confidence_count': high_confidence_count,
            'medium_confidence_count': medium_confidence_count,
            'low_confidence_count': low_confidence_count,
            'primary_correlation': primary_correlation,
        },
    }
