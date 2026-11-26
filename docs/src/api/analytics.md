---
seo_title: "Dashboard and analytics API"
description: "API endpoints for health score, service reliability, trends, MTTR and deployments shown on the SerOps dashboard."
---
# Dashboard & Analytics API

Endpoints for retrieving system health scores, service reliability metrics, trend analysis, MTTR, and deployment data.

These endpoints power the SerOps dashboard and provide aggregated insights across all projects and services.

The `/api/data/analytics/` endpoints, Recommendation Stats and Issue Stats take the optional `environment` (an environment name, or `all`) and `cluster` (a cluster id, or `all`) query parameters and return only that slice.

## System Health

```
GET /api/data/analytics/health/
```

Returns the health score of the issues open now, whatever their age. The formula and thresholds are in [How health is scored](../user-guide/dashboard.md#how-health-is-scored); the Service Health Map and Service Reliability use the same ones.

```json
{
  "health_score": 74,
  "status": "Degraded",
  "metrics": {"open_critical": 1, "open_warning": 1, "open_total": 2, "resolved_last_24h": 0}
}
```

## Service Reliability

```
GET /api/data/analytics/services/
```

Returns the five components (services) with the lowest health score from their open issues, worst first: `name`, `count` (open issues), `critical` (open critical issues), `health_score` and `status` (`healthy`, `degraded`, `critical`). A component with no open issue is not listed.

## Trend Analysis

```
GET /api/data/analytics/trends/
```

Returns issue counts over time, grouped by severity. Useful for visualising whether issue volume is increasing or decreasing.

## MTTR Statistics

```
GET /api/data/analytics/mttr/
```

Returns the mean time to resolution of the issues created in the last `days` (default 30) and resolved since: `overall_mttr_hours` (`null` with no sample), `sample_size`, `period_days`, `by_severity` (`CRITICAL`, `WARNING`, `INFO`, `OTHER`, each with `avg_hours` and `count`) and `trend`: `IMPROVING`, `DEGRADING` or `STABLE`, or `INSUFFICIENT_DATA` below `min_sample_for_trend` (12) resolved issues.

## Service Health Map

```
GET /api/data/analytics/service-health/
```

Returns every registered service, worst first (up to 200), and `total_services`. Each entry has `name`, `project_name` (the service's project, which tells apart two services of the same name), `health_score`, `status`, `open_issues`, `critical_issues`, `warning_issues`, `error_count` (open critical + warning) and `affected_by`. A service's issues are the open issues whose component is the service's name, in its project. `affected_by` lists the components of the open issues of the service's project that name the service among their affected services, under the same organisation, `environment` and `cluster` filters; names are matched without regard to case, a service is never listed as affected by itself, and the list is empty when no open issue names it.

## Root Cause Statistics

```
GET /api/data/analytics/root-causes/
```

Returns the distribution of root cause categories: `Infrastructure`, `Code`, `Configuration`, `Dependency` and `Unknown`.

## Recent Deployments

```
GET /api/data/analytics/deployments/
```

Returns the latest three pipeline runs or GitOps deploys of each service with CI/CD configured. With `environment`, only that environment's runs, and only the services that have one.

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

Returns discovered hosts and their metadata, from the organisation's metric provider.

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

## Recommendation Stats

```
GET /api/data/recommendation-stats/
```

Returns how many issues carry an AI recommendation, split into immediate (critical issues) and long term. `status=OPEN` (or `MUTED`, `RESOLVED`) counts only issues in that state; the Overview's **AI recommendations** card uses `status=OPEN`.

## Issue Stats

```
GET /api/data/issue-stats/
```

Returns issue counts by severity. `status=OPEN` (or `MUTED`, `RESOLVED`) counts only issues in that state; the Overview's **Open critical** card uses `status=OPEN`.

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
| `cluster` | integer | all | Filter by cluster id |

**Response:**

```json
{
  "period_days": 7,
  "total_batches": 150,
  "decisions": {
    "alert": 18,
    "quiet": 120,
    "first": 5,
    "shadow": 7,
    "manual": 0
  },
  "ai_analyzed": 30,
  "ai_skipped": 120,
  "skip_rate_percent": 80.0,
  "estimated_tokens_saved": 1440000
}
```

| Field | Description |
|-------|-------------|
| `decisions` | Count of each sentinel decision type; the five add up to `total_batches` |
| `ai_analyzed` | Batches that received full AI analysis |
| `ai_skipped` | Batches where AI was skipped (active mode, quiet decision) |
| `skip_rate_percent` | Percentage of batches that skipped AI |
| `estimated_tokens_saved` | Average tokens per analysis × skipped count |
| `ai_spend_usd` | AI spend in the window: the selected environment and cluster's batches when filtered, the whole organisation's otherwise |
| `estimated_cost_saved_usd` | Tokens saved × the organisation's cost per token in the window |

---

## Related

- [Issues](issues.md) -- Individual issue management and resolution
- [Batches & Data](batches.md) -- Source batch data behind analytics
- [Projects & Services](projects.md) -- Projects and services being tracked
- [API Overview](overview.md) -- Base URL, response format, and error codes
