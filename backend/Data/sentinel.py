"""
Sentinel — Tiered Intelligence Gate for batch analysis.

Phase 1: Shadow mode — evaluates every batch but always allows AI to run.
Logs decisions for observability without changing behavior.
"""

import hashlib
import logging
import math
import re
from datetime import datetime, timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

# Maximum number of data points to keep in rolling trend arrays
ROLLING_WINDOW = 24

# Exponential moving average smoothing factor (0.1 = slow adaptation)
EMA_ALPHA = 0.1

# Z-score threshold for metric anomaly detection
Z_SCORE_THRESHOLD = 3.0

# Multiplier for error rate spike detection
ERROR_SPIKE_MULTIPLIER = 2.0


# A log pattern unseen for this long counts as new again, so an error that
# went away and came back is analysed instead of being remembered forever.
KNOWN_LOG_PATTERN_TTL = timedelta(hours=6)
# Bound on remembered patterns per project/environment (most recent kept).
MAX_KNOWN_LOG_PATTERNS = 2000


def _get_sentinel_config(organisation):
    """Load per-org sentinel config. Returns (active_mode, thresholds_dict).

    Backwards-compat: original 2-tuple return preserved so all existing
    callers keep working. For the pre-creation gate flag, use
    :func:`is_pre_creation_gate_enabled` which reads the same config.
    """
    try:
        config = organisation.sentinel_config
        thresholds = {
            'error_spike_multiplier': config.error_spike_multiplier or ERROR_SPIKE_MULTIPLIER,
            'z_score_threshold': config.z_score_threshold or Z_SCORE_THRESHOLD,
            'max_quiet_batches': config.max_quiet_batches,
        }
        return config.active_mode, thresholds
    except Exception:
        # No config → shadow mode with defaults
        return False, {
            'error_spike_multiplier': ERROR_SPIKE_MULTIPLIER,
            'z_score_threshold': Z_SCORE_THRESHOLD,
            'max_quiet_batches': 12,
        }


def is_pre_creation_gate_enabled(organisation) -> bool:
    """Return True if the org has opted into pre-creation batch dropping.

    Batch 50 — separate from ``_get_sentinel_config`` so existing
    call sites don't need updating. Only meaningful when
    ``active_mode=True``; the gate no-ops in shadow mode regardless
    of this flag (shadow mode is for observing what Sentinel WOULD
    skip, so we always persist).

    Defaults to True on config load failure — the pre-creation
    behaviour is the safer default (less DB pressure, less AI cost)
    for the general population.
    """
    try:
        return bool(organisation.sentinel_config.pre_creation_gate_enabled)
    except Exception:
        return True


def should_skip_batch_pre_creation(project, environment, batch_data, organisation):
    """Cheap pre-flight check — should we drop this batch BEFORE persisting?

    Returns ``(should_skip, decision, triggers)``. Skip requires:
      * ``active_mode=True`` on the org's SentinelConfig
      * ``pre_creation_gate_enabled=True`` (the new toggle)
      * Sentinel decision is ``quiet`` (no triggers fired)

    Callers (only ``create_log_batch_with_project_name`` today) wrap
    the whole thing in try/except and never propagate — a failing gate
    check must NEVER block batch creation. Skipping on error would
    silently lose data; the safe failure mode is "let it through".

    IMPORTANT: this call mutates ``ProjectEnvironmentState`` via
    ``evaluate_batch`` (rolling averages, batches_since_last_ai
    counter). Callers MUST NOT then also call ``evaluate_batch``
    post-persist for the same batch — that would double-count state.
    See the pipeline switch in ``create_log_batch_with_project_name``
    for the wiring.
    """
    active_mode, thresholds = _get_sentinel_config(organisation)
    decision, triggers = evaluate_batch(
        project=project,
        environment=environment,
        batch_data=batch_data,
        organisation=organisation,
        thresholds=thresholds,
    )
    gate_on = is_pre_creation_gate_enabled(organisation)
    should_skip = (
        active_mode
        and gate_on
        and decision == 'quiet'
    )
    return should_skip, decision, triggers


