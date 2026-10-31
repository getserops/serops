"""Ingest health analysis for observability integrations.

Given a sample of records fetched from a user's log/metric provider,
report which canonical SerOps fields (``service_name``, ``project_name``,
etc.) are present, which are missing, and which industry-standard
aliases (Datadog USM ``service``, OpenTelemetry ``service.name``,
Kubernetes ``app``, ...) are covering the gap.

Used by:
  * ``python manage.py check_ingest --integration <id>`` (CLI)
  * ``GET /api/integrations/observability/<id>/ingest-health/`` (UI)

Both surfaces call ``collect_ingest_health(integration, ...)`` — which
loads the provider, samples recent records, and runs the analyzer.

Security notes:
  * Analyzer only reads FIELD NAMES from sampled records, not values.
    Real log messages / metric values never appear in the report.
    (The project-level "Check my data", ``Data/data_check.py``, does show
    the project / environment / service VALUES: identifiers, still never
    messages.)
  * ``collect_ingest_health`` clamps the sample window and size so a
    misconfigured caller can't DoS the user's own provider.
  * The API endpoint is admin-only (see ``views.py``).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from integrations.field_aliases import (
    lookup,
    ENVIRONMENT_ALIASES,
    LOG_LEVEL_ALIASES,
    ORGANISATION_NAME_ALIASES,
    PROJECT_NAME_ALIASES,
    SERVICE_NAME_ALIASES,
)

logger = logging.getLogger(__name__)


# Canonical fields that SerOps needs on ingested records, mapped to
# accepted alias lists. Order matters — canonical is always first.
CANONICAL_FIELDS: Dict[str, List[str]] = {
    'organisation_name': ORGANISATION_NAME_ALIASES,
    'project_name':      PROJECT_NAME_ALIASES,
    'service_name':      SERVICE_NAME_ALIASES,
    'environment':       ENVIRONMENT_ALIASES,
    'log_level':         LOG_LEVEL_ALIASES,
}

# Sample-window / sample-size clamps — protect the user's provider
# from an accidental firehose query.
MIN_SAMPLE_WINDOW_MIN = 1
MAX_SAMPLE_WINDOW_MIN = 1440    # 24h
MIN_SAMPLE_SIZE = 10
MAX_SAMPLE_SIZE = 1000


# ---------------------------------------------------------------------------
# Report models
# ---------------------------------------------------------------------------

@dataclass
class FieldReport:
    """Per-canonical-field summary across the sampled records."""
    canonical: str
    canonical_count: int
    alias_counts: Dict[str, int]
    missing_count: int
    total: int

    @property
    def canonical_pct(self) -> float:
        return round(100 * self.canonical_count / self.total, 1) if self.total else 0.0

    @property
    def any_present_count(self) -> int:
        return self.total - self.missing_count

    @property
    def coverage_pct(self) -> float:
        """Percentage of records that have EITHER canonical OR any alias."""
        return round(100 * self.any_present_count / self.total, 1) if self.total else 0.0

    @property
    def severity(self) -> str:
        """One of 'ok' (canonical dominant), 'info' (aliases cover),
        'warning' (many records lack the field entirely)."""
        if self.canonical_pct >= 80:
            return 'ok'
        if self.total and self.coverage_pct >= 80:
            return 'info'
        return 'warning'

    @property
    def message(self) -> str:
        if self.total == 0:
            return f'No records to analyse for `{self.canonical}`.'
        if self.severity == 'ok':
            return f'{self.canonical_count}/{self.total} records tagged with `{self.canonical}` (canonical).'
        if self.severity == 'info':
            top = sorted(self.alias_counts.items(), key=lambda x: -x[1])
            top_summary = ', '.join(f'{a}={c}' for a, c in top[:3])
            return (
                f'Canonical `{self.canonical}` missing/rare; alias fields '
                f'cover {self.coverage_pct}% ({top_summary}). SerOps '
                f'auto-aliases at query time — analysis works.'
            )
        return (
            f'{self.missing_count}/{self.total} records missing '
            f'`{self.canonical}` and all known aliases. These records '
            f'will NOT participate in filtered analysis.'
        )

    def to_dict(self) -> dict:
        return {
            'canonical': self.canonical,
            'canonical_count': self.canonical_count,
            'canonical_pct': self.canonical_pct,
            'alias_counts': dict(self.alias_counts),
            'missing_count': self.missing_count,
            'coverage_pct': self.coverage_pct,
            'severity': self.severity,
            'message': self.message,
        }


@dataclass
class IngestHealthReport:
    integration_id: int
    integration_name: str
    provider: str
    provider_type: str  # 'logs' | 'metrics'
    sample_size: int
    sample_window_minutes: int
    sampled_at: datetime
    fields: List[FieldReport] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'integration_id': self.integration_id,
            'integration_name': self.integration_name,
            'provider': self.provider,
            'provider_type': self.provider_type,
            'sample_size': self.sample_size,
            'sample_window_minutes': self.sample_window_minutes,
            'sampled_at': self.sampled_at.isoformat() if self.sampled_at else None,
            'fields': [f.to_dict() for f in self.fields],
            'warnings': list(self.warnings),
            'recommendations': list(self.recommendations),
            'error': self.error,
        }


# ---------------------------------------------------------------------------
# Analyzer — pure function, easy to test
# ---------------------------------------------------------------------------

def analyze_records(
    records: List[Dict[str, Any]],
    fields_to_check: Optional[Dict[str, List[str]]] = None,
) -> List[FieldReport]:
    """Count canonical vs alias field presence across sampled records.

    Each record is treated as a flat dict of ``key -> value``. For each
    canonical field, count records where:
      * The canonical key is present and non-empty (``canonical_count``)
      * OR one of the aliases is present and non-empty
        (contributes to ``alias_counts[first-matching-alias]``)
      * OR neither (``missing_count``)

    If both canonical AND an alias are present, canonical wins. Aliases
    are checked in the order given (so the "first matching" alias is
    the highest-precedence alternative).

    Nested/dotted keys (e.g. OTEL's ``service.name``) are treated as
    literal flat keys. Adapters that return nested docs should flatten
    the fields they care about into the ``labels`` dict before passing
    records here.
    """
    if fields_to_check is None:
        fields_to_check = CANONICAL_FIELDS

    total = len(records)
    reports: List[FieldReport] = []

    for canonical, aliases in fields_to_check.items():
        canonical_count = 0
        alias_counts: Dict[str, int] = {}
        missing = 0

        for record in records:
            if _has_nonempty(record, canonical):
                canonical_count += 1
                continue
            found = None
            for alias in aliases:
                if alias == canonical:
                    continue
                if _has_nonempty(record, alias):
                    found = alias
                    break
            if found:
                alias_counts[found] = alias_counts.get(found, 0) + 1
            else:
                missing += 1

        reports.append(FieldReport(
            canonical=canonical,
            canonical_count=canonical_count,
            alias_counts=alias_counts,
            missing_count=missing,
            total=total,
        ))

    return reports


def _has_nonempty(record: Dict[str, Any], key: str) -> bool:
    """True if ``key`` holds a non-empty value, stored flat or nested
    (``service.name`` in an Elastic Common Schema record is an object path).
    A nested object is not a value."""
    val = lookup(record, key)
    return bool(val) and not isinstance(val, (dict, list))


# ---------------------------------------------------------------------------
# Warnings + recommendations from a report
# ---------------------------------------------------------------------------

def build_warnings(fields: List[FieldReport]) -> List[str]:
    warnings: List[str] = []
    for f in fields:
        if f.severity == 'warning' and f.total > 0:
            warnings.append(
                f'{f.missing_count}/{f.total} records missing '
                f'`{f.canonical}` (canonical or any alias).'
            )
    return warnings


def build_recommendations(fields: List[FieldReport]) -> List[str]:
    recs: List[str] = []
    for f in fields:
        if f.severity == 'info' and f.alias_counts:
            top_alias = max(f.alias_counts.items(), key=lambda x: x[1])[0]
            recs.append(
                f'`{f.canonical}` is being read via alias `{top_alias}` '
                f'(auto-aliased, works today). To standardise, tag your '
                f'source with `{f.canonical}` directly.'
            )
    return recs


# ---------------------------------------------------------------------------
# Collector — sample records from an integration
# ---------------------------------------------------------------------------

def collect_ingest_health(
    integration,
    sample_size: int = 100,
    sample_window_minutes: int = 60,
) -> IngestHealthReport:
    """Sample records from the integration and return an analysis report.

    Handles clamping of sample size + window, provider-agnostic
    sampling (log providers use ``search()``, metric providers use
    ``discover_hosts()``), and error-to-report conversion so callers
    always get a valid ``IngestHealthReport`` back.
    """
    sample_size = _clamp(sample_size, MIN_SAMPLE_SIZE, MAX_SAMPLE_SIZE)
    sample_window_minutes = _clamp(
        sample_window_minutes, MIN_SAMPLE_WINDOW_MIN, MAX_SAMPLE_WINDOW_MIN,
    )
    sampled_at = datetime.now(timezone.utc)

    report = IngestHealthReport(
        integration_id=integration.id,
        integration_name=getattr(integration, 'display_name', str(integration.pk)),
        provider=integration.provider,
        provider_type=_provider_type(integration),
        sample_size=sample_size,
        sample_window_minutes=sample_window_minutes,
        sampled_at=sampled_at,
    )

    try:
        records = _sample_records(integration, sample_size, sample_window_minutes)
    except Exception as e:
        logger.warning('collect_ingest_health sample failed for integration %s: %s',
                       integration.id, e)
        report.error = f'Could not sample records: {e}'
        return report

    report.sample_size = len(records)  # actual count returned

    # No records is not a tagging verdict. Every field would come back
    # 'warning' purely because total == 0, which reads as "you are missing
    # all five canonical fields" and sends the operator off to re-tag a
    # cluster that may be perfectly configured. Say what actually
    # happened instead of rendering an empty table.
    if not records:
        report.error = (
            f'No records returned in the last {sample_window_minutes} min, '
            f'so tagging could not be assessed. Either nothing is being '
            f'ingested into this integration, or the window predates the '
            f'data. Widen it with --minutes and retry.'
        )
        return report

    report.fields = analyze_records(records)
    report.warnings = build_warnings(report.fields)
    report.recommendations = build_recommendations(report.fields)
    return report


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _provider_type(integration) -> str:
    caps = getattr(integration, 'capabilities', []) or []
    # 'logs' takes precedence when both are configured — logs are the
    # primary validation target for tag naming.
    if 'logs' in caps:
        return 'logs'
    if 'metrics' in caps:
        return 'metrics'
    return 'unknown'


def _sample_records(integration, sample_size: int, minutes: int) -> List[Dict[str, Any]]:
    """Fetch a sample of records from the provider, as flat dicts."""
    from integrations.registry import IntegrationRegistry

    ptype = _provider_type(integration)
    if ptype == 'logs':
        return _sample_log_records(integration, sample_size, minutes)
    if ptype == 'metrics':
        return _sample_metric_records(integration, sample_size)
    return []


def _sample_log_records(integration, sample_size: int, minutes: int) -> List[Dict[str, Any]]:
    from integrations.registry import IntegrationRegistry
    from integrations.schemas import LogQuery

    provider = IntegrationRegistry.get_log_provider(
        integration.log_adapter_class,
        integration.get_config(),
        org_id=integration.organisation_id,
    )

    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes)
    query = LogQuery(time_range=(start, end), max_results=sample_size)

    # Different adapters accept different index_pattern semantics; pass
    # None so each adapter falls back to its default lookup.
    try:
        entries = provider.search(None, query)
    except TypeError:
        # Some older adapter signatures require the index_pattern arg positionally.
        entries = provider.search('*', query)

    # Adapters deliberately swallow transport/query errors and return []
    # so the batch pipeline degrades instead of aborting. For validation
    # that is exactly wrong: "the query was rejected" must not be
    # presented as "your logs are missing these fields". Adapters that
    # track last_error let us tell the two apart.
    adapter_error = getattr(provider, 'last_error', None)
    if not entries and adapter_error:
        raise RuntimeError(adapter_error)

    records = []
    for entry in entries:
        # LogEntry.labels holds provider-specific tags/fields. That's
        # what tagging validation cares about — the raw field names
        # the user has on their source.
        rec = dict(entry.labels) if getattr(entry, 'labels', None) else {}
        # Also surface the LogEntry canonical fields under their canonical
        # names, since some adapters extract these into typed fields
        # before populating labels. Only fill if not already present.
        if getattr(entry, 'level', None):
            rec.setdefault('log_level', entry.level)
        if getattr(entry, 'service', None):
            rec.setdefault('service_name', entry.service)
        records.append(rec)
    return records


def _sample_metric_records(integration, sample_size: int) -> List[Dict[str, Any]]:
    from integrations.registry import IntegrationRegistry

    provider = IntegrationRegistry.get_metric_provider(
        integration.metric_adapter_class,
        integration.get_config(),
        org_id=integration.organisation_id,
    )

    # Metric providers don't have a "search" method — validate what
    # labels their host discovery returns.
    org_hint = ''  # empty triggers provider defaults; we just want a peek at label shapes
    hosts = provider.discover_hosts(org_hint)[:sample_size]
    records = []
    for h in hosts:
        rec = dict(h.labels) if getattr(h, 'labels', None) else {}
        # Surface HostInfo canonical hints
        if getattr(h, 'environment', None):
            rec.setdefault('environment', h.environment)
        if getattr(h, 'project', None):
            rec.setdefault('project_name', h.project)
        records.append(rec)
    return records
