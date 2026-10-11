# Clusters API

Endpoints for registering and managing clusters — the physical or
logical boundaries your workloads run in.

A cluster is one of the four scope dimensions SerOps uses to route a
project deployment to the right observability integration, alongside
environment, region, and namespace. Registering clusters is what lets
one organisation run the same project in several places and have each
copy analysed against its own log and metric backend.

## Endpoints

Standard DRF ViewSet routes, organisation-scoped:

```
GET    /api/integrations/clusters/
POST   /api/integrations/clusters/
GET    /api/integrations/clusters/{id}/
PATCH  /api/integrations/clusters/{id}/
DELETE /api/integrations/clusters/{id}/
```

Reads require authentication; writes require an admin role.

## Create a Cluster

```
POST /api/integrations/clusters/
```

**Request body:**

```json
{
  "name": "prod-eu-west-1",
  "region": "eu-west-1",
  "provider": "aws",
  "is_active": true
}
```

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Human-readable identifier, unique within the organisation. |
| `region` | string | Cloud region or datacentre label. |
| `provider` | string | Where it runs — for example `aws`, `gcp`, `azure`, `on-prem`. |
| `is_active` | boolean | Inactive clusters are excluded from batch generation. |

## Scope Matching

Clusters do not select integrations on their own. An
`IntegrationScope` record binds an observability integration to some
combination of cluster, environment, region, and namespace, and each
scope carries a priority tier — `primary`, `fallback`, or `tertiary`.

When a batch runs for a deployment, SerOps scores every candidate
integration by how specifically its scope matches, then walks the tiers
in order so an adapter error falls through to the next-best source
rather than failing the batch.

See [Observability Overview](../integrations/observability-overview.md)
for how to configure scopes and tiers.

---

## Related

- [Clusters](../admin/clusters.md) -- Registering clusters in the UI
- [Deployments](../user-guide/deployments.md) -- How clusters combine with environment, region, and namespace
- [Observability](observability.md) -- Integration management
- [API Overview](overview.md) -- Base URL, response format, and error codes
