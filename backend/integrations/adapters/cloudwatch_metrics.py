"""
AWS CloudWatch Metrics Adapter for MetricProvider.

Implements the MetricProvider ABC using boto3 CloudWatch client.
Uses GetMetricData for range queries and ListMetrics for host discovery.
"""
import logging
from datetime import datetime
from typing import List, Optional

from integrations.base import MetricProvider, MetricProviderCapabilities
from integrations.schemas import TimeSeries, TimeSeriesPoint, HostInfo

logger = logging.getLogger(__name__)


def _get_boto3_client(service: str, config: dict):
    """Create a boto3 client with optional explicit credentials."""
    try:
        import boto3
    except ImportError:
        raise ImportError(
            "boto3 is required for CloudWatch integration. "
            "Install it with: pip install boto3"
        )
    kwargs = {
        "service_name": service,
        "region_name": config.get("aws_region", "us-east-1"),
    }
    access_key = config.get("aws_access_key_id")
    secret_key = config.get("aws_secret_access_key")
    if access_key and secret_key:
        kwargs["aws_access_key_id"] = access_key
        kwargs["aws_secret_access_key"] = secret_key
    session_token = config.get("aws_session_token")
    if session_token:
        kwargs["aws_session_token"] = session_token
    return boto3.client(**kwargs)


# Map our metric names → CloudWatch namespace + metric name + stat.
# VM mode (default) uses AWS/EC2 + CWAgent metrics — bare-metal / EC2 hosts.
METRIC_MAP = {
    "node_memory_MemTotal_bytes": {
        "namespace": "CWAgent",
        "metric": "mem_total",
        "stat": "Average",
    },
    "node_memory_MemFree_bytes": {
        "namespace": "CWAgent",
        "metric": "mem_free",
        "stat": "Average",
    },
    "node_memory_MemAvailable_bytes": {
        "namespace": "CWAgent",
        "metric": "mem_available",
        "stat": "Average",
    },
    "node_cpu_seconds_total": {
        "namespace": "AWS/EC2",
        "metric": "CPUUtilization",
        "stat": "Average",
    },
}

# Kubernetes topology mode: CloudWatch Container Insights.
# Requires ContainerInsights enabled on the EKS cluster (`aws eks
# update-cluster-config` OR the CloudWatch agent DaemonSet). Metrics
# live in the `ContainerInsights` namespace with dimensions like
# ClusterName / Namespace / PodName / Service.
K8S_METRIC_MAP = {
    "node_memory_MemTotal_bytes": {
        "namespace": "ContainerInsights",
        "metric": "pod_memory_working_set",
        "stat": "Average",
    },
    "node_memory_MemFree_bytes": {
        # ContainerInsights doesn't expose free memory directly.
        # `pod_memory_utilization` (%) is the closest signal.
        "namespace": "ContainerInsights",
        "metric": "pod_memory_utilization",
        "stat": "Average",
    },
    "node_memory_MemAvailable_bytes": {
        "namespace": "ContainerInsights",
        "metric": "pod_memory_utilization",
        "stat": "Average",
    },
    "node_cpu_seconds_total": {
        "namespace": "ContainerInsights",
        "metric": "pod_cpu_utilization",
        "stat": "Average",
    },
}


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

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.client = _get_boto3_client("cloudwatch", self._config)
        # Topology mode: 'vm' uses AWS/EC2 + CWAgent, 'kubernetes' uses
        # ContainerInsights pod_* metrics.
        self._topology_mode = self._config.get("topology_mode", "vm")

    # ------------------------------------------------------------------
    # MetricProvider ABC
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """Validate credentials by listing metrics."""
        try:
            self.client.list_metrics(
                Namespace="AWS/EC2",
                MaxRecords=1,
            )
            return True
        except Exception as exc:
            logger.error("CloudWatch Metrics health check failed: %s", exc)
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

        # Build dimensions from labels
        dimensions = self._labels_to_dimensions(labels)

        # Calculate appropriate period
        delta_seconds = (end - start).total_seconds()
        if delta_seconds <= 3600:
            period = 60
        elif delta_seconds <= 86400:
            period = 300
        else:
            period = 3600

        try:
            response = self.client.get_metric_data(
                MetricDataQueries=[
                    {
                        "Id": "m1",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": mapping["namespace"],
                                "MetricName": mapping["metric"],
                                "Dimensions": dimensions,
                            },
                            "Period": period,
                            "Stat": mapping["stat"],
                        },
                        "ReturnData": True,
                    }
                ],
                StartTime=start,
                EndTime=end,
                ScanBy="TimestampDescending",
            )

            results = response.get("MetricDataResults", [])
            series_list: List[TimeSeries] = []

            for result in results:
                timestamps = result.get("Timestamps", [])
                values = result.get("Values", [])
                if not timestamps:
                    continue

                points = [
                    TimeSeriesPoint(
                        timestamp=ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts)),
                        value=float(val),
                    )
                    for ts, val in zip(timestamps, values)
                ]

                series_list.append(
                    TimeSeries(
                        metric_name=metric,
                        labels={**labels, "cw_namespace": mapping["namespace"]},
                        points=points,
                    )
                )

            return series_list

        except Exception as exc:
            logger.error("CloudWatch query_range failed: %s", exc)
            return []

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
        try:
            kwargs = {
                "Namespace": "AWS/EC2",
                "MetricName": "CPUUtilization",
                "MaxRecords": 500,
            }
            # Filter by specific dimensions if provided
            dim_filters = []
            if org:
                dim_filters.append({"Name": "organisation_name", "Value": org})
            if project:
                dim_filters.append({"Name": "project_name", "Value": project})
            if dim_filters:
                kwargs["Dimensions"] = dim_filters

            response = self.client.list_metrics(**kwargs)
            metrics = response.get("Metrics", [])

            seen = set()
            hosts: List[HostInfo] = []
            for m in metrics:
                dims = {d["Name"]: d["Value"] for d in m.get("Dimensions", [])}
                instance_id = dims.get("InstanceId", "")
                if not instance_id or instance_id in seen:
                    continue
                seen.add(instance_id)
                hosts.append(
                    HostInfo(
                        hostname=instance_id,
                        environment=environment or dims.get("environment", "unknown"),
                        labels={"instance": instance_id, **dims},
                        project=project or "",
                    )
                )

            return hosts

        except Exception as exc:
            logger.error("CloudWatch discover_hosts failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _labels_to_dimensions(labels: dict) -> list:
        """Convert a labels dict to CloudWatch Dimensions list."""
        return [
            {"Name": k, "Value": v}
            for k, v in labels.items()
            if v  # skip empty values
        ]
