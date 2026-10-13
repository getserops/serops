"""
Log Ingestion Module — extracted from Data/tasks.py (Phase 4).

Contains all log processing logic:
- Environment matching
- Log deduplication 
- Unique log filtering
- Elasticsearch query building
"""

import dataclasses
import logging
import os
from collections import defaultdict
from datetime import datetime

from django.conf import settings
from django.utils import timezone

from integrations.schemas import LogEntry

logger = logging.getLogger(__name__)

Metrics_interval = int(os.getenv('BATCH_GENERATION_INTERVAL', 5))

# Environment aliases for normalization
ENVIRONMENT_ALIASES = {
    'production': ['prod', 'prd', 'production'],
    'staging': ['stage', 'stg', 'staging', 'preprod'],
    'development': ['dev', 'development']
}


def is_log_matching_environment(log, target_environment):
    """
    Check if a log entry matches the target environment.
    Strictly filters logs to prevent cross-environment leakage.
    Returns True if:
    1. Log environment tag matches target (normalized)
    2. Log has NO environment tag (legacy fallback)
    Supports both LogEntry objects and legacy dictionaries.
    """
    if not target_environment:
        return True
        
    env_label = None
    
    # Check if log is LogEntry or dict
    if hasattr(log, 'labels'):
        # LogEntry
        labels = log.labels
        env_label = labels.get('environment') or labels.get('env')
        
        # Check for nested kubernetes labels if accessible
        if not env_label and 'kubernetes' in labels:
            k8s = labels['kubernetes']
            if isinstance(k8s, dict):
                env_label = k8s.get('labels', {}).get('environment')
    else:
        # Legacy dict
        source = log.get('_source', {})
        env_label = (
            source.get('environment') or 
            source.get('env') or 
            source.get('kubernetes', {}).get('labels', {}).get('environment') or
            source.get('labels', {}).get('environment')
        )
    
    # Legacy support: if no tag, assume match
    if not env_label:
        return True
        
    env_lower = str(env_label).lower()
    target_lower = target_environment.lower()
    
    # Direct match
    if env_lower == target_lower:
        return True
        
    # Alias match
    target_aliases = ENVIRONMENT_ALIASES.get(target_lower, [target_lower])
    return env_lower in target_aliases


def _parse_timestamp(ts_str):
    """Parse an ISO timestamp string into a datetime, or return None."""
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return None


def _make_signature(message):
    """Normalize a log message into a stable signature for grouping."""
    import re
    sig = message
    sig = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[.\d]*Z?', '<TIMESTAMP>', sig)
    sig = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '<IP>', sig)
    sig = re.sub(r'port \d+', 'port <PORT>', sig)
    sig = re.sub(r'\b[0-9a-f]{8,}\b', '<HEX>', sig)
    sig = re.sub(r'\b\d{5,}\b', '<NUM>', sig)
    return sig.strip()


