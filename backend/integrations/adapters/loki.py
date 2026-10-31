"""
Grafana Loki Adapter for LogProvider.

Implements the LogProvider ABC using the Loki HTTP API.
Translates generic query dicts into LogQL stream selectors + line filters.
"""
import json
import re
import logging
from datetime import datetime, timezone
from typing import List, Tuple, Optional

import requests
from requests.exceptions import RequestException

from integrations.base import LogProvider, LogProviderCapabilities
from integrations.schemas import (
    EMPTY_LOGQL_SELECTOR,
    LogEntry,
    LogStream,
    LogQuery,
    _parse_timestamp,
    _detect_level,
    _detect_level_from_line,
)
from integrations.schemas import level_from_value, level_of
from integrations.field_aliases import (
    LOG_LEVEL_ALIASES, SERVICE_NAME_ALIASES, first_present, first_present_with_key,
)

logger = logging.getLogger(__name__)

# Labels preferred when an unfiltered query needs a concrete stream
# selector (see _any_stream_selector). These are *structural* labels a
# collector sets regardless of whether the operator tagged anything
# canonically — which is exactly what the ingest-health validator needs:
# selecting on `service_name` would only ever sample streams that already
# have it, reporting a clean bill of health on a cluster that is 90%
# untagged. Ordered most- to least-universal.
_STRUCTURAL_LABELS = ('filename', 'pod', 'container', 'job', 'stream', 'instance')


