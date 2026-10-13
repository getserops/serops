# Observability API

Endpoints for managing log and metric provider connections per organisation.

Observability integrations connect SerOps to external log and metric sources such as Elasticsearch, Datadog, or Prometheus. See the [Observability Providers](../integrations/observability-overview.md) section for full setup guides.

## List Available Providers

```
GET /api/integrations/observability/providers/
```

Returns the list of supported observability providers and their capabilities (logs, metrics, traces, or a combination).

## List Integrations

```
GET /api/integrations/observability/
```

Returns all configured observability integrations for the organisation.

## Create Integration

```
POST /api/integrations/observability/
```

**Request body:**

```json
{
  "provider": "elasticsearch",
  "display_name": "Production ES",
  "capabilities": ["logs"],
  "host": "https://es.example.com:9200",
  "username": "serops",
  "password": "secret",
  "cluster": 42,
  "priority_tier": "primary",
  "scope": {
    "environment": "production",
    "region": "us-east-1",
    "namespace": "payments"
  }
}
```

**Credentials are write-only.** `password` and secret `extra_config` keys
(`api_key`, `app_key`, `bearer_token`, `token`, `client_secret`,
`credentials_json`) are encrypted at rest and never returned. Responses
include `has_password` and `secret_fields_set`, for example
`["api_key", "app_key"]`. On `PATCH`, a secret sent blank or left out keeps
its stored value.

**Scoping fields (multi-topology support):**

| Field           | Type            | Purpose |
|-----------------|-----------------|---------|
| `cluster`       | int or `null`   | Pin to a specific `Cluster` (see [Clusters](clusters.md)). `null` = unscoped fallback that serves any cluster. |
| `priority_tier` | enum            | `primary`, `fallback`, or `tertiary`. The batch pipeline tries `primary` first and falls through to `fallback` then `tertiary` on adapter errors. |
| `scope.environment` | string      | Free-text env label (e.g. `production`). Matches project deployments with the same env name. Empty = wildcard. |
| `scope.region`      | string      | Free-text region label (e.g. `us-east-1`). Empty = wildcard. |
| `scope.namespace`   | string      | K8s namespace. Requires `cluster` set. Empty = wildcard. |

**Uniqueness:** at most one integration per `(organisation, provider, cluster, priority_tier)`. Adding a second `primary` on the same cluster returns `400`; use a different `priority_tier` (fallback / tertiary) to layer HA integrations of the same provider.

**Match precedence:** `cluster > environment > region > namespace`. Ties are broken by `priority_tier` (primary > fallback > tertiary), then by managed-vs-self-hosted.

## Get Integration

```
GET /api/integrations/observability/{id}/
```

Returns details for a single observability integration.

## Update Integration

```
PATCH /api/integrations/observability/{id}/
```

Updates an existing observability integration's configuration.

## Delete Integration

```
DELETE /api/integrations/observability/{id}/
```

Removes the observability integration. Returns `204 No Content` on success.

## Health Check

```
POST /api/integrations/observability/{id}/health-check/
```

Tests connectivity to the provider and returns the current health status.

---

## Related

- [Integrations](integrations.md) -- Global SCM/CI-CD provider integrations
- [Projects & Services](projects.md) -- Services that consume observability data
- [Batches & Data](batches.md) -- Batch data ingested from observability providers
- [API Overview](overview.md) -- Base URL, response format, and error codes
