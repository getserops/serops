from celery import shared_task
from .prompts import get_batch_analysis_prompt
from .ai_service import (
    generate_with_fallback,
    generate_for_organisation,
    generate_text_unified,
    get_api_key_for_org,
)
from .adapters.base import AIServiceError
from Data.models import AIAnalyzedBatch
import logging
from django.utils import timezone
import json
from datetime import datetime


logger = logging.getLogger(__name__)


def _populate_issue_correlations(issue, correlations_data, metrics_summary):
    """
    Populate engine-driven correlation fields on an Issue from real correlation data.

    Sets:
      - has_metric_correlation, metric_correlation_type, metric_anomaly_type
      - has_commit_correlation, linked_commits
      - correlation_confidence
      - correlation_details
    """
    if not correlations_data:
        return

    corrs = correlations_data.get('correlations', {})
    details = {}

    issue_type_upper = (issue.issue_type or '').upper()
    component_lower = (issue.component or '').lower()

    # --- Metric anomaly matching ---
    # Match MEMORY_HIGH/MEMORY_LEAK → memory anomalies
    # Match CPU_HIGH → cpu anomalies
    metric_type = ''
    if issue_type_upper in ('MEMORY_HIGH', 'MEMORY_LEAK'):
        metric_type = 'memory'
    elif issue_type_upper == 'CPU_HIGH':
        metric_type = 'cpu'

    if metric_type and metrics_summary:
        anomalies = metrics_summary.get(metric_type, {}).get('anomalies', [])
        if anomalies:
            # Pick the most severe anomaly
            best = max(anomalies, key=lambda a: a.get('peak_value', 0))
            issue.has_metric_correlation = True
            issue.metric_correlation_type = metric_type
            issue.metric_anomaly_type = 'sustained_high' if best.get('sustained') else 'spike'
            details['metric_anomaly'] = {
                'peak_value': best.get('peak_value'),
                'duration_seconds': best.get('duration_seconds', 0),
                'sustained': best.get('sustained', False),
                'start_time': best.get('start_time', ''),
            }

    # --- File-to-error correlation matching (component → matching_files) ---
    file_to_error = corrs.get('file_to_error', [])
    matched_file_corrs = []
    for corr in file_to_error:
        # Match if any matching file contains the component name
        matching_files = corr.get('matching_files', [])
        if component_lower and any(component_lower in f.lower() for f in matching_files):
            matched_file_corrs.append(corr)

    if matched_file_corrs:
        best_fe = matched_file_corrs[0]  # Already sorted by score
        if not issue.has_commit_correlation:
            issue.has_commit_correlation = True
            sha = best_fe.get('commit_sha', '')
            if sha:
                issue.linked_commits = [{'sha': sha, 'provider': 'unknown', 'project_id': None}]
        details['file_to_error'] = {
            'commit_sha': best_fe.get('commit_sha', ''),
            'matching_files': best_fe.get('matching_files', []),
            'confidence': best_fe.get('confidence', ''),
            'time_since_commit_minutes': best_fe.get('time_since_commit_minutes', 0),
        }

    # --- Deployment-to-metric correlation matching ---
    deploy_corrs = corrs.get('deployment_to_metric_spike', [])
    matched_deploy = [c for c in deploy_corrs if c.get('metric_type') == metric_type] if metric_type else []
    if matched_deploy:
        best_dep = matched_deploy[0]
        sha = best_dep.get('commit_sha', '')
        if sha and not issue.has_commit_correlation:
            issue.has_commit_correlation = True
            issue.linked_commits = [{'sha': sha, 'provider': 'unknown', 'project_id': None}]
        details['deployment_correlation'] = {
            'commit_sha': best_dep.get('commit_sha', ''),
            'commit_message': best_dep.get('commit_message', ''),
            'time_after_deploy_minutes': best_dep.get('time_after_deploy_minutes', 0),
            'confidence': best_dep.get('confidence', ''),
            'files_changed': best_dep.get('files_changed', []),
        }

    # --- CI/CD failure-to-commit correlation matching ---
    CICD_ISSUE_TYPES = ('BUILD_FAILED', 'TEST_FAILED', 'DEPLOY_FAILED', 'PIPELINE_TIMEOUT')
    cicd_corrs = corrs.get('cicd_failure_to_commit', [])

    if cicd_corrs and issue_type_upper in CICD_ISSUE_TYPES:
        # Try component-based matching first (branch or job_name contains component)
        matched_cicd = []
        if component_lower:
            matched_cicd = [
                c for c in cicd_corrs
                if component_lower in (c.get('branch', '') or '').lower()
                or component_lower in (c.get('job_name', '') or '').lower()
            ]
        # Fallback: CI/CD-type issues strongly imply pipeline context — use all
        if not matched_cicd:
            matched_cicd = cicd_corrs

        if matched_cicd:
            best_cicd = matched_cicd[0]  # Already sorted by score
            issue.has_cicd_correlation = True

            sha = best_cicd.get('commit_sha', '')
            if sha and not issue.has_commit_correlation:
                issue.has_commit_correlation = True
                issue.linked_commits = [{'sha': sha, 'provider': 'unknown', 'project_id': None}]

            details['cicd_correlation'] = {
                'pipeline_id': best_cicd.get('pipeline_id', ''),
                'job_name': best_cicd.get('job_name', ''),
                'trace_errors': best_cicd.get('trace_errors', ''),
                'commit_sha': best_cicd.get('commit_sha', ''),
                'commit_message': best_cicd.get('commit_message', ''),
                'commit_author': best_cicd.get('commit_author', ''),
                'confidence': best_cicd.get('confidence', ''),
                'time_between_minutes': best_cicd.get('time_between_minutes', 0),
                'files_changed': best_cicd.get('files_changed', []),
            }

    # --- Determine overall confidence ---
    # Use highest confidence from any matched correlation
    confidence_order = {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1, '': 0}
    best_confidence = ''
    for section in [details.get('file_to_error', {}), details.get('deployment_correlation', {}), details.get('cicd_correlation', {})]:
        c = section.get('confidence', '')
        if confidence_order.get(c, 0) > confidence_order.get(best_confidence, 0):
            best_confidence = c

    # Also check the engine's primary correlation
    primary = correlations_data.get('summary', {}).get('primary_correlation', {})
    if primary:
        pc = primary.get('details', {}).get('confidence', '')
        if confidence_order.get(pc, 0) > confidence_order.get(best_confidence, 0):
            best_confidence = pc

    issue.correlation_confidence = best_confidence
    issue.correlation_details = details


def _build_project_context(batch):
    """Build project & service context dict for the AI prompt."""
    if not batch.project:
        return None
    project = batch.project
    services = []
    for svc in project.services.all():
        services.append({
            'name': svc.name,
            'type': svc.service_type or '',
            'subtype': getattr(svc, 'service_subtype', '') or '',
            'description': (svc.description or '')[:500],
        })
    ctx = {
        'name': project.name,
        'description': (project.description or '')[:500],
        'services': services,
    }
    # Item #17 / Q1.4: surface cluster to the AI so it can reason
    # about "this incident is in prod-eks" and correlate patterns
    # across clusters. Only present when the project is assigned.
    cluster = getattr(project, 'cluster', None)
    if cluster is not None:
        ctx['cluster'] = {
            'name': cluster.name,
            'provider': cluster.get_provider_display(),
            'region': cluster.region or '',
        }
    return ctx


def _redact_log_messages(formatted_logs):
    """Scrub PII / secrets from a list of formatted log dicts.

    Each input dict is expected to have a 'message' string. The message is
    rewritten in place with sensitive substrings replaced by `[REDACTED: <TYPE>]`
    tokens (see Utils.data_redaction.DataRedactionService). This runs before
    logs are stored on the batch or sent to AI providers, so neither the
    SerOps DB nor third-party AI APIs ever see the raw secrets.

    Returns (redacted_logs, summary). The summary aggregates counts by
    severity so callers can log it for audit. Failures are swallowed and
    logged — redaction must not break batch analysis. If redaction fails,
    the unredacted logs are returned (we degrade open here because the
    alternative is losing analysis entirely; the security trade-off should
    be revisited if redaction reliability becomes a concern).
    """
    try:
        from Utils.data_redaction import DataRedactionService
        service = DataRedactionService()
        all_findings = []
        for log in formatted_logs:
            message = log.get('message', '')
            if not message:
                continue
            redacted, findings = service.redact(message)
            if findings:
                log['message'] = redacted
                all_findings.extend(findings)
        return formatted_logs, service.get_summary(all_findings)
    except Exception as e:
        logger.warning(f"PII redaction failed, sending logs unredacted: {e}")
        return formatted_logs, {'total_count': 0, 'by_severity': {}, 'by_type': {}}


def _build_past_memories(batch):
    """Fetch and format resolved-issue memories for AI prompt injection.

    Returns (formatted_text, referenced_issue_ids). The IDs are the
    Issue.pk of every resolved issue that ended up in the prompt — we
    keep them so the frontend can render an "Informed by past
    resolutions" panel on the issues this batch produces.

    Empty string + empty list is returned when no project/organisation
    is resolvable so the prompt builder can skip the section cleanly.
    Any errors are swallowed and logged — memory is a hint, never a
    hard dependency for batch analysis.
    """
    if not batch or not batch.project:
        return '', []
    try:
        from Data.memory import find_past_memories, format_memories_for_prompt
        organisation = batch.organisation or batch.project.organisation
        if not organisation:
            return '', []
        environment = batch.environment or ''
        memory_tuples = find_past_memories(
            project=batch.project,
            environment=environment,
            organisation=organisation,
        )
        text = format_memories_for_prompt(memory_tuples)
        referenced_ids = [issue.id for issue, _tier in memory_tuples]
        return text, referenced_ids
    except Exception as e:
        logger.warning(f"Skipping past-memory injection for batch {batch.batch_id}: {e}")
        return '', []