class LokiLogProvider(LogProvider):
    """
    Grafana Loki adapter using the HTTP API.

    Endpoints used:
      - GET /loki/api/v1/query_range   – log queries
      - GET /loki/api/v1/labels        – index/stream discovery
      - GET /ready                      – health check
    """

    capabilities = LogProviderCapabilities(
        full_text=True,
        regex=True,
        aggregations=False,
        tail=True,
        max_query_window_days=30,
        indexing=True,
    )

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.base_url = self._config.get(
            "host", "http://loki:3100"
        ).rstrip("/")
        # Why a sticky error field instead of raising: search() returning []
        # on failure is relied on by the batch pipeline, which must degrade
        # rather than abort when one provider is down. But an empty list is
        # then ambiguous — "nothing matched" and "the query was rejected"
        # look identical. That ambiguity made the ingest-health validator
        # report five missing canonical fields when the real cause was a
        # 400 from Loki. Callers that need to tell the two apart read
        # last_error; nothing is forced to.
        self.last_error = None
        self._session = requests.Session()
        # Auth
        username = self._config.get("username")
        password = self._config.get("password")
        if username and password:
            self._session.auth = (username, password)
        bearer = self._config.get("bearer_token")
        if bearer:
            self._session.headers["Authorization"] = f"Bearer {bearer}"
        # Tenant header for multi-tenant Loki
        tenant_id = self._config.get("tenant_id")
        if tenant_id:
            self._session.headers["X-Scope-OrgID"] = tenant_id
        else:
            logger.warning(
                "LokiLogProvider initialized without tenant_id. "
                "In multi-tenant Loki deployments, queries will span ALL tenants. "
                "Set 'tenant_id' in the integration config for proper isolation."
            )

    def index(self, documents: list, stream: LogStream) -> int:
        """
        Push event documents to Loki via push API.
        
        Uses stream labels from LogStream for routing.
        """
        if not documents:
            return 0

        import json
        import time as _time

        labels = stream.to_loki_labels()
        values = []
        for doc in documents:
            ts_ns = str(int(_time.time() * 1e9))  # current time in nanoseconds
            if "timestamp" in doc:
                try:
                    dt = datetime.fromisoformat(doc["timestamp"].replace("Z", "+00:00"))
                    ts_ns = str(int(dt.timestamp() * 1e9))
                except (ValueError, AttributeError):
                    pass
            values.append([ts_ns, json.dumps(doc)])

        payload = {
            "streams": [
                {
                    "stream": labels,
                    "values": values,
                }
            ]
        }

        try:
            resp = self._session.post(
                f"{self.base_url}/loki/api/v1/push",
                json=payload,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            logger.info(
                "Loki push: %d entries → labels=%s", len(documents), labels
            )
            return len(documents)
        except RequestException as exc:
            logger.error("Loki push failed: %s", exc)
            return 0

    def health_check(self) -> bool:
        """Hit /ready endpoint."""
        try:
            resp = self._session.get(
                f"{self.base_url}/ready",
                timeout=self.timeout_seconds,
            )
            return resp.status_code == 200
        except RequestException as exc:
            logger.error("Loki health check failed: %s", exc)
            return False

    def search(
        self,
        index: str,
        query,  # dict (legacy) or LogQuery (new)
        time_range: Optional[Tuple[datetime, datetime]] = None,
        size: int = 10000,
    ) -> List[LogEntry]:
        """
        Query Loki and return canonical LogEntry objects.
        Accepts both legacy dict queries and LogQuery DTOs.
        """
        self.last_error = None

        # Translate LogQuery → LogQL if needed
        if isinstance(query, LogQuery):
            size = query.max_results
            # Extract time range from LogQuery if not passed explicitly
            if not time_range and query.time_range:
                time_range = query.time_range
            alternatives = query.to_logql_alternatives()
            if len(alternatives) > 1:
                # The project's logs are tagged several ways (Project.log_rules):
                # one query each, merged, newest first, each log once.
                merged, seen = [], set()
                for logql in alternatives:
                    for entry in self._query_range(logql, size, time_range, index):
                        key = (entry.timestamp, entry.message, entry.service)
                        if key not in seen:
                            seen.add(key)
                            merged.append(entry)
                merged.sort(key=lambda e: e.timestamp, reverse=True)
                return merged[:size]
            logql = alternatives[0]
        else:
            logql = self._build_logql(index, query)
        return self._query_range(logql, size, time_range, index)

    def _query_range(self, logql, size, time_range, index) -> List[LogEntry]:

        # An unfiltered LogQuery renders as "{}", which Loki rejects
        # outright: "queries require at least one regexp or equality
        # matcher that does not have an empty-compatible value". Loki
        # cannot express "every stream", so discover a real label and
        # match on its presence instead.
        if logql.strip() == EMPTY_LOGQL_SELECTOR:
            discovered = self._any_stream_selector(time_range)
            if not discovered:
                self.last_error = (
                    'Loki has no labels in the queried window, so an '
                    'unfiltered sample is impossible. Either nothing has '
                    'been ingested yet or the window is too narrow.'
                )
                logger.warning('Loki unfiltered search: %s', self.last_error)
                return []
            logger.info('Loki unfiltered search using discovered selector %s', discovered)
            logql = discovered

        params = {"query": logql, "limit": size, "direction": "backward"}

        if time_range:
            start_dt, end_dt = time_range
            params["start"] = str(int(start_dt.timestamp() * 1e9))  # nanoseconds
            params["end"] = str(int(end_dt.timestamp() * 1e9))

        try:
            resp = self._session.get(
                f"{self.base_url}/loki/api/v1/query_range",
                params=params,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "success":
                self.last_error = f'Loki returned non-success: {data.get("error", "unknown")}'
                logger.warning(
                    "Loki query non-success: %s", data.get("error", "unknown")
                )
                return []

            return self._parse_streams(data["data"]["result"], index)

        except RequestException as exc:
            # Include the LogQL so a 400 is diagnosable without turning on
            # debug logging — a rejected selector is the most common cause.
            self.last_error = f'Loki query failed ({logql}): {exc}'
            logger.error("Loki search failed: %s", exc)
            return []

    def get_indices(self, project) -> List[str]:
        """
        Discover the streams that belong to ``project``.

        The scheduler skips a project when this returns nothing, so it must
        recognise the labels our docs tell Loki users to set: canonical
        ``project_name`` / ``service_name``. It used to look only at the
        legacy ``app`` label, which the documented Promtail config does not
        produce, so a docs-compliant Loki install was never analysed (found
        by the journey suite, launch plan 9.9). Returns the project's
        ``service_name`` values; falls back to ``app`` values for
        pre-canonical setups. The batch query itself is built from
        LogQuery (canonical labels), not from these values.
        """
        name = getattr(project, 'name', None)
        rules = project.log_rules_clean() if hasattr(project, 'log_rules_clean') else []
        try:
            if name and name in self._label_values('project_name'):
                selector = '{project_name="%s"}' % name.replace('"', '\\"')
                return self._label_values('service_name', selector) or [name]
            # The project's own log rules (Project.log_rules), as Loki labels.
            for field, value in rules:
                label = re.sub(r'[^A-Za-z0-9_]', '_', field)
                if value in self._label_values(label):
                    selector = '{%s="%s"}' % (label, value.replace('"', '\\"'))
                    return self._label_values('service_name', selector) or [value]
            return self._label_values('app')
        except RequestException as exc:
            logger.warning("Loki get_indices failed: %s", exc)
            return []

    def _label_values(self, label: str, selector: Optional[str] = None) -> List[str]:
        resp = self._session.get(
            f"{self.base_url}/loki/api/v1/label/{label}/values",
            params={'query': selector} if selector else None,
            timeout=self.timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", []) if data.get("status") == "success" else []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _any_stream_selector(self, time_range=None) -> Optional[str]:
        """Build a valid "match as much as possible" LogQL selector.

        Loki has no equivalent of ``match_all``: every query needs a
        matcher that is not empty-compatible, so ``{}`` and ``{x=~".*"}``
        are both rejected while ``{x=~".+"}`` is accepted. To sample
        broadly we therefore have to name a label that actually exists,
        which means asking Loki what labels it has.

        Label choice matters more than it looks. Selecting on a canonical
        field like ``service_name`` would restrict the sample to streams
        that already carry it — so the ingest-health report would show
        100% coverage on a cluster where most streams are untagged. We
        prefer structural labels (``filename``, ``pod``, ...) that the
        collector sets unconditionally, so the sample spans tagged and
        untagged streams alike.

        Returns None when Loki reports no labels at all, which the caller
        surfaces rather than treating as "no data".
        """
        params = {}
        if time_range:
            start_dt, end_dt = time_range
            params["start"] = str(int(start_dt.timestamp() * 1e9))
            params["end"] = str(int(end_dt.timestamp() * 1e9))

        try:
            resp = self._session.get(
                f"{self.base_url}/loki/api/v1/labels",
                params=params,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "success":
                return None
            labels = data.get("data") or []
        except RequestException as exc:
            logger.warning("Loki label discovery failed: %s", exc)
            return None

        if not labels:
            return None

        for preferred in _STRUCTURAL_LABELS:
            if preferred in labels:
                return f'{{{preferred}=~".+"}}'

        # No structural label present. Fall back to any non-canonical
        # label before a canonical one, to keep the sample as unbiased as
        # the data allows.
        canonical = {
            'organisation_name', 'project_name', 'service_name',
            'environment', 'log_level',
        }
        for label in labels:
            if label not in canonical:
                return f'{{{label}=~".+"}}'

        return f'{{{labels[0]}=~".+"}}'

    @staticmethod
    def _build_logql(index: str, query: dict) -> str:
        """
        Build a LogQL query from the generic query dict.

        Examples:
            _build_logql("myapp", {})
            → '{app="myapp"}'

            _build_logql("myapp", {"match_phrase": {"message": "error"}})
            → '{app="myapp"} |= "error"'
        """
        # Raw LogQL override
        if query.get("logql"):
            return query["logql"]

        # Build stream selector
        labels = {"app": index}
        labels.update(query.get("stream_labels", {}))
        selector = "{" + ",".join(
            f'{k}="{v}"' for k, v in labels.items() if v
        ) + "}"

        # Line filters
        filters = ""
        match_phrase = query.get("match_phrase", {})
        text = match_phrase.get("message", "")
        if text:
            # Escape double quotes in search text
            escaped = text.replace('"', '\\"')
            filters = f' |= "{escaped}"'

        return selector + filters

    @staticmethod
    def _parse_streams(
        result: list, default_index: str
    ) -> List[LogEntry]:
        """
        Parse Loki streams response into canonical LogEntry objects.

        Loki response structure:
            [{"stream": {...labels}, "values": [["nanosecond_ts", "line"], ...]}, ...]
        """
        entries: List[LogEntry] = []
        for stream_item in result:
            stream_labels = stream_item.get("stream", {})
            for ts_ns, line in stream_item.get("values", []):
                # Loki timestamps are nanoseconds. Use tz-aware datetime
                # (UTC) — downstream batch code compares against
                # ``timezone.now()`` which is aware; naive datetimes
                # raise TypeError on comparison.
                ts = datetime.fromtimestamp(int(ts_ns) / 1e9, tz=timezone.utc)
                entries.append(
                    LogEntry(
                        timestamp=ts,
                        message=line,
                        # Prefer canonical SerOps labels (log_level /
                        # service_name — see CLAUDE.md "Canonical Log
                        # Field Names"), fall back to legacy Loki
                        # conventions (level / app) for backwards
                        # compat with pre-canonical setups.
                        #
                        # Final fallback parses the line itself. Loki
                        # users almost never promote severity to a stream
                        # label (it would multiply label cardinality), so
                        # without this every entry came back INFO — a real
                        # cluster of ERROR lines reached the AI flattened
                        # to INFO, and the ingest validator reported
                        # log_level as 100% covered.
                        # Level: a level label (Loki 3 adds detected_level),
                        # else the JSON line's level field (Pino's numbers
                        # included), else the line text. Loki users almost
                        # never promote severity to a stream label (it
                        # multiplies label cardinality).
                        level=_loki_level(stream_labels, line),
                        service=str(first_present(
                            stream_labels, SERVICE_NAME_ALIASES + ["container"], default="")),
                        host=stream_labels.get("host", stream_labels.get("hostname", "")),
                        labels={
                            **stream_labels,
                            # ``default_index`` can be None when the batch
                            # task can't discover any label values (get_indices
                            # returns []). Downstream code does ``'foo' in
                            # hit.labels.get('_index', '')`` which crashes
                            # on None — coerce to empty string here.
                            "_index": default_index or "",
                        },
                        trace_id=stream_labels.get("trace_id", ""),
                        raw_id=f"{ts_ns}-{hash(line) & 0xFFFFFFFF:08x}",
                    )
                )
        return entries


def _loki_level(stream_labels: dict, line: str) -> str:
    key, value = first_present_with_key(stream_labels, LOG_LEVEL_ALIASES + ["detected_level"])
    if key:
        return level_from_value(key, value)
    if line.lstrip().startswith("{"):
        try:
            record = json.loads(line)
        except ValueError:
            record = None
        if isinstance(record, dict):
            return level_of(record, line)
    return _detect_level_from_line(line)
