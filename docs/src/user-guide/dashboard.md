---
seo_title: "Overview: what's broken, why, and what to do"
description: "The SerOps Overview: the incident that needs attention now, key numbers, recent AI analyses and deployments, and 7-day trends."
---
# Overview

The Overview is the first page after sign-in (**Overview** in the sidebar). It answers three questions in order: what is broken right now, why, and what to do. It refreshes every minute.

The **Environment** picker at the top left (and **Cluster**, once you have registered clusters) filters it, like every other page.

---

## Needs attention now

The most important open issue, with the AI's explanation (**Why it is happening**) and recommendation (**What to do**), and buttons to open the issue or the analysis it came from. Other open issues are listed below it, one line each, with their service.

When nothing is open, the card says so.

## Key numbers

| Card | What it shows |
|------|---------------|
| **System health** | A 0–100 % score: green from 85, yellow 60–84, red below 60. |
| **Mean time to resolve** | Average resolution time, its trend, and the time per severity. |
| **AI insights** | Number of AI analyses in the period. |
| **Critical** | Open critical issues. |

## Recent AI analyses and deployments

- **Recent AI analyses**: the latest analyses, each with its environment, what was found and the model used. **View all** opens [Analyses](batches.md).
- **Recent deployments**: the latest pipeline per service, with its branch, age and success rate.

---

## Trends

Charts come in pairs:

| Chart | What it shows |
|-------|---------------|
| **7-day trend** | Critical and warning issues per day over the last 7 days. |
| **Root cause breakdown** | Issues by root-cause category: Code, Infrastructure, Configuration, Dependency, Unknown. |
| **Top failing services** | Services ranked by issue count. |
| **Service health map** | One tile per service: healthy (80–100 %), degraded (50–79 %), critical (below 50 %). |
| **AI correlation insights** | Share of issues SerOps linked to a deployment, a memory or CPU spike, or a failed pipeline, and the services most affected. |
| **Sentinel intelligence** | AI analyses Sentinel skipped on quiet batches, and what that saved. |

!!! info "Sentinel savings need active mode"
    Skips and savings only apply when Sentinel is in **active mode**. In shadow mode every batch is analysed. See [Sentinel](../how-to/sentinel.md).

## Workloads by cluster

Organisations with more than one Kubernetes cluster get a list of clusters with their projects and services. It is hidden with zero or one cluster.

---

## Related pages

- [Analyses](batches.md): the analyses behind these numbers
- [Issues](issues.md): drill into an issue
- [Environments](environments.md): how environment filtering works
- [Dashboard & Analytics API](../api/analytics.md): REST API reference
