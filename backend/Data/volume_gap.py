"""
Data gaps: a project or a service that logged steadily and has stopped.

The analysis reads errors and warnings, so a window in which logs stopped
arriving looked exactly like a healthy one: phase 3 client C4 (L5, the log
store went read-only and the collector's writes failed; L3, checkout traffic
stopped with nothing logged as an error) was reported healthy both times.

Two bounded reads of the same store, project, environment and locations as
the batch, at every level: this window, then the window before it of the same
length, only when this window's read came back small. A gap is reported only
against a steady baseline (enough records, spread over several minutes), so a
quiet service, a bursty job or a restart does not raise one.
"""
import logging
from dataclasses import replace
from datetime import timedelta

logger = logging.getLogger(__name__)

READ_CAP = 300              # records per read; a full read is never a gap
PROJECT_MIN_BASELINE = 50   # records in the window before, for a project-wide drop
PROJECT_DROP_RATIO = 0.10   # this window at or under 10 % of the window before
SERVICE_MIN_BASELINE = 20   # records of one service in the window before
MIN_STEADY_MINUTES = 3      # distinct minutes the baseline was spread over
MAX_SILENT_SERVICES = 10


def _minute(entry):
    ts = getattr(entry, 'timestamp', None)
    if ts is None and isinstance(entry, dict):
        src = entry.get('_source', {}) or {}
        ts = src.get('@timestamp') or src.get('timestamp')
    if hasattr(ts, 'strftime'):
        return ts.strftime('%Y%m%d%H%M')
    return str(ts or '')[:16]


def _read(provider, index_pattern, query, environment, env_labels):
    entries = list(provider.search(index_pattern, query) or [])
    if environment:
        from integrations.ingestion import is_log_matching_environment
        entries = [e for e in entries if is_log_matching_environment(e, environment, env_labels or ())]
    return entries


def assess(current, previous, current_full, service_of):
    """The gap between two reads, or None. Pure, for tests.

    ``current_full`` is True when this window's read hit the cap: then it is
    not a gap, and a missing service may only have been cut off.
    """
    if current_full or not previous:
        return None
    gap = {'window_logs': len(current), 'previous_logs': len(previous),
           'previous_capped': len(previous) >= READ_CAP,
           'collapsed': False, 'silent_services': []}
    steady = len({_minute(e) for e in previous}) >= MIN_STEADY_MINUTES
    if (steady and len(previous) >= PROJECT_MIN_BASELINE
            and len(current) <= PROJECT_DROP_RATIO * len(previous)):
        gap['collapsed'] = True
    now_services = {service_of(e) for e in current}
    before = {}
    for e in previous:
        name = service_of(e)
        if name:
            before.setdefault(name, []).append(e)
    for name, rows in sorted(before.items(), key=lambda kv: -len(kv[1])):
        if name in now_services or len(rows) < SERVICE_MIN_BASELINE:
            continue
        if len({_minute(e) for e in rows}) < MIN_STEADY_MINUTES:
            continue  # a burst (a job, a restart), not a steady stream
        gap['silent_services'].append({'service': name, 'previous_logs': len(rows)})
        if len(gap['silent_services']) >= MAX_SILENT_SERVICES:
            break
    if not gap['collapsed'] and not gap['silent_services']:
        return None
    return gap


def check_log_volume(provider, index_pattern, base_query, environment=None, env_labels=()):
    """This window against the window before, at every level; None when
    nothing stopped or when it cannot be told. Never raises."""
    if provider is None or base_query is None or not getattr(base_query, 'time_range', None):
        return None
    try:
        from .log_filters import log_service
        start, end = base_query.time_range
        query = replace(base_query, severity=None, services=None, text_search=None,
                        message_any=None, max_results=READ_CAP)
        current = _read(provider, index_pattern, query, environment, env_labels)
        if len(current) >= READ_CAP:
            return None  # plenty is arriving
        length = end - start
        if length <= timedelta(0):
            return None
        previous = _read(provider, index_pattern, replace(query, time_range=(start - length, start)),
                         environment, env_labels)
        return assess(current, previous, False, log_service)
    except Exception as e:  # never fail or change the batch
        logger.info('Log volume not compared: %s', e)
        return None


def format_data_gap(gap) -> tuple[str, str]:
    """``(facts, services)`` for the prompt: counts written by SerOps, and the
    silent service names, which come from the logs (fenced by the caller)."""
    if not gap:
        return '', ''
    cap = '+' if gap.get('previous_capped') else ''
    facts = (f"Records at every level: {gap.get('window_logs', 0)} in this window, "
             f"{gap.get('previous_logs', 0)}{cap} in the window before of the same length.")
    if gap.get('collapsed'):
        facts += " The project's log volume fell by 90 % or more."
    services = '\n'.join(f"{s['service']}: 0 records now, {s['previous_logs']}{cap} in the window before"
                         for s in gap.get('silent_services') or [])
    return facts, services