def deduplicate_logs(logs, time_tolerance_seconds=60):
    """
    Group identical errors that occur close in time to reduce AI processing costs.
    Supports both LogEntry objects and legacy dictionaries.

    Logs with the same message signature are only collapsed when they occur within
    ``time_tolerance_seconds`` of each other.  A gap larger than the tolerance
    starts a new group so that the same error recurring hours later is reported
    separately.

    Args:
        logs: List of LogEntry objects or legacy dicts
        time_tolerance_seconds: Max seconds between consecutive occurrences to
            merge into one group.  Logs farther apart keep separate entries.

    Returns:
        List of deduplicated log entries (LogEntry or dict)
    """
    if not logs:
        return []

    if len(logs) <= 1:
        return logs

    total_original = len(logs)

    # Collect entries grouped by message signature
    groups = defaultdict(list)

    for log in logs:
        is_obj = hasattr(log, 'message')

        if is_obj:
            message = log.message
            ts = log.timestamp
            timestamp_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
        else:
            source = log.get('_source', {})
            message = source.get('message', '')
            timestamp_str = source.get('@timestamp', '')

        signature = _make_signature(message)

        groups[signature].append({
            'timestamp': timestamp_str,
            'parsed_ts': _parse_timestamp(timestamp_str),
            'full_log': log,
            'message': message,
            'is_obj': is_obj,
        })

    # Process groups — split into time-windowed sub-groups, then aggregate each
    deduplicated = []

    for signature, occurrences in groups.items():
        if len(occurrences) == 1:
            deduplicated.append(occurrences[0]['full_log'])
            continue

        # Sort by timestamp for windowed grouping
        occurrences.sort(key=lambda x: x['timestamp'])

        # Split into sub-groups where consecutive entries are within tolerance
        sub_groups = []
        current_group = [occurrences[0]]

        for entry in occurrences[1:]:
            prev_ts = current_group[-1]['parsed_ts']
            curr_ts = entry['parsed_ts']

            # If either timestamp is unparseable, keep in same group (safe default)
            if prev_ts and curr_ts:
                gap = abs((curr_ts - prev_ts).total_seconds())
                if gap > time_tolerance_seconds:
                    sub_groups.append(current_group)
                    current_group = [entry]
                    continue

            current_group.append(entry)

        sub_groups.append(current_group)

        # Aggregate each sub-group
        for group in sub_groups:
            if len(group) == 1:
                deduplicated.append(group[0]['full_log'])
                continue

            first = group[0]
            timestamps = [o['timestamp'] for o in group]
            new_msg = (
                f"[REPEATED {len(group)}x between {timestamps[0]} and {timestamps[-1]}] "
                f"{first['message']}"
            )

            if first['is_obj']:
                aggregated = dataclasses.replace(
                    first['full_log'],
                    message=new_msg,
                    deduplicated=True,
                    occurrence_count=len(group),
                )
            else:
                aggregated = first['full_log'].copy()
                if '_source' in aggregated:
                    aggregated['_source'] = aggregated['_source'].copy()
                    aggregated['_source']['message'] = new_msg
                    aggregated['_source']['deduplicated'] = True
                    aggregated['_source']['occurrence_count'] = len(group)

            deduplicated.append(aggregated)

    total_deduplicated = len(deduplicated)
    if total_deduplicated < total_original:
        logger.info(
            f"Deduplication: {total_original} → {total_deduplicated} logs "
            f"({100 * (1 - total_deduplicated / total_original):.1f}% reduction)"
        )

    return deduplicated


def _escape_like(value):
    """Escape special characters for PostgreSQL LIKE/ILIKE patterns."""
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


# Hard cap on how far back to look for dedup (prevents unbounded memory growth).
# 30 days is generous; most batches run every 5 minutes so this covers 8,640 batches.
_MAX_DEDUP_LOOKBACK_DAYS = int(os.getenv('MAX_DEDUP_LOOKBACK_DAYS', 30))


def _clamp_window(time_window, hard_floor):
    """Pick the more recent of time_window and hard_floor, handling naive datetimes."""
    if not time_window:
        return hard_floor
    try:
        return max(time_window, hard_floor)
    except TypeError:
        # Comparing naive vs aware — make both aware
        if timezone.is_naive(time_window):
            time_window = timezone.make_aware(time_window)
        if timezone.is_naive(hard_floor):
            hard_floor = timezone.make_aware(hard_floor)
        return max(time_window, hard_floor)


_FETCH_CHUNK_SIZE = 5000


def _load_seen_data(cursor, filters, params):
    """
    Load previously-seen log identifiers from the database.
    Uses fetchmany() to iterate in chunks and avoid loading the full result
    set into Python memory at once.

    Returns a dict with 'messages', 'ids', 'timestamps' sets.
    """
    seen_data = {
        'messages': set(),
        'ids': set(),
        'timestamps': set(),
    }

    where_clause = " AND ".join(filters)

    cursor.execute(f"""
        SELECT DISTINCT
            log->>'_id' AS log_id,
            log->'_source'->>'message' AS message,
            log->'_source'->>'@timestamp' AS ts
        FROM "Data_aianalyzedbatch",
             jsonb_array_elements(data->'logs') AS log
        WHERE {where_clause}
          AND log->>'_id' IS NOT NULL
    """, params)

    while True:
        rows = cursor.fetchmany(_FETCH_CHUNK_SIZE)
        if not rows:
            break
        for log_id, message, timestamp in rows:
            if log_id:
                seen_data['ids'].add(log_id)
            if message:
                seen_data['messages'].add(message)
            if timestamp:
                seen_data['timestamps'].add(timestamp)

    return seen_data


