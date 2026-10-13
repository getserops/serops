"""Provider-agnostic trace schemas.

Similar in spirit to ``integrations.schemas.LogEntry`` /
``integrations.schemas.LogQuery``: adapters convert provider-specific
trace shapes (Jaeger JSON, Zipkin JSON, Datadog APM API) into these
canonical dataclasses. The AI prompt + correlation engine consume
only these types.

For OTLP ingestion (the pull direction), we skip the schema layer and
persist directly to ``traces.models.Trace`` / ``traces.models.Span``
because the OTLP shape is already close to our own storage model.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class SpanEvent:
    """A discrete event within a span (exception, log, etc.)."""
    time: datetime
    name: str
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SpanEntry:
    """A canonical span. Adapters return lists of these."""
    trace_id: str                       # 32-hex OTEL trace_id
    span_id: str                        # 16-hex OTEL span_id
    parent_span_id: str = ''
    service_name: str = ''
    operation_name: str = ''
    kind: str = 'INTERNAL'              # INTERNAL | SERVER | CLIENT | PRODUCER | CONSUMER
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_ms: int = 0
    status_code: str = 'UNSET'          # UNSET | OK | ERROR
    status_message: str = ''
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[SpanEvent] = field(default_factory=list)


@dataclass
class TraceEntry:
    """A canonical trace — includes the ordered span list."""
    trace_id: str
    root_service_name: str = ''
    root_operation: str = ''
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_ms: int = 0
    span_count: int = 0
    error_span_count: int = 0
    status_code: str = 'UNSET'
    spans: List[SpanEntry] = field(default_factory=list)
