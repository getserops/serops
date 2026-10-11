"""
Abstract Base Classes for Log and Metric Providers.

Defines the contracts that all adapters must implement.
Includes AdapterBase with connection lifecycle controls
(reuses patterns from ai_model/circuit_breaker.py and rate_limiter.py).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Tuple, List

from .schemas import LogEntry, TimeSeries, HostInfo, LogStream, LogQuery
from traces.schemas import TraceEntry


# --- Capability Flags ---

@dataclass
class LogProviderCapabilities:
    """What this log provider supports. Used for graceful degradation."""
    full_text: bool = True
    regex: bool = True
    aggregations: bool = True
    tail: bool = False            # live tail / streaming
    max_query_window_days: int = 30
    indexing: bool = False        # whether this provider supports index()


@dataclass
class MetricProviderCapabilities:
    """What this metric provider supports."""
    high_cardinality: bool = True
    histograms: bool = True
    exemplars: bool = False
    max_query_window_days: int = 30


@dataclass
class TraceProviderCapabilities:
    """What this trace provider supports."""
    # Whether the provider can return spans (some APM tools return only
    # aggregated stats). All three current adapters support spans.
    spans: bool = True
    # Max window the provider will honour for a single fetch_traces call.
    max_query_window_hours: int = 24
    # Whether the provider supports pulling a specific trace by ID.
    fetch_by_id: bool = True


# --- Adapter Base (lifecycle controls) ---

class AdapterBase:
    """
    Shared lifecycle controls for all adapters.
    Mirrors patterns from ai_model/circuit_breaker.py and rate_limiter.py.
    """
    max_retries: int = 3
    timeout_seconds: int = 30
    max_query_window_hours: int = 24
    rate_limit_per_minute: int = 60  # per-org

    def __init__(self, config: dict = None):
        """
        Initialize adapter with provider-specific config.
        Config typically comes from ObservabilityIntegration model.
        """
        self._config = config or {}
        self.max_retries = self._config.get("max_retries", self.max_retries)
        self.timeout_seconds = self._config.get("timeout_seconds", self.timeout_seconds)
        self.rate_limit_per_minute = self._config.get("rate_limit_per_minute", self.rate_limit_per_minute)


# --- Log Provider ABC ---

class LogProvider(AdapterBase, ABC):
    """
    Abstract base for all log source integrations.
    
    Implementations:
    - ElasticsearchLogProvider
    - OpenSearchLogProvider
    - LokiLogProvider
    - DatadogLogProvider
    - CloudWatchLogProvider
    """
    capabilities = LogProviderCapabilities()

    def index(self, documents: List[dict], stream: LogStream) -> int:
        """
        Write event documents to the log backend.
        
        Args:
            documents: List of enriched event documents to index
            stream: LogStream descriptor for routing (index name, labels, tags)
            
        Returns:
            Number of documents successfully indexed
            
        Raises:
            NotImplementedError: If adapter hasn't implemented indexing
        """
        raise NotImplementedError(f"{type(self).__name__} does not support indexing")

    @abstractmethod
    def search(
        self,
        index: str,
        query,  # dict (legacy ES DSL) or LogQuery (new agnostic)
        time_range: Optional[Tuple[datetime, datetime]] = None,
        size: int = 10000,
    ) -> List[LogEntry]:
        """
        Search logs and return canonical LogEntry list.
        
        Args:
            index: Index/stream name (or comma-separated for multi-index)
            query: dict (legacy ES DSL) or LogQuery (provider-agnostic)
            time_range: Optional (start, end) datetime tuple
            size: Max results to return
            
        Returns:
            List of canonical LogEntry objects
        """
        ...

    @abstractmethod
    def get_indices(self, project) -> List[str]:
        """
        Get available log indices/streams for a project.
        Replaces SCMService.es_index_name coupling.
        """
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """Check if the log provider is reachable and healthy."""
        ...


# --- Metric Provider ABC ---

class MetricProvider(AdapterBase, ABC):
    """
    Abstract base for all metric source integrations.

    Implementations:
    - PrometheusMetricProvider
    - VictoriaMetricsMetricProvider
    - MimirMetricProvider
    - DatadogMetricProvider
    - CloudWatchMetricProvider
    """
    capabilities = MetricProviderCapabilities()

    @property
    def topology_mode(self) -> str:
        """``'kubernetes'`` or ``'vm'`` (default), from the integration config.

        Public because callers outside the adapter have to branch on it.
        ``fetch_metrics_with_provider`` builds the CPU query itself instead of
        going through ``query_range``, and without this it had no way to ask —
        so it always emitted the node-exporter expression and Kubernetes
        installs silently got no CPU data at all.
        """
        return self._config.get('topology_mode', 'vm')

    @abstractmethod
    def query_range(
        self,
        metric: str,
        labels: dict,
        start: datetime,
        end: datetime,
    ) -> List[TimeSeries]:
        """
        Query metric time series over a range.
        
        Args:
            metric: Metric name (e.g. 'node_memory_MemTotal_bytes')
            labels: Label filters (e.g. {'organisation_name': 'acme', 'host': 'web-1'})
            start: Range start
            end: Range end
            
        Returns:
            List of canonical TimeSeries objects
        """
        ...

    @abstractmethod
    def discover_hosts(
        self,
        org: str,
        project: Optional[str] = None,
        environment: Optional[str] = None,
    ) -> List[HostInfo]:
        """
        Discover available hosts/targets for an organization.
        Replaces raw SQL on prom_catalog.label.
        """
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """Check if the metric provider is reachable and healthy."""
        ...


# --- Trace Provider ABC ---

class TraceProvider(AdapterBase, ABC):
    """
    Abstract base for external trace-store adapters.

    Unlike logs / metrics, SerOps has a native trace-store fed by the
    OTLP receiver (see ``traces.otlp_views``). Trace providers are for
    users who already ship traces to Jaeger, Zipkin, or Datadog APM and
    don't want to change their pipeline — SerOps pulls at analysis
    time to enrich RCA context.

    Implementations:
    - JaegerTraceAdapter
    - ZipkinTraceAdapter
    - DatadogTraceAdapter

    Security:
    * All ``service_name`` and ``trace_id`` values are user-provided
      and MUST be URL-encoded / parameterised — never string-formatted
      into a raw URL. See adapter implementations for encoding.
    * HTTP responses are user-controlled content from the trace store;
      never eval, exec, or template-inject their bodies.
    """

    capabilities = TraceProviderCapabilities()

    @abstractmethod
    def fetch_traces(
        self,
        service_name: str,
        since: datetime,
        until: datetime,
        limit: int = 50,
    ) -> List[TraceEntry]:
        """
        Return traces whose root span started in ``[since, until]`` for
        ``service_name``. Empty list on no matches; adapters translate
        vendor errors into exceptions the caller can catch.
        """
        ...

    @abstractmethod
    def fetch_trace(self, trace_id: str) -> Optional[TraceEntry]:
        """
        Return a single trace by ID (with all spans), or ``None`` if
        the trace is not found or expired.
        """
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """Check if the trace provider is reachable and healthy."""
        ...