def evaluate_batch(project, environment, batch_data, organisation, thresholds=None):
    """
    Evaluate whether a batch warrants AI analysis.

    Args:
        project: Project model instance
        environment: ProjectEnvironment model instance
        batch_data: dict — the batch's cleaned data payload
        organisation: Organisations model instance
        thresholds: optional dict with 'error_spike_multiplier', 'z_score_threshold', 'max_quiet_batches'

    Returns:
        (decision: str, triggers: list[str])
        decision is one of: 'first', 'alert', 'quiet'
    """
    from .models import ProjectEnvironmentState

    # Use provided thresholds or fall back to module-level defaults
    error_spike_mult = (thresholds or {}).get('error_spike_multiplier', ERROR_SPIKE_MULTIPLIER)
    z_score_thresh = (thresholds or {}).get('z_score_threshold', Z_SCORE_THRESHOLD)
    max_quiet = (thresholds or {}).get('max_quiet_batches', 12)

    state, created = ProjectEnvironmentState.objects.get_or_create(
        project=project,
        environment=environment,
        defaults={'organisation': organisation},
    )

    if created:
        # First batch ever for this project+environment — seed state
        batch_stats = _extract_batch_stats(batch_data)
        update_rolling_state(state, batch_stats)
        state.known_log_patterns = _remember_log_patterns(
            {}, _generate_log_fingerprints(batch_data.get('logs', [])))
        state.save()
        return ('first', ['first_batch'])

    triggers = []
    batch_stats = _extract_batch_stats(batch_data)

    # 1. Deployment detection
    code_changes = batch_data.get('code_changes', [])
    if code_changes:
        latest_sha = code_changes[0].get('sha', '') if code_changes else ''
        if latest_sha and latest_sha != state.last_deploy_sha:
            triggers.append('deployment_detected')
            state.last_deploy_sha = latest_sha
            state.last_deploy_at = timezone.now()

    # 2. New error pattern detection: a warning/error signature not seen in
    # this project+environment within KNOWN_LOG_PATTERN_TTL.
    log_fingerprints = _generate_log_fingerprints(batch_data.get('logs', []))
    recent_patterns = _prune_log_patterns(state.known_log_patterns or {})
    if any(fp not in recent_patterns for fp in log_fingerprints):
        triggers.append('new_error_pattern')
    state.known_log_patterns = _remember_log_patterns(recent_patterns, log_fingerprints)

    # 3. Error rate spike
    current_errors = batch_stats['error_count']
    if state.baseline_error_rate > 0 and current_errors > error_spike_mult * state.baseline_error_rate:
        triggers.append('error_rate_spike')

    # 4. Memory anomaly (z-score)
    if batch_stats['memory_avg'] is not None and state.baseline_stddev_memory > 0:
        z_mem = abs(batch_stats['memory_avg'] - state.baseline_memory) / state.baseline_stddev_memory
        if z_mem > z_score_thresh:
            triggers.append('memory_anomaly')

    # 5. CPU anomaly (z-score)
    if batch_stats['cpu_avg'] is not None and state.baseline_stddev_cpu > 0:
        z_cpu = abs(batch_stats['cpu_avg'] - state.baseline_cpu) / state.baseline_stddev_cpu
        if z_cpu > z_score_thresh:
            triggers.append('cpu_anomaly')

    # 6. Escalating error trend (last 3 batches monotonically increasing)
    recent_errors = list(state.error_counts or [])
    recent_errors.append(current_errors)
    if len(recent_errors) >= 3:
        last3 = recent_errors[-3:]
        if last3[0] < last3[1] < last3[2] and last3[0] > 0:
            triggers.append('error_rate_escalating')

    # Update rolling state
    update_rolling_state(state, batch_stats)

    state.batches_since_last_ai = (state.batches_since_last_ai or 0) + 1

    # 7. Safety net: force AI analysis after max_quiet_batches consecutive quiet batches
    if not triggers and state.batches_since_last_ai >= max_quiet:
        triggers.append('forced_periodic')

    state.save()

    decision = 'alert' if triggers else 'quiet'
    return (decision, triggers)


def record_ai_analysis(project, environment):
    """Called after successful AI analysis to reset quiet counters."""
    from .models import ProjectEnvironmentState
    try:
        state = ProjectEnvironmentState.objects.get(project=project, environment=environment)
        state.batches_since_last_ai = 0
        state.last_ai_analysis_at = timezone.now()
        state.save(update_fields=['batches_since_last_ai', 'last_ai_analysis_at'])
    except ProjectEnvironmentState.DoesNotExist:
        pass


