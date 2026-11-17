---
seo_title: "Overview: what's broken, why, and what to do"
description: "The SerOps Overview: the incident that needs attention now, key numbers, recent AI analyses and deployments, and 7-day trends."
---
# Overview

The Overview is the first page after sign-in (**Overview** in the sidebar). It answers three questions in order: what is broken right now, why, and what to do. It refreshes every minute.

The **Environment** picker at the top left (and **Cluster**, once you have registered clusters) filters it, like every other page. Both are kept in the address (`?environment=staging&cluster=3`), on the Overview, [Issues](issues.md) and [Analyses](batches.md), so a link opens the same view.

Every card says which time window it covers.

---

## Needs attention now

The most important open issue, with the AI's explanation (**Why it is happening**) and recommendation (**What to do**), and buttons to open the issue or the analysis it came from. Other open issues are listed below it, one line each, with their service.

When nothing is open, the card says so.

## Key numbers

| Card | Window | What it shows |
|------|--------|---------------|
| **System health** | Open issues now | A 0–100 % score from the open issues, see [How health is scored](#how-health-is-scored). |
| **Mean time to resolve** | Last 30 days | Average time from creation to resolution of the issues created in the window and resolved since, per severity (critical, warning, info), with the sample size (`n`). The trend compares the newer half of the sample with the older half and needs 12 resolved issues; below that the card says **Not enough data**. |
| **AI recommendations** | Open issues now | Open issues that carry an AI recommendation. |
| **Open critical** | Open issues now | Open critical issues. |

## Recent AI analyses and deployments

- **Recent AI analyses**: the five latest analyses, each with its environment, what was found and the model used. **View all** opens [Analyses](batches.md).
- **Recent deployments**: the latest three pipeline runs or GitOps deploys per service in the selected environment, with branch, age and success rate.

---

## Trends

Charts come in pairs:

| Chart | Window | What it shows |
|-------|--------|---------------|
| **7-day trend** | Last 7 days | Critical and warning issues created per day. |
| **Root cause breakdown** | Last 30 days | Issues by root-cause category: Code, Infrastructure, Configuration, Dependency, Unknown. |
| **Top failing services** | Open issues now | The five services with the lowest health score. A service with no open issue is healthy and is not listed. |
| **Service health map** | Open issues now | One tile per registered service, scored like System health. |
| **AI correlation insights** | Last 7 days | Share of issues SerOps linked to a commit (**Commit links**), a memory or CPU spike, or a failed pipeline, and the components with the most correlated issues. |
| **Sentinel intelligence** | Last 7 days | Sentinel's decision per batch (alert, quiet, first, and shadow or manual when there are any; they add up to the batch count), how many batches the AI analysed, the AI calls skipped on quiet batches, and what that saved. With an environment or cluster selected, AI spend counts only that selection's batches. |

## How health is scored

System health, the service health map and top failing services use one formula. It counts the issues that are **open now**, whatever their age; muted and resolved issues don't count.

```
score = 100 - 20 x open critical - 6 x open warning - 2 x other open issue
        + 2 x issue resolved in the last 24 h (at most +10, and only while something is open)
```

The score stays between 0 and 100, and is 100 when nothing is open.

| Status | Score |
|--------|-------|
| Healthy | 85–100 % |
| Degraded | 60–84 % |
| Critical | below 60 % |

One open warning is 94 % (healthy), one open critical 80 % (degraded), three open criticals 40 % (critical). On the map, a service's issues are the open issues whose component is the service's name, in its project; a service whose registry status is *error* is shown critical, *maintenance* degraded.

!!! info "Sentinel savings need active mode"
    Skips and savings only apply when Sentinel is in **active mode** (the default). In shadow mode every batch is analysed. See [Sentinel](../how-to/sentinel.md).

## Workloads by cluster

Organisations with more than one Kubernetes cluster get a list of clusters with their projects and services. It is hidden with zero or one cluster.

---

## Related pages

- [Analyses](batches.md): the analyses behind these numbers
- [Issues](issues.md): drill into an issue
- [Environments](environments.md): how environment filtering works
- [Dashboard & Analytics API](../api/analytics.md): REST API reference
