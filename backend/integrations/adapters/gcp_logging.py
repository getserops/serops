"""
Google Cloud Logging Adapter for LogProvider.

Uses the official ``google-cloud-logging`` SDK (v3+). The client is
constructed with an explicit service-account credential loaded from
the ``password`` field (the same encrypted-at-rest storage every
other adapter uses) — never from ADC / instance metadata, because a
multi-tenant SerOps process must not accidentally pick up whatever
credentials happen to be sitting on the host.

Endpoints used:
  - ``client.list_entries(filter_=..., page_size=..., order_by=...)``
    — search returns iterators of ``LogEntry`` structs
  - ``client.list_projects()`` (via the resource manager, in
    ``get_indices``) — enumerate log-bucket-ish scopes

Deliberately does NOT implement ``index()`` for now. Cloud Logging
supports ``client.logger(name).log_struct(...)`` but wiring it up
here needs its own review — the free-form ``jsonPayload`` shape,
retention/routing rules, and quota semantics all differ from
CloudWatch's ``put_log_events``. Ship search first, ingest later.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List, Optional, Tuple

from integrations.base import LogProvider, LogProviderCapabilities
from integrations.schemas import (
    LogEntry,
    LogQuery,
    _detect_level,
    _parse_timestamp,
)

logger = logging.getLogger(__name__)


def _load_credentials(config: dict):
    """Build a google.oauth2 credential from stored JSON.

    The service-account key is stored (encrypted) in the ``password``
    field of ObservabilityIntegration. We accept it either as a raw
    JSON string or as an already-parsed dict — both come out of
    ``get_config()`` the same way depending on how the caller set it,
    and we don't want a shape mismatch to trip a hard failure.

    Raises ``ValueError`` on any parse or shape error rather than
    letting the SDK raise later — the earlier we fail, the clearer
    the operator's error surface is.
    """
    raw = config.get("password") or config.get("credentials_json") or ""
    if not raw:
        raise ValueError(
            "GCP Cloud Logging requires a service-account JSON key in the "
            "'password' field (paste the full JSON contents)"
        )

    if isinstance(raw, dict):
        info = raw
    else:
        try:
            info = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "GCP Cloud Logging credentials: password field is not "
                "valid JSON"
            ) from exc

    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise ValueError(
            "GCP Cloud Logging credentials: expected a service-account "
            "JSON key (with type='service_account')"
        )

    try:
        from google.oauth2 import service_account
    except ImportError as exc:
        raise ImportError(
            "GCP integration requires the google-cloud-logging package. "
            "Install with: pip install google-cloud-logging"
        ) from exc

    return service_account.Credentials.from_service_account_info(info)


def _build_client(project_id: str, credentials):
    """Create the Cloud Logging client. Isolated so tests can monkeypatch."""
    try:
        from google.cloud import logging_v2
    except ImportError as exc:
        raise ImportError(
            "GCP integration requires the google-cloud-logging package. "
            "Install with: pip install google-cloud-logging"
        ) from exc
    return logging_v2.Client(project=project_id, credentials=credentials)


class GcpCloudLoggingProvider(LogProvider):
    """
    GCP Cloud Logging (formerly Stackdriver) log provider.

    Config (from ObservabilityIntegration):
        password           Service-account JSON key. Encrypted at rest.
        extra_config:
            project_id     GCP project ID (REQUIRED — no host inference)
            max_page_size  Cap per page in list_entries (default 1000)
    """

    capabilities = LogProviderCapabilities(
        full_text=True,
        regex=False,        # GCP filter uses `:` substring, not regex
        aggregations=True,  # via BigQuery export, not inline — but true in spirit
        tail=True,          # tail_log_entries() is supported
        max_query_window_days=30,
        indexing=False,
    )

    DEFAULT_PAGE_SIZE = 1000

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        project_id = self._config.get("project_id")
        if not project_id:
            raise ValueError(
                "GCP Cloud Logging requires 'project_id' in extra_config"
            )
        self._project_id = project_id
        self._max_page_size = int(
            self._config.get("max_page_size", self.DEFAULT_PAGE_SIZE)
        )
        credentials = _load_credentials(self._config)
        self._client = _build_client(project_id, credentials)

    # ------------------------------------------------------------------
    # LogProvider ABC
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """Prove the credentials work by listing one log entry.

        We can't use a project-info call because the SDK returns
        stale-cached project metadata even when auth is broken. The
        cheapest network-round-trip that actually authenticates is a
        one-entry list.
        """
        try:
            # Iterating a single item to force auth to run
            iterator = self._client.list_entries(
                page_size=1,
                max_results=1,
            )
            for _ in iterator:
                break
            return True
        except Exception as exc:
            logger.error("GCP Cloud Logging health check failed: %s", exc)
            return False

    def search(
        self,
        index: str,
        query,  # dict (legacy) or LogQuery
        time_range: Optional[Tuple[datetime, datetime]] = None,
        size: int = 5000,
    ) -> List[LogEntry]:
        """Execute a Cloud Logging query.

        ``index`` is used as an optional log-name filter (empty means
        all logs in the project). The rest of the filter is built
        from ``LogQuery`` via ``to_gcp_filter()``.
        """
        # Compose filter — start from LogQuery, then optionally
        # narrow by log_name (index).
        if isinstance(query, LogQuery):
            if not query.time_range and time_range:
                query.time_range = time_range
            gcp_filter = query.to_gcp_filter()
            size = query.max_results
        elif isinstance(query, dict):
            gcp_filter = query.get("filter", "")
        else:
            raise TypeError(
                f"GCP Cloud Logging search: unsupported query type "
                f"{type(query).__name__}"
            )

        if index:
            # log_name filter uses the fully-qualified form. If the
            # caller passes a short name we prefix it; if they pass a
            # full path we keep it. Never inline as a bareword.
            from integrations.schemas import _gcp_escape
            if index.startswith("projects/"):
                log_name = index
            else:
                log_name = f"projects/{self._project_id}/logs/{index}"
            log_clause = f'logName="{_gcp_escape(log_name)}"'
            gcp_filter = (
                f"{log_clause} AND {gcp_filter}" if gcp_filter else log_clause
            )

        try:
            iterator = self._client.list_entries(
                filter_=gcp_filter or None,
                page_size=min(self._max_page_size, size),
                max_results=size,
                order_by="timestamp desc",
            )
        except Exception as exc:
            logger.error("GCP Cloud Logging list_entries failed: %s", exc)
            return []

        entries: List[LogEntry] = []
        try:
            for gcp_entry in iterator:
                entries.append(self._to_log_entry(gcp_entry, index))
                if len(entries) >= size:
                    break
        except Exception as exc:
            # A mid-iteration failure is common (rate limits, token
            # expiry). Log it and return what we already have —
            # partial results are more useful than nothing.
            logger.warning(
                "GCP Cloud Logging iteration ended early after %d entries: %s",
                len(entries), exc,
            )
        return entries

    def get_indices(self, project) -> List[str]:
        """List the *distinct log names* seen in the configured project.

        Cloud Logging doesn't really have "indexes" in the ES sense;
        the closest analogue for a UI picker is the set of log names
        (``logName`` field) present in the project. We cap the number
        we list because pathological projects can have thousands.
        """
        # `project` is intentionally ignored — the ObservabilityIntegration
        # already scopes to a single GCP project via project_id.
        try:
            names: set = set()
            iterator = self._client.list_entries(
                page_size=100,
                max_results=100,
                order_by="timestamp desc",
            )
            for entry in iterator:
                if getattr(entry, "log_name", None):
                    names.add(entry.log_name)
                if len(names) >= 50:
                    break
            return sorted(names)
        except Exception as exc:
            logger.warning("GCP Cloud Logging get_indices failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _to_log_entry(gcp_entry, index_hint: str = "") -> LogEntry:
        """Normalise a google.cloud.logging_v2.LogEntry to LogEntry.

        The SDK returns one of several concrete entry types
        (``StructEntry``, ``TextEntry``, ``ProtobufEntry``) — we
        inspect attributes rather than isinstance-check to stay loose.
        """
        # payload might be str (TextEntry), dict (StructEntry), or a
        # protobuf message (rare). We coerce to string for the
        # canonical message and keep structured data in labels.
        payload = getattr(gcp_entry, "payload", None)
        labels_from_payload = {}
        if isinstance(payload, dict):
            message = payload.get("message") or json.dumps(payload)[:1000]
            labels_from_payload = {k: v for k, v in payload.items() if k != "message"}
        elif isinstance(payload, str):
            message = payload
        else:
            message = str(payload) if payload is not None else ""

        # Labels come from three places: SDK ``labels``, the payload
        # dict (for jsonPayload-style logs), and resource labels.
        sdk_labels = dict(getattr(gcp_entry, "labels", None) or {})
        resource = getattr(gcp_entry, "resource", None)
        resource_labels = {}
        if resource is not None:
            resource_labels = dict(getattr(resource, "labels", None) or {})

        # Timestamp — Cloud Logging gives us a python datetime already,
        # already in UTC. Fall back to _parse_timestamp for the rare
        # case where the SDK gives a string.
        ts = getattr(gcp_entry, "timestamp", None)
        if isinstance(ts, datetime):
            timestamp = ts
        elif isinstance(ts, str):
            timestamp = _parse_timestamp(ts)
        else:
            timestamp = datetime.min

        # Severity is an int (100..800) or a string. Normalise to str
        # before hitting _detect_level.
        raw_severity = getattr(gcp_entry, "severity", "INFO")
        if isinstance(raw_severity, int):
            # Reverse the ordinal map — mirrors LogQuery.to_gcp_filter.
            severity_by_ord = {
                100: "DEBUG", 200: "INFO", 300: "NOTICE",
                400: "WARNING", 500: "ERROR",
                600: "CRITICAL", 700: "ALERT", 800: "EMERGENCY",
            }
            raw_severity = severity_by_ord.get(raw_severity, "INFO")

        return LogEntry(
            timestamp=timestamp,
            message=message,
            level=_detect_level(raw_severity),
            service=(
                sdk_labels.get("service_name")
                or labels_from_payload.get("service_name")
                or resource_labels.get("service_name", "")
            ),
            host=resource_labels.get("instance_id", ""),
            trace_id=str(getattr(gcp_entry, "trace", "") or ""),
            raw_id=str(getattr(gcp_entry, "insert_id", "") or ""),
            labels={
                "_index": index_hint or getattr(gcp_entry, "log_name", "") or "",
                **sdk_labels,
                **{f"resource.{k}": v for k, v in resource_labels.items()},
                **{k: v for k, v in labels_from_payload.items() if k not in (
                    "message", "level", "log_level", "service_name",
                )},
            },
        )
