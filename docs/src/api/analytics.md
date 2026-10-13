# Dashboard & Analytics API

Endpoints for retrieving system health scores, service reliability metrics, trend analysis, MTTR, and deployment data.

These endpoints power the SerOps dashboard and provide aggregated insights across all projects and services.

## System Health

```
GET /api/data/analytics/health/
```

Returns the overall system health score and breakdown by category.

## Service Reliability

```
GET /api/data/analytics/services/
```

Returns per-service reliability scores based on recent batch analysis.

## Trend Analysis

```
GET /api/data/analytics/trends/
```

Returns issue counts over time, grouped by severity. Useful for visualising whether issue volume is increasing or decreasing.

## MTTR Statistics

```
GET /api/data/analytics/mttr/
```

Returns Mean Time To Resolution metrics, showing how quickly issues are being resolved across the organisation.

## Service Health Map

```
GET /api/data/analytics/service-health/
```

Returns heatmap data for all services, showing health status across time periods.

## Root Cause Statistics

```
GET /api/data/analytics/root-causes/
```

Returns the distribution of root cause categories (e.g., memory, CPU, database, network).

## Recent Deployments

```
GET /api/data/analytics/deployments/
```

Returns the latest deployment events across all projects. Useful for correlating deployments with issue spikes.

## Correlation Insights

```
GET /api/data/analytics/correlations/
```

Returns correlation insights linking issues to infrastructure metrics, code changes, and deployments.

## Recent AI Analysis Feed

```
GET /api/data/analytics/feed/
```

Returns a feed of the most recent AI analyses performed across all projects.

## Host Discovery

```
GET /api/data/hosts/
```

Returns discovered hosts and their metadata, based on log data analysis.

## Node Memory Metrics

```
GET /api/data/metrics
```

Returns raw node memory + swap samples from the configured metric provider. Useful for building custom charts alongside the batch view.

## Node CPU Metrics

```
GET /api/data/cpu/raw/
```

Returns raw node CPU samples from the configured metric provider.

## Log Ingest (Fluentd)

```
POST /api/data/logs
```

Endpoint that accepts log documents from a Fluentd forwarder. Used only by the [self-managed data-collection agent](../how-to/configure-data-collection.md); regular API clients should query batches instead.

## Recommendation Stats

```
GET /api/data/recommendation-stats/
```

Returns statistics on AI-generated recommendations (total, accepted, dismissed).

## Issue Stats

```
GET /api/data/issue-stats/
```

Returns aggregate issue statistics (open, resolved, muted counts) across the organisation.

## Sentinel Stats

```
GET /api/data/analytics/sentinel/
```

Returns Sentinel decision distribution and AI savings statistics.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `days` | integer | 7 | Lookback period in days |
| `environment` | string | all | Filter by environment name |

**Response:**

```json
{
  "period_days": 7,
  "total_batches": 150,
  "decisions": {
    "alert": 18,
    "quiet": 120,
    "first": 5,
    "shadow": 7
  },
  "ai_analyzed": 30,
  "ai_skipped": 120,
  "skip_rate_percent": 80.0,
  "estimated_tokens_saved": 1440000
}
```

| Field | Description |
|-------|-------------|
| `decisions` | Count of each sentinel decision type |
| `ai_analyzed` | Batches that received full AI analysis |
| `ai_skipped` | Batches where AI was skipped (active mode, quiet decision) |
| `skip_rate_percent` | Percentage of batches that skipped AI |
| `estimated_tokens_saved` | Average tokens per analysis × skipped count |

---

## Related

- [Issues](issues.md) -- Individual issue management and resolution
- [Batches & Data](batches.md) -- Source batch data behind analytics
- [Projects & Services](projects.md) -- Projects and services being tracked
- [API Overview](overview.md) -- Base URL, response format, and error codes
