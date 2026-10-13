"""
Datadog Logs Adapter for LogProvider.

Implements the LogProvider ABC using the Datadog HTTP API v2.
Uses Log Search endpoint for querying.
"""
import logging
from datetime import datetime
from typing import List, Tuple, Optional

import requests
from requests.exceptions import RequestException

from integrations.base import LogProvider, LogProviderCapabilities
from integrations.schemas import LogEntry, LogStream, LogQuery, _parse_timestamp, _detect_level

logger = logging.getLogger(__name__)


class DatadogLogProvider(LogProvider):
    """
    Datadog Logs adapter using the HTTP API.

    Endpoints used:
      - POST /api/v2/logs/events/search — log queries
      - GET  /api/v2/logs/config/indexes — index discovery
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
        site = self._config.get("site", "datadoghq.com")
        self.base_url = f"https://api.{site}"
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
        """Validate API key via /api/v1/validate."""
        try:
            resp = self._session.get(
                f"{self.base_url}/api/v1/validate",
                timeout=self.timeout_seconds,
            )
            return resp.status_code == 200
        except RequestException as exc:
            logger.error("Datadog Logs health check failed: %s", exc)
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
                "from": time_range[0].isoformat() + "Z" if time_range else "now-1h",
                "to": time_range[1].isoformat() + "Z" if time_range else "now",
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
            resp.raise_for_status()
            data = resp.json()
            events = data.get("data", [])
            return [self._event_to_log_entry(e) for e in events]

        except RequestException as exc:
            logger.error("Datadog Logs search failed: %s", exc)
            return []

    def get_indices(self, project) -> List[str]:
        """Get available Datadog log indexes."""
        try:
            resp = self._session.get(
                f"{self.base_url}/api/v1/logs/indexes",
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                idx.get("name", "") for idx in data.get("indexes", [])
            ]
        except RequestException as exc:
            logger.warning("Datadog get_indices failed: %s", exc)
            return []

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

        return LogEntry(
            timestamp=_parse_timestamp(attrs.get("timestamp", "")),
            message=attrs.get("message", ""),
            level=_detect_level(attrs.get("status", "info")),
            service=attrs.get("service", tags.get("service", "")),
            host=attrs.get("host", tags.get("host", "")),
            labels={
                "_index": tags.get("index", "main"),
                **tags,
            },
            trace_id=attrs.get("attributes", {}).get("trace_id", ""),
            raw_id=event.get("id", ""),
        )
