"""
Canonical Data Models for Log and Metric Integrations.

All adapters return these types. AI prompts, dedup logic, and frontend
consume only canonical models — never provider-shaped data.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from integrations.field_aliases import (
    ENVIRONMENT_ALIASES,
    LOG_LEVEL_ALIASES,
    PROJECT_NAME_ALIASES,
    SERVICE_NAME_ALIASES,
)

# What ``LogQuery.to_logql()`` returns when the query carries no label
# matchers at all. This is NOT a valid LogQL query — Loki rejects it with
# "queries require at least one regexp or equality matcher that does not
# have an empty-compatible value". Loki has no way to express "every
# stream", so a caller that needs an unfiltered sample (the ingest-health
# validator) has to discover a real label first; the Loki adapter keys off
# this exact constant to do that. Kept as a named constant so the adapter
# and the query builder cannot drift apart.
EMPTY_LOGQL_SELECTOR = "{}"


@dataclass
class LogEntry:
    """
    Provider-agnostic log entry.
    ES `_source`, Loki stream, or OpenSearch hit all normalize to this.
    """
    timestamp: datetime
    message: str
    level: str = "INFO"        # ERROR, WARN, INFO, DEBUG
    service: str = ""
    host: str = ""
    labels: dict = field(default_factory=dict)  # provider-specific metadata
    trace_id: str = ""
    raw_id: str = ""           # original provider ID (_id in ES, etc.)
    deduplicated: bool = False
    occurrence_count: int = 1

    @classmethod
    def from_es_hit(cls, hit: dict) -> "LogEntry":
        """Convert an Elasticsearch hit to canonical LogEntry."""
        source = hit.get("_source", {})
        # Level field: try log_level (Fluentd), then level, then severity
        raw_level = (
            source.get("log_level")
            or source.get("level")
            or source.get("severity")
            or "INFO"
        )
        # Service field: try service_name (Fluentd), then kubernetes.container_name, then service
        raw_service = (
            source.get("service_name")
            or source.get("kubernetes", {}).get("container_name")
            or source.get("service", "")
        )
        return cls(
            timestamp=_parse_timestamp(source.get("@timestamp", "")),
            message=source.get("message", ""),
            level=_detect_level(raw_level),
            service=raw_service,
            host=source.get("hostname", source.get("host", "")),
            labels={k: v for k, v in source.items() if k not in ("message", "@timestamp", "level", "severity")},
            trace_id=source.get("trace_id", ""),
            raw_id=hit.get("_id", ""),
        )

    def to_legacy_dict(self) -> dict:
        """
        Convert canonical LogEntry back to legacy ES-style dict.
        Bridge function to maintain compatibility with existing key-based logic.
        """
        source = {
            '@timestamp': self.timestamp.isoformat(),
            'message': self.message,
            'level': self.level,
            'service': self.service,
            'host': self.host,
            'trace_id': self.trace_id,
            **self.labels  # Include all other labels
        }
        # Ensure legacy environment fields if they exist in labels
        if 'environment' in self.labels:
            source['environment'] = self.labels['environment']
        
        if self.deduplicated:
            source['deduplicated'] = True
            source['occurrence_count'] = self.occurrence_count
            
        return {
            '_id': self.raw_id,
            '_source': source,
            # include _index if available in labels or generic
            '_index': self.labels.get('_index', 'unknown')
        }


@dataclass
class TimeSeriesPoint:
    """Single data point in a time series."""
    timestamp: datetime
    value: float


@dataclass
class TimeSeries:
    """
    Provider-agnostic metric time series.
    All metric providers normalize to this.
    """
    metric_name: str
    labels: dict = field(default_factory=dict)
    points: list = field(default_factory=list)  # list[TimeSeriesPoint]

    @property
    def values(self) -> list:
        """Get just the float values for stats calculations."""
        return [p.value for p in self.points]

    @property
    def is_empty(self) -> bool:
        return len(self.points) == 0


@dataclass
class HostInfo:
    """Discovered host from metric provider."""
    hostname: str
    labels: dict = field(default_factory=dict)
    environment: str = ""
    project: str = ""


@dataclass
class LogStream:
    """
    Provider-agnostic log routing descriptor.
    
    Drives index/stream naming for all log backends:
    - ES/OpenSearch: index name  →  serops-{category}-{org_slug}
    - Loki: stream labels        →  {category="cicd", organisation_name="acme"}
    - Datadog: tags + source     →  source:serops, organisation_name:acme
    - CloudWatch: log group      →  /serops/{category}/{org_slug}
    """
    category: str           # "cicd" | "application" | "infrastructure"
    org_slug: str           # Tenant isolation key — drives index name

    # Contextual metadata (included in docs, not in index splits)
    project: str = ""       # project name
    service: str = ""       # service name
    environment: str = ""   # "production" | "staging" | ...

    def to_index_name(self) -> str:
        """Default index name pattern (adapters can override)."""
        return f"serops-{self.category}-{self.org_slug}"

    def to_loki_labels(self) -> dict:
        """Convert to Loki stream labels."""
        labels = {"category": self.category, "organisation_name": self.org_slug}
        if self.project:
            labels["project_name"] = self.project
        if self.service:
            labels["service_name"] = self.service
        if self.environment:
            labels["environment"] = self.environment
        return labels

    def to_datadog_tags(self) -> list:
        """Convert to Datadog tags list."""
        tags = [f"source:serops", f"category:{self.category}", f"organisation_name:{self.org_slug}"]
        if self.project:
            tags.append(f"project_name:{self.project}")
        if self.service:
            tags.append(f"service_name:{self.service}")
        if self.environment:
            tags.append(f"environment:{self.environment}")
        return tags

    def to_cloudwatch_log_group(self) -> str:
        """Convert to CloudWatch log group name."""
        return f"/serops/{self.category}/{self.org_slug}"


@dataclass
class LogQuery:
    """
    Provider-agnostic log query.
    
    Replaces raw ES DSL, LogQL, Datadog query strings, and CloudWatch
    Insights queries with a single, agnostic representation.
    Each adapter's search() translates this into its native format.
    """
    time_range: Optional[tuple] = None  # (start: datetime, end: datetime)
    severity: Optional[list] = None     # ["ERROR", "WARNING", "CRITICAL"]
    services: Optional[list] = None     # filter by serops_meta.service_name
    # SECURITY: if any future endpoint accepts `services` from user
    # input (query params, POST body), the caller MUST first pass the
    # list through `LogQuery.scope_services_to_org()` so cross-org
    # service names can't leak in. Today all callers (Data/tasks.py)
    # populate this from server-controlled Project/Service records, so
    # no runtime enforcement is needed — but the helper below exists
    # so it's easy to do it right when a new endpoint adds one.
    project: Optional[str] = None       # filter by serops_meta.project_name
    environment: Optional[str] = None   # filter by serops_meta.environment
    event_type: Optional[str] = None    # "cicd_job_failure"
    text_search: Optional[str] = None   # free-text search in message
    category: Optional[str] = None      # "cicd" filter on serops_meta
    max_results: int = 5000

    def scope_services_to_org(self, organisation) -> "LogQuery":
        """Filter ``self.services`` to only names belonging to ``organisation``.

        Mutates in place and returns self so callers can chain it into
        a construction line. No-op if ``services`` is None or empty.

        Use this any time ``services`` comes from an untrusted source
        (query params, POST body). Reads ProjectService names for the
        org and drops anything not in that set. Silently — no error
        raised, because a caller passing a mix of "real" + "junk"
        names shouldn't be blocked from getting results for the real
        ones. The dropped names are logged for observability.

        Safe for server-controlled callers to also invoke — a no-op if
        services was already populated from ProjectService.
        """
        if not self.services:
            return self
        # Import lazily to avoid a Django-model import at schemas
        # module load time (schemas.py should be importable in tests
        # that don't touch the DB).
        try:
            from Projects.models import ProjectService
        except ImportError:
            return self
        if organisation is None:
            self.services = []
            return self
        allowed = set(
            ProjectService.objects.filter(
                project__organisation=organisation,
            ).values_list('name', flat=True)
        )
        dropped = [s for s in self.services if s not in allowed]
        if dropped:
            import logging
            logging.getLogger(__name__).info(
                "scope_services_to_org dropped %d out-of-org service name(s): %s",
                len(dropped), dropped,
            )
        self.services = [s for s in self.services if s in allowed]
        return self

    def to_es_dsl(self) -> dict:
        """Translate to Elasticsearch DSL query.

        Alias-aware: for canonical fields with common alternatives
        (``service_name`` / ``service`` / ``app`` / etc.), builds a
        ``bool.should`` clause that matches ANY of the aliases. Users
        with Datadog USM (``service``), OpenTelemetry (``service.name``),
        or Kubernetes (``app``) tagging get results without retagging.
        """
        must = []
        filter_clauses = []

        if self.time_range:
            start, end = self.time_range
            filter_clauses.append({
                "range": {
                    "@timestamp": {
                        "gte": start.isoformat() if hasattr(start, 'isoformat') else start,
                        "lte": end.isoformat() if hasattr(end, 'isoformat') else end,
                    }
                }
            })

        if self.severity:
            normalized = [s.upper() for s in self.severity]
            # log_level.keyword is the ES-canonical mapped field; each
            # alias is queried as a plain field (users may or may not
            # have a .keyword mapping on aliases). minimum_should_match=1
            # ensures at least one alias matches.
            should = [{"terms": {"log_level.keyword": normalized}}]
            should.extend(
                {"terms": {alias: normalized}} for alias in LOG_LEVEL_ALIASES
            )
            filter_clauses.append({
                "bool": {"should": should, "minimum_should_match": 1}
            })

        # E9-1 fix: use `.keyword` sub-field for exact-match filters on
        # canonical string fields. On indices with default dynamic
        # mapping, text fields are analyzed (tokenised) — a term match
        # against the raw value fails because ES tokenises to
        # ``["acme","checkout"]`` while our filter sends "acme-checkout".
        # Every dynamically-mapped field automatically gets a
        # ``.keyword`` sub-field with keyword type (untokenised) — we
        # match against BOTH the plain alias (works on ILM templates
        # with explicit keyword mapping) AND the ``.keyword`` sub-field
        # (works on fresh dynamic-mapped indices) so both configurations
        # succeed.
        def _keyword_variants(alias):
            """Yield both the plain alias and its .keyword variant."""
            yield alias
            if not alias.endswith('.keyword'):
                yield f'{alias}.keyword'

        if self.project:
            should_terms = []
            for alias in PROJECT_NAME_ALIASES:
                for variant in _keyword_variants(alias):
                    should_terms.append({"term": {variant: self.project}})
            filter_clauses.append({
                "bool": {"should": should_terms, "minimum_should_match": 1}
            })

        if self.environment:
            should_terms = []
            for alias in ENVIRONMENT_ALIASES:
                for variant in _keyword_variants(alias):
                    should_terms.append({"term": {variant: self.environment}})
            filter_clauses.append({
                "bool": {"should": should_terms, "minimum_should_match": 1}
            })

        if self.event_type:
            filter_clauses.append({
                "bool": {
                    "should": [
                        {"term": {"event_type": self.event_type}},
                        {"term": {"event_type.keyword": self.event_type}},
                    ],
                    "minimum_should_match": 1,
                }
            })

        if self.services:
            should_terms = []
            for alias in SERVICE_NAME_ALIASES:
                for variant in _keyword_variants(alias):
                    should_terms.append({"terms": {variant: self.services}})
            filter_clauses.append({
                "bool": {"should": should_terms, "minimum_should_match": 1}
            })

        if self.category:
            filter_clauses.append({
                "bool": {
                    "should": [
                        {"term": {"category": self.category}},
                        {"term": {"category.keyword": self.category}},
                    ],
                    "minimum_should_match": 1,
                }
            })

        if self.text_search:
            must.append({
                "match": {"message": self.text_search}
            })

        query = {"bool": {}}
        if must:
            query["bool"]["must"] = must
        if filter_clauses:
            query["bool"]["filter"] = filter_clauses
        if not must and not filter_clauses:
            query = {"match_all": {}}

        return {"query": query, "size": self.max_results}

    def to_logql(self) -> str:
        """Translate to LogQL query for Loki."""
        label_matchers = []
        if self.project:
            label_matchers.append(f'project_name="{self.project}"')
        if self.environment:
            label_matchers.append(f'environment="{self.environment}"')
        if self.category:
            label_matchers.append(f'category="{self.category}"')
        if self.services:
            # Separator is "|" with NO surrounding space. A "| " join makes
            # every alternative after the first carry a leading space, so
            # `service_name=~"api| checkout"` matches `api` and nothing
            # else — RE2 treats " checkout" as a literal with a space.
            # Verified against a live Loki: the spaced form returned 1 of
            # 2 streams, silently. Multi-service batches fed the AI logs
            # from only the first service.
            label_matchers.append(f'service_name=~"{"|".join(self.services)}"')

        selector = "{" + ", ".join(label_matchers) + "}" if label_matchers else EMPTY_LOGQL_SELECTOR

        filters = []
        if self.severity:
            # Severity is a LINE filter (`|~`), not a label filter (`| x=~`).
            #
            # `| log_level=~"..."` only works if log_level is a Loki label,
            # and it essentially never is: promoting severity to a label
            # multiplies Loki's label cardinality, so collectors leave it in
            # the line. Verified against a live Loki — the stream selector
            # alone returned 500 lines, and appending
            # `| log_level=~"ERROR|WARNING|CRITICAL"` returned ZERO. Every
            # batch for every Loki user was analysing an empty log set, and
            # the batch still reported success.
            #
            # This is a coarse pre-filter to cut transfer volume, not the
            # final classification: `_detect_level_from_line` decides the
            # actual level per entry once the lines arrive. So a false
            # positive (the word "error" in an INFO body) is harmless, while
            # a false negative would silently lose data — which is why no
            # word-boundary anchoring is applied here.
            filters.append(f'|~ "(?i)({_logql_severity_alternatives(self.severity)})"')
        if self.text_search:
            filters.append(f'|~ "{self.text_search}"')
        if self.event_type:
            filters.append(f'| event_type="{self.event_type}"')

        return selector + " " + " ".join(filters) if filters else selector

    def to_datadog_query(self) -> str:
        """Translate to Datadog log search query.

        Alias-aware: uses Datadog's OR syntax so a search for
        ``service=checkout`` matches records tagged with ``service_name``,
        ``service``, ``service.name``, ``app``, or ``app.kubernetes.io/name``.
        Datadog USM users (with ``service``/``env``) get results
        without adding SerOps-specific tags.
        """
        parts = []

        def _or_across_aliases(value_expr: str, aliases: list) -> str:
            return "(" + " OR ".join(f"@{alias}:{value_expr}" for alias in aliases) + ")"

        if self.project:
            parts.append(_or_across_aliases(self.project, PROJECT_NAME_ALIASES))

        if self.environment:
            parts.append(_or_across_aliases(self.environment, ENVIRONMENT_ALIASES))

        if self.event_type:
            parts.append(f"@event_type:{self.event_type}")

        if self.severity:
            values = " OR ".join(s.lower() for s in self.severity)
            # `status` is Datadog's native severity field (no @-prefix);
            # other aliases need the @ prefix for log-attribute lookup.
            severity_clauses = [f"status:({values})"]
            severity_clauses.extend(
                f"@{alias}:({values})" for alias in LOG_LEVEL_ALIASES
            )
            parts.append("(" + " OR ".join(severity_clauses) + ")")

        if self.services:
            values = " OR ".join(self.services)
            parts.append(_or_across_aliases(f"({values})", SERVICE_NAME_ALIASES))

        if self.text_search:
            parts.append(self.text_search)
        if self.category:
            parts.append(f"@category:{self.category}")
        return " ".join(parts) if parts else "*"

    def to_cloudwatch_insights(self) -> str:
        """Translate to CloudWatch Logs Insights query.

        Alias-aware: emits ``(field_a = 'X' or field_b = 'X' ...)``
        clauses so records tagged with any of the accepted alternatives
        match. Users on ECS/EKS with Container Insights typically emit
        ``service`` (Datadog USM style); native support saves them
        from double-tagging.
        """
        filters = []

        def _or_across_aliases(aliases: list, value) -> str:
            # value can be a scalar or a list (for `in [...]` clauses).
            if isinstance(value, list):
                vlist = ", ".join(f"'{v}'" for v in value)
                clauses = [f"{alias} in [{vlist}]" for alias in aliases]
            else:
                clauses = [f"{alias} = '{value}'" for alias in aliases]
            return "(" + " or ".join(clauses) + ")"

        if self.severity:
            normalized = [s.upper() for s in self.severity]
            filters.append(_or_across_aliases(LOG_LEVEL_ALIASES, normalized))
        if self.project:
            filters.append(_or_across_aliases(PROJECT_NAME_ALIASES, self.project))
        if self.environment:
            filters.append(_or_across_aliases(ENVIRONMENT_ALIASES, self.environment))
        if self.event_type:
            filters.append(f"event_type = '{self.event_type}'")
        if self.services:
            filters.append(_or_across_aliases(SERVICE_NAME_ALIASES, self.services))
        if self.text_search:
            filters.append(f"@message like '{self.text_search}'")

        where = " and ".join(filters)
        query = "fields @timestamp, @message, log_level, project_name, service_name"
        if where:
            query += f" | filter {where}"
        query += f" | sort @timestamp desc | limit {self.max_results}"
        return query

    def to_azure_kql(self, table: str = "AppTraces") -> str:
        """Translate to a KQL query for Azure Log Analytics.

        KQL is Azure's SQL-like log query language. Every filter uses
        the pipe syntax (``| where ...``), string equality is ``==``
        not ``=``, and multi-value uses ``in (...)``. Time range is
        emitted inline as ``TimeGenerated`` bounds — Azure's
        LogsQueryClient also accepts a separate ``timespan`` arg, but
        embedding is more portable and lets a single KQL string be
        pasted straight into the Log Analytics UI.

        The default ``table`` is ``AppTraces`` (Application Insights
        traces, the most common shape for app logs). Operators using
        Perf, Syslog, ContainerLog or a custom table pass it via
        ``extra_config.default_table`` on the integration and it flows
        in as the ``table`` argument.

        Example output::

            AppTraces
            | where TimeGenerated >= datetime(2026-08-27T09:00:00Z)
            | where TimeGenerated <= datetime(2026-08-27T10:00:00Z)
            | where Properties.project_name == "acme-checkout"
            | where SeverityLevel >= 3
            | where Message contains "timeout"
            | top 5000 by TimeGenerated desc
        """
        # Table name goes through the bareword sanitiser — it's a
        # position where a stray character could route the query to
        # the wrong table (or worse, execute a KQL let-expression).
        lines: list = [f"{_kql_bareword(table)}"]

        # Time range — embed as datetime() literals. Even though
        # LogsQueryClient also takes timespan separately, doing it
        # here keeps the KQL self-contained.
        if self.time_range:
            start, end = self.time_range
            start_iso = start.isoformat() if hasattr(start, "isoformat") else str(start)
            end_iso = end.isoformat() if hasattr(end, "isoformat") else str(end)
            start_iso = start_iso.replace("+00:00", "Z")
            end_iso = end_iso.replace("+00:00", "Z")
            # datetime() literal is native KQL — no quoting needed
            # around the value, but we validate the ISO shape via a
            # bareword-style char check so a malicious payload can't
            # inject KQL between the parens.
            lines.append(f"| where TimeGenerated >= datetime({_kql_datetime(start_iso)})")
            lines.append(f"| where TimeGenerated <= datetime({_kql_datetime(end_iso)})")

        # Label filters — AppTraces stores custom properties under
        # Properties.<name>. Perf / Syslog use flat columns; those
        # operators would rewrite these via a custom KQL block.
        if self.project:
            lines.append(f'| where Properties.project_name == "{_kql_escape(self.project)}"')
        if self.environment:
            lines.append(f'| where Properties.environment == "{_kql_escape(self.environment)}"')
        if self.category:
            lines.append(f'| where Properties.category == "{_kql_escape(self.category)}"')
        if self.event_type:
            lines.append(f'| where Properties.event_type == "{_kql_escape(self.event_type)}"')

        if self.services:
            svc_list = ", ".join(f'"{_kql_escape(s)}"' for s in self.services)
            lines.append(f'| where Properties.service_name in ({svc_list})')

        # SeverityLevel in AppTraces: Verbose=0, Information=1,
        # Warning=2, Error=3, Critical=4. Requesting ["ERROR", "WARN"]
        # becomes >= 2 (the min).
        if self.severity:
            sev_map = {
                "DEBUG": 0, "TRACE": 0, "VERBOSE": 0,
                "INFO": 1, "NOTICE": 1,
                "WARN": 2, "WARNING": 2,
                "ERROR": 3, "ERR": 3, "FATAL": 3,
                "CRITICAL": 4, "CRIT": 4, "ALERT": 4, "EMERGENCY": 4,
            }
            requested = [sev_map.get(s.upper(), 3) for s in self.severity]
            threshold = min(requested)
            # threshold is an int we control — no injection surface
            lines.append(f"| where SeverityLevel >= {int(threshold)}")

        if self.text_search:
            lines.append(f'| where Message contains "{_kql_escape(self.text_search)}"')

        # `top N by TimeGenerated desc` gives us newest-first bounded
        # results — matches how Detail.jsx expects to render.
        lines.append(f"| top {int(self.max_results)} by TimeGenerated desc")

        return "\n".join(lines)

    def to_gcp_filter(self) -> str:
        """Translate to a Google Cloud Logging filter string.

        GCP's filter language is separate from LogQL / SPL / ES DSL —
        it uses ``field OP value`` with ``AND`` between clauses and a
        specific set of operators (``=``, ``!=``, ``>=``, ``<=``,
        ``:`` for substring). Time bounds go inline as ``timestamp>=``
        because Cloud Logging's API takes the filter as its only
        selector — there's no separate time-range param the way
        Splunk and CloudWatch have.

        Example output for a "prod ERRORs on backend-api" query::

            severity>=ERROR
            AND labels.project_name="acme-checkout"
            AND labels.environment="production"
            AND labels.service_name="backend-api"
            AND jsonPayload.message:"timeout"
            AND timestamp>="2026-08-27T09:00:00Z"
            AND timestamp<="2026-08-27T10:00:00Z"

        SerOps stores its enrichment tags under ``labels.*`` (Fluentd
        conventions). If your logs use ``jsonPayload.*`` for the same
        keys the operator can adapt via a small filter override
        (future work — this baseline covers the common case).
        """
        clauses: list = []

        # Severity comes first because operators expect it up front
        # when scanning a filter. GCP severity is ordinal — using >=
        # with the lowest requested level captures the whole set.
        if self.severity:
            # Input aliases → GCP canonical name. Multiple aliases can
            # map to the same ordinal (e.g. WARN and WARNING both
            # 400) but the output side must be a single canonical
            # name per ordinal so the reverse-lookup is deterministic.
            aliases_to_ord = {
                "DEBUG": 100, "TRACE": 100,
                "INFO": 200,
                "NOTICE": 300,
                "WARN": 400, "WARNING": 400,
                "ERROR": 500, "ERR": 500, "FATAL": 500,
                "CRITICAL": 600, "CRIT": 600,
                "ALERT": 700,
                "EMERGENCY": 800, "EMERG": 800,
            }
            ord_to_canonical = {
                100: "DEBUG", 200: "INFO", 300: "NOTICE",
                400: "WARNING", 500: "ERROR",
                600: "CRITICAL", 700: "ALERT", 800: "EMERGENCY",
            }
            requested_ords = [
                aliases_to_ord.get(s.upper(), 500) for s in self.severity
            ]
            # Lowest requested level as the >= threshold — captures
            # everything above it including the requested levels.
            severity_name = ord_to_canonical[min(requested_ords)]
            clauses.append(f'severity>={_gcp_bareword(severity_name)}')

        # Label filters — quoted so anything with a space or colon works.
        if self.project:
            clauses.append(f'labels.project_name="{_gcp_escape(self.project)}"')
        if self.environment:
            clauses.append(f'labels.environment="{_gcp_escape(self.environment)}"')
        if self.category:
            clauses.append(f'labels.category="{_gcp_escape(self.category)}"')
        if self.event_type:
            clauses.append(f'labels.event_type="{_gcp_escape(self.event_type)}"')

        # Multi-value: GCP filter language supports OR groups; we
        # parenthesise to keep AND binding correct across the group.
        if self.services:
            svc_clauses = " OR ".join(
                f'labels.service_name="{_gcp_escape(s)}"' for s in self.services
            )
            clauses.append(f"({svc_clauses})")

        # Free-text search — GCP's `:` operator is substring, not
        # regex, matching how a user typically thinks about "find
        # requests that mention …".
        if self.text_search:
            clauses.append(f'jsonPayload.message:"{_gcp_escape(self.text_search)}"')

        # Time range inline — GCP has no separate param for this.
        if self.time_range:
            start, end = self.time_range
            start_iso = start.isoformat() if hasattr(start, "isoformat") else str(start)
            end_iso = end.isoformat() if hasattr(end, "isoformat") else str(end)
            # Normalise +00:00 → Z for consistency with GCP examples.
            clauses.append(f'timestamp>="{_gcp_escape(start_iso.replace("+00:00", "Z"))}"')
            clauses.append(f'timestamp<="{_gcp_escape(end_iso.replace("+00:00", "Z"))}"')

        return " AND ".join(clauses) if clauses else ""

    def to_splunk_spl(self, index: str = "main") -> str:
        """Translate to Splunk SPL (Search Processing Language).

        The Splunk adapter passes ``earliest``/``latest`` as separate
        API params (not embedded in SPL), so time_range is *not*
        rendered here — that avoids double-filtering.

        Example output for a "prod ERRORs on backend-api" query::

            search index=main project_name="acme"
                   environment="production"
                   service_name IN ("backend-api")
                   (log_level="ERROR" OR log_level="CRITICAL")
                   "timeout"
                   | head 5000
        """
        # index=... must be the first clause after `search`.
        parts = [f'search index={_spl_token(index)}']

        # Field filters — quoted values so anything with a space works.
        # Use conservative escaping (backslash-quote) to defeat
        # accidental SPL injection via a malicious value.
        if self.project:
            parts.append(f'project_name="{_spl_escape(self.project)}"')
        if self.environment:
            parts.append(f'environment="{_spl_escape(self.environment)}"')
        if self.category:
            parts.append(f'category="{_spl_escape(self.category)}"')
        if self.event_type:
            parts.append(f'event_type="{_spl_escape(self.event_type)}"')

        if self.services:
            svc_list = ", ".join(f'"{_spl_escape(s)}"' for s in self.services)
            parts.append(f'service_name IN ({svc_list})')

        if self.severity:
            # SPL uses OR joins for value alternation on the same key.
            sev_clauses = " OR ".join(
                f'log_level="{_spl_escape(s.upper())}"' for s in self.severity
            )
            parts.append(f'({sev_clauses})')

        if self.text_search:
            # Free-text term goes as a bare quoted phrase.
            parts.append(f'"{_spl_escape(self.text_search)}"')

        # `head N` caps result count — Splunk default is 100 which is
        # far too small for our batch aggregation use case.
        parts.append(f'| head {self.max_results}')
        return " ".join(parts)


# --- Helpers ---

def _parse_timestamp(ts: str) -> datetime:
    """Parse ISO timestamp string, handling common formats."""
    if not ts:
        return datetime.min
    try:
        # Handle Z suffix
        ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return datetime.min


def _detect_level(level_str: str) -> str:
    """Normalize log level string."""
    if not level_str:
        return "INFO"
    upper = level_str.upper().strip()
    if upper in ("ERROR", "ERR", "FATAL", "CRITICAL", "CRIT"):
        return "ERROR"
    if upper in ("WARN", "WARNING"):
        return "WARN"
    if upper in ("DEBUG", "TRACE"):
        return "DEBUG"
    return "INFO"


# Spellings each canonical severity appears as in real log lines. SerOps
# asks for WARNING; emitters overwhelmingly write WARN — so a filter built
# from the canonical name alone misses almost everything. Same for
# ERROR/ERR and CRITICAL/CRIT/FATAL.
_SEVERITY_LINE_SYNONYMS = {
    'ERROR':    ('ERROR', 'ERR'),
    'ERR':      ('ERROR', 'ERR'),
    'CRITICAL': ('CRITICAL', 'CRIT', 'FATAL'),
    'CRIT':     ('CRITICAL', 'CRIT', 'FATAL'),
    'FATAL':    ('CRITICAL', 'CRIT', 'FATAL'),
    'WARNING':  ('WARNING', 'WARN'),
    'WARN':     ('WARNING', 'WARN'),
    'DEBUG':    ('DEBUG', 'TRACE'),
    'TRACE':    ('DEBUG', 'TRACE'),
    'INFO':     ('INFO',),
}


def _logql_severity_alternatives(severities) -> str:
    """Expand requested severities into a LogQL regex alternation.

    Longer spellings come first so RE2's leftmost-first alternation matches
    the full token (ERROR, not the ERR prefix of it).
    """
    out = []
    for level in severities or ():
        for spelling in _SEVERITY_LINE_SYNONYMS.get(str(level).upper(), (str(level).upper(),)):
            if spelling not in out:
                out.append(spelling)
    out.sort(key=lambda s: (-len(s), s))
    return "|".join(out)


# Matches a severity token that stands on its own, so the word "error"
# inside prose ("retrying after error handler ran") does not promote an
# INFO line. Accepts the shapes real emitters produce: bare/leading token,
# bracketed ``[ERROR]``, logfmt ``level=error``, and JSON ``"level":"error"``.
# Longer alternatives precede their prefixes (ERROR before ERR) so the
# full token wins.
_LEVEL_TOKEN_RE = re.compile(
    r'(?:^|[\s\[\("\']|level=|lvl=|severity=|"level"\s*:\s*"?)'
    r'(FATAL|CRITICAL|CRIT|ERROR|ERR|WARNING|WARN|DEBUG|TRACE|INFO)'
    r'(?=$|[\s\]\)"\':,])',
    re.IGNORECASE,
)

# Only the head of the line is scanned. Every common format puts the level
# in the prefix, while message bodies (especially stack traces) are full of
# words like "error" that would otherwise misclassify the entry.
_LEVEL_SCAN_CHARS = 200


def _detect_level_from_line(line: str, default: str = "INFO") -> str:
    """Extract a severity from a raw log line.

    Needed for providers that carry no level field of their own. Loki is
    the main one: severity lives in the line text, because promoting it to
    a stream label would multiply Loki's label cardinality. ``_detect_level``
    cannot do this job — it compares the *whole* string against a set of
    level names, so handing it a log line always yields INFO.

    First match wins rather than most-severe, matching how log lines are
    actually shaped: the level sits in the prefix, and a later mention is
    usually part of the message.
    """
    if not line:
        return default
    match = _LEVEL_TOKEN_RE.search(line[:_LEVEL_SCAN_CHARS])
    return _detect_level(match.group(1)) if match else default


# ---------------------------------------------------------------------------
# Provider-specific string helpers
# ---------------------------------------------------------------------------


def _spl_escape(value: str) -> str:
    """Escape a value for interpolation inside a double-quoted SPL literal.

    SPL treats ``\`` as an escape character and ``"`` as the string
    delimiter. Anything else inside quotes is literal, including single
    quotes and the entire punctuation set — no HTML entities needed.

    We reject non-string inputs early so a caller can't pass a dict or
    list and accidentally leak its ``str()`` form into a query.
    """
    if not isinstance(value, str):
        raise TypeError(f"SPL escape expects str, got {type(value).__name__}")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _spl_token(value: str) -> str:
    """Sanitise a bareword SPL token (index name, etc.).

    Splunk index names are restricted to lowercase letters, digits,
    hyphens, underscores. Any character outside that set indicates a
    misconfiguration (or an injection attempt) and is rejected — never
    silently rewritten, because a silent rewrite could route a query
    to the wrong index.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("SPL token must be a non-empty string")
    if not all(c.isalnum() or c in "-_" for c in value):
        raise ValueError(f"Invalid SPL token: {value!r}")
    return value