def filter_unique_logs(hits, time_window, organisation=None):
    """
    Filter logs based on multiple criteria and timestamps.
    Supports both LogEntry objects and legacy dictionaries.

    Args:
        hits: List of log entries (LogEntry or dict)
        time_window: Only consider batches after this timestamp
        organisation: If provided, only deduplicate against this org's batches
    """
    from django.db import connection
    from datetime import timedelta

    # Clamp lookback to prevent unbounded memory growth
    hard_floor = timezone.now() - timedelta(days=_MAX_DEDUP_LOOKBACK_DAYS)
    effective_window = _clamp_window(time_window, hard_floor)

    filters = ["timestamp >= %s"]
    params = [effective_window]

    if organisation is not None:
        filters.append("organisation_id = %s")
        params.append(organisation.id)

    with connection.cursor() as cursor:
        seen_data = _load_seen_data(cursor, filters, params)

    logger.info(f"Found {len(seen_data['messages'])} previously seen messages, "
                f"{len(seen_data['ids'])} IDs, {len(seen_data['timestamps'])} timestamps")

    unique_logs = []
    for hit in hits:
        if hasattr(hit, 'message'):
            message = hit.message
            log_id = hit.raw_id
            ts = hit.timestamp
            timestamp = ts.isoformat() if isinstance(ts, datetime) else str(ts)
        elif isinstance(hit, dict):
            source = hit.get('_source', {})
            message = source.get('message')
            log_id = hit.get('_id')
            timestamp = source.get('@timestamp')
        else:
            logger.warning(f"Skipping unknown hit type: {type(hit)}")
            continue

        if all([
            message and log_id and timestamp,
            message not in seen_data['messages'],
            log_id not in seen_data['ids'],
            timestamp not in seen_data['timestamps'],
        ]):
            seen_data['messages'].add(message)
            seen_data['ids'].add(log_id)
            seen_data['timestamps'].add(timestamp)
            unique_logs.append(hit)

    def get_sort_key(item):
        if hasattr(item, 'timestamp'):
            ts = item.timestamp
            return ts.isoformat() if isinstance(ts, datetime) else str(ts)
        return item.get('_source', {}).get('@timestamp', '')

    return sorted(unique_logs, key=get_sort_key, reverse=True)


def filter_unique_logs_for_project(hits, time_window, project_name=None, organisation=None):
    """
    Filter logs based on multiple criteria and timestamps for a specific project.
    Supports both LogEntry objects and legacy dictionaries.

    Args:
        hits: List of log entries (LogEntry or dict)
        time_window: Only consider batches after this timestamp
        project_name: Filter batches by project name
        organisation: If provided, only deduplicate against this org's batches
    """
    from django.db import connection
    from datetime import timedelta

    hard_floor = timezone.now() - timedelta(days=_MAX_DEDUP_LOOKBACK_DAYS)
    effective_window = _clamp_window(time_window, hard_floor)

    filters = ["timestamp >= %s"]
    params = [effective_window]

    if organisation is not None:
        filters.append("organisation_id = %s")
        params.append(organisation.id)

    if project_name:
        # Escape LIKE wildcards to prevent cross-project matching
        project_pattern = _escape_like(project_name.lower().replace(' ', '-'))
        filters.append("batch_id ILIKE %s")
        params.append(f"%{project_pattern}%")

    with connection.cursor() as cursor:
        seen_data = _load_seen_data(cursor, filters, params)

    logger.info(f"Found {len(seen_data['messages'])} previously seen messages for project {project_name}")

    unique_logs = []
    for hit in hits:
        if hasattr(hit, 'message'):
            message = hit.message
            log_id = hit.raw_id
            ts = hit.timestamp
            timestamp = ts.isoformat() if isinstance(ts, datetime) else str(ts)
            hit_index = hit.labels.get('_index', '')
        elif isinstance(hit, dict):
            source = hit.get('_source', {})
            message = source.get('message')
            log_id = hit.get('_id')
            timestamp = source.get('@timestamp')
            hit_index = hit.get('_index', '')
        else:
            logger.warning(f"Skipping unknown hit type: {type(hit)}")
            continue

        # Additional filtering for project-specific logs
        is_project_relevant = True
        if project_name and 'ci_cd-logs-project-' in hit_index:
            expected_index = f"ci_cd-logs-project-{project_name.lower()}"
            is_project_relevant = hit_index == expected_index

        if all([
            message and log_id and timestamp,
            message not in seen_data['messages'],
            log_id not in seen_data['ids'],
            timestamp not in seen_data['timestamps'],
            is_project_relevant,
        ]):
            seen_data['messages'].add(message)
            seen_data['ids'].add(log_id)
            seen_data['timestamps'].add(timestamp)
            unique_logs.append(hit)

    def get_sort_key(item):
        if hasattr(item, 'timestamp'):
            ts = item.timestamp
            return ts.isoformat() if isinstance(ts, datetime) else str(ts)
        return item.get('_source', {}).get('@timestamp', '')

    return sorted(unique_logs, key=get_sort_key, reverse=True)