# Levels that carry root-cause signal. INFO/DEBUG lines rarely help
# analysis and burn tokens (they also displace real errors from the
# 100-signature Smart Aggregation cap). Any log whose ``level`` starts
# with one of these keeps its slot in the AI prompt; everything else
# is dropped from the prompt only — batch.data still holds every
# original entry so audit and debug views see the full stream.
_HIGH_SIGNAL_LEVELS = ('ERROR', 'WARNING', 'CRITICAL', 'FATAL', 'ALERT', 'EMERG', 'SEVERE')

# Substrings hinting at severity even when the level field is generic
# (some log shippers ship 'INFO' with an error message body). Matched
# case-insensitively against the message body.
_HIGH_SIGNAL_MESSAGE_KEYWORDS = (
    'EXCEPTION', 'TRACEBACK', 'PANIC', 'FAILURE', 'FAILED',
    'CONNECTION REFUSED', 'PERMISSION DENIED', 'ACCESS DENIED',
    'UNAUTHORIZED', 'TIMEOUT', 'DEADLOCK', 'OUT OF MEMORY',
    'STACK OVERFLOW', 'ASSERTION', 'SEGFAULT',
)


def _filter_logs_for_ai(formatted_logs):
    """Return the subset of logs worth spending AI tokens on.

    Non-destructive: caller passes ``all_logs``; the returned list is
    a new list containing high-signal entries only. Callers that need
    the full log stream (e.g. audit trail on batch.data) keep the
    original list untouched.

    Signal rule: keep any log whose level is high-severity, OR whose
    message body contains an error-shaped keyword (catches shippers
    that mis-tag exceptions as INFO). Everything else drops out of
    the prompt.

    Replaces the standalone ``preprocess_logs`` task, which destroyed
    ``batch.data['logs']`` in-place and was only wired to the manual
    trigger endpoint (never the scheduled Celery pipeline).
    """
    if not formatted_logs:
        return []
    kept = []
    for log in formatted_logs:
        level = (log.get('level') or '').upper()
        if level.startswith(_HIGH_SIGNAL_LEVELS):
            kept.append(log)
            continue
        message_upper = (log.get('message') or '').upper()
        if any(kw in message_upper for kw in _HIGH_SIGNAL_MESSAGE_KEYWORDS):
            kept.append(log)
    return kept


# Patterns used to strip volatile fragments from log messages before
# they're hashed into a Smart Aggregation signature. Without this,
# ``Connection refused to redis:6379`` and ``Connection refused to
# redis:6380`` are treated as distinct patterns and each burn a
# signature slot in the 100-line AI prompt. With this, both collapse
# into ``Connection refused to redis:{PORT}`` and share one slot.
#
# Order matters: apply the most specific patterns first (UUIDs
# before generic hex, ISO timestamps before generic digit runs).
import re as _re

