---
seo_title: "Batch metrics: CPU and memory"
description: "Read CPU and memory metrics for each batch in SerOps and see how they correlate with errors and deployments."
---
# Metrics

View system performance metrics for each batch including memory and CPU usage.

## Overview

Access metrics from the batch detail view by selecting **Metrics** from the **Data Type** dropdown.

## What SerOps reads

SerOps reads **resource metrics**, the same ones for every analysis. It has
no setting for queries of your own.

| Metric store | What is read |
|---|---|
| Every store (Prometheus, VictoriaMetrics, Mimir, Datadog, CloudWatch, Azure Monitor, Google Cloud Monitoring) | CPU and memory: per node on VMs, per container and service on Kubernetes |
| Prometheus, VictoriaMetrics, Mimir | Also the busiest pod of a service (memory against its limit, CPU), and JVM garbage-collection time when the store has it |
| Prometheus, VictoriaMetrics, Mimir, with the project in Kubernetes mode | Also CPU throttling, and kube-state-metrics: restarts and their reason (`OOMKilled`), containers stuck starting, rollouts, replica counts, image and CPU/memory limit changes |

**Not read:** request rate, error rate, latency histograms, network, disk,
queue depth, business or custom metrics. SerOps sees errors and slowness
through your **logs** and **traces** (error patterns, error-rate spikes in
logs, slow and failing spans), not through application metrics. If an
incident shows only in an application metric, with nothing in the logs or
traces of the window, SerOps does not see it.

The exact series and queries are on the [Prometheus](../integrations/prometheus.md) page.

---

## Memory Usage

### Chart
Line/Area chart showing memory usage over the batch time window.

| Element | Description |
|---------|-------------|
| X-axis | Time (HH:mm:ss) |
| Y-axis | Usage (0-100%) |
| Blue Area | Memory usage trend |

### Threshold Indicators

The colours use the same thresholds the backend uses to flag anomalies
for the AI, so a red value is one the analysis also treats as abnormal.

| Level | Memory | CPU | Color |
|-------|--------|-----|-------|
| Over threshold | > 75% | > 80% | 🔴 Red |
| Approaching | > 68% | > 72% | 🟡 Yellow |
| Healthy | ≤ 68% | ≤ 72% | 🟢 Green |

"Approaching" starts at 90% of the threshold. Reference lines on the chart show these thresholds.

### Average Usage
Circular gauge showing average memory usage for the batch with color-coded status.

---

## CPU Usage

### Chart
Same format as memory, showing CPU usage over time.

### Average Usage
Circular gauge with percentage and threshold indicators.

---

## Filtering

### Host Filter
Filter metrics by host when multiple hosts are present:
- **All Hosts** (default)
- Individual host names discovered from metrics

### Type Filter
Both Memory and CPU usage are displayed simultaneously. Use the type dropdown to scroll to the selected metric type:
- Memory Usage
- CPU Usage

---

## Navigation

| Action | Description |
|--------|-------------|
| **Back** | Returns to batch detail view |
| **Type Dropdown** | Switch between metric types |
| **Host Dropdown** | Filter by specific host |

---

## Data Source

Metrics are fetched from the configured **Metric Provider** (Prometheus, VictoriaMetrics, Datadog, etc.) and stored within batches.

| Field | Description |
|-------|-------------|
| `timestamp` | When metric was recorded |
| `host` | Host/instance identifier |
| `value` | Usage percentage (0-100) |
| `type` | `memory_usage` or `cpu_usage` |

---

## Related Pages

- [Analyses](batches.md) — Metrics are collected as part of batch creation
- [Integrations Overview](../integrations/overview.md) — Supported metric providers
- [Prometheus](../integrations/prometheus.md) · [VictoriaMetrics](../integrations/victoriametrics.md) · [Datadog](../integrations/datadog.md) — Provider-specific setup
- [Observability API](../api/observability.md) — REST API reference
