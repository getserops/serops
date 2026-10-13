"""
VictoriaMetrics Adapter for MetricProvider.

Subclasses PrometheusMetricProvider since VictoriaMetrics exposes a
Prometheus-compatible HTTP API (MetricsQL ⊇ PromQL).

Differences from Prometheus:
  - Default port: 8428 (single-node) or 8481 (cluster)
  - Health endpoint: /health instead of /-/healthy
  - No exemplar support
  - Supports additional MetricsQL functions (transparent to our queries)
"""
import logging

from requests.exceptions import RequestException

from integrations.adapters.prometheus import PrometheusMetricProvider
from integrations.base import MetricProviderCapabilities

logger = logging.getLogger(__name__)


class VictoriaMetricsMetricProvider(PrometheusMetricProvider):
    """
    VictoriaMetrics adapter — thin wrapper around PrometheusMetricProvider.

    VictoriaMetrics is API-compatible with Prometheus for query_range
    and series endpoints. Only health check and defaults differ.
    """

    capabilities = MetricProviderCapabilities(
        high_cardinality=True,
        histograms=True,
        exemplars=False,  # VictoriaMetrics doesn't support exemplars
        max_query_window_days=90,  # VM typically retains longer
    )

    def __init__(self, config: dict = None):
        config = config or {}
        # Default to VM single-node port
        config.setdefault("host", "http://victoriametrics:8428")
        super().__init__(config)

    def health_check(self) -> bool:
        """VictoriaMetrics uses /health (returns 200 OK)."""
        try:
            resp = self._session.get(
                f"{self.base_url}/health",
                timeout=self.timeout_seconds,
            )
            return resp.status_code == 200
        except RequestException as exc:
            logger.error("VictoriaMetrics health check failed: %s", exc)
            return False
