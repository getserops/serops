"""
Prometheus Adapter for MetricProvider.

Implements the MetricProvider ABC using the Prometheus HTTP API.
Implements the MetricProvider ABC using standard PromQL over HTTP.
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
# Translate canonical SerOps metric names into container-metric PromQL
# expressions aggregated by `service_name`. The user's Prometheus must be
# scraping cAdvisor / kubelet metrics (standard with kube-prometheus-stack)
# and its `relabel_configs` must promote the pod's service label into a
# top-level `service_name` label — see docs/how-to/configure-data-collection.md
# for the recommended Kubernetes SD config.
#
# Only used when the integration has `topology_mode='kubernetes'`. In `vm`
# mode (the default) SerOps queries node-level metrics as before, unchanged.
# Restrict container metrics to the root kubepods cgroup tree.
#
# Nested container runtimes — minikube, kind, Docker Desktop, some CI runners
# — run the kubelet inside a container, so cAdvisor sees each workload cgroup
# TWICE: once at `/kubepods/...` and once under the outer container at
# `/docker/<id>/kubepods/...`. Both series are live and carry identical
# labels apart from `id`, so `sum by (service_name)` counted every container
# twice. Measured on minikube: 6 series for 3 pods, 2.45 MiB reported against
# 1.22 MiB actual — exactly 2x.
#
# That is not cosmetic. Memory anomalies trip at 75% usage, so a doubled
# reading can manufacture a sustained-high-memory anomaly on a perfectly
# healthy service — and these nested runtimes are precisely where people
# evaluate SerOps before trusting it.
#
# Safe on real clusters: cgroupfs drivers produce `/kubepods/...` and systemd
# drivers `/kubepods.slice/...`, and Prometheus regexes are fully anchored, so
# `/kubepods.*` matches both while excluding the `/docker/...` duplicate.
ROOT_CGROUP_MATCHER = 'id=~"/kubepods.*"'

# Container lifecycle signals from kube-state-metrics.
#
# An OOMKill is a KUBELET event, not an application log line: the container's
# logs simply stop mid-stream. Without these, a memory exhaustion looks to the
# AI like a dependency that suddenly stopped responding, and it correctly
# describes the resulting cascade while never naming the cause. Measured on
# the chaos suite: a01 and b02 both failed exactly that way.
#
# kube-state-metrics is part of kube-prometheus-stack, so this is usually
# already scraped. When it is absent these queries return nothing and the
# summary simply omits the section.
#
# `last_terminated_reason` is NOT time-bounded: it reports the most recent
# termination for as long as the pod lives. Reported unfiltered it attributes
# an OOMKill from an hour ago to whatever incident is being analysed now —
# measured on the chaos suite, an unrelated exception scenario came back with
# two fabricated MEMORY_HIGH issues inherited from the previous run. So the
# reason is only reported for containers whose restart counter actually moved
# during the batch window, which `increase()` gives us.
K8S_LIFECYCLE_EXPR_TEMPLATES = {
    'container_last_terminated_reason': (
        'max by (container, reason) '
        '(kube_pod_container_status_last_terminated_reason{{{labels}}} > 0)'
    ),
    'container_restarts_in_window': (
        'max by (container) '
        '(increase(kube_pod_container_status_restarts_total{{{labels}}}[{window}]) > 0)'
    ),
}

# Peak utilisation of the WORST SINGLE POD in a service.
#
# Everything in K8S_METRIC_EXPR_TEMPLATES aggregates `sum by (service_name)`,
# which collapses every pod, replica and node of a service into one series.
# That is the right view of capacity and the wrong view of risk: three replicas
# at 95%, 20% and 20% sum to about 45%, comfortably under the 75% anomaly
# threshold, so nothing fires and the prompt reports a healthy service until the
# kubelet OOMKills the hot one.
#
# This is the same fault that made project-wide aggregation hide a saturating
# service, one level further down — service-wide aggregation hiding a saturating
# pod. Measured on the validation cluster, the unlabelled container bucket read
# 40.2% aggregate against 52.8% for its worst member.
#
# `max by (service_name)` costs one extra series per service rather than one per
# pod, so the token and query cost is flat in replica count.
K8S_PEAK_POD_EXPR_TEMPLATES = {
    'peak_pod_memory_percent': (
        # Ratio per pod, then the worst. The `> 0` keeps unlimited containers
        # out of the denominator instead of dividing by zero.
        'max by (service_name) ('
        'container_memory_working_set_bytes{{{labels}}} '
        '/ (container_spec_memory_limit_bytes{{{labels}}} > 0)'
        ') * 100'
    ),
    'peak_pod_cpu_cores': (
        # Cores/sec for the busiest pod. Not a percentage: a pod with no CPU
        # limit has no ceiling to be a percentage of, and inventing one is what
        # produced negative free memory before.
        'max by (service_name) '
        '(rate(container_cpu_usage_seconds_total{{{labels}}}[5m]))'
    ),
}

K8S_METRIC_EXPR_TEMPLATES = {
    'node_cpu_seconds_total': (
        'sum by (service_name) '
        '(rate(container_cpu_usage_seconds_total{{{labels}}}[5m]))'
    ),
    # A container with no memory limit reports
    # container_spec_memory_limit_bytes == 0, which is the common case —
    # most workloads set requests but not limits. Taken literally that
    # said a service had 0 bytes of memory and NEGATIVE free memory
    # (0 - working_set). Observed on a real cluster: etcd came back at
    # -75 MB free, and that number was what reached the AI and the
    # anomaly detector. Both expressions below now refuse to invent a
    # ceiling that does not exist.
    'node_memory_MemTotal_bytes': (
        # `> 0` drops unlimited containers instead of counting them as
        # zero. When every container of a service is unlimited the series
        # is absent, which is honest — an absent limit is not a limit of 0.
        'sum by (service_name) '
        '(container_spec_memory_limit_bytes{{{labels}}} > 0)'
    ),
    'node_memory_MemFree_bytes': (
        # "Free" ~= limit - working_set (best proxy in container land).
        # clamp_min sits INSIDE the sum so it applies per container: an
        # unlimited container contributes 0 rather than a negative number
        # that would silently cancel out a sibling's real headroom.
        'sum by (service_name) '
        '(clamp_min(container_spec_memory_limit_bytes{{{labels}}} '
        '- container_memory_working_set_bytes{{{labels}}}, 0))'
    ),
    'node_memory_MemAvailable_bytes': (
        # cAdvisor doesn't distinguish free/available — same expression.
        'sum by (service_name) '
        '(clamp_min(container_spec_memory_limit_bytes{{{labels}}} '
        '- container_memory_working_set_bytes{{{labels}}}, 0))'
    ),
}


class PrometheusMetricProvider(MetricProvider):
    """
    Prometheus adapter using the HTTP API.

    Endpoints used:
      - GET /api/v1/query_range   – range queries
      - GET /api/v1/series        – host/target discovery
      - GET /-/healthy             – health check
    """

    capabilities = MetricProviderCapabilities(
        high_cardinality=True,
        histograms=True,
        exemplars=True,
        max_query_window_days=30,
    )

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.base_url = self._config.get(
            "host", "http://prometheus:9090"
        ).rstrip("/")
        self._session = requests.Session()
        # Optional basic auth
        username = self._config.get("username")
        password = self._config.get("password")
        if username and password:
            self._session.auth = (username, password)
        # Optional bearer token (for Grafana Cloud, Thanos, etc.)
        bearer = self._config.get("bearer_token")
        if bearer:
            self._session.headers["Authorization"] = f"Bearer {bearer}"
        # Topology mode: 'vm' (node metrics) | 'kubernetes' (container metrics
        # aggregated by service_name). Passed via ObservabilityIntegration.get_config().
        self._topology_mode = self._config.get("topology_mode", "vm")

    # ------------------------------------------------------------------
    # MetricProvider ABC
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """Hit /-/healthy (returns 200 OK if Prometheus is up)."""
        try:
            resp = self._session.get(
                f"{self.base_url}/-/healthy",
                timeout=self.timeout_seconds,
            )
            return resp.status_code == 200
        except RequestException as exc:
            logger.error("Prometheus health check failed: %s", exc)
            return False

    def query_range(
        self,
        metric: str,
        labels: dict,
        start: datetime,
        end: datetime,
    ) -> List[TimeSeries]:
        """
        Execute a PromQL range query.

        VM mode (default) builds a simple selector:
            node_memory_MemTotal_bytes{organisation_name="acme",environment="prod"}

        Kubernetes mode translates to a container-metric expression
        aggregated by `service_name`:
            sum by (service_name) (rate(container_cpu_usage_seconds_total{...}[5m]))
        Falls back to VM behavior if the canonical metric has no K8s template.
        """
        if self._topology_mode == "kubernetes":
            template = K8S_METRIC_EXPR_TEMPLATES.get(metric)
            if template:
                label_str = ",".join(f'{k}="{v}"' for k, v in labels.items() if v)
                # Built as a list so an empty label_str cannot produce a
                # leading comma ("{,id=~...}" is a parse error).
                selectors = [s for s in (label_str, ROOT_CGROUP_MATCHER) if s]
                expr = template.format(labels=",".join(selectors))
                return self.query_range_expr(expr, start, end)
            logger.debug(
                "Prometheus K8s mode: no template for metric %s — falling back "
                "to VM-style query. Add an entry to K8S_METRIC_EXPR_TEMPLATES "
                "if this metric should be K8s-aware.", metric,
            )
        selector = self._build_selector(metric, labels)
        params = {
            "query": selector,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "step": self._auto_step(start, end),
        }
        try:
            resp = self._session.get(
                f"{self.base_url}/api/v1/query_range",
                params=params,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "success":
                logger.warning(
                    "Prometheus query_range non-success: %s",
                    data.get("error", "unknown"),
                )
                return []

            return self._parse_matrix(data["data"]["result"], metric)

        except RequestException as exc:
            logger.error("Prometheus query_range failed: %s", exc)
            return []

    def query_range_expr(
        self,
        expr: str,
        start: datetime,
        end: datetime,
    ) -> List[TimeSeries]:
        """
        Execute an arbitrary PromQL expression as a range query.

        Unlike query_range(), this accepts a full PromQL expression
        (e.g. rate(), avg(), arithmetic) instead of a metric + labels.
        """
        params = {
            "query": expr,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "step": self._auto_step(start, end),
        }
        try:
            resp = self._session.get(
                f"{self.base_url}/api/v1/query_range",
                params=params,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "success":
                logger.warning(
                    "Prometheus query_range_expr non-success: %s",
                    data.get("error", "unknown"),
                )
                return []

            return self._parse_matrix(data["data"]["result"], expr)

        except RequestException as exc:
            logger.error("Prometheus query_range_expr failed: %s", exc)
            return []

    def discover_hosts(
        self,
        org: str,
        project: Optional[str] = None,
        environment: Optional[str] = None,
    ) -> List[HostInfo]:
        """
        Use /api/v1/series to find distinct instance labels
        for the given org, optionally filtered by project/env.
        """
        match_labels = {"organisation_name": org, "serops_type": "server"}
        if project:
            match_labels["project_name"] = project
        if environment:
            match_labels["environment"] = environment

        selector = self._build_selector("node_uname_info", match_labels)
        params = {"match[]": selector}
        try:
            resp = self._session.get(
                f"{self.base_url}/api/v1/series",
                params=params,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "success":
                return []

            seen = set()
            hosts: List[HostInfo] = []
            for series in data.get("data", []):
                instance = series.get("instance", "")
                if instance in seen:
                    continue
                seen.add(instance)
                hosts.append(
                    HostInfo(
                        hostname=series.get("hostname", instance),
                        environment=series.get("environment", "unknown"),
                        labels={"instance": instance},
                        project=project or "",
                    )
                )
            return hosts

        except RequestException as exc:
            logger.error("Prometheus discover_hosts failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_selector(metric: str, labels: dict) -> str:
        """
        Build a PromQL selector string.

        Example:
            _build_selector("up", {"job": "api", "env": "prod"})
            → 'up{job="api",env="prod"}'
        """
        if not labels:
            return metric
        parts = ",".join(
            f'{k}="{v}"' for k, v in labels.items() if v
        )
        return f"{metric}{{{parts}}}" if parts else metric

    @staticmethod
    def _auto_step(start: datetime, end: datetime) -> str:
        """
        Choose a reasonable step size based on the time range.
        Keeps the maximum result count around ~500 points.
        """
        delta = (end - start).total_seconds()
        if delta <= 3600:       # ≤ 1 h
            return "15s"
        if delta <= 21600:      # ≤ 6 h
            return "60s"
        if delta <= 86400:      # ≤ 1 d
            return "5m"
        return "15m"

    @staticmethod
    def _parse_matrix(
        result: list, metric_name: str
    ) -> List[TimeSeries]:
        """
        Parse Prometheus matrix (range vector) response into
        canonical TimeSeries objects.

        Each element in `result` has:
            {"metric": {...labels}, "values": [[ts, "val"], ...]}
        """
        series_list: List[TimeSeries] = []
        for item in result:
            labels = {
                k: v
                for k, v in item.get("metric", {}).items()
                if k != "__name__"
            }
            points = [
                TimeSeriesPoint(
                    timestamp=datetime.fromtimestamp(float(pair[0])),
                    value=float(pair[1]),
                )
                for pair in item.get("values", [])
            ]
            series_list.append(
                TimeSeries(
                    metric_name=metric_name,
                    labels=labels,
                    points=points,
                )
            )
        return series_list