_SIGNATURE_NORMALIZERS = [
    # ISO-8601 timestamps: 2026-09-01T12:34:56.123456Z / +00:00 / no-tz
    (_re.compile(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?'), '{TS}'),
    # UUIDs (v1-5 all match 8-4-4-4-12 hex)
    (_re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b'), '{UUID}'),
    # Hex hashes ≥16 chars (git SHAs, MD5/SHA-256 prefixes)
    (_re.compile(r'\b[0-9a-fA-F]{16,}\b'), '{HASH}'),
    # IPv4 addresses
    (_re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'), '{IP}'),
    # Quoted strings — user data, query args, file paths that vary
    # per request. Both single and double quotes. Collapses greedy
    # to avoid splitting a single line into many small captures.
    (_re.compile(r'"[^"]*"'), '"{STR}"'),
    (_re.compile(r"'[^']*'"), "'{STR}'"),
    # Numeric literals last — anything left is a bare number
    # (port, PID, count, latency, error code). No word boundaries
    # so we also collapse ``250ms`` -> ``{N}ms`` and ``HTTP500`` ->
    # ``HTTP{N}``. Slightly aggressive but the common log-line
    # cases benefit (retry-counts, latencies, HTTP status codes,
    # shard IDs) and the "over-collapse" false positives are rare
    # enough that Smart Aggregation's priority sort still surfaces
    # the right groups first.
    (_re.compile(r'\d+'), '{N}'),
]


def _normalize_for_signature(message):
    """Return a shape-preserving canonical form of a log message.

    Strips volatile fragments (timestamps, UUIDs, hex hashes, IPs,
    quoted strings, numeric literals) so semantically-identical logs
    that differ only in variable parts collapse to the same signature.
    Pure function, no side effects.

    Reasoning: Smart Aggregation hashes level+component+first-60-chars
    of the raw message. That produces false-negatives on any log line
    where a variable fragment falls within those first 60 chars —
    ``Connection refused to redis:6379`` and ``…:6380`` each get
    their own signature slot, wasting the 100-signature budget on
    what's really one pattern with different ports. Normalising
    first collapses them onto one slot.
    """
    if not message:
        return ''
    normalized = message
    for pattern, replacement in _SIGNATURE_NORMALIZERS:
        normalized = pattern.sub(replacement, normalized)
    return normalized


def _drop_hollow_issues(parsed_result):
    """Remove issue entries that truncation left as empty shells.

    A response cut mid-object balances into valid JSON whose last entry holds
    only the fields the model had got to. ``{"issue_type": "LATEN"}`` parses
    cleanly, then the issue-creation loop below fills in its defaults and it
    lands on the incident page as a CRITICAL "OTHER" issue against no component
    with no evidence — an invented finding, which is worse than a short list.

    An issue is kept only if it names WHAT is wrong and WHERE. Everything else
    in the schema has a sensible default; these two do not, and an entry missing
    them says nothing an operator can act on.

    Returns the number dropped. Only called for truncated responses — a
    complete response returning a thin issue is the model's judgement to make,
    not something to second-guess here.
    """
    issues = parsed_result.get('correlated_issues')
    if not isinstance(issues, list):
        return 0

    def is_usable(issue):
        if not isinstance(issue, dict):
            return False
        where = issue.get('component') or issue.get('service') or issue.get('scope')
        what = (issue.get('title') or issue.get('description')
                or issue.get('root_cause'))
        return bool(where) and bool(what)

    kept = [i for i in issues if is_usable(i)]
    parsed_result['correlated_issues'] = kept
    return len(issues) - len(kept)


def _notify_investigation_requester(investigation, batch, issue_count):
    """Tell whoever asked for the investigation that it finished."""
    if investigation.requested_by_id is None:
        return
    try:
        from notifications.models import Notification
        found = f"{issue_count} issue(s) found" if issue_count else "no issues found"
        Notification.objects.create(
            user_id=investigation.requested_by_id,
            subject=f"Investigation finished: {investigation.project.name}",
            message=f"Your investigation of {investigation.project.name} is done: {found}.",
            notification_type='investigation_done',
            batch_id=batch.batch_id,
        )
    except Exception as e:
        logger.warning(f"Could not notify the requester of investigation {investigation.pk}: {e}")


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def analyze_batch(self, batch_id, preprocessed_logs=None):
    """Analyze a batch using Gemini AI and save results"""
    import re
    from django.contrib.auth import get_user_model
    from notifications.services import send_notification_email
    from notifications.models import Notification
    from django.conf import settings
    from django.utils import timezone

    try:
        # Check if batch exists before proceeding
        try:
            batch = AIAnalyzedBatch.objects.get(batch_id=batch_id)
        except AIAnalyzedBatch.DoesNotExist:
            logger.error(f"Batch {batch_id} not found, retrying in 10 seconds")
            self.retry(countdown=10)  # Retry after a delay
            return
            
        # Handle logs retrieval or use passed preprocessed_logs
        logs = preprocessed_logs
        if logs is None:
            logs = batch.data.get('logs', [])
        
        # Verify logs is a list
        if not isinstance(logs, list):
            logger.error(f"Logs is not a list in analyze_batch for {batch_id}, type: {type(logs)}")
            # Try to convert non-list to list, or use empty list
            logs = [] if logs is None else [logs]
        
        # Verify metrics is a dictionary
        metrics = batch.data.get('metrics', {})
        if not isinstance(metrics, dict):
            logger.error(f"Metrics is not a dict in analyze_batch for {batch_id}, type: {type(metrics)}")
            metrics = {}
        
        # === LEVEL 3 SAFEGUARD: Check all data sources before calling API ===
        # Don't consume API quota if batch has no meaningful data to analyze
        cicd_logs = batch.data.get('cicd_logs', [])
        code_changes = batch.data.get('code_changes', [])
        metrics_summary = batch.data.get('metrics_summary', {})
        
        # Count TRACES too, and count metric DATA POINTS rather than the
        # number of keys in metrics_summary.
        #
        # `len(metrics_summary)` is the size of a fixed-shape dict (cpu,
        # memory, time_range, data_points), so it is 4 whenever the summary
        # exists — even when every series inside is empty. That made the
        # check pass on no data and fail only when the summary was absent
        # entirely. Traces were not counted at all, so a batch carrying only
        # spans — a latency regression with no error logs, which is exactly
        # the case distributed tracing exists for — was skipped without an
        # AI call.
        traces_summary = batch.data.get('traces') or {}
        trace_span_count = 0
        if isinstance(traces_summary, dict):
            trace_span_count = int(traces_summary.get('span_count') or 0)
        metric_points = 0
        if isinstance(metrics_summary, dict):
            points = metrics_summary.get('data_points') or {}
            if isinstance(points, dict):
                metric_points = sum(int(v or 0) for v in points.values()
                                    if isinstance(v, (int, float)))

        total_data_items = (len(logs) + len(cicd_logs) + len(code_changes)
                            + metric_points + trace_span_count)
        if total_data_items == 0:
            logger.info(
                f"⏭️ Skipping AI for batch {batch_id}: no data to analyze "
                f"(0 logs, 0 cicd, 0 changes, 0 metric points, 0 spans)")
            batch.model_name = "SKIPPED (NO_DATA)"
            batch.analyzed_at = timezone.now()
            batch.save(update_fields=['model_name', 'analyzed_at'])
            return f"Batch {batch_id} skipped - no data to analyze"
        
        # Get the preprocessed metrics summary for AI analysis (token-efficient)
        metrics_summary = batch.data.get('metrics_summary', {})
        
        # Build AILogContext from batch data (canonical contract for AI input)
        from integrations.ai_contract import AILogContext
        from integrations.schemas import LogEntry, _parse_timestamp, _detect_level
        
        log_entries = []
        for log in logs:
            source = log.get('_source', {})
            entry = LogEntry(
                timestamp=_parse_timestamp(source.get('@timestamp', '')),
                message=source.get('message', ''),
                level=_detect_level(source.get('log_level', source.get('level', 'UNKNOWN'))),
                service=source.get('service', {}).get('name', source.get('component', 'unknown')) if isinstance(source.get('service'), dict) else source.get('service', 'unknown'),
                host=source.get('host', {}).get('name', source.get('hostname', 'unknown')) if isinstance(source.get('host'), dict) else source.get('host', 'unknown'),
                raw_id=log.get('_id', ''),
                deduplicated=source.get('deduplicated', False),
                occurrence_count=source.get('occurrence_count', 1),
            )
            log_entries.append(entry)
        
        ai_log_context = AILogContext(
            logs=log_entries,
            total_count=len(log_entries),
            time_range_start=min((e.timestamp for e in log_entries), default=None),
            time_range_end=max((e.timestamp for e in log_entries), default=None),
            service_names=list(set(e.service for e in log_entries if e.service)),
        )
        
        # Build log summaries and formatted logs from AILogContext (backward compatible)
        all_logs = []
        log_summaries = {
            "severity_counts": {"ERROR": 0, "WARNING": 0, "CRITICAL": 0, "INFO": 0, "DEBUG": 0, "UNKNOWN": 0},
            "components": set(),
            "hosts": set(),
            "time_range": {"earliest": None, "latest": None}
        }
        
        for entry in ai_log_context.logs:
            level = entry.level.upper() if entry.level else "UNKNOWN"
            
            # Update summaries
            if level in log_summaries["severity_counts"]:
                log_summaries["severity_counts"][level] += 1
            else:
                log_summaries["severity_counts"]["UNKNOWN"] += 1
                
            log_summaries["components"].add(entry.service or 'unknown')
            log_summaries["hosts"].add(entry.host or 'unknown')
            
            # Track time range
            if entry.timestamp and entry.timestamp != datetime.min:
                ts = entry.timestamp
                if not log_summaries["time_range"]["earliest"] or ts < log_summaries["time_range"]["earliest"]:
                    log_summaries["time_range"]["earliest"] = ts
                if not log_summaries["time_range"]["latest"] or ts > log_summaries["time_range"]["latest"]:
                    log_summaries["time_range"]["latest"] = ts
            
            # Create formatted log object (backward compatible with downstream code)
            formatted_log = {
                "timestamp": entry.timestamp.isoformat() if entry.timestamp != datetime.min else '',
                "level": level,
                "message": entry.message,
                "host": entry.host or 'unknown',
                "component": entry.service or 'unknown',
            }
            all_logs.append(formatted_log)

        # PII redaction — scrub passwords, API keys, emails, etc. from log
        # messages BEFORE they are persisted on the batch or sent to AI providers.
        all_logs, redaction_summary = _redact_log_messages(all_logs)
        if redaction_summary['total_count'] > 0:
            logger.info(
                f"Redacted {redaction_summary['total_count']} sensitive items "
                f"from batch {batch.batch_id} logs before AI analysis"
            )

        # Severity pre-filter for the AI prompt. INFO/DEBUG lines rarely
        # help root-cause analysis but they consume tokens (and can push
        # ERROR patterns off the end of the 100-signature aggregation
        # cap). Filter on a *local copy* — batch.data['logs'] is
        # untouched so audit/debug views still see everything. Prior
        # code did this destructively in preprocess_logs(), which is
        # now removed (see commit note).
        logs_raw_count = len(all_logs)
        logs_for_ai = _filter_logs_for_ai(all_logs)
        logs_after_filter = len(logs_for_ai)
        if logs_after_filter < logs_raw_count:
            logger.info(
                f"Severity filter dropped {logs_raw_count - logs_after_filter} of "
                f"{logs_raw_count} logs from batch {batch.batch_id} AI prompt "
                f"(kept {logs_after_filter} at ERROR/WARNING/CRITICAL/FATAL)"
            )

        # Convert sets to lists for JSON serialization
        log_summaries["components"] = list(log_summaries["components"])
        log_summaries["hosts"] = list(log_summaries["hosts"])
        
        # Format time range as strings
        if log_summaries["time_range"]["earliest"]:
            log_summaries["time_range"]["earliest"] = log_summaries["time_range"]["earliest"].isoformat()
        if log_summaries["time_range"]["latest"]:
            log_summaries["time_range"]["latest"] = log_summaries["time_range"]["latest"].isoformat()
        
        # Format metrics for analysis with more context
        memory_usage = metrics.get('memory_usage_percent', [])
        memory_total = metrics.get('memory_total', [])
        memory_available = metrics.get('memory_available', [])
        cpu_usage = metrics.get('cpu_usage_percent', [])
        
        # Sort metrics by timestamp for trend analysis
        memory_usage.sort(key=lambda x: x['time'])
        if cpu_usage:
            cpu_usage.sort(key=lambda x: x['time'])
        
        # Create enhanced system metrics object
        system_metrics = {
            'memory_usage_percent': memory_usage,
            'cpu_usage_percent': cpu_usage,
            'memory_context': {
                'total_memory_bytes': [m for m in memory_total if 'value' in m],
                'available_memory_bytes': [m for m in memory_available if 'value' in m],
                'memory_summary': {
                    'last_total_memory_gb': round(memory_total[0]['value'] / 1_073_741_824, 2) if memory_total else None,
                    'last_available_memory_gb': round(memory_available[0]['value'] / 1_073_741_824, 2) if memory_available else None,
                    'average_usage_percent': round(sum(m['value'] for m in memory_usage) / len(memory_usage), 2) if memory_usage else None,
                    'peak_usage_percent': max([m['value'] for m in memory_usage], default=None)
                }
            }
        }
        
        # Check if we have metrics to analyze
        has_metrics = bool(memory_usage) or bool(cpu_usage)
        
        # Create structured data for AI analysis. Note: use the
        # severity-filtered logs (``logs_for_ai``), not all_logs.
        # batch.data still holds the full log set — only the AI
        # prompt is trimmed.
        analysis_data = {
            'logs': logs_for_ai,
            'log_summary': log_summaries,
            'system_metrics': system_metrics
        }
        
        # Prepare batch data for prompt
        batch_data = {
            'batch_id': batch.batch_id,
            'timestamp': batch.timestamp.isoformat(),
            'environment': batch.environment or 'production',
        }
        
        # Prepare log list and truncate if too many to avoid quota/token limits
        log_strings = [f"[{log.get('timestamp', '')}] [{log.get('level', '')}] [{log.get('component', '')}] {log.get('message', '')}" for log in analysis_data['logs']]
        
        # Limit to 100 logs if there are too many, prioritizing the EARLIEST and LATEST to catch start and end of issues
        # Intelligent Truncation: Prioritize ERROR/WARNING/CRITICAL logs
        # Lowered threshold to activate smart grouping more frequently
        if len(analysis_data['logs']) > 20:  # Changed from 100 to 20
            logger.info(f"Batch {batch_id} has {len(analysis_data['logs'])} logs. intelligently truncating to 100.")
            
            # SMART AGGREGATION LOGIC
            # Problem: 1000 errors -> 100 lines = 90% data loss.
            # Solution: Group identical/similar errors. "Error X happened 900 times".
            
            # 1. Group by "Signature" (Level + Component + normalized-message-prefix)
            grouped_logs = {}
            for log in analysis_data['logs']:
                lvl = log.get('level', '').upper()
                comp = log.get('component', 'unknown')
                msg = log.get('message', '')

                # Normalise volatile fragments (ports, UUIDs, timestamps,
                # IPs, quoted strings, numeric literals) BEFORE slicing
                # so semantically-identical errors collapse to one
                # signature. Prior version hashed raw first-60-chars —
                # ``Connection refused to redis:6379`` and ``redis:6380``
                # each burned a slot. Now both share
                # ``Connection refused to redis:{N}``.
                normalized_msg = _normalize_for_signature(msg)
                signature = f"{lvl}|{comp}|{normalized_msg[:60]}"
                
                if signature not in grouped_logs:
                    grouped_logs[signature] = {
                        'count': 0,
                        'first_seen': log.get('timestamp'),
                        'last_seen': log.get('timestamp'),
                        'sample_log': log,
                        'level': lvl
                    }
                
                group = grouped_logs[signature]
                group['count'] += 1
                # Update timestamps (assuming ISO format sorting matches string sorting roughly)
                if log.get('timestamp', '') > group['last_seen']:
                    group['last_seen'] = log.get('timestamp')
                if log.get('timestamp', '') < group['first_seen']:
                    group['first_seen'] = log.get('timestamp')

            # 2. Prioritize Signals
            # We want to show ALL unique signatures if possible.
            unique_signatures = list(grouped_logs.values())
            
            # Sort by priority: Error/Critical first, then by frequency
            def priority_score(item):
                score = 0
                if item['level'] in ['ERROR', 'CRITICAL', 'FATAL', 'EXCEPTION']:
                    score += 10000
                elif item['level'] == 'WARNING':
                    score += 5000
                score += item['count'] # Tie-breaker: frequency
                return score

            unique_signatures.sort(key=priority_score, reverse=True)

            logs_unique_patterns = len(unique_signatures)

            # 3. Construct the 100-line context
            log_strings = []
            log_strings.append(f"... [System: Log Aggregation Active. Processed {len(analysis_data['logs'])} raw logs into {logs_unique_patterns} unique patterns.] ...")

            slots_used = 1 # Header

            for group in unique_signatures:
                if slots_used >= 100:
                    break

                log = group['sample_log']
                base_msg = f"[{log.get('timestamp', '')}] [{log.get('level', '')}] [{log.get('component', '')}] {log.get('message', '')}"

                if group['count'] > 1:
                    # Append aggregation info
                    agg_msg = f"{base_msg} ... [Repeated {group['count']} times between {group['first_seen']} and {group['last_seen']}]"
                    log_strings.append(agg_msg)
                else:
                    log_strings.append(base_msg)

                slots_used += 1

            # If we fit all groups and still have space, maybe show a few more distinct raw samples for the top error?
            # (Optional optimization, skipping for now to keep it clean)
        else:
            # No truncation needed — each surviving log is one "pattern"
            # from the aggregation-stats standpoint, even though we
            # didn't run the grouping algorithm.
            log_strings = [f"[{log.get('timestamp', '')}] [{log.get('level', '')}] [{log.get('component', '')}] {log.get('message', '')}" for log in analysis_data['logs']]
            logs_unique_patterns = len(analysis_data['logs'])

        # Persist the aggregation stats on the batch — powers the
        # future "AI Cost Efficiency" dashboard cards and gives users
        # per-batch visibility into what the AI actually saw.
        # ``logs_raw_count`` + ``logs_after_filter`` were captured
        # earlier (right after redaction). ``logs_sent_to_ai`` counts
        # only the informational content, excluding the aggregation
        # header line the AI receives when Smart Aggregation ran.
        logs_sent_to_ai = max(len(log_strings) - (1 if len(analysis_data['logs']) > 20 else 0), 0)
        try:
            AIAnalyzedBatch.objects.filter(pk=batch.pk).update(
                logs_raw_count=logs_raw_count,
                logs_after_severity_filter=logs_after_filter,
                logs_unique_patterns=logs_unique_patterns,
                logs_sent_to_ai=logs_sent_to_ai,
            )
        except Exception as e:
            # Stat persistence must not block AI analysis — cost
            # visibility is best-effort observability.
            logger.warning(f"Could not persist aggregation stats for batch {batch_id}: {e}")

        # === DEPLOYMENT-AWARE COMMIT RETRIEVAL (Adaptive Window) ===
        # Replaces naive batch.data.get('code_changes')
        try:
            from providers.models import Deployment, CodeChange
            from datetime import timedelta
            
            project = batch.project
            environment = batch.environment or 'production'
            
            if project:
                # 1. Determine Batch Interval
                # Find previous batch to define the start of this window
                prev_batch = AIAnalyzedBatch.objects.filter(
                    project=project,
                    timestamp__lt=batch.timestamp
                ).order_by('-timestamp').first()
                
                # Default to configured batch interval if no previous batch found
                from Data.batch_config import get_batch_interval_for_org
                batch_interval_minutes = get_batch_interval_for_org(
                    batch.organisation or (batch.project.organisation if batch.project else None)
                )
                interval_start = batch.timestamp - timedelta(minutes=batch_interval_minutes)
                
                if prev_batch:
                    interval_start = prev_batch.timestamp
                    
                logger.info(f"Batch {batch_id}: Analyzing window from {interval_start} to {batch.timestamp}")
                
                # 2. Find deployments relevant to this window
                # (a) Deployments occurring WITHIN the window (e.g. deployed in the last hour)
                window_deployments = list(Deployment.objects.filter(
                    pipeline__project__organisation__projects=project,
                    environment=environment,
                    status='success',
                    deployed_at__gt=interval_start,
                    deployed_at__lte=batch.timestamp
                ).select_related('code_change', 'pipeline'))
                
                # (b) Deployment active AT THE START of the window (the baseline code running at t=0)
                base_deploy = Deployment.objects.filter(
                    pipeline__project__organisation__projects=project,
                    environment=environment,
                    status='success',
                    deployed_at__lte=interval_start
                ).select_related('code_change', 'pipeline').order_by('-deployed_at').first()
                
                if base_deploy:
                    # Avoid duplicates if base_deploy happens to be in window_deployments (unlikely due to query split but safe)
                    if base_deploy not in window_deployments:
                        window_deployments.append(base_deploy)
                
                logger.info(f"Batch {batch_id}: Found {len(window_deployments)} relevant deployments")
                
                # 3. Collect Commits from ALL relevant deployments
                relevant_commit_shas = set()
                
                for deploy in window_deployments:
                    # Find what came before THIS deployment to define ITS commit range
                    prev_to_deploy = Deployment.objects.filter(
                        pipeline__project__organisation__projects=project,
                        environment=environment,
                        status='success',
                        deployed_at__lt=deploy.deployed_at
                    ).order_by('-deployed_at').first()
                    
                    # If this is the first deployment ever, look back 7 days
                    start_hash_time = prev_to_deploy.code_change.timestamp if prev_to_deploy else (deploy.code_change.timestamp - timedelta(days=7))
                    
                    # Fetch commits that landed in this deployment
                    # Logic: Commits OLDER than this deploy key commit provided they are NEWER than the previous deploy
                    deploy_commits = CodeChange.objects.filter(
                        organisation=project.organisation, # Optimization: Filter by org
                        timestamp__gt=start_hash_time,
                        timestamp__lte=deploy.code_change.timestamp
                    ).values_list('commit_sha', flat=True)
                    
                    relevant_commit_shas.update(deploy_commits)
                
                # 4. Fetch full commit objects
                if relevant_commit_shas:
                    commits_qs = CodeChange.objects.filter(
                        commit_sha__in=list(relevant_commit_shas)
                    ).order_by('-timestamp')[:50] # Limit to 50 most recent relevant commits

                    code_changes = [c.get_summary_for_ai() for c in commits_qs]
                    logger.info(f"Batch {batch_id}: Retrieved {len(code_changes)} commits from {len(window_deployments)} deployments")

                    # Update batch data to persist this intel
                    if batch.data is None: batch.data = {}
                    batch.data['code_changes'] = code_changes
                    batch.save(update_fields=['data'])
                else:
                    # Q1.1-audit finding: fall back to whatever the batch
                    # already has staged in ``batch.data`` before we
                    # decide there's nothing to correlate. Alert-triggered
                    # batches, backfills, migrations, and manually-created
                    # batches populate ``batch.data['code_changes']``
                    # directly without ever running the SCM webhook →
                    # CodeChange row → CICD webhook → Deployment row
                    # chain that this Deployment-derivation path expects.
                    # Without this fallback those batches silently lose
                    # every code correlation even though the RCA prompt
                    # still says "code is available".
                    staged = batch.data.get('code_changes') if isinstance(batch.data, dict) else None
                    if staged:
                        code_changes = staged
                        logger.info(
                            f"Batch {batch_id}: no Deployment chain in window; "
                            f"falling back to {len(staged)} staged code_changes on batch.data"
                        )
                    else:
                        code_changes = []
                        logger.info(f"Batch {batch_id}: No commits found in relevant window")

            else:
                 # Fallback for legacy batches without project link
                 code_changes = batch.data.get('code_changes', [])

        except Exception as e:
            logger.error(f"Error fetching deployment-aware commits for {batch_id}: {e}")
            code_changes = batch.data.get('code_changes', [])

        # Build comprehensive correlations AFTER deployment-aware commits are retrieved
        # so the engine has the freshest code_changes data
        correlations_data = {}
        try:
            from Data.correlation_engine import build_comprehensive_correlations

            # Trace summary is on the batch snapshot (see #10.5).
            batch_traces_summary = (
                batch.data.get('traces') if isinstance(batch.data, dict) else None
            )

            # Q5-3: pull owner-declared service→path globs from the
            # project's ProjectService rows. Fast + safe: skips the
            # DB round-trip when there's no trace context to correlate
            # against.
            service_paths_by_name = None
            if batch_traces_summary and getattr(batch, 'project_id', None):
                try:
                    from Projects.models import ProjectService
                    _rows = ProjectService.objects.filter(
                        project_id=batch.project_id,
                    ).values('name', 'provider_config')
                    _svc_map = {}
                    for row in _rows:
                        _name = (row.get('name') or '').strip()
                        _cfg = row.get('provider_config') or {}
                        _globs = _cfg.get('service_paths') if isinstance(_cfg, dict) else None
                        if _name and isinstance(_globs, list) and _globs:
                            _svc_map[_name] = _globs
                    if _svc_map:
                        service_paths_by_name = _svc_map
                except Exception as _sp_exc:
                    logger.warning(
                        'service_paths lookup failed for batch %s: %s',
                        batch.batch_id, _sp_exc,
                    )

            if all_logs or metrics_summary or code_changes or batch_traces_summary:
                correlations_data = build_comprehensive_correlations(
                    logs=all_logs,
                    metrics_summary=metrics_summary,
                    code_changes=code_changes,
                    cicd_logs=cicd_logs,
                    traces_summary=batch_traces_summary,
                    service_paths_by_name=service_paths_by_name,
                )
                logger.info(f"Correlations built: {correlations_data.get('summary', {}).get('total_correlations', 0)} total")

                # Persist engine output on batch for downstream consumers
                if batch.data is None:
                    batch.data = {}
                batch.data['correlation_results'] = correlations_data
                batch.save(update_fields=['data'])
        except Exception as e:
            logger.warning(f"Failed to build correlations: {e}")
            correlations_data = {}

        # Get CI/CD logs with preprocessed trace errors for AI
        cicd_logs = batch.data.get('cicd_logs', [])
        # Build CI/CD output list using trace_errors (preprocessed) for token efficiency
        cicd_outputs = []
        succeeded_count = 0
        total_duration = 0
        duration_count = 0
        for cicd in cicd_logs:
            if cicd.get('status') == 'failed':
                output = f"[CI/CD] Job '{cicd.get('job_name', 'unknown')}' FAILED on branch '{cicd.get('branch', 'unknown')}' (Pipeline #{cicd.get('pipeline_id', 'N/A')})"
                if cicd.get('trace_errors'):
                    output += f"\n  Errors:\n{cicd['trace_errors']}"
                cicd_outputs.append(output)
            elif cicd.get('status') in ('success', 'passed'):
                succeeded_count += 1
                dur = cicd.get('duration')
                if dur is not None:
                    total_duration += dur
                    duration_count += 1

        # Build CI/CD summary for deployment context
        cicd_summary = None
        if cicd_logs:
            cicd_summary = {
                'total': len(cicd_logs),
                'succeeded': succeeded_count,
                'avg_duration_seconds': (total_duration / duration_count) if duration_count else None,
            }

        # Build sentinel context from batch metadata
        sentinel_context = None
        if batch.sentinel_decision:
            sentinel_context = {
                'decision': batch.sentinel_decision,
                'triggers': batch.sentinel_triggers or [],
            }

        # Generate analysis prompt with enhanced data
        # Use metrics_summary for token efficiency, fallback to raw system_metrics
        project_context = _build_project_context(batch)
        past_memories_text, past_memory_ids = _build_past_memories(batch)
        # Track which resolved issues fed this analysis so the frontend
        # can surface an "Informed by past resolutions" panel.
        if past_memory_ids:
            batch.referenced_resolution_ids = past_memory_ids
            batch.save(update_fields=['referenced_resolution_ids'])

        # Distributed-trace enrichment (native OTLP store first, then any
        # configured Jaeger/Zipkin/DD APM adapter). Wrapped so trace
        # failures never break RCA — this is an enrichment, not a hard
        # dependency.
        try:
            from .trace_context import build_trace_context
            traces_summary = build_trace_context(batch)
        except Exception as _trace_exc:
            logger.warning('Trace context build failed: %s', _trace_exc)
            traces_summary = None

        # Enabled data-source capabilities for this project. Prefer the
        # batch snapshot (batch.data['project_capabilities']) so that
        # reanalysis of an old batch reasons over the coverage that
        # existed *when the batch was created* — not whatever is
        # configured now.
        enabled_capabilities = batch.data.get('project_capabilities') if isinstance(batch.data, dict) else None
        if enabled_capabilities is None:
            try:
                from Organisations.capability_registry import enabled_capabilities_for
                enabled_capabilities = sorted(enabled_capabilities_for(batch.project))
            except Exception as _cap_exc:
                logger.warning('Capability lookup failed: %s', _cap_exc)
                enabled_capabilities = None

        # Build the prompt as (static_system, dynamic_user) so cache-
        # aware adapters can route the static half through provider
        # caching (Claude cache_control, OpenAI/DeepSeek auto-cache on
        # stable system messages ≥1024 tokens). See prompts.py.
        from .prompt_context import DataSourceContext
        from .prompts import get_batch_analysis_prompt_parts
        context = DataSourceContext(
            batch_data=batch_data,
            logs=log_strings,
            system_metrics=analysis_data['system_metrics'],
            metrics_summary=metrics_summary,
            code_changes=code_changes,
            ci_cd_outputs=cicd_outputs if cicd_outputs else None,
            correlations=correlations_data,
            project_context=project_context,
            sentinel_context=sentinel_context,
            operator_context=batch.data.get('operator_context') if isinstance(batch.data, dict) else None,
            cicd_summary=cicd_summary,
            past_memories=past_memories_text,
            traces_summary=traces_summary,
            enabled_capabilities=enabled_capabilities,
        )
        system_prompt, analysis_prompt = get_batch_analysis_prompt_parts(context)

        # Get AI analysis with org-specific settings or fallback
        # Try to get organisation from batch data
        organisation = None
        try:
            if hasattr(batch, 'project') and batch.project:
                organisation = batch.project.organisation
            elif 'organisation_id' in batch.data:
                from Organisations.models import Organisations
                organisation = Organisations.objects.filter(
                    id=batch.data['organisation_id']
                ).first()
        except Exception as e:
            logger.warning(f"Could not determine organisation for batch {batch_id}: {e}")

        # === AI COST TRACKING: prepare token counters (no quota enforcement) ===
        tokens_input = 0
        tokens_output = 0

        # Use org-specific generation if we have an org, otherwise fallback
        if organisation:
            from ai_model.exceptions import NoAIProviderConfigured
            from ai_model.budget import BudgetExceeded
            try:
                analysis_result, model_name, api_error, tokens_input, tokens_output = generate_for_organisation(
                    analysis_prompt,
                    organisation,
                    system_prefix=system_prompt,
                )
                model_name = model_name or "unknown"
            except NoAIProviderConfigured as e:
                # Distinct from an API failure: the org never picked a
                # provider. Surface a batch-level error the wizard's
                # "waiting for first analysis" state can key off of
                # (analysis_error='ai_not_configured') rather than a
                # generic AUTH_MISSING that reads as "your key is bad".
                logger.warning(f"Batch {batch_id}: {e}")
                analysis_result = None
                model_name = "unconfigured"
                api_error = AIServiceError(
                    'auth_error', 'AI_NOT_CONFIGURED',
                    'No AI provider is configured for this organisation.',
                    'Open Settings → AI to pick a provider and add an API key.',
                )
                tokens_input = 0
                tokens_output = 0
            except BudgetExceeded as e:
                # Q3.3 — org hit its monthly AI cost cap. Rule-based
                # issue creation (Sentinel, correlation engine) still
                # runs from earlier in this pipeline — users don't
                # lose incident detection, just the AI RCA polish.
                # Marking with a distinct error code so the UI can
                # show "AI paused: monthly budget reached" instead
                # of a generic AUTH_ERROR.
                logger.warning(f"Batch {batch_id}: {e}")
                analysis_result = None
                model_name = "budget_exceeded"
                api_error = AIServiceError(
                    'quota_exceeded', 'AI_BUDGET_EXCEEDED',
                    f'Monthly AI spend cap reached (${e.current:.2f} of '
                    f'${e.budget:.2f}). AI analysis paused until next month.',
                    'Raise Settings → AI → Monthly budget or wait for '
                    'the calendar month to reset.',
                )
                tokens_input = 0
                tokens_output = 0
        else:
            # Legacy fallback without token tracking
            analysis_result, api_error = generate_with_fallback(
                analysis_prompt, system_prefix=system_prompt,
            )
            model_name = "gemini"  # Default when no org
            tokens_input = 0
            tokens_output = 0

        # === SALVAGE A TRUNCATED RESPONSE ===
        # A response that hits the output ceiling was previously discarded in
        # full: the batch got zero issues and an empty narrative, and the
        # tokens were billed anyway. But a cut-off analysis is mostly a
        # complete analysis — the model writes the root cause first and runs
        # out of room somewhere in the issue list — and the parser below
        # already closes unbalanced braces for exactly this shape of input.
        # Observed on the chaos suite: a five-issue diagnosis stopped at ~7997
        # output tokens and was thrown away whole.
        #
        # ``analysis_truncated`` is set so the batch and the UI can say the
        # analysis is partial rather than present it as complete, and so the
        # parser knows to drop the element the model was mid-way through. A
        # body that cannot be repaired at all still ends up recorded as a parse
        # failure with the raw text attached, which is what the operator needs
        # to see either way.
        analysis_truncated = False
        if (analysis_result is None and api_error is not None
                and getattr(api_error, 'code', None) == 'TRUNCATED'):
            partial = getattr(api_error, 'partial_text', None)
            if partial and partial.strip():
                logger.warning(
                    f"Batch {batch_id}: response truncated at {tokens_output} output "
                    f"tokens — attempting to salvage the partial analysis."
                )
                analysis_result = partial
                analysis_truncated = True

        # === AI COST TRACKING: Log usage after successful AI call ===
        # (The failure branch below logs usage for calls that produced no
        # usable text, so every billed call is accounted for exactly once.)
        if analysis_result and organisation and (tokens_input > 0 or tokens_output > 0):
            from ai_model.usage_tracking import AITokenUsageService

            try:
                usage = AITokenUsageService.log_usage(
                    organisation=organisation,
                    batch=batch,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    model_name=model_name,
                    usage_type=('manual_analysis' if batch.trigger == AIAnalyzedBatch.TRIGGER_MANUAL
                                else 'batch_analysis')
                )
                if usage:
                    logger.info(
                        f"Logged AI usage for batch {batch_id}: "
                        f"{usage.tokens_total} tokens, ${usage.cost_usd:.6f} ({model_name})"
                    )
            except Exception as e:
                logger.error(f"Failed to log AI usage for batch {batch_id}: {e}")
                # Don't fail the batch on usage logging error

        if analysis_result:
            try:
                # Remove Markdown-style ```json ... ``` wrappers
                cleaned_result = re.sub(r"^```(?:json)?\n|\n```$", "", analysis_result.strip())

                # Parse the response. ``repair_json`` handles both the
                # formatting slips models make and bodies cut short by the
                # output-token ceiling — its balancing closes structures
                # innermost-first, which the counting version that used to
                # live here could not do (it emitted "}]" for a body opened
                # as '{"correlated_issues": [', which parses as nothing).
                from ai_model.response_repair import repair_json

                parsed_result = None
                try:
                    parsed_result = json.loads(cleaned_result)
                except json.JSONDecodeError as e:
                    logger.warning(f"Batch {batch_id}: JSON parse failed ({e}), attempting repair")
                    parsed_result = repair_json(cleaned_result)
                    if parsed_result is not None:
                        logger.info(f"Batch {batch_id}: JSON repair successful")
                    else:
                        # AI sometimes returns Python dict syntax (single quotes).
                        import ast
                        logger.warning(f"Batch {batch_id}: JSON repair failed, trying ast.literal_eval")
                        try:
                            parsed_result = ast.literal_eval(cleaned_result)
                        except (ValueError, SyntaxError) as ast_error:
                            logger.error(f"Batch {batch_id}: All parsing failed. Error: {ast_error}")
                            parsed_result = {
                                "correlated_issues": [],
                                "ai_parsing_error": str(ast_error),
                                "raw_response_preview": cleaned_result[:500]
                            }
                if not isinstance(parsed_result, dict):
                    parsed_result = {
                        "correlated_issues": [],
                        "ai_parsing_error": "response was not a JSON object",
                        "raw_response_preview": cleaned_result[:500],
                    }

                # A salvaged analysis is labelled as one. The issues it did
                # produce are real and worth keeping, but the list is known to
                # be cut short, so it must never read as a complete diagnosis
                # — "no other issues found" and "one issue, truncated" are
                # very different answers for whoever is on call.
                if analysis_truncated and isinstance(parsed_result, dict):
                    dropped = _drop_hollow_issues(parsed_result)
                    parsed_result['analysis_truncated'] = True
                    parsed_result['truncation_note'] = (
                        'The model hit its output token limit. The issues below '
                        'are the part of the analysis that completed; there may '
                        'be more. Re-analyse with a higher max_tokens for the '
                        'full picture.'
                    )
                    salvaged = len(parsed_result.get('correlated_issues', []) or [])
                    logger.warning(
                        f"Batch {batch_id}: salvaged {salvaged} issue(s) from a "
                        f"truncated response (dropped {dropped} incomplete)."
                    )
                    model_name = f"{model_name} (truncated)"

                # Save structured analysis with model name
                batch.save_analysis(parsed_result, model_name=model_name)

                # Mark batch as analyzed (issue_count set after dedup below)
                batch.analyzed_at = timezone.now()
                batch.save(update_fields=['analyzed_at'])

                # --- Issue Deduplication v2: Use issue_type + scope + component fingerprints ---
                try:
                    from Data.models import Issue
                    
                    # Get environment from batch
                    environment = batch.environment or 'production'
                    
                    # Track fingerprints within this batch to avoid intra-batch duplicates
                    seen_fingerprints = set()
                    issues_created = 0
                    issues_updated = 0
                    
                    # Valid issue types from enum
                    valid_issue_types = [t[0] for t in Issue.ISSUE_TYPES]
                    valid_scopes = [s[0] for s in Issue.SCOPE_CHOICES]
                    
                    for issue_data in parsed_result.get('correlated_issues', []):
                        if not isinstance(issue_data, dict):
                            continue
                        
                        # Extract and validate fields
                        issue_type = issue_data.get('issue_type', 'OTHER').upper()
                        if issue_type not in valid_issue_types:
                            issue_type = 'OTHER'
                        
                        scope = issue_data.get('scope', 'SERVICE').upper()
                        if scope not in valid_scopes:
                            scope = 'SERVICE'
                        
                        # Get component from AI response
                        component = issue_data.get('component', '')
                        if not component and scope == 'INFRASTRUCTURE':
                            component = 'INFRASTRUCTURE'
                        
                        severity = issue_data.get('severity', 'UNKNOWN').upper()
                        if severity not in dict(Issue.SEVERITY_CHOICES):
                            severity = 'UNKNOWN'
                        
                        # Handle root_cause - could be string or dict from AI
                        root_cause = issue_data.get('root_cause', '')
                        if isinstance(root_cause, dict):
                            root_cause = root_cause.get('description', '')
                        
                        # Add required fields to issue_data for find_or_create_deduplicated
                        issue_data['issue_type'] = issue_type
                        issue_data['scope'] = scope
                        issue_data['component'] = component
                        issue_data['severity'] = severity
                        issue_data['root_cause'] = root_cause
                        
                        # Generate fingerprint for intra-batch dedup check (C3: include error_class/error_target)
                        project_name = batch.project.name if batch.project else ''
                        error_class = Issue.validate_error_class(issue_data.get('error_class', 'OTHER'))
                        error_target = Issue.normalize_error_target(issue_data.get('error_target', ''))
                        fingerprint = Issue.generate_fingerprint(
                            issue_type, scope, project_name, component, environment,
                            error_class=error_class, error_target=error_target
                        )
                        
                        # Skip if already processed in this batch
                        if fingerprint in seen_fingerprints:
                            logger.debug(f"Skipping intra-batch duplicate: {issue_type}/{component}")
                            continue
                        seen_fingerprints.add(fingerprint)
                        
                        # Use tiered matching for deduplication
                        issue, created = Issue.find_or_create_deduplicated(
                            issue_data, batch, batch.project, environment
                        )
                        
                        if created:
                            issues_created += 1
                        else:
                            issues_updated += 1
                    
                    # Populate engine-driven correlation fields on all batch issues
                    if correlations_data:
                        try:
                            batch_issues = Issue.objects.filter(occurrences__batch=batch).distinct()
                            for iss in batch_issues:
                                _populate_issue_correlations(iss, correlations_data, metrics_summary)
                                iss.save(update_fields=[
                                    'has_metric_correlation', 'metric_correlation_type',
                                    'metric_anomaly_type', 'has_commit_correlation',
                                    'linked_commits', 'correlation_confidence',
                                    'correlation_details', 'has_cicd_correlation',
                                ])
                            logger.info(f"Batch {batch_id}: Engine-driven correlations populated on {batch_issues.count()} issues")
                        except Exception as e:
                            logger.warning(f"Failed to populate engine correlations for batch {batch_id}: {e}")

                    # FIX: Update issue_count to reflect actual issues in DB (handling duplicates + previous orphaned issues)
                    try:
                        actual_issue_count = Issue.objects.filter(occurrences__batch=batch).distinct().count()
                        logger.info(f"Batch {batch_id}: Database issue count: {actual_issue_count} (Created: {issues_created}, Updated: {issues_updated})")
                        batch.issue_count = actual_issue_count
                        batch.save(update_fields=['issue_count'])
                        issue_count = actual_issue_count # Update local context
                    except Exception as e:
                        logger.error(f"Error syncing batch issue count: {e}")

                    logger.info(f"Issues for batch {batch_id}: {issues_created} new, {issues_updated} deduplicated")
                except Exception as e:
                    logger.error(f"Error saving issues for batch {batch_id}: {str(e)}", exc_info=True)
                    # Sync issue_count from actual DB records (some may have been created before the error)
                    actual_count = Issue.objects.filter(occurrences__batch=batch).distinct().count()
                    batch.issue_count = actual_count
                    batch.save(update_fields=['issue_count'])
                # -----------------------------------------------

                # Log what was analyzed
                if all_logs and has_metrics:
                    analyzed_msg = f"logs and metrics"
                elif all_logs:
                    analyzed_msg = f"only logs"
                else:
                    analyzed_msg = f"only metrics"

                logger.info(f"Successfully analyzed batch {batch_id} with {issue_count} issues using model {model_name} (analyzed {analyzed_msg})")

                # === SENTINEL: Record successful AI analysis ===
                # Not for investigations: they must not reset the counter that
                # forces a periodic analysis of quiet environments.
                try:
                    if batch.project and batch.environment and batch.trigger != AIAnalyzedBatch.TRIGGER_MANUAL:
                        from Data.sentinel import record_ai_analysis
                        from Projects.models import ProjectEnvironment
                        env_obj = ProjectEnvironment.objects.filter(
                            project=batch.project,
                            name__iexact=batch.environment
                        ).first()
                        if env_obj:
                            record_ai_analysis(batch.project, env_obj)
                except Exception as e:
                    logger.warning(f"Failed to record AI analysis for sentinel: {e}")
                # === END SENTINEL ===

                # Investigations page nobody unless the requester opted in;
                # the requester always hears back in the app.
                investigation = batch.investigation if batch.trigger == AIAnalyzedBatch.TRIGGER_MANUAL else None
                route = investigation is None or investigation.notify_routing
                if investigation is not None:
                    _notify_investigation_requester(investigation, batch, issue_count)

                # === DISPATCH NOTIFICATIONS VIA NEW SYSTEM ===
                # Uses NotificationDispatcher with:
                # - Project subscriptions (explicit opt-in)
                # - User preferences (channels, severity, digest, quiet hours)
                # - Suppression checks (muting, duplicates)
                # - Escalation triggers
                try:
                    from notifications.dispatcher import dispatch_for_batch_issues
                    from Data.models import Issue
                    
                    # Get the actual Issue objects that were created/updated for this batch
                    batch_issues = Issue.objects.filter(occurrences__batch=batch).distinct()
                    
                    if route and batch_issues.exists():
                        dispatch_results = dispatch_for_batch_issues(batch, list(batch_issues))
                        logger.info(f"Notification dispatch complete for batch {batch_id}: {len(dispatch_results)} notifications processed")
                    else:
                        logger.debug(f"No issues to notify for batch {batch_id}")
                        
                except Exception as e:
                    logger.error(f"Error dispatching notifications for batch {batch_id}: {e}", exc_info=True)
                # === END NOTIFICATION DISPATCH ===

                # Outbound incident notifications — Slack / Teams /
                # PagerDuty / OpsGenie / email (Items #22 + #23). Runs after
                # in-app dispatch, wrapped so a broken channel never fails
                # RCA. One analysis is one incident: every event that
                # applies goes in one dispatch, so a channel gets one
                # message. Alert-triggered runs used to notify from
                # analyze_alert_ondemand before the AI had run ("INFO,
                # 0 issues"), then again here.
                try:
                    from notifications.incident_dispatcher import dispatch as _incident_dispatch
                    if route:
                        events = ['batch_analyzed']
                        # Only an issue that just became critical pages:
                        # an ongoing one re-reported every batch did so
                        # every 5 minutes.
                        if any(
                            i.is_newly_critical(batch)
                            for i in Issue.objects.filter(occurrences__batch=batch).distinct()
                        ):
                            events.append('critical_issue')
                        alert_event = None
                        if batch.trigger == AIAnalyzedBatch.TRIGGER_ALERT:
                            events.append('alert_triggered')
                            from Data.models import AlertEvent
                            alert_event = AlertEvent.objects.filter(triggered_batch=batch).first()
                        _incident_dispatch(batch, event=events, alert_event=alert_event)
                except Exception as e:
                    logger.warning(f"Incident notification dispatch failed for batch {batch_id}: {e}")

                return f"Analysis completed for batch {batch_id} with {issue_count} issues using model {model_name}"

            except json.JSONDecodeError as json_err:
                logger.error(f"JSON parsing error in save_analysis: {str(json_err)}")

                # Save raw response for inspection — capped so a
                # runaway multi-page dump doesn't bloat the row or the
                # Batch Detail card. Full body is still available in
                # ``batch.data['raw_response']`` when we set it above.
                raw = str(analysis_result or '')[:4000]
                batch.analysis_text = raw or None
                batch.analyzed_at = timezone.now()
                batch.model_name = "FAILED (PARSE ERROR)"
                batch.save(update_fields=['analysis_text', 'analyzed_at', 'model_name'])

                return f"Analysis failed due to JSON error for batch {batch_id}"

        else:
            # API call failed - store error details
            error_status = api_error.get_display_status() if api_error else "FAILED (UNKNOWN)"
            error_message = api_error.get_user_message() if api_error else "Unknown error occurred"

            logger.error(f"Failed to get AI analysis for batch {batch_id}: {error_status} - {error_message}")

            # Log token usage even on failure (truncated responses still consume tokens)
            if organisation and (tokens_input > 0 or tokens_output > 0):
                from ai_model.usage_tracking import AITokenUsageService
                usage = AITokenUsageService.log_usage(
                    organisation=organisation,
                    batch=batch,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    model_name=model_name or "unknown",
                    usage_type=('manual_analysis' if batch.trigger == AIAnalyzedBatch.TRIGGER_MANUAL
                                else 'batch_analysis')
                )
                if usage:
                    logger.info(
                        f"Logged AI usage for failed batch {batch_id}: "
                        f"{usage.tokens_total} tokens, ${usage.cost_usd:.6f} ({error_status})"
                    )

            # Record failure state with error details.
            #
            # RCA gauntlet finding (2026-09-20): prior to this edit,
            # ``analyzed_at`` was NOT set on the API-failure path — only
            # ``model_name`` got the error tag. That left the batch
            # detail card spinning forever (no ``analyzed_at`` → the
            # UI treats it as "AI still running"). Set it here so the
            # frontend can render "AI failed: <error>" cleanly, and so
            # any downstream polling (gauntlet, tests) can exit.
            batch.model_name = error_status
            batch.analyzed_at = timezone.now()
            # Store error details in the data field for the frontend
            if batch.data is None:
                batch.data = {}
            batch.data['error'] = api_error.to_dict() if api_error else {'error_code': 'UNKNOWN', 'error_message': error_message}
            batch.save(update_fields=['model_name', 'analyzed_at', 'data'])
            return f"Analysis failed for batch {batch_id}: {error_message}"

    except AIAnalyzedBatch.DoesNotExist:
        logger.error(f"Batch {batch_id} not found")
        return f"Batch {batch_id} not found"
    except Exception as e:
        logger.error(f"Error analyzing batch {batch_id}: {str(e)}")
        return f"Error analyzing batch {batch_id}: {str(e)}"

@shared_task
def check_pending_analyses():
    """Check for batches that haven't been analyzed and retry them"""
    try:
        # Find batches older than 5 minutes that haven't been analyzed
        cutoff_time = timezone.now() - timezone.timedelta(minutes=5)
        pending_batches = AIAnalyzedBatch.objects.filter(
            analyzed_at__isnull=True, 
            timestamp__lt=cutoff_time
        ).order_by('-timestamp')[:20]  # Limit to 20 most recent
        
        count = 0
        for batch in pending_batches:
            analyze_batch.delay(batch.batch_id)
            count += 1
            
        if count > 0:
            logger.info(f"Queued analysis for {count} pending batches")
        return f"Processed {count} pending batches"
    except Exception as e:
        logger.error(f"Error checking pending analyses: {str(e)}")
        return f"Error checking pending analyses: {str(e)}"


def promote_history_entry_to_primary(batch, analyzed_at_iso):
    """Take an existing ``analysis_history`` entry and make it primary.

    Fast (no AI call) — used by the "Promote to primary" button in
    the Compare view. RCA audit finding #11 (2026-09-20).

    Returns the summary dict from ``_apply_primary_analysis_to_batch``.
    Raises ``ValueError`` if no history entry matches ``analyzed_at_iso``.
    """
    history = batch.analysis_history or []
    target = None
    for entry in history:
        if isinstance(entry, dict) and entry.get('analyzed_at') == analyzed_at_iso:
            target = entry
            break
    if target is None:
        raise ValueError(
            f'No analysis_history entry with analyzed_at={analyzed_at_iso!r} '
            f'on batch {batch.batch_id}'
        )

    for entry in history:
        if isinstance(entry, dict):
            entry['is_primary'] = (entry is target)

    target_result = target.get('analysis_result') or {}
    target_model = target.get('model_name') or batch.model_name
    summary = _apply_primary_analysis_to_batch(batch, target_result, target_model)

    batch.save(update_fields=['analysis_history'])
    return summary


def _apply_primary_analysis_to_batch(batch, parsed_result, model_name):
    """Promote a parsed AI result to the batch's primary analysis.

    Extracted for reuse by ``reanalyze_batch_with_model(mode='primary')``
    and by the promote-from-history view. Mirrors the persistence tail
    of ``analyze_batch``: it calls ``save_analysis`` (which handles the
    narrative extraction fixed in PR-AUDIT6) and runs the same
    fingerprint-based ``Issue.find_or_create_deduplicated`` loop, so
    triage state on existing Issues (acknowledged / resolved / muted)
    survives a re-run: an Issue with a matching fingerprint has its
    ``occurrence_count`` bumped instead of being recreated.

    RCA audit finding #11 (2026-09-20): before this helper existed,
    re-analysis only appended to ``analysis_history`` — the button
    labelled "Re-Analyze" produced no visible change on the Issues
    page. The new ``mode='primary'`` path uses this helper to make the
    verb match the outcome.
    """
    from Data.models import Issue

    # Set the narrative + analyzed_at + model_name directly. We do NOT
    # call ``batch.save_analysis`` here because that would append its
    # own entry to ``analysis_history`` — the caller
    # (``reanalyze_batch_with_model`` in primary mode, or the promote
    # view) owns history writes and passes a richer entry that carries
    # token counts + the ``mode`` flag.
    batch.analysis_text = batch.__class__.extract_narrative(parsed_result)
    batch.analyzed_at = timezone.now()
    if model_name:
        batch.model_name = model_name
    if batch.data is None:
        batch.data = {}
    batch.data['analysis_result'] = parsed_result
    batch.save(update_fields=['analysis_text', 'analyzed_at', 'model_name', 'data'])

    environment = batch.environment or 'production'
    valid_issue_types = [t[0] for t in Issue.ISSUE_TYPES]
    valid_scopes = [s[0] for s in Issue.SCOPE_CHOICES]
    valid_severities = dict(Issue.SEVERITY_CHOICES)
    seen_fingerprints = set()
    issues_created = 0
    issues_updated = 0

    for issue_data in parsed_result.get('correlated_issues', []) or []:
        if not isinstance(issue_data, dict):
            continue

        issue_type = str(issue_data.get('issue_type', 'OTHER')).upper()
        if issue_type not in valid_issue_types:
            issue_type = 'OTHER'
        scope = str(issue_data.get('scope', 'SERVICE')).upper()
        if scope not in valid_scopes:
            scope = 'SERVICE'
        component = issue_data.get('component', '')
        if not component and scope == 'INFRASTRUCTURE':
            component = 'INFRASTRUCTURE'
        severity = str(issue_data.get('severity', 'UNKNOWN')).upper()
        if severity not in valid_severities:
            severity = 'UNKNOWN'
        root_cause = issue_data.get('root_cause', '')
        if isinstance(root_cause, dict):
            root_cause = root_cause.get('description', '')

        issue_data['issue_type'] = issue_type
        issue_data['scope'] = scope
        issue_data['component'] = component
        issue_data['severity'] = severity
        issue_data['root_cause'] = root_cause

        project_name = batch.project.name if batch.project else ''
        error_class = Issue.validate_error_class(issue_data.get('error_class', 'OTHER'))
        error_target = Issue.normalize_error_target(issue_data.get('error_target', ''))
        fingerprint = Issue.generate_fingerprint(
            issue_type, scope, project_name, component, environment,
            error_class=error_class, error_target=error_target,
        )
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)

        _issue, created = Issue.find_or_create_deduplicated(
            issue_data, batch, batch.project, environment,
        )
        if created:
            issues_created += 1
        else:
            issues_updated += 1

    actual_issue_count = Issue.objects.filter(occurrences__batch=batch).distinct().count()
    batch.issue_count = actual_issue_count
    batch.save(update_fields=['issue_count'])
    return {
        'issues_created': issues_created,
        'issues_updated': issues_updated,
        'issue_count': actual_issue_count,
    }


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def reanalyze_batch_with_model(self, batch_id, model_name, mode='compare'):
    """
    Re-analyze a batch with a specific AI model.

    Two modes (RCA audit finding #11, 2026-09-20):

    * ``mode='compare'`` (default, back-compat): appends the new result
      to ``analysis_history`` with ``is_primary=False``. The primary
      analysis and its Issues are untouched. Feeds the Compare view.
    * ``mode='primary'``: additionally promotes the result to the
      primary analysis via ``_apply_primary_analysis_to_batch``, which
      updates ``analysis_text`` and runs the Issue fingerprint-dedup
      flow so triage state on existing Issues survives.

    Args:
        batch_id: The batch to re-analyze
        model_name: Any active AI provider name (e.g. 'gemini', 'claude')
        mode: 'compare' or 'primary'
    """
    import re
    from .prompts import get_batch_analysis_prompt
    
    try:
        batch = AIAnalyzedBatch.objects.get(batch_id=batch_id)
        logger.info(f"Starting re-analysis for batch {batch_id} with model {model_name}")
        
        # Get logs from batch
        logs = batch.data.get('logs', [])
        metrics_summary = batch.data.get('metrics_summary', {})
        # === DEPLOYMENT-AWARE COMMIT RETRIEVAL (Adaptive Window) ===
        try:
            from providers.models import Deployment, CodeChange
            from datetime import timedelta
            
            project = batch.project
            environment = batch.environment or 'production'
            
            if project:
                # 1. Determine Batch Interval
                prev_batch = AIAnalyzedBatch.objects.filter(
                    project=project,
                    timestamp__lt=batch.timestamp
                ).order_by('-timestamp').first()
                
                from Data.batch_config import get_batch_interval_for_org
                batch_interval_minutes = get_batch_interval_for_org(
                    batch.organisation or (batch.project.organisation if batch.project else None)
                )
                interval_start = batch.timestamp - timedelta(minutes=batch_interval_minutes)
                
                if prev_batch:
                    interval_start = prev_batch.timestamp
                
                # 2. Find deployments
                window_deployments = list(Deployment.objects.filter(
                    pipeline__project__organisation__projects=project,
                    environment=environment,
                    status='success',
                    deployed_at__gt=interval_start,
                    deployed_at__lte=batch.timestamp
                ).select_related('code_change', 'pipeline'))
                
                base_deploy = Deployment.objects.filter(
                    pipeline__project__organisation__projects=project,
                    environment=environment,
                    status='success',
                    deployed_at__lte=interval_start
                ).select_related('code_change', 'pipeline').order_by('-deployed_at').first()
                
                if base_deploy and base_deploy not in window_deployments:
                    window_deployments.append(base_deploy)
                
                # 3. Collect Commits
                relevant_commit_shas = set()
                
                for deploy in window_deployments:
                    prev_to_deploy = Deployment.objects.filter(
                        pipeline__project__organisation__projects=project,
                        environment=environment,
                        status='success',
                        deployed_at__lt=deploy.deployed_at
                    ).order_by('-deployed_at').first()
                    
                    start_hash_time = prev_to_deploy.code_change.timestamp if prev_to_deploy else (deploy.code_change.timestamp - timedelta(days=7))
                    
                    deploy_commits = CodeChange.objects.filter(
                        organisation=project.organisation,
                        timestamp__gt=start_hash_time,
                        timestamp__lte=deploy.code_change.timestamp
                    ).values_list('commit_sha', flat=True)
                    
                    relevant_commit_shas.update(deploy_commits)
                
                # 4. Fetch full commit objects
                if relevant_commit_shas:
                    commits_qs = CodeChange.objects.filter(
                        commit_sha__in=list(relevant_commit_shas)
                    ).order_by('-timestamp')[:50]

                    code_changes = [c.get_summary_for_ai() for c in commits_qs]
                    logger.info(f"Re-analysis: Retrieved {len(code_changes)} commits from {len(window_deployments)} deployments for batch {batch_id}")

                    # Persist updated context
                    if batch.data is None: batch.data = {}
                    batch.data['code_changes'] = code_changes
                    batch.save(update_fields=['data'])
                else:
                    # Q1.1-audit finding: mirror the analyze_batch fallback —
                    # a reanalysis of a batch created outside the full
                    # webhook chain must still see its staged
                    # ``batch.data['code_changes']``, otherwise correlations
                    # silently disappear on the second pass.
                    staged = batch.data.get('code_changes') if isinstance(batch.data, dict) else None
                    if staged:
                        code_changes = staged
                        logger.info(
                            f"Re-analysis {batch_id}: no Deployment chain in window; "
                            f"falling back to {len(staged)} staged code_changes on batch.data"
                        )
                    else:
                        code_changes = []
            else:
                 code_changes = batch.data.get('code_changes', [])

        except Exception as e:
            logger.error(f"Error fetching commits during re-analysis of {batch_id}: {e}")
            code_changes = batch.data.get('code_changes', [])
        
        # Format logs for analysis
        log_strings = []
        for log in logs[:100]:  # Limit to 100 logs
            source = log.get('_source', {})
            timestamp = source.get('@timestamp', '')
            level = (source.get('log_level') or source.get('level') or '').upper() or 'UNKNOWN'
            message = source.get('message', '')
            # ``service`` is an ECS object only for Elasticsearch-shaped logs; Loki,
            # Splunk, Datadog... store a plain string (and ``level``, not
            # ``log_level``). Reading it as a dict crashed every re-analysis.
            service = source.get('service')
            if isinstance(service, dict):
                component = service.get('name') or source.get('component', 'unknown')
            else:
                component = source.get('service_name') or service or source.get('component', 'unknown')
            log_strings.append(f"[{timestamp}] [{level}] [{component}] {message}")
        
        # Prepare batch data for prompt
        batch_data = {
            'batch_id': batch.batch_id,
            'timestamp': batch.timestamp.isoformat(),
            'environment': batch.environment or 'production',
        }
        
        # Generate prompt
        project_context = _build_project_context(batch)
        past_memories_text, past_memory_ids = _build_past_memories(batch)
        if past_memory_ids:
            batch.referenced_resolution_ids = past_memory_ids
            batch.save(update_fields=['referenced_resolution_ids'])

        try:
            from .trace_context import build_trace_context
            traces_summary = build_trace_context(batch)
        except Exception as _trace_exc:
            logger.warning('Trace context build failed (reanalyze): %s', _trace_exc)
            traces_summary = None

        enabled_capabilities = batch.data.get('project_capabilities') if isinstance(batch.data, dict) else None
        if enabled_capabilities is None:
            try:
                from Organisations.capability_registry import enabled_capabilities_for
                enabled_capabilities = sorted(enabled_capabilities_for(batch.project))
            except Exception as _cap_exc:
                logger.warning('Capability lookup failed (reanalyze): %s', _cap_exc)
                enabled_capabilities = None

        # Split prompt into cacheable system + per-batch user content.
        from .prompt_context import DataSourceContext
        from .prompts import get_batch_analysis_prompt_parts
        context = DataSourceContext(
            batch_data=batch_data,
            logs=log_strings,
            system_metrics={},
            metrics_summary=metrics_summary,
            code_changes=code_changes,
            project_context=project_context,
            past_memories=past_memories_text,
            traces_summary=traces_summary,
            enabled_capabilities=enabled_capabilities,
        )
        system_prompt, analysis_prompt = get_batch_analysis_prompt_parts(context)

        # Resolve organisation for API key lookup and token tracking
        organisation = None
        try:
            if hasattr(batch, 'project') and batch.project:
                organisation = batch.project.organisation
        except Exception as e:
            logger.warning(f"Could not determine organisation for re-analysis of batch {batch_id}: {e}")

        # Get org-specific API key + extras (e.g. Anthropic workspace_id).
        if organisation:
            api_key, base_url, extra_config = get_api_key_for_org(organisation, model_name)
        else:
            api_key, base_url, extra_config = None, None, {}

        # Call the unified pipeline (routes to correct adapter dynamically)
        analysis_result, api_error, tokens_input, tokens_output = generate_text_unified(
            analysis_prompt,
            provider=model_name,
            api_key=api_key,
            base_url=base_url,
            system_prefix=system_prompt,
            extra_config=extra_config,
        )

        # Log token usage for cost visibility
        if analysis_result and organisation and (tokens_input > 0 or tokens_output > 0):
            from ai_model.usage_tracking import AITokenUsageService
            usage = AITokenUsageService.log_usage(
                organisation=organisation,
                batch=batch,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                model_name=model_name,
                usage_type='batch_reanalysis'
            )
            if usage:
                logger.info(
                    f"Logged re-analysis AI usage for batch {batch_id}: "
                    f"{usage.tokens_total} tokens, ${usage.cost_usd:.6f} ({model_name})"
                )

        if analysis_result:
            try:
                # Parse result
                cleaned_result = re.sub(r"^```(?:json)?\n|\n```$", "", analysis_result.strip())
                
                try:
                    parsed_result = json.loads(cleaned_result)
                except json.JSONDecodeError:
                    import ast
                    parsed_result = ast.literal_eval(cleaned_result)
                
                current_time = timezone.now()
                is_primary = (mode == 'primary')

                if batch.analysis_history is None:
                    batch.analysis_history = []

                # Promotion side-effects: update analysis_text +
                # dedup-Issues. Runs BEFORE we append the history entry
                # so a failure here leaves history in its old shape.
                if is_primary:
                    # A new primary demotes every earlier history entry.
                    for entry in batch.analysis_history:
                        if isinstance(entry, dict):
                            entry['is_primary'] = False
                    _apply_primary_analysis_to_batch(batch, parsed_result, model_name)

                history_entry = {
                    'model_name': model_name,
                    'analyzed_at': current_time.isoformat(),
                    'analysis_result': parsed_result,
                    'is_primary': is_primary,
                    'issue_count': len(parsed_result.get('correlated_issues', []) or []),
                    'tokens_input': tokens_input,
                    'tokens_output': tokens_output,
                    'mode': mode,
                }

                batch.analysis_history.append(history_entry)
                if len(batch.analysis_history) > 5:
                    batch.analysis_history = batch.analysis_history[-5:]
                batch.save(update_fields=['analysis_history'])

                issue_count = history_entry['issue_count']
                logger.info(
                    "Re-analysis %s (%s) for batch %s: %s issues",
                    'promoted-to-primary' if is_primary else 'stored-for-compare',
                    model_name, batch_id, issue_count,
                )
                return (
                    f"Re-analysis completed for batch {batch_id} with model "
                    f"{model_name} (mode={mode}): {issue_count} issues"
                )
                
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"JSON parsing error during re-analysis: {str(e)}")
                return f"Re-analysis failed: JSON parsing error for batch {batch_id}"
        else:
            logger.error(f"No result from {model_name} for batch {batch_id}")
            return f"Re-analysis failed: No result from {model_name}"
            
    except AIAnalyzedBatch.DoesNotExist:
        logger.error(f"Batch {batch_id} not found for re-analysis")
        return f"Batch {batch_id} not found"
    except Exception as e:
        logger.error(f"Error during re-analysis of batch {batch_id}: {str(e)}", exc_info=True)
        # Retry on failure
        raise self.retry(exc=e)
