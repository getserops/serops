---
seo_title: "Dashboard: system health and open incidents"
description: "The SerOps dashboard: what needs attention now, system health, MTTR, AI insights, trends, failing services and recent deployments."
---
# Dashboard

The Dashboard provides a comprehensive view of your system health, issues, and trends.

## Overview

The Dashboard displays the following key components:

1. **Health Score Card** - Overall system health
2. **MTTR Card** - Mean Time To Resolution
3. **Trend Analysis Chart** - Issue trends over time
4. **Service Ranking Chart** - Top problematic services
5. **Root Cause Pie** - Distribution of root causes
6. **Service Health Heatmap** - Grid view of service status
7. **Recent Deployments** - Latest deployment activity
8. **AI Analysis Feed** - Recent AI analyses
9. **Correlation Insights Card** - Cross-signal correlation insights

---

## Health Score Card

**Location**: Top left

Displays the overall system health as a percentage:

| Score | Color | Meaning |
|-------|-------|---------|
| 85-100% | Green | Healthy |
| 60-84% | Yellow | Needs attention |
| 0-59% | Red | Critical |

**Calculated from**:
- Active issue count and severity
- Service availability
- Recent error rate

---

## MTTR Card

**Mean Time To Resolution** shows how quickly issues are being resolved.

| Metric | Description |
|--------|-------------|
| **Current MTTR** | Average resolution time (last 7 days) |
| **Trend** | ↑ or ↓ compared to previous period |
| **Severity Breakdown** | MTTR per severity level (Critical, Warning) |

!!! tip "Improving MTTR"
    - Investigate issues promptly
    - Use AI analysis for quick root cause identification
    - Set up notifications for critical issues

---

## Trend Analysis Chart

**Location**: Main chart area

Line chart showing issue trends over time:

- **X-axis**: Time (hours/days/weeks)
- **Y-axis**: Issue count
- **Lines**: Critical (red), Warning (yellow), Info (blue)

### Time Range Options
- Last 24 hours
- Last 7 days
- Last 30 days
- Custom range

---

## Service Ranking Chart

**Location**: Right panel

Bar chart showing which services have the most issues:

| Rank | Service | Issues |
|------|---------|--------|
| 1 | payment-api | 47 |
| 2 | user-service | 23 |
| 3 | notification-worker | 12 |

---

## Root Cause Pie

**Location**: Bottom left

Pie chart showing distribution of identified root causes:

| Category | Example |
|----------|---------|
| **Resource** | Memory exhaustion, CPU spike |
| **Network** | Connection timeout, DNS failure |
| **Application** | Null pointer, unhandled exception |
| **Database** | Query timeout, connection pool |
| **External** | Third-party API failure |

---

## Service Health Heatmap

**Location**: Center

Grid showing all services with color-coded health:

```
┌─────────┬─────────┬─────────┐
│ 🟢 API  │ 🟢 Auth │ 🟡 Pay  │
├─────────┼─────────┼─────────┤
│ 🔴 Notif│ 🟢 User │ 🟢 Log  │
└─────────┴─────────┴─────────┘
```

Hover over a cell to see:
- Last issue time
- Issue count
- Last deployment

---

## Recent Deployments Card

**Location**: Bottom right

Shows the latest deployments across all projects:

| Time | Project | Environment | Status |
|------|---------|-------------|--------|
| 14:30 | api-gateway | Production | ✅ Success |
| 13:45 | user-service | Staging | ✅ Success |
| 12:00 | payment-api | Production | ❌ Failed |

Click a deployment to see:
- Commit details
- Code changes
- Pipeline logs

---

## AI Analysis Feed

**Location**: Dashboard panel

Displays recent AI analyses across your projects:

- Latest batch analysis results
- Issues detected with severity indicators
- Quick links to full analysis details

---

## Correlation Insights Card

Highlights cross-signal correlations detected by AI:

- Links between code deployments and issue spikes
- Memory/CPU anomalies correlated with specific services
- Timeline view of correlated events

---

## Sentinel Intelligence Card

Displays Sentinel gating statistics and AI cost savings:

| Metric | Description |
|--------|-------------|
| **AI Skip Rate** | Percentage of batches where AI analysis was skipped (quiet batches) |
| **Decision Breakdown** | Count of alert, quiet, and first decisions in the period |
| **Batches Skipped** | Total batches that skipped AI analysis |
| **Tokens Saved** | Estimated AI tokens saved by skipping quiet batches |

!!! info "Requires Sentinel Active Mode"
    The skip rate and savings metrics are only meaningful when Sentinel is in **active mode**. In shadow mode, all batches run AI analysis regardless of the sentinel decision.

See [Sentinel How-To](../how-to/sentinel.md) for configuration details.

---

## Filtering

### Global Environment Filter

Toggle between environments:
- **All** (default)
- **Production**
- **Staging**
- **Dev**

---

## Refresh & Auto-Update

- Dashboard auto-refreshes via polling
- New batches trigger real-time updates

---

## Related Pages

- [Batches & Analysis](batches.md) — View batch details behind dashboard metrics
- [Issues](issues.md) — Drill into issues shown on the dashboard
- [Environments](environments.md) — Understand environment filtering
- [Dashboard & Analytics API](../api/analytics.md) — REST API reference
