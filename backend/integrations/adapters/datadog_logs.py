"""
Datadog Logs Adapter for LogProvider.

Implements the LogProvider ABC using the Datadog HTTP API v2.
Uses Log Search endpoint for querying.
"""
import logging
import re
from datetime import datetime, timezone
from typing import List, Tuple, Optional

import requests
from requests.exceptions import RequestException

from integrations.base import LogProvider, LogProviderCapabilities, LogSearchError
from integrations.field_aliases import first_present
from integrations.schemas import LogEntry, LogStream, LogQuery, _parse_timestamp, _detect_level, level_of

logger = logging.getLogger(__name__)


def datadog_site(config: dict) -> str:
    """The Datadog site (datadoghq.com, datadoghq.eu, us5.datadoghq.com...).

    The UI saves the site in ``host`` ("Datadog Site"), the API docs put it
    in ``site``; people also paste "app.datadoghq.eu" or a full URL. Only
    ``site`` used to be read, so every EU (and US3/US5) install called the
    US site and saw its valid keys refused.
    """
    extras = config.get("extra_config") or {}
    raw = config.get("site") or extras.get("site") or config.get("host") or "datadoghq.com"
    raw = re.sub(r"^[a-z]+://", "", str(raw).strip().lower()).split("/")[0]
    for prefix in ("api.", "app.", "http-intake.logs."):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
    return raw or "datadoghq.com"


