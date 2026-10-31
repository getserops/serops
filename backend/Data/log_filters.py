"""
The filters a scheduled analysis applies to fetched logs, shared with the
project's "Check my data" so both say the same thing about the same logs.
"""
import logging

from integrations.schemas import _detect_level_from_line, level_of

logger = logging.getLogger(__name__)

# What the scheduled query asks the log store for.
SEVERITIES = ['ERROR', 'WARNING', 'CRITICAL']

_IMPORTANT_LEVELS = ('WARNING', 'WARN', 'ERROR', 'CRITICAL', 'ERR', 'FATAL')

# Words that make a log worth analysing whatever its level says.
IMPORTANT_MESSAGE_WORDS = (
    'EXCEPTION', 'TRACEBACK', 'PANIC', 'FAILED', 'FAILURE', 'INVALID USER',
    'AUTHENTICATION FAILURE', 'CONNECTION REFUSED', 'PERMISSION DENIED', 'OUT OF MEMORY',
    'DEADLOCK', 'TIMED OUT', 'TIMEOUT',
)


def is_important_log(log):
    """A warning, an error, or a line that reads like one."""
    if hasattr(log, 'message'):
        message = log.message or ''
        level = (log.level or '').upper()
    else:
        source = log.get('_source', {})
        message = source.get('message', '')
        level = level_of(source, message)

    if level in _IMPORTANT_LEVELS:
        return True
    # A level written in the line itself ("... ERROR ...", "level=warn")
    if _detect_level_from_line(message) in ('ERROR', 'WARN'):
        return True
    msg_upper = message.upper()
    if any(word in msg_upper for word in IMPORTANT_MESSAGE_WORDS):
        return True
    # Security related messages
    if 'sshd' in message and ('invalid user' in message.lower() or 'authentication failure' in message.lower()):
        return True
    return False


def log_service(log):
    """The service a log came from, lowercased ('' when it names none)."""
    if hasattr(log, 'service'):
        return (log.service or '').lower()
    return str(log.get('_source', {}).get('service_name', '')).lower()


def registered_service_names(project):
    from Projects.models import ProjectService
    return {s.name.lower() for s in ProjectService.objects.filter(project=project) if s.name}


def system_indices(provider):
    """``system-*`` indices on the provider's own cluster (Elasticsearch-like only)."""
    try:
        if provider is not None and hasattr(getattr(provider, 'client', None), 'cat'):
            return [i['index'] for i in provider.client.cat.indices(index="system-*", h="index", format="json")]
    except Exception as e:
        logger.debug(f"No system indices: {e}")
    return []


def project_log_locations(project, provider):
    """Where the project's logs are read from: indices, log groups or
    streams the provider discovers, then the legacy per-project indices."""
    found = []
    try:
        found.extend(provider.get_indices(project) or [])
    except Exception as e:
        logger.warning(f"Failed to discover indices via provider for project '{project.name}': {e}")

    client = getattr(provider, 'client', None)
    if not found and project.es_index_name:
        try:
            if client is not None and client.indices.exists(index=project.es_index_name):
                found.append(project.es_index_name)
        except Exception as e:
            logger.warning(f"Error checking legacy index: {e}")
    if getattr(project, 'app_logs_index_name', None):
        try:
            if client is not None and client.indices.exists(index=project.app_logs_index_name):
                found.append(project.app_logs_index_name)
        except Exception as e:
            logger.warning(f"Error checking app logs index: {e}")
    return found