def _gcp_escape(value: str) -> str:
    """Escape a value for a double-quoted GCP filter string literal.

    GCP's filter language treats ``\\`` as escape and ``"`` as
    delimiter — same as SPL. Everything else is literal inside quotes,
    including newlines and colons, so we don't need to fight those.

    Non-string input is rejected so a caller can't sneak in a dict's
    ``str()`` form.
    """
    if not isinstance(value, str):
        raise TypeError(f"GCP filter escape expects str, got {type(value).__name__}")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _gcp_bareword(value: str) -> str:
    """Validate a GCP filter bareword (severity level, resource type).

    Barewords appear on the RHS of ``severity>=X`` and similar clauses
    where a quoted string would be a syntax error. GCP accepts
    uppercase letters, digits, underscores. Any character outside that
    set is rejected loudly — silent rewrites of a severity threshold
    would let ERROR-level requests through as INFO-level.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("GCP bareword must be a non-empty string")
    if not all(c.isalnum() or c == "_" for c in value):
        raise ValueError(f"Invalid GCP bareword: {value!r}")
    return value


def _kql_escape(value: str) -> str:
    """Escape a value for a double-quoted KQL string literal.

    KQL follows the same convention as SPL and GCP filter — ``\\`` is
    the escape and ``"`` is the delimiter. Anything else inside quotes
    is literal, including single-quotes and colons.
    """
    if not isinstance(value, str):
        raise TypeError(f"KQL escape expects str, got {type(value).__name__}")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _kql_bareword(value: str) -> str:
    """Validate a KQL bareword (table name, column, etc.).

    KQL table names must start with a letter and can contain letters,
    digits, and underscores. Anything else is rejected — an unquoted
    KQL identifier is executable code, so silent rewrites here are the
    highest-severity risk in the entire schema layer.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("KQL bareword must be a non-empty string")
    if not (value[0].isalpha() or value[0] == "_"):
        raise ValueError(f"Invalid KQL bareword (bad start): {value!r}")
    if not all(c.isalnum() or c == "_" for c in value):
        raise ValueError(f"Invalid KQL bareword: {value!r}")
    return value


def _kql_datetime(value: str) -> str:
    """Validate an ISO timestamp for inline datetime() interpolation.

    ``datetime(<value>)`` is unquoted in KQL — the value has to
    contain only ISO-timestamp characters. Anything else could inject
    a KQL sub-expression between the parens.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("KQL datetime literal must be a non-empty string")
    # Allow: digits, ``-``, ``:``, ``T``, ``Z``, ``.``, ``+``.
    if not all(c.isdigit() or c in "-:T.Z+" for c in value):
        raise ValueError(f"Invalid KQL datetime literal: {value!r}")
    return value
