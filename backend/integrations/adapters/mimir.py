"""
Grafana Mimir Adapter for MetricProvider.

Subclasses PrometheusMetricProvider since Mimir exposes a
100% Prometheus-compatible HTTP API at /prometheus/* prefix.

Differences from Prometheus:
  - API path prefix: /prometheus/api/v1/* (instead of /api/v1/*)
  - Multi-tenant via X-Scope-OrgID header
  - Health endpoint: /ready instead of /-/healthy
"""
import logging
from contextlib import contextmanager

from requests.exceptions import RequestException

from integrations.adapters.prometheus import PrometheusMetricProvider
from integrations.base import MetricProviderCapabilities

logger = logging.getLogger(__name__)


class MimirMetricProvider(PrometheusMetricProvider):
    """
    Grafana Mimir adapter — thin wrapper around PrometheusMetricProvider.

    Mimir claims 100% Prometheus HTTP API compatibility.
    Only path prefix, tenant header, and health endpoint differ.
    """

    capabilities = MetricProviderCapabilities(
        high_cardinality=True,
        histograms=True,
        exemplars=True,
        max_query_window_days=365,  # Mimir is long-term storage
    )

    def __init__(self, config: dict = None):
        config = config or {}
        config.setdefault("host", "http://mimir:9009")
        super().__init__(config)

        # Mimir serves Prometheus API under /prometheus prefix
        self.base_url = self.base_url.rstrip("/")
        path_prefix = config.get("path_prefix", "/prometheus")
        self._query_base = f"{self.base_url}{path_prefix}"

        # Multi-tenant header
        tenant_id = config.get("tenant_id")
        if tenant_id:
            self._session.headers["X-Scope-OrgID"] = tenant_id

    def health_check(self) -> bool:
        """Mimir uses /ready endpoint."""
        try:
            resp = self._session.get(
                f"{self.base_url}/ready",
                timeout=self.timeout_seconds,
            )
            return resp.status_code == 200
        except RequestException as exc:
            logger.error("Mimir health check failed: %s", exc)
            return False

    def query_range(self, metric, labels, start, end):
        """Override to use /prometheus/api/v1/query_range path."""
        with self._prom_base():
            return super().query_range(metric, labels, start, end)

    def query_range_expr(self, expr, start, end):
        """Override so arbitrary PromQL expressions also go through the
        /prometheus path prefix. Without this override the inherited
        Prometheus method hits ``${base_url}/api/v1/query_range``
        directly → 404 on Mimir (E14-1, filed 2026-09-12). Any caller
        using rate()/avg()/histogram_quantile() — including the
        correlation engine — would silently return zero series.
        """
        with self._prom_base():
            return super().query_range_expr(expr, start, end)

    def discover_hosts(self, org, project=None, environment=None):
        """Override to use /prometheus/api/v1/series path."""
        with self._prom_base():
            return super().discover_hosts(org, project, environment)

    @contextmanager
    def _prom_base(self):
        """Swap ``self.base_url`` to the /prometheus-prefixed URL for
        the duration of the block, restore after.

        Extracted from the three query overrides so adding a fourth
        Prometheus-API method (query_instant, labels, series, etc.)
        just needs `with self._prom_base():` rather than repeated
        try/finally boilerplate.
        """
        original = self.base_url
        self.base_url = self._query_base
        try:
            yield
        finally:
            self.base_url = original
