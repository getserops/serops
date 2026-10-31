"""
Datadog Metrics Adapter for MetricProvider.

Implements the MetricProvider ABC using the Datadog HTTP API.
Uses the Query Timeseries endpoint for range queries.
"""
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

import requests
from requests.exceptions import RequestException

from integrations.base import MetricProvider, MetricProviderCapabilities
from integrations.schemas import TimeSeries, TimeSeriesPoint, HostInfo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Kubernetes topology mode
# ---------------------------------------------------------------------------
def _dd_tag_value(value) -> str:
    """A tag value as Datadog stores it: lowercase, other characters as "_".

    Datadog keeps "organisation_name:Acme Cloud" as "acme_cloud", and a
    query naming "Acme Cloud" is not even parsed (the space ends it), so an
    organisation with a space in its name got no metrics at all.
    """
    v = re.sub(r"[^a-z0-9_:./-]", "_", str(value).lower())
    return re.sub(r"_+", "_", v).strip("_")


def _tag_filter(labels: dict) -> str:
    return ",".join(f"{k}:{_dd_tag_value(v)}" for k, v in labels.items() if v)


# Kubernetes topology mode: the container metrics the Datadog Agent sends
# (container check, on by default), summed per service like the Prometheus
# templates. Found against a real Agent (7.x, datadog/datadog chart): it sends
# no kubernetes.cpu.usage.total nor kubernetes.memory.usage, and no
# service_name tag. Every container carries `service` (the deployment name
# unless Unified Service Tagging sets it).
#   CPU     container.cpu.usage is nanocores: / 1e9 gives cores, which the
#           pipeline turns into "% of one core" as for Prometheus.
#   Memory  free = limit - usage (no "free" metric in container land).
K8S_METRIC_QUERIES = {
    'node_memory_MemTotal_bytes':     'sum:container.memory.limit{sel} by {{service}}',
    'node_memory_MemFree_bytes':      ('sum:container.memory.limit{sel} by {{service}} - '
                                       'sum:container.memory.usage{sel} by {{service}}'),
    'node_memory_MemAvailable_bytes': ('sum:container.memory.limit{sel} by {{service}} - '
                                       'sum:container.memory.usage{sel} by {{service}}'),
    'node_cpu_seconds_total':         'sum:container.cpu.usage{sel} by {{service}} / 1000000000',
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

    @property
    def cpu_is_percent(self) -> bool:
        """system.cpu.user is a percentage, not a seconds counter."""
        return self._topology_mode != "kubernetes"

    def __init__(self, config: dict = None):
        super().__init__(config)
        from integrations.adapters.datadog_logs import datadog_site
        self.base_url = f"https://api.{datadog_site(self._config)}"
        self.last_error = None
        self._session = requests.Session()
        self._session.headers.update({
            "DD-API-KEY": self._config.get("api_key", ""),
            "DD-APPLICATION-KEY": self._config.get("app_key", ""),
            "Content-Type": "application/json",
        })
        # Topology mode: 'vm' (system.mem/cpu metrics, one series per host) |
        # 'kubernetes' (container.* metrics, one series per service).
        self._topology_mode = self._config.get("topology_mode", "vm")

    # ------------------------------------------------------------------
    # MetricProvider ABC
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """The API key is valid on this site AND the application key can
        query metrics (timeseries_query scope)."""
        import time
        self.last_error = None
        try:
            resp = self._session.get(f"{self.base_url}/api/v1/validate", timeout=self.timeout_seconds)
            if resp.status_code != 200:
                self.last_error = (f"The API key is not valid on {self.base_url.replace('https://api.', '')}. "
                                   "Check the key and the Datadog site (e.g. datadoghq.eu).")
                return False
            now = int(time.time())
            resp = self._session.get(f"{self.base_url}/api/v1/query", timeout=self.timeout_seconds,
                                     params={"from": now - 300, "to": now, "query": "avg:system.cpu.user{*}"})
            if resp.status_code in (401, 403):
                self.last_error = ("The application key cannot query metrics. Give it the "
                                   "timeseries_query scope.")
                return False
            return True
        except RequestException as exc:
            logger.error("Datadog Metrics health check failed: %s", exc)
            self.last_error = f"Datadog is not reachable: {exc}"
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
        Kubernetes mode uses the container metrics summed per service:
            sum:container.cpu.usage{organisation_name:acme} by {service} / 1000000000
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
            series = self._parse_series(data, metric)
            if self._topology_mode == 'kubernetes':
                # The pipeline keys per-service series on service_name.
                for ts in series:
                    if 'service' in ts.labels:
                        ts.labels.setdefault('service_name', ts.labels['service'])
            return series

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
            → 'sum:container.cpu.usage{organisation_name:acme} by {service} / 1000000000'

        Unknown metrics in K8s mode fall through to the VM name map so
        callers passing custom metrics still get a query (just not
        aggregated by service).
        """
        if topology_mode == 'kubernetes':
            template = K8S_METRIC_QUERIES.get(metric)
            if template:
                return template.format(sel=f"{{{_tag_filter(labels) or '*'}}}")
            # Fall through to VM path for unmapped metrics.

        # One series per host: averaged over every host, one host running out
        # of memory read as a fleet at half capacity.
        dd_metric = cls.METRIC_NAME_MAP.get(metric, metric)
        selector = f"{{{_tag_filter(labels)}}}" if _tag_filter(labels) else "{*}"
        return f"avg:{dd_metric}{selector} by {{host}}"

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
                    timestamp=datetime.fromtimestamp(point[0] / 1000, tz=timezone.utc),
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
