---
seo_title: "Multiple Kubernetes clusters"
description: "Register each Kubernetes cluster (EKS, GKE, AKS, kind) in SerOps so integrations and analyses route to the right one."
---
# Kubernetes Clusters (multi-cluster)

If you run SerOps against **multiple K8s clusters** (e.g., `prod-eks`,
`staging-gke`, `dev-kind`), register each cluster in *Settings →
Clusters* so integrations route correctly.

Single-cluster installs can skip this entirely — existing
integrations serve everything by default.

## Concept

- A **Cluster** is a record with a name, provider (EKS / GKE / AKS /
  generic K8s / bare metal / ...), optional region, and an optional
  kubectl context (stored for reference only).
- **ObservabilityIntegration** rows (Prometheus, Loki, Datadog,
  Tempo, ...) have an optional `cluster` FK:
  - **Cluster-scoped** — this integration serves *that* cluster only.
    Best when you run one Prometheus per cluster.
  - **Unscoped** (default) — serves *any* cluster. Best when you use
    a federated Prometheus / Thanos / Mimir that already merges
    across clusters.

## Uniqueness rules

Enforced by the DB (not just serializer):

- Per (org, provider, cluster) — one integration per provider per
  cluster. You can't have two `prometheus` rows scoped to `prod-eks`.
- Per (org, provider) unscoped — one unscoped fallback per provider
  per org.

Combined: one cluster-scoped `prometheus` per cluster **plus** one
unscoped fallback. The registry prefers the cluster-scoped one when
a cluster is specified; falls back to the unscoped one when no
cluster match exists.

## Registration

*Settings → Clusters → New cluster:*

| Field | Purpose |
|---|---|
| Name | Unique per org (e.g. `prod-eks`). Used in dropdowns + prompts. |
| Provider | Metadata only — helps you scan the list. |
| Region | Optional (`us-west-2`, `europe-west1`). |
| kubectl context | Optional metadata for CLI users. **SerOps never shells out to kubectl** — queries go via the cluster's Prometheus / Loki / etc. |
| Description | Free-form notes. |
| Active | Deactivate without deleting to hide from routing. |

Or via API (admin auth):

```bash
curl -X POST https://your-serops-host/api/integrations/clusters/ \
  -H "Authorization: Token $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"prod-eks","provider":"eks","region":"us-west-2"}'
```

## Attaching integrations to a cluster

When creating a new `ObservabilityIntegration`, pass `cluster: <id>`
in the payload (or select from the dropdown in the UI). Leaving it
blank creates an unscoped fallback.

Existing integrations remain unscoped after upgrade — nothing
changes for single-cluster installs.

## Deleting a cluster

Deleting a cluster **does not delete its integrations** — they
become unscoped (SET_NULL) so the registry still finds them under
"any cluster". This is intentional: a cluster deletion is often a
rename or a migration, not a full data purge.

## Assigning projects to clusters

*Settings → Projects → (project) → Cluster.* Or via API:

```bash
curl -X PATCH https://your-serops-host/api/projects/42/ \
  -H "Authorization: Token $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"cluster": 3}'
```

Projects without a cluster assignment show under "All clusters" only.

## Cluster picker

A **cluster dropdown** appears in the header when your org has 2+
clusters. It defaults to "All clusters" and persists in localStorage
across sessions. Selecting a cluster filters:

- Batches list (`Data` page)
- Issues list (`Issues` page)
- Dashboard analytics (per-cluster views coming — currently the
  dashboard cards still show org-wide until the analytics endpoints
  are cluster-aware)

The picker forwards `?cluster=<id>` on relevant API calls. Backend
endpoints silently ignore invalid ids (never 500 on stale picker
state).

## Workload view

The **Workloads by Cluster** card on the dashboard groups all your
projects + services under their assigned cluster. Rendered only
when the org has 2+ clusters. Each cluster row expands to show
project + service breakdown, sourced from
`GET /api/integrations/clusters/<id>/workloads/`.

## What multi-cluster does *not* do (yet)

- **Federated Prometheus** — SerOps queries whichever Prom you point
  it at. If you run a federated Prom that aggregates across
  clusters, leave the integration unscoped and use the `cluster`
  label in your PromQL for filtering (Prometheus native).
- **Cluster-scoped analytics** — the Dashboard cards (MTTR, Root
  Cause, Trends) don't yet honour the cluster picker; they still
  aggregate org-wide. Tracked in the Q1 quality backlog.
