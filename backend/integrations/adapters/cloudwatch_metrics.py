"""
AWS CloudWatch Metrics Adapter for MetricProvider.

Implements the MetricProvider ABC using boto3 CloudWatch client.
Uses GetMetricData for range queries and ListMetrics for host discovery.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from integrations.adapters.cloudwatch_logs import _aws_error, _get_boto3_client
from integrations.base import MetricProvider, MetricProviderCapabilities
from integrations.schemas import TimeSeries, TimeSeriesPoint, HostInfo

logger = logging.getLogger(__name__)


# Map our metric names → CloudWatch namespace + metric name + stat.
# VM mode (default) reads the CloudWatch agent (namespace CWAgent), whose
# series carry a ``host`` dimension; CPU falls back to the EC2 basic
# monitoring metric, which every instance has without the agent.
# ``where``: dimensions a series must have (the agent sends one CPU series
# per core plus a ``cpu-total`` one). ``host``: the dimension naming the host.
METRIC_MAP = {
    "node_memory_MemTotal_bytes": {
        "namespace": "CWAgent",
        "metric": "mem_total",
        "stat": "Average",
        "host": "host",
    },
    "node_memory_MemFree_bytes": {
        "namespace": "CWAgent",
        "metric": "mem_free",
        "stat": "Average",
        "host": "host",
    },
    "node_memory_MemAvailable_bytes": {
        "namespace": "CWAgent",
        "metric": "mem_available",
        "stat": "Average",
        "host": "host",
    },
    "node_cpu_seconds_total": {
        "namespace": "CWAgent",
        "metric": "cpu_usage_active",
        "stat": "Average",
        "host": "host",
        "where": {"cpu": "cpu-total"},
        "fallback": {
            "namespace": "AWS/EC2",
            "metric": "CPUUtilization",
            "stat": "Average",
            "host": "InstanceId",
        },
    },
}

# Kubernetes topology mode: CloudWatch Container Insights.
# The CloudWatch agent DaemonSet (EKS add-on or AWS's quickstart) publishes
# pod metrics in the `ContainerInsights` namespace, one series per
# Kubernetes Service with dimensions ClusterName / Namespace / Service.
# By default it publishes percentages only; pod_memory_working_set lives in
# the performance log events, never as a metric. Checked against a real
# agent (1.300074) on 2026-10-31.
#
# ``expr``: CloudWatch metric math over the listed series ``{m}``. ``with``:
# more metrics the expression reads, from the same series (``series``) or
# from the cluster (``cluster``).
#
# Memory: the pipeline takes total and available and divides them, so a
# percentage becomes 100 and 100 - used. Used is measured against the pod's
# memory limit, like Prometheus and Datadog, so a pod nearing its OOMKill
# shows it; with no limit set anywhere in scope, against the node.
def _k8s_memory(expr):
    def mapping(metric):
        return {"namespace": "ContainerInsights", "metric": metric,
                "stat": "Average", "host": "Service", "expr": expr}
    return {**mapping("pod_memory_utilization_over_pod_limit"),
            "fallback": mapping("pod_memory_utilization")}


# CPU: the pipeline multiplies by 100, expecting cores. pod_cpu_utilization
# is a percentage of the node: times the node's cores (node_cpu_limit, in
# millicores) times the running pods.
K8S_METRIC_MAP = {
    "node_memory_MemTotal_bytes": _k8s_memory("{m} * 0 + 100"),
    "node_memory_MemFree_bytes": _k8s_memory("100 - {m}"),
    "node_memory_MemAvailable_bytes": _k8s_memory("100 - {m}"),
    "node_cpu_seconds_total": {
        "namespace": "ContainerInsights",
        "metric": "pod_cpu_utilization",
        "stat": "Average",
        "host": "Service",
        "expr": "{m} / 100 * {node_cpu} / 1000 * {pods}",
        "with": {
            "node_cpu": ("node_cpu_limit", "cluster"),
            "pods": ("service_number_of_running_pods", "series"),
        },
    },
}

# A SerOps label scopes the series only when they carry one of these
# dimensions. AWS metrics rarely do (the agent adds EC2 fields, not
# custom ones), and then every series in the account and region counts.
SCOPE_DIMENSIONS = {
    "organisation_name": ("organisation_name",),
    "project_name": ("project_name",),
    "environment": ("environment", "env"),
}
# Container Insights cannot carry custom dimensions (the pod labels never
# reach it), so a Kubernetes namespace is the only scope: the one named
# after the project, or after the environment, as for kube-state-metrics.
NAMESPACE_SCOPE = ("project_name", "environment")
MAX_SERIES = 100


class CloudWatchMetricProvider(MetricProvider):
    """
    AWS CloudWatch Metrics adapter.

    Maps canonical metric names to CloudWatch namespaces and uses
    GetMetricData for range queries.
    """

    capabilities = MetricProviderCapabilities(
        high_cardinality=False,  # CW has limited cardinality
        histograms=False,
        exemplars=False,
        max_query_window_days=14,  # CW detailed metrics: 15 days
    )
    # The agent's cpu_usage_active, EC2's CPUUtilization and Container
    # Insights' pod_cpu_utilization are all percentages.
    cpu_is_percent = True

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.client = _get_boto3_client("cloudwatch", self._config)
        # Topology mode: 'vm' uses AWS/EC2 + CWAgent, 'kubernetes' uses
        # ContainerInsights pod_* metrics.
        self._topology_mode = self._config.get("topology_mode", "vm")
        # The integration's cluster, if it has one: Container Insights series
        # of other clusters in the account and region are left out (_series).
        self._cluster = str(self._config.get("cluster_name") or "").strip()

    # ------------------------------------------------------------------
    # MetricProvider ABC
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """Validate the key by listing metrics, then reading one."""
        self.last_error = None
        try:
            self.client.list_metrics(Namespace="CWAgent")
        except Exception as exc:
            logger.error("CloudWatch Metrics health check failed: %s", exc)
            self.last_error = _aws_error(exc, "cloudwatch:ListMetrics")
            return False
        try:
            now = datetime.now(timezone.utc)
            self.client.get_metric_data(
                MetricDataQueries=[{"Id": "m1", "MetricStat": {
                    "Metric": {"Namespace": "AWS/EC2", "MetricName": "CPUUtilization"},
                    "Period": 300, "Stat": "Average"}}],
                StartTime=now - timedelta(minutes=10), EndTime=now)
            return True
        except Exception as exc:
            logger.error("CloudWatch Metrics health check failed: %s", exc)
            self.last_error = _aws_error(exc, "cloudwatch:GetMetricData")
            return False

    def query_range(
        self,
        metric: str,
        labels: dict,
        start: datetime,
        end: datetime,
    ) -> List[TimeSeries]:
        """
        Query CloudWatch metrics using GetMetricData.

        Maps canonical metric names (e.g. 'node_memory_MemTotal_bytes')
        to CloudWatch namespace/metric/stat. In `kubernetes` topology
        mode, uses the `ContainerInsights` namespace instead of
        AWS/EC2 + CWAgent.
        """
        active_map = K8S_METRIC_MAP if self._topology_mode == "kubernetes" else METRIC_MAP
        mapping = active_map.get(metric)
        if not mapping:
            logger.warning(
                "Unknown metric for CloudWatch (topology=%s): %s",
                self._topology_mode, metric,
            )
            return []

        # Calculate appropriate period
        delta_seconds = (end - start).total_seconds()
        if delta_seconds <= 3600:
            period = 60
        elif delta_seconds <= 86400:
            period = 300
        else:
            period = 3600

        try:
            series = self._series(mapping, labels)
            if not series and mapping.get("fallback"):
                mapping = mapping["fallback"]
                series = self._series(mapping, labels)
            if not series:
                return []
            response = self.client.get_metric_data(
                MetricDataQueries=self._queries(mapping, series, period),
                StartTime=start,
                EndTime=end,
                ScanBy="TimestampAscending",
            )
        except Exception as exc:
            logger.error("CloudWatch query_range failed: %s", exc)
            return []

        # A host can have several candidate series (one per cluster, see
        # _series): keep the one with the most points in the window.
        best = {}
        for result in response.get("MetricDataResults", []):
            if not result.get("Timestamps"):
                continue
            host = series[int(result["Id"][1:])].get(mapping["host"], "")
            if len(result["Timestamps"]) > len(best.get(host, {}).get("Timestamps", [])):
                best[host] = result

        series_list: List[TimeSeries] = []
        for result in best.values():
            timestamps = result["Timestamps"]
            dims = series[int(result["Id"][1:])]
            host = dims.get(mapping["host"], "")
            extra = {"service_name": host} if mapping["host"] == "Service" else {}
            series_list.append(
                TimeSeries(
                    metric_name=metric,
                    labels={**labels, **dims, **extra, "host": host, "instance": host,
                            "cw_namespace": mapping["namespace"]},
                    points=[
                        TimeSeriesPoint(timestamp=ts, value=float(val))
                        for ts, val in zip(timestamps, result.get("Values", []))
                    ],
                )
            )
        return series_list

    def discover_hosts(
        self,
        org: str,
        project: Optional[str] = None,
        environment: Optional[str] = None,
    ) -> List[HostInfo]:
        """
        Discover EC2 instances reporting metrics to CloudWatch.
        Uses ListMetrics to find unique InstanceId dimensions.
        """
        labels = {"organisation_name": org, "project_name": project, "environment": environment}
        mapping = (K8S_METRIC_MAP if self._topology_mode == "kubernetes" else METRIC_MAP)["node_cpu_seconds_total"]
        try:
            series = self._series(mapping, labels)
            if not series and mapping.get("fallback"):
                mapping = mapping["fallback"]
                series = self._series(mapping, labels)
        except Exception as exc:
            logger.error("CloudWatch discover_hosts failed: %s", exc)
            return []
        series = list({dims[mapping["host"]]: dims for dims in reversed(series)}.values())
        return [
            HostInfo(
                hostname=dims[mapping["host"]],
                environment=environment or dims.get("environment", "unknown"),
                labels={"instance": dims[mapping["host"]], **dims},
                project=project or "",
            )
            for dims in series
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _queries(mapping: dict, series: List[dict], period: int) -> list:
        """GetMetricData queries: one result per series, ``r<i>``.

        With an ``expr`` the series is read as ``m<i>`` and the result is
        the expression; the ``with`` metrics are read alongside, a cluster's
        once for all its series.
        """
        def stat(qid, metric, dims, returned):
            return {"Id": qid, "ReturnData": returned, "MetricStat": {
                "Metric": {"Namespace": mapping["namespace"], "MetricName": metric,
                           "Dimensions": [{"Name": k, "Value": v} for k, v in dims.items()]},
                "Period": period, "Stat": mapping["stat"]}}

        if not mapping.get("expr"):
            return [stat(f"r{i}", mapping["metric"], dims, True) for i, dims in enumerate(series)]
        queries, clusters = [], {}
        for i, dims in enumerate(series):
            ids = {"m": f"m{i}"}
            queries.append(stat(f"m{i}", mapping["metric"], dims, False))
            for name, (metric, scope) in mapping.get("with", {}).items():
                if scope == "cluster":
                    cluster = dims.get("ClusterName", "")
                    if (name, cluster) not in clusters:
                        clusters[(name, cluster)] = f"{name}{len(clusters)}"
                        queries.append(stat(clusters[(name, cluster)], metric,
                                            {"ClusterName": cluster}, False))
                    ids[name] = clusters[(name, cluster)]
                else:
                    ids[name] = f"{name}{i}"
                    queries.append(stat(ids[name], metric, dims, False))
            queries.append({"Id": f"r{i}", "Expression": mapping["expr"].format(**ids),
                            "Period": period, "ReturnData": True})
        return queries

    def _series(self, mapping: dict, labels: dict) -> List[dict]:
        """The series of a metric to read, as dimension dicts, one per host.

        GetMetricData returns a metric only when the dimensions match
        exactly, so the series are listed first. A SerOps label narrows
        them only when the series carry a matching dimension (see
        SCOPE_DIMENSIONS).
        """
        found = []
        pages = self.client.get_paginator("list_metrics").paginate(
            Namespace=mapping["namespace"], MetricName=mapping["metric"])
        for page in pages:
            found += [{d["Name"]: d["Value"] for d in m.get("Dimensions", [])}
                      for m in page.get("Metrics", [])]
            if len(found) >= 1000:
                break
        host = mapping["host"]
        found = [d for d in found if d.get(host)
                 and all(d.get(k) == v for k, v in mapping.get("where", {}).items())]
        for label, names in SCOPE_DIMENSIONS.items():
            value = str((labels or {}).get(label) or "").lower()
            for name in names:
                if value and any(name in d for d in found):
                    found = [d for d in found if str(d.get(name, "")).lower() == value]
        namespaces = {str((labels or {}).get(k) or "").lower() for k in NAMESPACE_SCOPE} - {""}
        if namespaces and any("Namespace" in d for d in found):
            found = [d for d in found if str(d.get("Namespace", "")).lower() in namespaces]
        # A cluster's label in SerOps need not be its EKS name: it scopes
        # only when a series carries it.
        if self._cluster and any(d.get("ClusterName") == self._cluster for d in found):
            found = [d for d in found if d.get("ClusterName") == self._cluster]
        # One series per host and cluster: the agent may also send aggregated
        # copies. Two clusters in the account and region (or one deleted in
        # the last two weeks, which ListMetrics still returns) can both have
        # the Service: each stays a candidate, and query_range keeps the one
        # with data.
        by_host = {}
        for dims in sorted(found, key=len):
            by_host.setdefault((dims[host], dims.get("ClusterName", "")), dims)
        return list(by_host.values())[:MAX_SERIES]

    @staticmethod
    def _labels_to_dimensions(labels: dict) -> list:
        """Convert a labels dict to CloudWatch Dimensions list."""
        return [
            {"Name": k, "Value": v}
            for k, v in labels.items()
            if v  # skip empty values
        ]