def _dd_time(dt: datetime) -> str:
    """A time for the Datadog search API: ISO 8601 in UTC with a Z.

    ``isoformat() + "Z"`` on an aware datetime gave "...+00:00Z", which
    Datadog rejects (400): every query with a time range failed.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class DatadogLogProvider(LogProvider):
    """
    Datadog Logs adapter using the HTTP API.

    Endpoints used:
      - POST /api/v2/logs/events/search — log queries
      - GET  /api/v1/logs/config/indexes — index discovery
      - GET  /api/v1/validate            — health check
    """

    capabilities = LogProviderCapabilities(
        full_text=True,
        regex=True,
        aggregations=True,
        tail=True,
        max_query_window_days=15,  # DD default retention
        indexing=True,
    )

    def __init__(self, config: dict = None):
        super().__init__(config)
        # Datadog site: datadoghq.com, datadoghq.eu, etc.
        self.base_url = f"https://api.{datadog_site(self._config)}"
        self.last_error = None
        self._session = requests.Session()
        # DD auth headers
        self._session.headers.update({
            "DD-API-KEY": self._config.get("api_key", ""),
            "DD-APPLICATION-KEY": self._config.get("app_key", ""),
            "Content-Type": "application/json",
        })

    def index(self, documents: list, stream: LogStream) -> int:
        """
        Send event documents to Datadog via Log Intake API.
        Tags are derived from LogStream.
        """
        if not documents:
            return 0

        import json
        tags = stream.to_datadog_tags()

        # Datadog expects an array of log objects
        dd_logs = []
        for doc in documents:
            dd_logs.append({
                "ddsource": "serops",
                "ddtags": ",".join(tags),
                "hostname": doc.get("serops_meta", {}).get("service_name", "serops"),
                "service": doc.get("serops_meta", {}).get("service_name", "serops"),
                "message": json.dumps(doc),
            })

        try:
            resp = self._session.post(
                f"{self.base_url}/api/v2/logs",
                json=dd_logs,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            logger.info("Datadog Logs index: %d docs, tags=%s", len(documents), tags)
            return len(documents)
        except RequestException as exc:
            logger.error("Datadog Logs index failed: %s", exc)
            return 0

    def health_check(self) -> bool:
        """The API key is valid on this site AND the application key can
        search logs. Checking the API key alone said "healthy" with a wrong
        or missing application key, and every search then failed."""
        self.last_error = None
        try:
            resp = self._session.get(f"{self.base_url}/api/v1/validate", timeout=self.timeout_seconds)
            if resp.status_code != 200:
                self.last_error = (f"The API key is not valid on {self.base_url.replace('https://api.', '')}. "
                                   "Check the key and the Datadog site (e.g. datadoghq.eu).")
                return False
            resp = self._session.post(
                f"{self.base_url}/api/v2/logs/events/search",
                json={"filter": {"query": "*", "from": "now-1m", "to": "now"}, "page": {"limit": 1}},
                timeout=self.timeout_seconds,
            )
            if resp.status_code in (401, 403):
                self.last_error = ("The application key cannot read logs. Create an application key "
                                   "(not a personal access token) with the logs_read_data scope.")
                return False
            return True
        except RequestException as exc:
            logger.error("Datadog Logs health check failed: %s", exc)
            self.last_error = f"Datadog is not reachable: {exc}"
            return False

    def search(
        self,
        index: str,
        query,  # dict (legacy) or LogQuery (new)
        time_range: Optional[Tuple[datetime, datetime]] = None,
        size: int = 10000,
    ) -> List[LogEntry]:
        """
        Search logs using Datadog Log Search API.
        Accepts both legacy dict queries and LogQuery DTOs.
        """
        # Translate LogQuery → Datadog query if needed
        if isinstance(query, LogQuery):
            dd_query = query.to_datadog_query()
            size = query.max_results
            if not time_range and query.time_range:
                time_range = query.time_range
        else:
            dd_query = self._build_query(index, query)

        body = {
            "filter": {
                "query": dd_query,
                "from": _dd_time(time_range[0]) if time_range else "now-1h",
                "to": _dd_time(time_range[1]) if time_range else "now",
            },
            "sort": "-timestamp",
            "page": {
                "limit": min(size, 1000),  # DD max per page
            },
        }

        try:
            resp = self._session.post(
                f"{self.base_url}/api/v2/logs/events/search",
                json=body,
                timeout=self.timeout_seconds,
            )
        except RequestException as exc:
            logger.error("Datadog Logs search failed: %s", exc)
            raise LogSearchError(f"Datadog search failed: {exc}") from exc
        if not resp.ok:
            # Refused queries used to come back as "no logs": a scheduled run
            # then said there were no errors, and Check my data that the logs
            # were missing, while Datadog was answering 400 to every query.
            try:
                detail = "; ".join(map(str, resp.json().get("errors", []))) or resp.text[:200]
            except ValueError:
                detail = resp.text[:200]
            logger.error("Datadog Logs search refused (%s): %s", resp.status_code, detail)
            raise LogSearchError(f"Datadog refused the query ({resp.status_code}): {detail}")
        events = resp.json().get("data", [])
        return [self._event_to_log_entry(e) for e in events]

    def get_indices(self, project) -> List[str]:
        """Get available Datadog log indexes.

        A search needs no index named (Datadog searches them all), so when
        the list is empty or cannot be read (an application key without
        logs_read_index_data) this answers "*" rather than nothing: an empty
        answer made the scheduler skip the project as having nowhere to read
        logs from.
        """
        try:
            resp = self._session.get(
                f"{self.base_url}/api/v1/logs/config/indexes",
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            names = [idx.get("name", "") for idx in resp.json().get("indexes", []) if idx.get("name")]
            return names or ["*"]
        except (RequestException, ValueError) as exc:
            logger.warning("Datadog get_indices failed, searching every index: %s", exc)
            return ["*"]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_query(index: str, query: dict) -> str:
        """Build a Datadog query string."""
        # Raw override
        if query.get("dd_query"):
            return query["dd_query"]

        parts = []
        if index:
            parts.append(f"index:{index}")

        match_phrase = query.get("match_phrase", {})
        text = match_phrase.get("message", "")
        if text:
            parts.append(text)

        level = query.get("level")
        if level:
            parts.append(f"status:{level.lower()}")

        return " ".join(parts) if parts else "*"

    @staticmethod
    def _event_to_log_entry(event: dict) -> LogEntry:
        """Convert a Datadog log event to canonical LogEntry."""
        attrs = event.get("attributes", {})
        tags_list = attrs.get("tags", [])
        # Convert tag list ["env:prod", "service:api"] to dict
        tags = {}
        for tag in tags_list:
            if ":" in tag:
                k, v = tag.split(":", 1)
                tags[k] = v

        # Custom attributes (the JSON log body) sit under attributes.attributes;
        # reserved ones (service, host, status, message) one level up; tags
        # are "key:value" strings. One record so every alias is read alike.
        custom = attrs.get("attributes", {}) or {}
        record = {**tags, **custom, **{k: v for k, v in attrs.items() if k not in ("attributes", "tags")}}
        message = attrs.get("message", "") or ""
        # status is Datadog's own severity, already normalised; a level
        # attribute from the body wins when status was left at "info".
        level = _detect_level(attrs.get("status", "info"))
        if level == "INFO":
            level = level_of(custom, message)
        return LogEntry.from_record(
            record,
            raw_id=event.get("id", ""),
            timestamp=_parse_timestamp(attrs.get("timestamp", "")),
            message=message,
            level=level,
            labels={"_index": tags.get("index", "main"), **tags, **custom},
            trace_id=str(first_present(custom, ("trace_id", "dd.trace_id"), default="")),
        )
