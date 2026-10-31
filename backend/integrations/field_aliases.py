"""Canonical field-name aliases for user-side log/metric enrichment.

SerOps' canonical vocabulary is (`organisation_name`, `project_name`,
`service_name`, `environment`, `log_level`). But existing DevOps stacks
tag data with their own conventions:

- **Datadog USM** (Unified Service Tagging) — `service`, `env`, `version`
- **OpenTelemetry semantic conventions** — `service.name`,
  `deployment.environment`
- **Kubernetes standard labels** — `app`, `app.kubernetes.io/name`
- Various — `level`, `severity`, `status` (Datadog) for log level

Requiring users to retag everything to SerOps' names is a huge
adoption tax. Instead: adapters accept the common alternatives
at both **query time** (search clauses match ANY alias) and
**parse time** (field-extraction helpers try aliases in order).

This module is the single source of truth for the alias lists.
When adding a new alias:
1. Add it to the appropriate list below (canonical first, most
   common alternatives next).
2. Add a test case in ``integrations/tests/test_field_aliases.py``.
3. If it needs special handling for a specific provider (e.g., Loki
   can't OR-across-stream-selectors easily), document that in the
   provider's page under ``docs/integrations/``.
"""

from typing import Any, Iterable, Mapping, Optional


# ---------------------------------------------------------------------------
# Alias lists (canonical first)
# ---------------------------------------------------------------------------

SERVICE_NAME_ALIASES = [
    'service_name',             # SerOps canonical
    'service',                  # Datadog USM
    'service.name',             # OpenTelemetry semantic conventions
    'app',                      # Kubernetes common label
    'app.kubernetes.io/name',   # Kubernetes standard label
    'kubernetes.labels.app',    # Fluent Bit / Filebeat kubernetes metadata
    'kubernetes.container_name',  # Fluent Bit kubernetes filter
    'kubernetes.container.name',  # Filebeat / Elastic Agent (ECS)
    'resource.attributes.service.name',  # OTel Collector elasticsearch exporter (otel mode)
]

ENVIRONMENT_ALIASES = [
    'environment',              # SerOps canonical
    'env',                      # Datadog USM
    'deployment.environment',   # OpenTelemetry semantic conventions (old)
    'deployment.environment.name',  # OpenTelemetry semantic conventions >= 1.27
    'service.environment',      # Elastic Common Schema (ECS)
    'resource.attributes.deployment.environment.name',  # OTel Collector elasticsearch exporter (otel mode)
    'resource.attributes.deployment.environment',
]

LOG_LEVEL_ALIASES = [
    'log_level',                # SerOps canonical
    'level',                    # Common (Zap, Bunyan, Winston, ...)
    'log.level',                # Elastic Common Schema (Filebeat, Elastic Agent)
    'severity',                 # syslog, OpenTelemetry
    'severity_text',            # OpenTelemetry log record
    'status',                   # Datadog log-severity field
]

# Organisation + project — SerOps-native concepts. Less variation
# in the wild but a couple of aliases people use.
ORGANISATION_NAME_ALIASES = [
    'organisation_name',        # SerOps canonical
    'organization_name',        # US-English spelling variant
    'org_name',
]

PROJECT_NAME_ALIASES = [
    'project_name',             # SerOps canonical
    'project',
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def first_present(
    doc: Mapping[str, Any],
    aliases: Iterable[str],
    default: Optional[Any] = '',
) -> Any:
    """Return the first non-empty value from ``doc`` for any alias key.

    Used to read a canonical field from a user log document that
    might have tagged it under any of several alternate names.
    Falsy values (empty string, ``None``) are skipped so a present-but-
    empty ``service`` field doesn't shadow a real ``service_name``.

    >>> first_present({'service': 'checkout'}, SERVICE_NAME_ALIASES)
    'checkout'
    >>> first_present({'service_name': '', 'app': 'api'}, SERVICE_NAME_ALIASES)
    'api'
    >>> first_present({}, SERVICE_NAME_ALIASES, default='unknown')
    'unknown'
    """
    for key in aliases:
        val = lookup(doc, key)
        # A nested object (ECS ``service: {name: ...}``) is not a value.
        if val and not isinstance(val, (dict, list)):
            return val
    return default


def lookup(doc: Any, path: str) -> Any:
    """Read ``path`` from ``doc``, whether it is stored flat or nested.

    Shippers disagree on dotted names: OpenTelemetry and Datadog send a flat
    ``"service.name"`` key, Elastic Common Schema documents nest it as
    ``{"service": {"name": ...}}``, and Kubernetes label keys contain dots
    of their own (``app.kubernetes.io/name``). Every split is tried, the
    flat key first.

    >>> lookup({'service': {'name': 'checkout'}}, 'service.name')
    'checkout'
    >>> lookup({'service.name': 'checkout'}, 'service.name')
    'checkout'
    """
    if not isinstance(doc, Mapping):
        return None
    if path in doc:
        return doc[path]
    parts = path.split('.')
    for i in range(1, len(parts)):
        head = '.'.join(parts[:i])
        sub = doc.get(head)
        if isinstance(sub, Mapping):
            found = lookup(sub, '.'.join(parts[i:]))
            if found is not None:
                return found
    return None


def first_present_with_key(doc: Mapping[str, Any], aliases: Iterable[str]):
    """Like :func:`first_present` but also returns the alias that matched
    (numeric levels mean different things under different keys)."""
    for key in aliases:
        val = lookup(doc, key)
        if val not in (None, '') and not isinstance(val, (dict, list)):
            return key, val
    return None, None


# ---------------------------------------------------------------------------
# Environment value aliases
# ---------------------------------------------------------------------------

# Spellings of the same environment. SerOps queries every spelling of the
# environment it analyses: logs tagged ``prod`` belong to ``production``.
ENVIRONMENT_VALUE_ALIASES = {
    'production': ['production', 'prod', 'prd'],
    'staging': ['staging', 'stage', 'stg', 'preprod'],
    'development': ['development', 'dev'],
}


def environment_values(environment: Optional[str], extra: Iterable[str] = ()) -> list:
    """Every spelling of ``environment`` to query, the given one first.

    ``extra`` adds the values a project environment says its logs carry
    (``ProjectEnvironment.log_label_value``, e.g. ``live``).

    >>> environment_values('production')
    ['production', 'prod', 'prd']
    >>> environment_values('prod')
    ['prod', 'production', 'prd']
    >>> environment_values('qa-eu')
    ['qa-eu']
    """
    if not environment:
        return []
    values = [environment]
    lowered = environment.lower()
    for spellings in ENVIRONMENT_VALUE_ALIASES.values():
        if lowered in spellings:
            values += [v for v in spellings if v not in values]
    values += [v for v in extra if v and v not in values]
    return values
