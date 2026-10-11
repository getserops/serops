"""
Azure Log Analytics Adapter for LogProvider.

Uses the ``azure-monitor-query`` SDK (LogsQueryClient) with a service
principal for auth. Deliberately does NOT support DefaultAzureCredential
or ManagedIdentityCredential — same reason as GCP: a multi-tenant
SerOps process must not accidentally inherit host-level credentials
and read the wrong customer's workspace.

Endpoints used (via SDK):
  - ``client.query_workspace(workspace_id, query, timespan)`` — search
  - ``client.query_workspace(...)`` with a metadata query — health check
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from integrations.base import LogProvider, LogProviderCapabilities
from integrations.schemas import (
    LogEntry,
    LogQuery,
    _detect_level,
)

logger = logging.getLogger(__name__)


def _build_credential(tenant_id: str, client_id: str, client_secret: str):
    """Build a ClientSecretCredential. Isolated for test monkeypatching."""
    if not (tenant_id and client_id and client_secret):
        raise ValueError(
            "Azure adapter requires tenant_id + client_id + password "
            "(client secret) — service principal auth is the only "
            "supported mode"
        )
    try:
        from azure.identity import ClientSecretCredential
    except ImportError as exc:
        raise ImportError(
            "Azure integration requires the azure-identity package. "
            "Install with: pip install azure-identity"
        ) from exc
    return ClientSecretCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )


def _build_logs_client(credential):
    """Build a LogsQueryClient. Isolated for test monkeypatching."""
    try:
        from azure.monitor.query import LogsQueryClient
    except ImportError as exc:
        raise ImportError(
            "Azure integration requires the azure-monitor-query package. "
            "Install with: pip install azure-monitor-query"
        ) from exc
    return LogsQueryClient(credential=credential)


class AzureLogAnalyticsProvider(LogProvider):
    """
    Azure Log Analytics log provider.

    Config (from ObservabilityIntegration):
        password           Client secret. Encrypted at rest.
        extra_config:
            tenant_id      Azure AD tenant ID (REQUIRED)
            client_id      Service principal application ID (REQUIRED)
            workspace_id   Log Analytics workspace ID (REQUIRED)
            default_table  KQL table to query (default 'AppTraces')
            timeout_seconds  Per-query timeout (default 30)
    """

    capabilities = LogProviderCapabilities(
        full_text=True,
        regex=True,
        aggregations=True,
        tail=False,
        max_query_window_days=30,
        indexing=False,
    )

    DEFAULT_TABLE = "AppTraces"

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)

        tenant_id = self._config.get("tenant_id")
        client_id = self._config.get("client_id")
        workspace_id = self._config.get("workspace_id")
        client_secret = self._config.get("password") or self._config.get("client_secret")

        if not workspace_id:
            raise ValueError(
                "Azure Log Analytics requires 'workspace_id' in extra_config"
            )
        self._workspace_id = workspace_id
        self._default_table = self._config.get("default_table", self.DEFAULT_TABLE)

        # This will raise ValueError early if any auth field is missing.
        credential = _build_credential(tenant_id, client_id, client_secret)
        self._client = _build_logs_client(credential)

    # ------------------------------------------------------------------
    # LogProvider ABC
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """One-row metadata query — cheapest authenticated call."""
        try:
            self._client.query_workspace(
                workspace_id=self._workspace_id,
                query="print now()",
                timespan=timedelta(minutes=1),
            )
            return True
        except Exception as exc:
            logger.error("Azure Log Analytics health check failed: %s", exc)
            return False

    def search(
        self,
        index: str,
        query,  # dict, str KQL, or LogQuery
        time_range: Optional[Tuple[datetime, datetime]] = None,
        size: int = 5000,
    ) -> List[LogEntry]:
        """Execute a KQL query against the configured workspace.

        ``index`` is used as the KQL table name when a ``LogQuery`` is
        supplied — matches the SPL adapter's index concept.
        """
        table = index or self._default_table

        if isinstance(query, LogQuery):
            if not query.time_range and time_range:
                query.time_range = time_range
            kql = query.to_azure_kql(table=table)
            size = query.max_results
        elif isinstance(query, dict):
            kql = query.get("kql") or query.get("query", "")
        elif isinstance(query, str):
            kql = query
        else:
            raise TypeError(
                f"Azure Log Analytics search: unsupported query type "
                f"{type(query).__name__}"
            )

        # Timespan — Azure accepts a timedelta, a (start, end) tuple,
        # or (start, timedelta). We use the tuple form for clarity.
        if time_range:
            timespan = time_range
        else:
            now = datetime.utcnow()
            timespan = (now - timedelta(hours=1), now)

        try:
            response = self._client.query_workspace(
                workspace_id=self._workspace_id,
                query=kql,
                timespan=timespan,
            )
        except Exception as exc:
            logger.error("Azure Log Analytics query_workspace failed: %s", exc)
            return []

        return self._parse_response(response, table, size)

    def get_indices(self, project) -> List[str]:
        """List Log Analytics table names visible to the service principal.

        We use a KQL metadata query — ``getschema | distinct TableName``
        would be ideal but doesn't work for cross-table introspection.
        Instead we run a fixed query that returns table names from the
        workspace schema.
        """
        # `project` is intentionally ignored — the integration record
        # already scopes to a single workspace.
        query = "search *\n| take 0\n| getschema | project TableName | distinct TableName"
        try:
            response = self._client.query_workspace(
                workspace_id=self._workspace_id,
                query=query,
                timespan=timedelta(minutes=1),
            )
        except Exception as exc:
            logger.warning("Azure get_indices failed: %s", exc)
            return []
        # Best-effort — the exact shape depends on SDK response class.
        tables = getattr(response, "tables", None) or []
        names: list = []
        for table in tables:
            for row in getattr(table, "rows", []) or []:
                if row and isinstance(row[0], str):
                    names.append(row[0])
        return sorted(set(names))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(response, table_name: str, size: int) -> List[LogEntry]:
        """Normalise a LogsQueryResult into LogEntry objects.

        The SDK returns a ``LogsQueryResult`` (success) or
        ``LogsQueryPartialResult`` (partial failure with useful data).
        Both expose ``tables[i].rows`` + ``tables[i].columns`` — we
        handle both by attribute-inspecting rather than type-checking.
        """
        entries: List[LogEntry] = []
        # Partial results have a ``partial_data`` list; success has ``tables``.
        tables = getattr(response, "tables", None) or getattr(response, "partial_data", None) or []
        for tbl in tables:
            columns = [
                getattr(c, "name", c) if not isinstance(c, str) else c
                for c in getattr(tbl, "columns", []) or []
            ]
            for row in getattr(tbl, "rows", []) or []:
                if len(entries) >= size:
                    return entries
                fields = dict(zip(columns, row))
                # Standard AppTraces columns; fall back gracefully for
                # other tables.
                ts = fields.get("TimeGenerated")
                if not isinstance(ts, datetime):
                    ts = datetime.min

                raw_level = str(
                    fields.get("SeverityLevel")
                    or fields.get("Level")
                    or "Information"
                )
                # AppTraces SeverityLevel is 0..4; other tables use
                # strings. _detect_level handles the string case; we
                # translate the int case here.
                int_level_map = {
                    "0": "DEBUG", "1": "INFO", "2": "WARN",
                    "3": "ERROR", "4": "CRITICAL",
                }
                if raw_level in int_level_map:
                    raw_level = int_level_map[raw_level]

                # AppTraces Properties is a JSON string; we surface
                # the whole dict into labels so downstream filtering
                # works uniformly.
                properties = fields.get("Properties") or fields.get("CustomDimensions") or {}
                if isinstance(properties, str):
                    import json
                    try:
                        properties = json.loads(properties)
                    except (TypeError, ValueError):
                        properties = {"_raw_properties": properties}
                if not isinstance(properties, dict):
                    properties = {}

                entries.append(
                    LogEntry(
                        timestamp=ts,
                        message=str(
                            fields.get("Message")
                            or fields.get("RenderedMessage")
                            or fields.get("_ResourceId", "")
                        ),
                        level=_detect_level(raw_level),
                        service=str(
                            properties.get("service_name")
                            or fields.get("ServiceName", "")
                            or ""
                        ),
                        host=str(
                            fields.get("Computer")
                            or fields.get("HostName", "")
                            or ""
                        ),
                        trace_id=str(fields.get("OperationId", "") or ""),
                        raw_id=str(fields.get("ItemId", "") or ""),
                        labels={
                            "_index": table_name,
                            **{
                                k: v for k, v in fields.items()
                                if k not in (
                                    "TimeGenerated", "Message", "SeverityLevel",
                                    "Level", "OperationId", "ItemId",
                                    "Properties", "CustomDimensions",
                                )
                            },
                            **{f"properties.{k}": v for k, v in properties.items()},
                        },
                    )
                )
        return entries
