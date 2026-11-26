---
seo_title: "Overview: what's broken, why, and what to do"
description: "The SerOps Overview: how many services have an open issue, what is broken and the first step, every service by name, recent analyses, and the week."
---
# Overview

The Overview is the first page after sign-in (**Overview** in the sidebar). It answers three questions in order: what is broken right now, why, and what to do. It refreshes every minute.

The **Environment** picker at the top left (and **Cluster**, once you have registered two or more clusters) filters it, like every other page. Both are kept in the address (`?environment=staging&cluster=3`), on the Overview, [Issues](issues.md) and [Analyses](batches.md), so a link opens the same view.

Every card says which time window it covers.

---

## Status

One sentence and a bar at the top: how many services have an open critical issue (or an open issue, when none is critical), how many more are affected by them, and how many are healthy. The bar has one square per service, in that order; hover a square, or read it with a screen reader, for the service's name. Above about 60 services the bar is in three parts instead.

A service **has an open issue** when an open critical or warning issue names it as its component. It is **affected** when it has no open issue of its own but an open issue elsewhere lists it among the services it affects (see [One issue per root cause](issues.md#one-issue-per-root-cause)). The rest are **healthy**.

## Needs attention now

The three worst open issues, each in the same shape: the severity, the service, the other services it affects, the project and the environment; **What is broken** (the first sentence of the issue); **Why it is happening** (the first sentence of the AI's root cause); the **First step** of the recommended action and how many more steps the issue holds; and **Open issue**. Texts are cut only at the end of a sentence; the whole text is in the issue. **All N open issues** opens [Issues](issues.md) filtered on them.

When nothing is open, the card says so.

## Services and recent analyses

- **Services**: every monitored service by name, in the three groups of the status bar, with the count in each title. A long healthy group shows the first five names; **and N more** shows the rest. A name opens [Issues](issues.md) filtered on that service. When two projects each have a service of the same name, the project follows the name, for example *notifier · Fleet*, here and in the status bar.
- **Recent analyses**: the five latest analyses, each with when it ran, what was found and its most severe level. **View all** opens [Analyses](batches.md).
- **Recent deployments**, when CI/CD is connected: the latest three pipeline runs or GitOps deploys per service in the selected environment, with branch, age and success rate.

On a phone, these panels and those of the week show only their title and summary line; tap one to open it. The status and **Needs attention now** stay open.

---

## The week

| Panel | Window | What it shows |
|-------|--------|---------------|
| **Issues found, last 7 days** | Last 7 days | Critical and warning issues created per day. |
| **What caused them** | Last 30 days | Issues by root-cause category (Code, Infrastructure, Configuration, Dependency, Unknown), as one bar with the counts beside it. |

Other figures are on the pages they belong to: correlation insights are a strip at the top of [Analyses](batches.md), Sentinel figures are on **Settings → Sentinel** (see [Sentinel](../how-to/sentinel.md)), and workloads by cluster are on **Settings → Clusters**.

## How health is scored

The Overview shows no score since 1.5.6. The [health endpoints of the API](../api/analytics.md) still return one, from one formula. It counts the issues that are **open now**, whatever their age; muted and resolved issues don't count.

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

One open warning is 94 % (healthy), one open critical 80 % (degraded), three open criticals 40 % (critical). For a service, its issues are the open issues whose component is the service's name, in its project; a service whose registry status is *error* is scored critical, *maintenance* degraded.

---

## Related pages

- [Analyses](batches.md): the analyses behind these numbers
- [Issues](issues.md): drill into an issue
- [Environments](environments.md): how environment filtering works
- [Dashboard & Analytics API](../api/analytics.md): REST API reference