def update_rolling_state(state, batch_stats):
    """
    Append current batch values to trend arrays (capped at ROLLING_WINDOW)
    and update baselines using exponential moving average.
    """
    # Append to rolling arrays
    def _append_rolling(arr, value):
        """Append value to array, keeping at most ROLLING_WINDOW items."""
        if arr is None:
            arr = []
        arr = list(arr)
        arr.append(value)
        return arr[-ROLLING_WINDOW:]

    state.error_counts = _append_rolling(state.error_counts, batch_stats['error_count'])
    state.log_volume = _append_rolling(state.log_volume, batch_stats['log_count'])

    if batch_stats['memory_avg'] is not None:
        state.memory_avg = _append_rolling(state.memory_avg, batch_stats['memory_avg'])
    if batch_stats['cpu_avg'] is not None:
        state.cpu_avg = _append_rolling(state.cpu_avg, batch_stats['cpu_avg'])

    # Update baselines with EMA
    state.baseline_error_rate = _ema(state.baseline_error_rate, batch_stats['error_count'])

    if batch_stats['memory_avg'] is not None:
        state.baseline_memory = _ema(state.baseline_memory, batch_stats['memory_avg'])
        state.baseline_stddev_memory = _update_stddev(
            state.memory_avg, state.baseline_memory
        )

    if batch_stats['cpu_avg'] is not None:
        state.baseline_cpu = _ema(state.baseline_cpu, batch_stats['cpu_avg'])
        state.baseline_stddev_cpu = _update_stddev(
            state.cpu_avg, state.baseline_cpu
        )


def _extract_batch_stats(batch_data):
    """
    Extract numeric stats from batch data for sentinel evaluation.

    Returns dict with: error_count, memory_avg, cpu_avg, log_count
    """
    logs = batch_data.get('logs', [])
    log_count = len(logs)

    # Count errors
    error_count = 0
    for log in logs:
        source = log.get('_source', {}) if isinstance(log, dict) else {}
        level = source.get('log_level', source.get('level', '')).upper()
        if level in ('ERROR', 'CRITICAL', 'FATAL'):
            error_count += 1

    # Extract metric averages from metrics_summary
    metrics_summary = batch_data.get('metrics_summary', {})
    memory_avg = None
    cpu_avg = None

    mem_stats = metrics_summary.get('memory', {}).get('usage_percent', {})
    if mem_stats.get('avg') is not None:
        try:
            memory_avg = float(mem_stats['avg'])
        except (ValueError, TypeError):
            pass

    cpu_stats = metrics_summary.get('cpu', {}).get('usage_percent', {})
    if cpu_stats.get('avg') is not None:
        try:
            cpu_avg = float(cpu_stats['avg'])
        except (ValueError, TypeError):
            pass

    return {
        'error_count': error_count,
        'memory_avg': memory_avg,
        'cpu_avg': cpu_avg,
        'log_count': log_count,
    }


def _generate_log_fingerprints(logs):
    """
    Signatures of the warning/error lines in a batch.

    The message is normalised first (timestamps, IPs, hex ids and every
    number collapse to placeholders) so one error with different order ids,
    durations or retry counts is one pattern, not a new one each time.
    """
    from integrations.ingestion import _make_signature

    fingerprints = set()
    for log in logs:
        source = log.get('_source', {}) if isinstance(log, dict) else {}
        level = source.get('log_level', source.get('level', '')).upper()
        message = source.get('message', '')
        if level in ('ERROR', 'CRITICAL', 'FATAL', 'WARNING') and message:
            signature = _NUMBER.sub('<N>', _make_signature(message))[:120]
            fp = hashlib.md5(f"{level}|{signature}".encode()).hexdigest()[:16]
            fingerprints.add(fp)
    return fingerprints


_NUMBER = re.compile(r'\d+')


def _prune_log_patterns(patterns):
    """Drop patterns last seen longer ago than KNOWN_LOG_PATTERN_TTL."""
    cutoff = timezone.now() - KNOWN_LOG_PATTERN_TTL
    kept = {}
    for fp, seen in patterns.items():
        try:
            if datetime.fromisoformat(seen) >= cutoff:
                kept[fp] = seen
        except (TypeError, ValueError):
            continue
    return kept


def _remember_log_patterns(patterns, fingerprints):
    """Mark fingerprints as seen now, keeping the most recent MAX entries."""
    now = timezone.now().isoformat()
    merged = {**patterns, **{fp: now for fp in fingerprints}}
    if len(merged) > MAX_KNOWN_LOG_PATTERNS:
        newest = sorted(merged.items(), key=lambda kv: kv[1], reverse=True)[:MAX_KNOWN_LOG_PATTERNS]
        merged = dict(newest)
    return merged


def _ema(current, new_value):
    """Exponential moving average update."""
    if current == 0:
        return float(new_value)
    return EMA_ALPHA * float(new_value) + (1 - EMA_ALPHA) * float(current)


def _update_stddev(values_list, mean):
    """Compute standard deviation from rolling values, with floor of 1.0."""
    if not values_list or len(values_list) < 2:
        return 1.0
    n = len(values_list)
    variance = sum((v - mean) ** 2 for v in values_list) / n
    stddev = math.sqrt(variance)
    return max(stddev, 1.0)  # Floor at 1.0 to avoid division by zero
