# Deployments

A **deployment** is one instance of "where a project runs" — a composed shape across four independent dimensions:

| Dimension     | Example                          | What it means |
|---------------|----------------------------------|---------------|
| `environment` | `production` / `staging` / `dev` | Which lifecycle stage this copy serves. |
| `cluster`     | `prod-eks`                       | The Kubernetes cluster (optional — VM-only projects leave this unset). |
| `region`      | `us-east-1` / `europe-west1`     | Free-text geographic tag. Used to distinguish multi-region copies. |
| `namespace`   | `payments` / `checkout`          | The K8s namespace. Only valid when a cluster is set. |

SerOps runs its batch pipeline once per active deployment. Multi-region, multi-cluster, and namespace-partitioned deployments are analysed independently so each copy gets its own timeline, its own issue set, and its own AI-generated root-cause verdicts.

## When you need multiple deployments

- **You run the same service in two regions.** `us-east-1` and `eu-west-1` see different traffic, different failures, and different neighbours. You want two rows on your Batches list, not one blended row.
- **You partition by K8s namespace.** The `payments` and `checkout` teams share `prod-eks` but operate on different SLOs. Separate deployments keep their issues in their own inbox.
- **Blue/green or canary.** The primary and canary copy of a service are separate deployments — different scope, different observability data.

## When you don't

Small SMB projects with one env × one cluster × one region need exactly one deployment. SerOps auto-creates it when the environment is first created — no user action required. The Deployments tab on the Project detail page stays hidden until you actually need it (progressive disclosure).

## How the auto-created deployment works

When you activate a `ProjectEnvironment` (via the onboarding wizard, the environments tab, or the API), a Django signal creates a matching `ProjectDeployment` immediately, inheriting the project's cluster (if any). No region, no namespace — just the base shape. Editing region / namespace later doesn't create a new deployment; it edits the existing one in place.

To add a *second* deployment (e.g. an eu-west-1 copy), open the project's **Deployments** tab and click **New deployment**. Fill in only the dimensions that differ.

## Invariants

SerOps enforces two model-level rules that the UI and API both surface:

1. **Namespace requires cluster.** You can't set `namespace='payments'` without a cluster — namespaces exist within clusters. The namespace field in the form is disabled until you pick a cluster.
2. **Unique shape per project.** The tuple `(project, environment, cluster, region, namespace)` must be unique. Two deployments with the same shape would produce identical batches — the DB refuses this at the constraint level.

## How deployments interact with observability

Observability integrations have their own scope (see [Observability Providers](../integrations/observability-overview.md)). When the batch pipeline picks which log / metric provider to query for a given deployment, it match-scores every integration against the deployment's four dimensions:

```
cluster > environment > region > namespace
```

The most specific match wins. Ties are broken by `priority_tier` (primary → fallback → tertiary), then by managed-vs-self-hosted. If the top pick errors, the pipeline falls through to the next tier in the chain — that's the resilience the [priority tier system](../integrations/observability-overview.md#scope-and-priority-tiers) is designed for.

## API

See the [Projects & Services API](../api/projects.md#deployments) for the full CRUD reference:

```
GET    /api/projects/deployments/?project={id}
POST   /api/projects/deployments/
PATCH  /api/projects/deployments/{id}/
DELETE /api/projects/deployments/{id}/
GET    /api/projects/deployments/suggest/?cluster={id}
```

The `suggest` endpoint returns proposed deployments for a newly-registered cluster — the frontend shows them as a modal so you accept individual rows rather than auto-materialising dozens.

## Composed filter (dashboard, batches, issues)

The header filter picker lets you scope the whole UI to any combination of cluster / environment / region / namespace at once. The selection persists across page reloads via a single JSON blob in `localStorage`. Clearing the cluster automatically clears the namespace to keep the invariant intact.