def create_elasticsearch_query(last_batch_time, interval_minutes=None):
    """Build the Elasticsearch query for log ingestion.

    Args:
        last_batch_time: Timestamp of the most recent batch (or None).
        interval_minutes: Per-org batch interval override (falls back to
            module-level ``Metrics_interval``).
    """
    effective_interval = interval_minutes or Metrics_interval
    current_time = timezone.now()
    query = {
        "query": {
            "bool": {
                "must": [
                    {
                        "exists": {
                            "field": "@timestamp"
                        }
                    }
                ],
                "must_not": [],
                "filter": [
                    {
                        "range": {
                            "@timestamp": {
                                "lte": current_time.isoformat()
                            }
                        }
                    }
                ]
            }
        },
        "sort": [
            {
                "@timestamp": {
                    "order": "desc",
                    "missing": "_last"
                }
            }
        ],
        "size": 10000
    }

    if last_batch_time:
        query["query"]["bool"]["filter"][0]["range"]["@timestamp"]["gt"] = last_batch_time.isoformat()
    else:
        query["query"]["bool"]["filter"][0]["range"]["@timestamp"]["gte"] = (
            current_time - timezone.timedelta(minutes=effective_interval)
        ).isoformat()

    return query


def _real_org_batches():
    """Queryset of batches that belong to non-demo orgs.

    The demo org (organisation.is_demo=True) is regenerated nightly
    with synthetic timestamps. If its batches participated in the
    scheduler's "what was the most recent batch?" calculation they
    would poison the window for real orgs. Filter them out at the
    source so every caller benefits.
    """
    from Data.models import AIAnalyzedBatch
    return AIAnalyzedBatch.objects.exclude(organisation__is_demo=True)


def get_latest_batch_timestamp():
    """Get the timestamp of the most recent batch (excluding demo)."""
    latest_batch = _real_org_batches().order_by('-timestamp').first()
    return latest_batch.timestamp if latest_batch else None


def get_last_processed_log_timestamp():
    """Get the timestamp of the most recent processed log (excluding demo)."""
    latest_batch = _real_org_batches().order_by('-timestamp').first()
    if not latest_batch or not latest_batch.data.get('logs'):
        return None

    try:
        latest_log = latest_batch.data['logs'][0]
        return latest_log.get('_source', {}).get('@timestamp')
    except (IndexError, KeyError):
        return None


def get_latest_batch_timestamp_for_project(project_name=None):
    """Get the timestamp of the most recent batch for a specific project."""
    query = _real_org_batches()

    if project_name:
        project_prefix = project_name.strip().replace(' ', '-').replace('_', '-').lower()
        query = query.filter(batch_id__startswith=project_prefix)

    latest_batch = query.order_by('-timestamp').first()
    return latest_batch.timestamp if latest_batch else None
