"""
AI Input Contract — Provider-Agnostic Schema for AI Prompts.

Replaces raw ES _source / prom_catalog structures in AI analysis.
Adapter changes never touch AI prompts — they only produce these contracts.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List

from .schemas import LogEntry, TimeSeries


@dataclass
class Anomaly:
    """A detected metric anomaly with correlation window."""
    metric_type: str            # 'memory', 'cpu'
    severity: str               # 'warning', 'critical'
    peak_value: float
    threshold: float
    start_time: datetime = None
    end_time: datetime = None
    duration_seconds: float = 0
    correlation_window_start: datetime = None
    correlation_window_end: datetime = None


@dataclass
class MetricSummary:
    """Compact summary of a single metric type for AI consumption."""
    metric_type: str            # 'memory', 'cpu'
    current_value: float = 0
    avg_value: float = 0
    max_value: float = 0
    min_value: float = 0
    trend: str = "stable"       # 'increasing', 'decreasing', 'stable'
    unit: str = ""              # '%', 'bytes', 'cores'
    sample_count: int = 0


@dataclass
class AILogContext:
    """
    Normalized log context for AI analysis.
    Built from LogProvider output — never from raw ES hits.
    """
    logs: List[LogEntry] = field(default_factory=list)
    total_count: int = 0
    dedup_reduction: float = 0.0   # percentage (0-100)
    time_range_start: datetime = None
    time_range_end: datetime = None
    service_names: List[str] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        """Convert to text suitable for AI prompt injection."""
        lines = []
        for log in self.logs:
            ts = log.timestamp.isoformat() if log.timestamp != datetime.min else "unknown"
            lines.append(f"[{ts}] [{log.level}] [{log.service or 'unknown'}] {log.message}")
        
        header = f"--- {self.total_count} logs"
        if self.dedup_reduction > 0:
            header += f" ({self.dedup_reduction:.0f}% deduplication)"
        header += " ---"
        
        return header + "\n" + "\n".join(lines)


@dataclass
class AIMetricContext:
    """
    Normalized metric context for AI analysis.
    Built from MetricProvider output.
    """
    memory: Optional[MetricSummary] = None
    cpu: Optional[MetricSummary] = None
    anomalies: List[Anomaly] = field(default_factory=list)
    correlation_window_minutes: int = 5
    has_data: bool = False

    def to_prompt_text(self) -> str:
        """Convert to text suitable for AI prompt injection."""
        if not self.has_data:
            return "--- No metric data available ---"
        
        parts = []
        if self.memory:
            parts.append(
                f"Memory: current={self.memory.current_value:.1f}{self.memory.unit}, "
                f"avg={self.memory.avg_value:.1f}{self.memory.unit}, "
                f"max={self.memory.max_value:.1f}{self.memory.unit}, "
                f"trend={self.memory.trend}"
            )
        if self.cpu:
            parts.append(
                f"CPU: current={self.cpu.current_value:.1f}{self.cpu.unit}, "
                f"avg={self.cpu.avg_value:.1f}{self.cpu.unit}, "
                f"max={self.cpu.max_value:.1f}{self.cpu.unit}, "
                f"trend={self.cpu.trend}"
            )
        if self.anomalies:
            parts.append(f"Anomalies detected: {len(self.anomalies)}")
            for a in self.anomalies:
                parts.append(f"  - {a.metric_type} {a.severity}: peak={a.peak_value:.1f} (threshold={a.threshold:.1f}), duration={a.duration_seconds:.0f}s")
        
        return "--- Infrastructure Metrics ---\n" + "\n".join(parts)
