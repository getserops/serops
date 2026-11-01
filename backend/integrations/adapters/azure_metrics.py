"""
Azure Monitor Metrics Adapter for MetricProvider.

Uses the ``azure-monitor-query`` SDK (MetricsQueryClient). Same
service-principal auth as the Log Analytics adapter — reused via the
``_build_credential`` helper in ``azure_logs``.

Endpoints used (via SDK):
  - ``client.query_resource(resource_uri, metric_names, timespan,
    granularity, aggregations)`` — range query for one metric on one
    resource
  - ``client.list_metric_definitions(resource_uri)``   — used by
    health_check + discover_hosts
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from integrations.adapters.azure_logs import _azure_error, _build_credential, _build_logs_client
from integrations.base import MetricProvider, MetricProviderCapabilities
from integrations.schemas import _kql_datetime, _kql_escape
from integrations.schemas import HostInfo, TimeSeries, TimeSeriesPoint

logger = logging.getLogger(__name__)


def _build_metrics_client(credential):
    """Build a MetricsQueryClient. Isolated for test monkeypatching."""
    try:
        from azure.monitor.query import MetricsQueryClient
    except ImportError as exc:
        raise ImportError(
            "Azure Monitor integration requires azure-monitor-query. "
            "Install with: pip install azure-monitor-query"
        ) from exc
    return MetricsQueryClient(credential=credential)


class AzureMonitorProvider(MetricProvider):
    """
    Azure Monitor metrics provider.

    Config (from ObservabilityIntegration):
        password           Client secret. Encrypted at rest.
        extra_config:
            tenant_id      Azure AD tenant ID (REQUIRED)
            client_id      Service principal application ID (REQUIRED)
            default_resource_uri  Fallback resource to query when
                                  labels don't supply one (REQUIRED)
    """

    capabilities = MetricProviderCapabilities(
        high_cardinality=True,
        histograms=True,
        exemplars=False,
        max_query_window_days=93,  # Azure Monitor retains 93 days by default
    )

    # Canonical Prometheus names → Azure metric names.
    # VM mode: Compute VM + generic host-level metrics.
    METRIC_NAME_MAP = {
        "node_cpu_seconds_total": "Percentage CPU",
        "node_memory_MemAvailable_bytes": "Available Memory Bytes",
        "container_cpu_usage_seconds_total": "CPU Usage",
        "container_memory_usage_bytes": "Memory Usage",
    }

    # Kubernetes topology mode (Item #18): AKS metrics via Azure
    # Monitor Container Insights. Metrics live on the AKS cluster
    # resource (Microsoft.ContainerService/managedClusters) — the
    # ``default_resource_uri`` should point at the AKS cluster.
    # Reference: https://learn.microsoft.com/en-us/azure/aks/monitor-aks-reference
    K8S_METRIC_NAME_MAP = {
        # Cluster + node capacity — the metrics AKS surfaces natively.
        # ``node_cpu_usage_percentage`` (metric name at the cluster
        # scope) covers the "how much CPU is being used" question.
        "node_cpu_seconds_total": "node_cpu_usage_percentage",
        "node_memory_MemAvailable_bytes": "node_memory_working_set_bytes",
        "node_memory_MemTotal_bytes": "node_memory_rss_percentage",
        # Container-level metrics — the workload story.
        "container_cpu_usage_seconds_total": "container_cpu_usage_percentage",
        "container_memory_usage_bytes": "container_memory_working_set_bytes",
    }

    # Kubernetes mode, with the integration's Log Analytics workspace:
    # Container Insights' per-container counters (Perf, ObjectName
    # K8SContainer), summed per container. Azure Monitor's AKS platform
    # metrics above are per node only; SerOps compares services. Checked
    # against a live AKS cluster (2026-11-01).
    #   limit  memoryLimitBytes (the node's allocatable when unlimited)
    #   free   limit - memoryWorkingSetBytes
    #   cpu    cpuUsageNanoCores in cores (the pipeline multiplies by 100)
    K8S_PERF = {
        "node_memory_MemTotal_bytes": "lim",
        "node_memory_MemFree_bytes": "max_of(lim - ws, 0.0)",
        "node_memory_MemAvailable_bytes": "max_of(lim - ws, 0.0)",
        "node_cpu_seconds_total": "cpu / 1000000000.0",
    }
    # A minute whose counters have not all arrived is left out ("free"
    # would read as the whole limit).
    K8S_PERF_COMPLETE = {
        "node_memory_MemTotal_bytes": "lim > 0",
        "node_memory_MemFree_bytes": "lim > 0 and ws > 0",
        "node_memory_MemAvailable_bytes": "lim > 0 and ws > 0",
        "node_cpu_seconds_total": "cpu > 0",
    }
    # Without a workspace, node metrics with the right units: memory
    # allocatable and working set in bytes, CPU in cores.
    K8S_NODE = {
        "node_memory_MemTotal_bytes": ("kube_node_status_allocatable_memory_bytes", None),
        "node_memory_MemFree_bytes": ("kube_node_status_allocatable_memory_bytes", "node_memory_working_set_bytes"),
        "node_memory_MemAvailable_bytes": ("kube_node_status_allocatable_memory_bytes", "node_memory_working_set_bytes"),
        "node_cpu_seconds_total": ("node_cpu_usage_millicores", None),
    }

    @property
    def cpu_is_percent(self) -> bool:
        """Percentage CPU (VM) is a percentage; Kubernetes mode returns cores."""
        return self._topology_mode != "kubernetes"

    # Filter dimensions that AKS Container Insights exposes.
    # Canonical SerOps label → Azure dimension name.
    _K8S_LABEL_ALIASES = {
        'service_name': 'controllerName',
        'service': 'controllerName',
        'namespace': 'kubernetesNamespace',
        'pod': 'podName',
        'container': 'containerName',
        'node': 'node',
    }

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)

        default_resource = self._config.get("default_resource_uri")
        kubernetes_with_workspace = (self._config.get("topology_mode") == "kubernetes"
                                     and self._config.get("workspace_id"))
        if not default_resource and not kubernetes_with_workspace:
            raise ValueError(
                "Azure Monitor requires 'default_resource_uri' in extra_config "
                "(the Azure resource ID to query metrics from — e.g. "
                "/subscriptions/…/resourceGroups/…/providers/Microsoft.Compute/virtualMachines/…, "
                "OR the AKS cluster ID for topology_mode=kubernetes)"
            )
        self._default_resource = default_resource
        # Item #18: topology_mode governs metric name selection.
        # 'vm'         → Percentage CPU / Available Memory (VM metrics)
        # 'kubernetes' → node_cpu_usage_percentage / container_* (AKS)
        self._topology_mode = self._config.get("topology_mode", "vm")

        credential = _build_credential(
            tenant_id=self._config.get("tenant_id"),
            client_id=self._config.get("client_id"),
            client_secret=self._config.get("password") or self._config.get("client_secret"),
        )
        self._client = _build_metrics_client(credential)
        self._workspace_id = self._config.get("workspace_id")
        self._logs = _build_logs_client(credential) if self._workspace_id else None

    # ------------------------------------------------------------------
    # MetricProvider ABC
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """List metric definitions for the default resource — cheapest auth'd call."""
        self.last_error = None
        if not self._default_resource:
            # Kubernetes mode on the workspace alone: the metrics are read there.
            try:
                self._logs.query_workspace(workspace_id=self._workspace_id, query="print now()",
                                           timespan=timedelta(minutes=1))
                return True
            except Exception as exc:
                logger.error("Azure Monitor health check failed: %s", exc)
                self.last_error = _azure_error(exc)
                return False
        try:
            iterator = self._client.list_metric_definitions(
                self._default_resource
            )
            for _ in iterator:
                return True
            # Empty list is still a successful call
            return True
        except Exception as exc:
            logger.error("Azure Monitor health check failed: %s", exc)
            self.last_error = _azure_error(exc).replace(
                "Log Analytics Reader role on the workspace", "Monitoring Reader role on the resource")
            return False

    def query_range(
        self,
        metric: str,
        labels: dict,
        start: datetime,
        end: datetime,
    ) -> List[TimeSeries]:
        """Query a metric time series.

        The Azure resource URI comes from ``labels['resource_uri']`` if
        supplied, else the adapter default. This lets a caller point
        at any resource without reconfiguring the integration.
        """
        try:
            from azure.monitor.query import MetricAggregationType
        except ImportError:
            return []

        resource_uri = labels.get("resource_uri") if labels else None
        resource_uri = resource_uri or self._default_resource

        if self._topology_mode == "kubernetes" and metric in self.K8S_PERF:
            if self._logs is not None:
                return self._container_series(metric, labels or {}, start, end)
            return self._node_series(metric, resource_uri, start, end)

        # Pick metric name per topology.
        active_map = (
            self.K8S_METRIC_NAME_MAP if self._topology_mode == "kubernetes"
            else self.METRIC_NAME_MAP
        )
        azure_metric = active_map.get(metric, metric)

        timespan = (start, end)
        # Compute an appropriate granularity from the range so we
        # don't overshoot Azure's max-data-point budget.
        granularity = self._pick_granularity(start, end)

        # Build an Azure dimension filter when we're in K8s mode +
        # have workload labels to filter on. Format: 'name eq "value"'
        # joined by 'and'. Any label the AKS metric doesn't support is
        # silently skipped so a misconfigured filter doesn't kill the
        # query.
        filter_str = self._build_dim_filter(labels or {}) if self._topology_mode == 'kubernetes' else None

        try:
            kwargs = {
                'resource_uri': resource_uri,
                'metric_names': [azure_metric],
                'timespan': timespan,
                'granularity': granularity,
                'aggregations': [MetricAggregationType.AVERAGE],
            }
            if filter_str:
                kwargs['filter'] = filter_str
            response = self._client.query_resource(**kwargs)
        except Exception as exc:
            logger.error("Azure Monitor query_resource failed: %s", exc)
            return []

        return self._parse_metrics(response, metric)

    def _container_series(self, metric, labels, start, end) -> List[TimeSeries]:
        """One series per container from Container Insights' Perf counters,
        in the namespace named after the project or the environment (the
        same scope as the CloudWatch and kube-state-metrics paths)."""
        step = int(self._pick_granularity(start, end).total_seconds())
        s = _kql_datetime(start.isoformat().replace("+00:00", "Z"))
        e = _kql_datetime(end.isoformat().replace("+00:00", "Z"))
        namespaces = [str(labels.get(k)) for k in ("project_name", "environment") if labels.get(k)]
        ns = ""
        if namespaces:
            ns = "| where Namespace in~ (" + ", ".join(f'"{_kql_escape(n)}"' for n in namespaces) + ")"
        kql = f"""let pods = KubePodInventory
| where TimeGenerated between (datetime({s}) .. datetime({e}))
{ns}
| distinct PodUid;
Perf
| where TimeGenerated between (datetime({s}) .. datetime({e}))
| where ObjectName == "K8SContainer" and CounterName in ("memoryLimitBytes", "memoryWorkingSetBytes", "cpuUsageNanoCores")
| extend parts = split(InstanceName, "/")
| extend PodUid = tostring(parts[array_length(parts) - 2]), service = tostring(parts[array_length(parts) - 1])
| join kind=inner pods on PodUid
| summarize v = avg(CounterValue) by TimeGenerated = bin(TimeGenerated, {step}s), PodUid, service, CounterName
| summarize lim = sumif(v, CounterName == "memoryLimitBytes"), ws = sumif(v, CounterName == "memoryWorkingSetBytes"),
            cpu = sumif(v, CounterName == "cpuUsageNanoCores") by TimeGenerated, service
| where {self.K8S_PERF_COMPLETE[metric]}
| extend value = {self.K8S_PERF[metric]}
| project TimeGenerated, service, value
| order by service asc, TimeGenerated asc"""
        try:
            response = self._logs.query_workspace(workspace_id=self._workspace_id, query=kql, timespan=(start, end))
        except Exception as exc:
            logger.error("Azure Container Insights metrics query failed: %s", exc)
            return []
        by_service: dict = {}
        for table in getattr(response, "tables", None) or []:
            for ts, service, value in getattr(table, "rows", []) or []:
                if service and value is not None:
                    by_service.setdefault(service, []).append(TimeSeriesPoint(timestamp=ts, value=float(value)))
        return [TimeSeries(metric_name=metric,
                           labels={**labels, "service_name": svc, "host": svc, "instance": svc},
                           points=pts)
                for svc, pts in by_service.items()]

    def _node_series(self, metric, resource_uri, start, end) -> List[TimeSeries]:
        """The AKS cluster as one series, in the units the pipeline expects
        (bytes; CPU in cores). Allocatable memory is a cluster total with no
        node dimension, so this is the whole cluster, not a service: give
        the integration its workspace for per-service metrics."""
        try:
            from azure.monitor.query import MetricAggregationType
        except ImportError:
            return []
        first, minus = self.K8S_NODE[metric]

        def read(name):
            try:
                response = self._client.query_resource(
                    resource_uri=resource_uri, metric_names=[name], timespan=(start, end),
                    granularity=self._pick_granularity(start, end),
                    aggregations=[MetricAggregationType.AVERAGE])
            except Exception as exc:
                logger.error("Azure Monitor query_resource %s failed: %s", name, exc)
                return {}
            out: dict = {}
            for metric_result in getattr(response, "metrics", []) or []:
                for series in getattr(metric_result, "timeseries", []) or []:
                    for point in getattr(series, "data", []) or []:
                        if getattr(point, "average", None) is not None:
                            out[point.timestamp] = out.get(point.timestamp, 0.0) + float(point.average)
            return out

        base = read(first)
        sub = read(minus) if minus else {}
        cluster = resource_uri.rstrip("/").rsplit("/", 1)[-1]
        points = []
        for ts in sorted(base):
            if minus and ts not in sub:
                continue
            value = base[ts] - sub.get(ts, 0.0)
            if first == "node_cpu_usage_millicores":
                value /= 1000.0
            points.append(TimeSeriesPoint(timestamp=ts, value=max(value, 0.0)))
        if not points:
            return []
        return [TimeSeries(metric_name=metric, labels={"host": cluster, "instance": cluster}, points=points)]

    @classmethod
    def _build_dim_filter(cls, labels: dict) -> Optional[str]:
        """Build an Azure Monitor dimension filter string.

        Values are quoted; the underlying SDK further escapes them
        before sending. We reject values with double quotes to
        prevent even the appearance of injection into the filter.
        """
        parts = []
        for raw_key, v in labels.items():
            if v is None or v == "" or raw_key == 'resource_uri':
                continue
            v_str = str(v)
            if '"' in v_str:
                # Malformed / hostile label — silently skip rather
                # than send unquoted content into the filter.
                continue
            mapped = cls._K8S_LABEL_ALIASES.get(str(raw_key))
            if mapped is None:
                continue
            parts.append(f'{mapped} eq "{v_str}"')
        return ' and '.join(parts) if parts else None

    def discover_hosts(
        self,
        org: str,
        project: Optional[str] = None,
        environment: Optional[str] = None,
    ) -> List[HostInfo]:
        """Return one HostInfo per distinct resource seen in a recent CPU query.

        Azure doesn't have a "hosts" endpoint — metrics are scoped to
        resource URIs. Simplest useful surface: sample the default
        resource and return it as the single known host. Callers that
        need multi-resource discovery pass an explicit ``resource_uri``
        via labels.
        """
        if not self._default_resource:
            return []
        return [
            HostInfo(
                hostname=self._default_resource.rsplit("/", 1)[-1] or self._default_resource,
                environment=environment or "",
                project=project or "",
                labels={"resource_uri": self._default_resource},
            )
        ]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _pick_granularity(start: datetime, end: datetime) -> timedelta:
        """Choose a granularity that keeps points under Azure's cap.

        Azure returns at most ~24k points per query. Aim for ~200
        points across the window — smooth enough for a dashboard,
        sparse enough not to trip pagination.
        """
        span = end - start
        seconds = max(int(span.total_seconds()), 60)
        step = max(60, seconds // 200)  # never finer than 1 minute
        return timedelta(seconds=step)

    @staticmethod
    def _parse_metrics(response, canonical_name: str) -> List[TimeSeries]:
        """Normalise MetricsQueryResult into TimeSeries objects."""
        series_list: List[TimeSeries] = []
        for metric_result in getattr(response, "metrics", []) or []:
            for time_series in getattr(metric_result, "timeseries", []) or []:
                labels_from_dims = {}
                for dim in getattr(time_series, "metadata_values", []) or []:
                    # Each dim has .name.value and .value
                    name = getattr(getattr(dim, "name", None), "value", None) or getattr(dim, "name", "")
                    val = getattr(dim, "value", "")
                    if name:
                        labels_from_dims[str(name)] = str(val)

                points: list = []
                for point in getattr(time_series, "data", []) or []:
                    ts = getattr(point, "timestamp", None) or datetime.min
                    if not isinstance(ts, datetime):
                        ts = datetime.min
                    # AVERAGE aggregation is the value we asked for
                    value = getattr(point, "average", None)
                    if value is None:
                        # Fall back to total / count if avg missing
                        value = getattr(point, "total", None) or getattr(point, "count", 0.0)
                    points.append(
                        TimeSeriesPoint(
                            timestamp=ts,
                            value=float(value) if value is not None else 0.0,
                        )
                    )

                series_list.append(
                    TimeSeries(
                        metric_name=canonical_name,
                        labels=labels_from_dims,
                        points=points,
                    )
                )
        return series_list
