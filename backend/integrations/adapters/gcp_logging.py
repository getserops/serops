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
    _detect_level_from_line,
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
                "GCP credentials: password field is not "
                "valid JSON"
            ) from exc

    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise ValueError(
            "GCP credentials: expected a service-account "
            "JSON key (with type='service_account')"
        )
    info = _checked_key_info(info)

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


GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


def _checked_key_info(info: dict) -> dict:
    """The key with Google's token endpoint, or ValueError.

    The key file names the URL the SDK sends the signed token to. A key
    pointing it anywhere but Google made the server POST to an internal
    address and showed part of the answer in the health check (review
    2026-11-05). Only Google's own token endpoint and domain are accepted.
    """
    token_uri = info.get("token_uri") or GOOGLE_TOKEN_URI
    if token_uri != GOOGLE_TOKEN_URI:
        raise ValueError(f"GCP credentials: token_uri must be {GOOGLE_TOKEN_URI}")
    if info.get("universe_domain", "googleapis.com") != "googleapis.com":
        raise ValueError("GCP credentials: universe_domain must be googleapis.com")
    return {**info, "token_uri": GOOGLE_TOKEN_URI}


def _health_reason(exc: Exception, project_id: str, role: str) -> str:
    """What the health check shows when Google refuses: the reason, not
    "Health check failed" (a project ID typo looked like a broken key)."""
    text = str(exc)
    if "403" in text or "PermissionDenied" in type(exc).__name__ or "permission" in text.lower():
        return (f"Google refused access to project {project_id}: check the project ID, "
                f"and that the service account has the {role} role on it.")
    if "404" in text or "NotFound" in type(exc).__name__:
        return f"Google found no project {project_id}: check the project ID."
    # Never the exception text: it can carry another server's answer.
    return "Google Cloud refused the request; the backend log has the details."


def _is_audit_log(log_name: str) -> bool:
    return "cloudaudit.googleapis.com" in (log_name or "")


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

    # Cloud Logging selects by filter, like Loki: no location is needed, and
    # none is discovered (see get_indices).
    NEEDS_LOG_LOCATION = False

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
            self.last_error = None
            return True
        except Exception as exc:
            logger.error("GCP Cloud Logging health check failed: %s", exc)
            self.last_error = _health_reason(exc, self._project_id, "Logs Viewer")
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

        log_clause = self._log_name_clause(index)
        if log_clause:
            gcp_filter = f"{log_clause} AND {gcp_filter}" if gcp_filter else log_clause

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
        """No locations: the project's logs are found by filter.

        This listed the log names of the last 100 entries, and callers then
        searched only those. Whichever log was busiest at that moment decided
        what an analysis could see: once a GKE cluster's VMs logged their
        integrity checks, its container logs (stdout, stderr) dropped out and
        every search returned nothing (GKE live test, 2026-11-05).
        """
        return []

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _log_name_clause(self, index: str) -> str:
        """``logName`` filter for one location or several, comma-separated.

        Callers join every location with commas (Check my data, batch
        collection), and that string used to become a single
        ``logName="a,b,c"`` matching nothing: on GKE, Check my data said
        "no logs at all" next to thousands of container logs. Audit logs
        are left out unless asked for alone: they are Google's record of
        API calls (most of a GKE project's volume), not application logs.
        """
        from integrations.schemas import _gcp_escape
        names = [n.strip() for n in (index or "").split(",") if n.strip()]
        if len(names) > 1:
            names = [n for n in names if not _is_audit_log(n)]
        if not names:
            return 'NOT logName:"cloudaudit.googleapis.com"'
        full = [n if n.startswith("projects/") else f"projects/{self._project_id}/logs/{n}" for n in names]
        ors = [f'logName="{_gcp_escape(n)}"' for n in full]
        return ors[0] if len(ors) == 1 else "(" + " OR ".join(ors) + ")"

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

        level = _detect_level(raw_severity)
        k8s = getattr(resource, "type", "") == "k8s_container"
        if k8s and isinstance(payload, str) and str(getattr(gcp_entry, "log_name", "")).endswith("/stderr"):
            # GKE rates every plain-text stderr line ERROR (and stdout INFO):
            # the stream, not the line. Read the line's own level instead; a
            # line naming none stays INFO. Observed on GKE: an OpenTelemetry
            # collector's 660 ordinary lines a hour all showed as errors.
            level = _detect_level_from_line(message, default="INFO")

        # GKE names the workload in pod labels and the namespace on the
        # resource; nothing carries service_name. Without this every GKE log
        # had no service and no host (GKE live test, 2026-11-05).
        service = (sdk_labels.get("service_name")
                   or labels_from_payload.get("service_name")
                   or resource_labels.get("service_name", ""))
        if k8s and not service:
            service = (sdk_labels.get("k8s-pod/app")
                       or sdk_labels.get("k8s-pod/app_kubernetes_io/name")
                       or sdk_labels.get("logging.gke.io/top_level_controller_name")
                       or resource_labels.get("container_name", ""))
        k8s_labels = {}
        if k8s and resource_labels.get("namespace_name"):
            # What Check my data groups by and offers as a project rule.
            k8s_labels["namespace"] = resource_labels["namespace_name"]

        return LogEntry(
            timestamp=timestamp,
            message=message,
            level=level,
            service=service,
            host=(sdk_labels.get("compute.googleapis.com/resource_name")
                  or resource_labels.get("instance_id", "")),
            trace_id=str(getattr(gcp_entry, "trace", "") or ""),
            raw_id=str(getattr(gcp_entry, "insert_id", "") or ""),
            labels={
                "_index": index_hint or getattr(gcp_entry, "log_name", "") or "",
                **k8s_labels,
                **sdk_labels,
                **{f"resource.{k}": v for k, v in resource_labels.items()},
                **{k: v for k, v in labels_from_payload.items() if k not in (
                    "message", "level", "log_level", "service_name",
                )},
            },
        )
