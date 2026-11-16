"""
Change and job events: the INFO lines that say something started, stopped or
changed (a nightly reindex, a migration, a restart, a failover).

The analysis reads errors and warnings only, so a cause that logs itself at
INFO was invisible: phase 3 client C1 (nightly reindex) and C3 (a REINDEX job
locking the table) found the saturated database and never named the job.
One extra, bounded query per batch fetches these lines; the prompt shows them
as context, never as findings on their own.
"""
import logging
import re
from dataclasses import replace

logger = logging.getLogger(__name__)

# Words a store is asked for (any of them, case-insensitive). Stores that
# cannot express the filter return a capped sample and Python filters it.
CHANGE_EVENT_WORDS = (
    'started', 'starting', 'finished', 'completed', 'cron', 'cronjob', 'job',
    'reindex', 'vacuum', 'analyze', 'migration', 'migrate', 'migrating',
    'backup', 'restore', 'deploy', 'deployed', 'deploying', 'rollout', 'release',
    'version', 'restart', 'restarting', 'shutdown', 'scaling', 'scaled',
    'reload', 'reloaded', 'flag', 'failover', 'promoted', 'promotion',
    'flush', 'flushed', 'purge', 'purged', 'compaction', 'snapshot',
)

# Words that name an operation by themselves rank first when there are more
# lines than the cap; "started" / "version" alone are frequent and weak.
_STRONG = re.compile(
    r'\b(cron(job)?|reindex(ing|ed)?|vacuum|analyze|migrat\w*|backup|restore\w*|deploy\w*|'
    r'rollout|rolled|release[ds]?|restart\w*|shutdown|shutting down|scal(ed|ing)|reload\w*|'
    r'feature[ -]?flag|failover|promot\w*|flush\w*|purg\w*|compaction|snapshot)\b',
    re.IGNORECASE)
_WEAK = re.compile(
    r'\b(start(ed|ing)|finish(ed)?|complet(ed|e)|job|version|flag)\b', re.IGNORECASE)

MAX_LINES = 20
MAX_CHARS = 2000        # rendered size of the block, all lines together
MAX_LINE_CHARS = 200
FETCH_LIMIT = 500       # records asked for; the store's newest-or-oldest cut is fine here

_NOT_INFO = {'ERROR', 'ERR', 'WARN', 'WARNING', 'CRITICAL', 'FATAL', 'DEBUG', 'TRACE'}
_NUMBERS = re.compile(r'\d+')


def _field(entry, name, default=''):
    if hasattr(entry, name):
        return getattr(entry, name) or default
    return (entry.get('_source', {}) or {}).get(name, default) if isinstance(entry, dict) else default


def is_change_event(entry) -> bool:
    """An INFO line that reads like a start, stop or change."""
    from .log_filters import is_important_log
    level = str(_field(entry, 'level') or 'INFO').upper()
    if level in _NOT_INFO:
        return False
    if is_important_log(entry):
        return False  # an error or warning: the main log read has it
    message = str(_field(entry, 'message'))
    return bool(_STRONG.search(message) or _WEAK.search(message))


def select_change_events(entries, max_lines=MAX_LINES, max_chars=MAX_CHARS):
    """Deduplicate (numbers ignored), rank strong operations first, keep the
    first ``max_lines`` that fit ``max_chars``, in time order."""
    patterns = {}
    for e in entries:
        if not is_change_event(e):
            continue
        message = ' '.join(str(_field(e, 'message')).split())[:MAX_LINE_CHARS]
        key = (str(_field(e, 'service')).lower(), _NUMBERS.sub('#', message.lower()))
        ts = _field(e, 'timestamp')
        ts = ts.isoformat() if hasattr(ts, 'isoformat') else str(ts or '')
        if key in patterns:
            patterns[key]['count'] += 1
            patterns[key]['timestamp'] = min(patterns[key]['timestamp'], ts) if ts else patterns[key]['timestamp']
            continue
        patterns[key] = {'timestamp': ts, 'service': str(_field(e, 'service')),
                         'message': message, 'count': 1,
                         '_score': 2 if _STRONG.search(message) else 1}
    ranked = sorted(patterns.values(), key=lambda p: (-p['_score'], p['timestamp']))
    kept, size = [], 0
    for p in ranked:
        line = format_change_event(p)
        if len(kept) >= max_lines or size + len(line) + 1 > max_chars:
            break
        kept.append({k: v for k, v in p.items() if k != '_score'})
        size += len(line) + 1
    return sorted(kept, key=lambda p: p['timestamp'])


def format_change_event(event) -> str:
    repeat = f" [x{event['count']}]" if event.get('count', 1) > 1 else ''
    service = f" [{event['service']}]" if event.get('service') else ''
    return f"[{event.get('timestamp', '')}]{service} {event.get('message', '')}{repeat}"


def fetch_change_events(provider, index_pattern, base_query, environment=None, env_labels=()):
    """The window's change and job events, or [] (never raises).

    Same store, locations, project, environment and window as the batch's
    error query; no level filter on the store side, because unstructured
    lines carry no level field. The words go to the store as ``message_any``;
    whatever the store could not filter is filtered here.
    """
    if provider is None or base_query is None:
        return []
    try:
        query = replace(base_query, severity=None, services=None, text_search=None,
                        message_any=list(CHANGE_EVENT_WORDS), max_results=FETCH_LIMIT)
        entries = list(provider.search(index_pattern, query) or [])
    except Exception as e:  # never fail or empty the batch
        logger.info('Change events not read: %s', e)
        return []
    if environment:
        try:
            from integrations.ingestion import is_log_matching_environment
            entries = [e for e in entries if is_log_matching_environment(e, environment, env_labels or ())]
        except Exception as e:
            logger.info('Change events environment filter skipped: %s', e)
    try:
        return select_change_events(entries)
    except Exception as e:
        logger.info('Change events not selected: %s', e)
        return []
