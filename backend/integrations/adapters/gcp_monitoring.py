"""
Google Cloud Monitoring Adapter for MetricProvider.

Uses the official ``google-cloud-monitoring`` SDK (v2+). Same
credential-loading model as ``gcp_logging`` — service-account JSON
from the encrypted ``password`` field, never ADC.

Endpoints used:
  - ``MetricServiceClient.list_time_series(request)``  — range query
  - ``MetricServiceClient.list_metric_descriptors(request)`` — metric
    discovery for health checks
  - ``list_monitored_resources()``                     — host discovery

Metric name mapping follows the same pattern as the Datadog adapter:
canonical Prometheus-style names map to GCP metric types via a small
static dictionary. Unmapped names pass through unchanged so operators
can query raw GCP metric types directly.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from integrations.adapters.gcp_logging import _health_reason, _load_credentials
from integrations.base import MetricProvider, MetricProviderCapabilities
from integrations.schemas import HostInfo, TimeSeries, TimeSeriesPoint

logger = logging.getLogger(__name__)


def _build_metric_client(credentials):
    """Isolated for test monkeypatching."""
    try:
        from google.cloud import monitoring_v3
    except ImportError as exc:
        raise ImportError(
            "GCP Monitoring integration requires google-cloud-monitoring. "
            "Install with: pip install google-cloud-monitoring"
        ) from exc
    return monitoring_v3.MetricServiceClient(credentials=credentials)


def _point_time(end_time):
    """A point's time as a naive UTC datetime.

    The current SDK (proto-plus) hands back ``DatetimeWithNanoseconds``, a
    datetime; the code read ``.seconds``/``.nanos`` of a raw protobuf
    Timestamp, so every series with a point raised and the iteration
    stopped: no GCP metric ever reached an analysis (GKE live test).
    """
    if end_time is None:
        return datetime.min
    if isinstance(end_time, datetime):
        if end_time.tzinfo is not None:
            end_time = end_time.astimezone(timezone.utc).replace(tzinfo=None)
        return datetime(end_time.year, end_time.month, end_time.day, end_time.hour,
                        end_time.minute, end_time.second, end_time.microsecond)
    return datetime.utcfromtimestamp(end_time.seconds + end_time.nanos / 1_000_000_000)


class GcpCloudMonitoringProvider(MetricProvider):
    """
    GCP Cloud Monitoring (formerly Stackdriver) metric provider.

    Config (from ObservabilityIntegration):
        password           Service-account JSON key. Encrypted at rest.
        extra_config:
            project_id     GCP project ID (REQUIRED)
    """

    capabilities = MetricProviderCapabilities(
        high_cardinality=True,
        histograms=True,
        exemplars=False,
        max_query_window_days=30,  # GCP retains custom metrics 24 months, VM metrics 6 weeks
    )

    # Canonical Prometheus-style names → GCP metric type paths.
    # VM mode (default) uses Compute Engine instance metrics.
    METRIC_NAME_MAP = {
        "node_cpu_seconds_total": "compute.googleapis.com/instance/cpu/utilization",
        "node_memory_MemTotal_bytes": "compute.googleapis.com/instance/memory/balloon/ram_size",
        "node_memory_MemAvailable_bytes": "compute.googleapis.com/instance/memory/balloon/ram_used",
        "container_cpu_usage_seconds_total": "kubernetes.io/container/cpu/core_usage_time",
        "container_memory_usage_bytes": "kubernetes.io/container/memory/used_bytes",
    }

    # Kubernetes topology mode (Item #18): map generic node_* names
    # to GKE per-container metrics so a user with a GKE cluster gets
    # workload-level rollups instead of "no data" from Compute Engine
    # instance metrics that don't apply to pods.
    K8S_METRIC_NAME_MAP = {
        "node_cpu_seconds_total": "kubernetes.io/container/cpu/core_usage_time",
        "node_memory_MemTotal_bytes": "kubernetes.io/container/memory/request_bytes",
        "node_memory_MemAvailable_bytes": "kubernetes.io/container/memory/used_bytes",
        "container_cpu_usage_seconds_total": "kubernetes.io/container/cpu/core_usage_time",
        "container_memory_usage_bytes": "kubernetes.io/container/memory/used_bytes",
    }

    # What the pipeline asks for in Kubernetes mode, as GKE system metrics
    # (checked against a real GKE 1.36 cluster, 2026-11-05). One series per
    # workload: grouped by the pod's top-level controller (its Deployment),
    # labelled service_name. The pipeline multiplies CPU by 100 expecting
    # cores, and divides memory total by available; GKE publishes memory as
    # a fraction of the container's limit, so total is 100 and available is
    # 100 - used, as for CloudWatch Container Insights. ``value`` turns the
    # aligned point into what the pipeline expects.
    #   metric: (GKE metric type, aligner, cross-series reducer, value)
    _K8S_SPECS = {
        "node_cpu_seconds_total": ("kubernetes.io/container/cpu/core_usage_time", "ALIGN_RATE", "REDUCE_SUM", None),
        "container_cpu_usage_seconds_total": ("kubernetes.io/container/cpu/core_usage_time", "ALIGN_RATE", "REDUCE_SUM", None),
        "node_memory_MemTotal_bytes": ("kubernetes.io/container/memory/limit_utilization", "ALIGN_MEAN", "REDUCE_MAX",
                                       lambda v: 100.0),
        "node_memory_MemAvailable_bytes": ("kubernetes.io/container/memory/limit_utilization", "ALIGN_MEAN", "REDUCE_MAX",
                                           lambda v: round(100.0 - v * 100.0, 2)),
        "node_memory_MemFree_bytes": ("kubernetes.io/container/memory/limit_utilization", "ALIGN_MEAN", "REDUCE_MAX",
                                      lambda v: round(100.0 - v * 100.0, 2)),
        "container_memory_usage_bytes": ("kubernetes.io/container/memory/used_bytes", "ALIGN_MEAN", "REDUCE_SUM", None),
    }
    _K8S_GROUP_BY = "metadata.system_labels.top_level_controller_name"
    _ALIGNMENT_SECONDS = 60

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        project_id = self._config.get("project_id")
        if not project_id:
            raise ValueError(
                "GCP Cloud Monitoring requires 'project_id' in extra_config"
            )
        self._project_id = project_id
        self._project_name = f"projects/{project_id}"
        # Item #18: topology_mode governs metric selection + resource labels.
        # 'vm'         → compute.googleapis.com/instance/* + resource.instance_id
        # 'kubernetes' → kubernetes.io/container/*         + resource.namespace_name/pod_name/container_name
        self._topology_mode = self._config.get("topology_mode", "vm")
        credentials = _load_credentials(self._config)
        self._client = _build_metric_client(credentials)

    # ------------------------------------------------------------------
    # MetricProvider ABC
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """Cheapest authenticated call — list a single metric descriptor."""
        try:
            iterator = self._client.list_metric_descriptors(
                request={"name": self._project_name, "page_size": 1}
            )
            for _ in iterator:
                break
            self.last_error = None
            return True
        except Exception as exc:
            logger.error("GCP Cloud Monitoring health check failed: %s", exc)
            self.last_error = _health_reason(exc, self._project_id, "Monitoring Viewer")
            return False

    def query_range(
        self,
        metric: str,
        labels: dict,
        start: datetime,
        end: datetime,
    ) -> List[TimeSeries]:
        """Query a metric time series.

        Returns a list of TimeSeries — one per distinct label
        combination (e.g. one per instance for a CPU metric).
        """
        try:
            from google.cloud import monitoring_v3
        except ImportError:
            # Already caught at __init__; guard here in case a caller
            # constructed us via an odd path.
            return []

        if self._topology_mode == "kubernetes" and metric in self._K8S_SPECS:
            return self._query_k8s(metric, labels, start, end)

        # Pick metric name + label routing per topology.
        active_map = (
            self.K8S_METRIC_NAME_MAP if self._topology_mode == "kubernetes"
            else self.METRIC_NAME_MAP
        )
        gcp_metric = active_map.get(metric, metric)

        interval = monitoring_v3.TimeInterval({
            "start_time": {"seconds": int(start.timestamp())},
            "end_time": {"seconds": int(end.timestamp())},
        })

        filter_str = self._build_filter(gcp_metric, labels, self._topology_mode)

        try:
            iterator = self._client.list_time_series(
                request={
                    "name": self._project_name,
                    "filter": filter_str,
                    "interval": interval,
                    "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
                }
            )
        except Exception as exc:
            logger.error("GCP Cloud Monitoring query_range failed: %s", exc)
            return []

        series_list: List[TimeSeries] = []
        try:
            for series in iterator:
                series_list.append(self._to_timeseries(series, metric))
        except Exception as exc:
            logger.warning(
                "GCP Cloud Monitoring iteration ended early: %s", exc
            )
        return series_list

    def _query_k8s(self, metric: str, labels: dict, start: datetime, end: datetime) -> List[TimeSeries]:
        """One series per workload, scoped to the project's namespace.

        The pipeline's labels (organisation_name, project_name, environment)
        exist on no GKE metric: as ``metric.labels.*`` filters they matched
        nothing, so every query came back empty (GKE live test).
        """
        from google.cloud import monitoring_v3
        from integrations.schemas import _gcp_escape
        gcp_type, aligner, reducer, value_of = self._K8S_SPECS[metric]
        clauses = [f'metric.type="{gcp_type}"']
        namespaces = sorted({str((labels or {}).get(k) or "").lower() for k in ("project_name", "environment")} - {""})
        if namespaces:
            clauses.append("resource.labels.namespace_name = one_of("
                           + ", ".join(f'"{_gcp_escape(n)}"' for n in namespaces) + ")")
        service = (labels or {}).get("service_name") or (labels or {}).get("service")
        if service:
            clauses.append(f'metadata.system_labels.top_level_controller_name = "{_gcp_escape(str(service))}"')
        request = {
            "name": self._project_name,
            "filter": " AND ".join(clauses),
            "interval": monitoring_v3.TimeInterval({
                "start_time": {"seconds": int(start.timestamp())},
                "end_time": {"seconds": int(end.timestamp())},
            }),
            "aggregation": monitoring_v3.Aggregation({
                "alignment_period": {"seconds": self._ALIGNMENT_SECONDS},
                "per_series_aligner": getattr(monitoring_v3.Aggregation.Aligner, aligner),
                "cross_series_reducer": getattr(monitoring_v3.Aggregation.Reducer, reducer),
                "group_by_fields": [self._K8S_GROUP_BY],
            }),
            "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
        }
        try:
            iterator = self._client.list_time_series(request=request)
            series_list = []
            for i, series in enumerate(iterator):
                ts = self._to_timeseries(series, metric)
                system = dict(getattr(getattr(series, "metadata", None), "system_labels", {}) or {})
                workload = system.get("top_level_controller_name", "")
                ts.labels.update({"service_name": workload, "series_id": str(i)})
                if value_of is not None:
                    for point in ts.points:
                        point.value = value_of(point.value)
                series_list.append(ts)
            return series_list
        except Exception as exc:
            logger.warning("GCP Cloud Monitoring %s (%s) failed: %s", metric, gcp_type, exc)
            return []

    def discover_hosts(
        self,
        org: str,
        project: Optional[str] = None,
        environment: Optional[str] = None,
    ) -> List[HostInfo]:
        """Enumerate distinct instances seen in a CPU metric.

        GCP's ListMonitoredResourceDescriptors gives descriptor types,
        not concrete instances. To get actual hosts we sample the
        last-hour CPU metric and gather distinct ``instance_id`` labels
        from the returned time series. Cheap, and matches Datadog's
        approach of "hosts that emitted something recently".
        """
        try:
            from google.cloud import monitoring_v3
        except ImportError:
            return []

        from datetime import timedelta
        end = datetime.utcnow()
        start = end - timedelta(hours=1)
        interval = monitoring_v3.TimeInterval({
            "start_time": {"seconds": int(start.timestamp())},
            "end_time": {"seconds": int(end.timestamp())},
        })
        # Choose the discovery metric per topology. VM mode probes
        # Compute Engine instance CPU (concrete hosts); K8s mode probes
        # GKE container CPU (workloads = pods).
        if self._topology_mode == 'kubernetes':
            from integrations.schemas import _gcp_escape
            probe_filter = 'metric.type="kubernetes.io/container/cpu/core_usage_time"'
            # The project's namespace, not every pod of every cluster
            # (kube-system included).
            namespaces = sorted({str(v or "").lower() for v in (project, environment)} - {""})
            if namespaces:
                probe_filter += (" AND resource.labels.namespace_name = one_of("
                                 + ", ".join(f'"{_gcp_escape(n)}"' for n in namespaces) + ")")
        else:
            probe_filter = 'metric.type="compute.googleapis.com/instance/cpu/utilization"'

        # HEADERS view returns only labels — no data points — so it's
        # much cheaper than pulling the whole series.
        try:
            iterator = self._client.list_time_series(
                request={
                    "name": self._project_name,
                    "filter": probe_filter,
                    "interval": interval,
                    "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.HEADERS,
                }
            )
        except Exception as exc:
            logger.error("GCP discover_hosts failed: %s", exc)
            return []

        seen: dict = {}
        try:
            for series in iterator:
                res_labels = dict(getattr(series.resource, "labels", {}) or {})
                if self._topology_mode == 'kubernetes':
                    # Key by (cluster, namespace, pod) — the K8s
                    # workload identity — and expose pod as hostname
                    # so callers that "discover hosts" still get
                    # something meaningful in the multi-cluster case.
                    cluster = res_labels.get("cluster_name", "")
                    namespace = res_labels.get("namespace_name", "")
                    pod = res_labels.get("pod_name", "")
                    key = f"{cluster}/{namespace}/{pod}"
                    if not pod or key in seen:
                        continue
                    seen[key] = HostInfo(
                        hostname=pod,
                        environment=environment or namespace or res_labels.get("location", ""),
                        project=project or self._project_id,
                        labels={f"resource.{k}": v for k, v in res_labels.items()},
                    )
                else:
                    instance_id = res_labels.get("instance_id", "")
                    if not instance_id or instance_id in seen:
                        continue
                    seen[instance_id] = HostInfo(
                        hostname=res_labels.get("instance_name", instance_id),
                        environment=environment or res_labels.get("zone", ""),
                        project=project or self._project_id,
                        labels={f"resource.{k}": v for k, v in res_labels.items()},
                    )
        except Exception as exc:
            logger.warning("GCP discover_hosts iteration ended early: %s", exc)

        return list(seen.values())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    # In kubernetes mode, service / namespace / pod / container /
    # cluster live on the RESOURCE (not the metric), so their access
    # path is resource.labels.<name>. Non-K8s labels still route to
    # metric.labels.<name> as before.
    _K8S_RESOURCE_LABELS = frozenset({
        'cluster_name', 'location', 'namespace_name', 'pod_name',
        'container_name', 'project_id',
    })

    # Canonical SerOps label → GCP resource label (for k8s mode).
    _K8S_LABEL_ALIASES = {
        'service_name': 'container_name',   # our canonical service tag
        'service': 'container_name',
        'namespace': 'namespace_name',
        'pod': 'pod_name',
        'container': 'container_name',
        'cluster': 'cluster_name',
    }

    @classmethod
    def _build_filter(cls, metric_type: str, labels: dict, topology_mode: str = 'vm') -> str:
        """Build a Cloud Monitoring filter string.

        In ``kubernetes`` mode, canonical SerOps labels (service_name,
        namespace, pod, container, cluster) are routed to
        ``resource.labels.*`` — that's where GKE puts them. Other
        labels still go to ``metric.labels.*``.

        Every user value goes through ``_gcp_escape`` so a
        maliciously-crafted label can't break out of the string.
        """
        from integrations.schemas import _gcp_escape
        clauses = [f'metric.type="{_gcp_escape(metric_type)}"']
        for raw_key, v in (labels or {}).items():
            if v is None or v == "":
                continue
            k = str(raw_key)
            v_str = str(v)
            escaped_v = _gcp_escape(v_str)
            if topology_mode == 'kubernetes':
                # Alias then check if it lands on the resource.
                mapped = cls._K8S_LABEL_ALIASES.get(k, k)
                if mapped in cls._K8S_RESOURCE_LABELS:
                    clauses.append(
                        f'resource.labels.{_gcp_escape(mapped)}="{escaped_v}"'
                    )
                    continue
            clauses.append(
                f'metric.labels.{_gcp_escape(k)}="{escaped_v}"'
            )
        return " AND ".join(clauses)

    @staticmethod
    def _to_timeseries(gcp_series, canonical_name: str) -> TimeSeries:
        """Normalise a GCP TimeSeries to the canonical TimeSeries."""
        # Labels: pull metric.labels + resource.labels
        metric_labels = dict(getattr(gcp_series.metric, "labels", {}) or {})
        resource_labels = dict(getattr(gcp_series.resource, "labels", {}) or {})
        combined_labels = {
            **metric_labels,
            **{f"resource.{k}": v for k, v in resource_labels.items()},
        }

        points: list = []
        for point in getattr(gcp_series, "points", []) or []:
            interval = getattr(point, "interval", None)
            end_time = getattr(interval, "end_time", None) if interval else None
            # GCP's Point.value is a TypedValue — one of int64/double/
            # bool/string/distribution. We coerce numeric ones and
            # skip the rest so a stray boolean doesn't blow up.
            value_obj = getattr(point, "value", None)
            value = 0.0
            if value_obj is not None:
                for attr in ("double_value", "int64_value"):
                    v = getattr(value_obj, attr, None)
                    if v is not None and v != 0:
                        value = float(v)
                        break
                else:
                    # Both zero (or missing) is legitimate — keep 0.0.
                    if getattr(value_obj, "double_value", None) == 0.0:
                        value = 0.0

            ts = _point_time(end_time)

            points.append(TimeSeriesPoint(timestamp=ts, value=value))

        return TimeSeries(
            metric_name=canonical_name,
            labels=combined_labels,
            points=points,
        )
