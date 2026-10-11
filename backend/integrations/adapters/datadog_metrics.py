"""
Datadog Metrics Adapter for MetricProvider.

Implements the MetricProvider ABC using the Datadog HTTP API.
Uses the Query Timeseries endpoint for range queries.
"""
import logging
from datetime import datetime
from typing import List, Optional

import requests
from requests.exceptions import RequestException

from integrations.base import MetricProvider, MetricProviderCapabilities
from integrations.schemas import TimeSeries, TimeSeriesPoint, HostInfo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Kubernetes topology mode
# ---------------------------------------------------------------------------
# Maps canonical SerOps metric names to Datadog's Kubernetes integration
# metric names. Requires the Datadog Agent's Kubernetes check to be enabled
# (default on DaemonSet installs). Aggregated `by {service_name}` at query
# time so per-service dashboards work across pod restarts / node reschedules.
K8S_METRIC_NAME_MAP = {
    'node_memory_MemTotal_bytes':     'kubernetes.memory.limits',
    'node_memory_MemFree_bytes':      'kubernetes.memory.usage',   # inverse — DD lacks a "free" metric
    'node_memory_MemAvailable_bytes': 'kubernetes.memory.usage',
    'node_cpu_seconds_total':         'kubernetes.cpu.usage.total',
}


class DatadogMetricProvider(MetricProvider):
    """
    Datadog Metrics adapter using the HTTP API.

    Endpoints used:
      - GET  /api/v1/query — timeseries queries
      - GET  /api/v1/hosts — host discovery
      - GET  /api/v1/validate — health check
    """

    capabilities = MetricProviderCapabilities(
        high_cardinality=True,
        histograms=True,
        exemplars=False,
        max_query_window_days=15,
    )

    def __init__(self, config: dict = None):
        super().__init__(config)
        site = self._config.get("site", "datadoghq.com")
        self.base_url = f"https://api.{site}"
        self._session = requests.Session()
        self._session.headers.update({
            "DD-API-KEY": self._config.get("api_key", ""),
            "DD-APPLICATION-KEY": self._config.get("app_key", ""),
            "Content-Type": "application/json",
        })
        # Topology mode: 'vm' (system.mem/cpu metrics) | 'kubernetes'
        # (kubernetes.* metrics aggregated by service_name).
        self._topology_mode = self._config.get("topology_mode", "vm")

    # ------------------------------------------------------------------
    # MetricProvider ABC
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """Validate API key."""
        try:
            resp = self._session.get(
                f"{self.base_url}/api/v1/validate",
                timeout=self.timeout_seconds,
            )
            return resp.status_code == 200
        except RequestException as exc:
            logger.error("Datadog Metrics health check failed: %s", exc)
            return False

    def query_range(
        self,
        metric: str,
        labels: dict,
        start: datetime,
        end: datetime,
    ) -> List[TimeSeries]:
        """
        Query Datadog timeseries.

        VM mode builds a DD query like:
            avg:system.mem.total{organisation_name:acme,environment:prod}
        Kubernetes mode uses `kubernetes.*` metrics aggregated by service:
            avg:kubernetes.cpu.usage.total{organisation_name:acme} by {service_name}
        """
        dd_query = self._build_metric_query(metric, labels, topology_mode=self._topology_mode)
        params = {
            "from": int(start.timestamp()),
            "to": int(end.timestamp()),
            "query": dd_query,
        }

        try:
            resp = self._session.get(
                f"{self.base_url}/api/v1/query",
                params=params,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            return self._parse_series(data, metric)

        except RequestException as exc:
            logger.error("Datadog query_range failed: %s", exc)
            return []

    def discover_hosts(
        self,
        org: str,
        project: Optional[str] = None,
        environment: Optional[str] = None,
    ) -> List[HostInfo]:
        """
        Discover hosts from Datadog infrastructure.
        Uses /api/v1/hosts endpoint.
        """
        params = {"count": 1000}
        if environment:
            params["filter"] = f"env:{environment}"

        try:
            resp = self._session.get(
                f"{self.base_url}/api/v1/hosts",
                params=params,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()

            hosts: List[HostInfo] = []
            for host_data in data.get("host_list", []):
                tags = {}
                for tag in host_data.get("tags_by_source", {}).get("Datadog", []):
                    if ":" in tag:
                        k, v = tag.split(":", 1)
                        tags[k] = v

                hosts.append(
                    HostInfo(
                        hostname=host_data.get("name", ""),
                        environment=tags.get("env", environment or "unknown"),
                        labels={"host_name": host_data.get("name", ""), **tags},
                        project=project or "",
                    )
                )
            return hosts

        except RequestException as exc:
            logger.error("Datadog discover_hosts failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    # Map canonical names → Datadog metric names
    METRIC_NAME_MAP = {
        "node_memory_MemTotal_bytes": "system.mem.total",
        "node_memory_MemFree_bytes": "system.mem.free",
        "node_memory_MemAvailable_bytes": "system.mem.usable",
        "node_cpu_seconds_total": "system.cpu.user",
    }

    @classmethod
    def _build_metric_query(cls, metric: str, labels: dict, topology_mode: str = 'vm') -> str:
        """
        Build a Datadog metric query.

        VM mode:
            _build_metric_query("node_memory_MemTotal_bytes", {"organisation_name": "acme"})
            → 'avg:system.mem.total{organisation_name:acme}'

        Kubernetes mode:
            _build_metric_query("node_cpu_seconds_total", {"organisation_name": "acme"}, topology_mode='kubernetes')
            → 'avg:kubernetes.cpu.usage.total{organisation_name:acme} by {service_name}'

        Unknown metrics in K8s mode fall through to the VM name map so
        callers passing custom metrics still get a query (just not
        aggregated by service).
        """
        if topology_mode == 'kubernetes':
            k8s_metric = K8S_METRIC_NAME_MAP.get(metric)
            if k8s_metric:
                if labels:
                    tag_filter = ",".join(f"{k}:{v}" for k, v in labels.items() if v)
                    selector = f"{{{tag_filter}}}"
                else:
                    selector = "{*}"
                return f"avg:{k8s_metric}{selector} by {{service_name}}"
            # Fall through to VM path for unmapped metrics.

        dd_metric = cls.METRIC_NAME_MAP.get(metric, metric)
        if labels:
            tag_filter = ",".join(f"{k}:{v}" for k, v in labels.items() if v)
            return f"avg:{dd_metric}{{{tag_filter}}}"
        return f"avg:{dd_metric}{{*}}"

    @staticmethod
    def _parse_series(data: dict, metric_name: str) -> List[TimeSeries]:
        """
        Parse Datadog query API response into canonical TimeSeries.

        Response format:
            {"series": [{"pointlist": [[ts_ms, value], ...], "scope": "host:web-1", ...}]}
        """
        series_list: List[TimeSeries] = []
        for series in data.get("series", []):
            # Parse scope string "host:web-1,env:prod" into labels
            scope = series.get("scope", "")
            labels = {}
            if scope and scope != "*":
                for part in scope.split(","):
                    if ":" in part:
                        k, v = part.split(":", 1)
                        labels[k] = v

            points = [
                TimeSeriesPoint(
                    timestamp=datetime.fromtimestamp(point[0] / 1000),
                    value=float(point[1]) if point[1] is not None else 0.0,
                )
                for point in series.get("pointlist", [])
                if len(point) >= 2
            ]

            series_list.append(
                TimeSeries(
                    metric_name=metric_name,
                    labels=labels,
                    points=points,
                )
            )
        return series_list
