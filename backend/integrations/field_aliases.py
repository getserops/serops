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
]

ENVIRONMENT_ALIASES = [
    'environment',              # SerOps canonical
    'env',                      # Datadog USM
    'deployment.environment',   # OpenTelemetry semantic conventions
]

LOG_LEVEL_ALIASES = [
    'log_level',                # SerOps canonical
    'level',                    # Common (Zap, Bunyan, Winston, ...)
    'severity',                 # syslog, OpenTelemetry
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
        val = doc.get(key)
        if val:
            return val
    return default
