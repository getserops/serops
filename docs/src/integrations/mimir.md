---
seo_title: "Grafana Mimir integration"
description: "Connect Grafana Mimir to SerOps as a metric provider, with multi-tenant headers and PromQL queries."
---
# Grafana Mimir

Grafana Mimir is a horizontally scalable, highly available, long-term storage solution for Prometheus metrics. SerOps uses it as a metric provider, querying time-series data via PromQL with support for multi-tenant isolation and up to 365 days of retention.

| | |
|---|---|
| **Type** | Metrics |
| **Auth** | Basic / Tenant ID |
| **Query Language** | PromQL |

## Prerequisites

- Grafana Mimir 2.x (tested: 2.14.2 — see [Compatibility](compatibility.md))
- Network access from the SerOps backend to the Mimir endpoint
- Valid credentials (basic auth or tenant ID)
- Tenant ID if using multi-tenant mode

## Configuration

```json
{
  "provider": "mimir",
  "display_name": "Grafana Mimir",
  "capabilities": ["metrics"],
  "host": "http://mimir:9009",
  "extra_config": {
    "path_prefix": "/prometheus",
    "tenant_id": "my-tenant"
  }
}
```

## Authentication Options

Mimir supports multiple authentication methods:

- **Basic Auth**: Provide `username` and `password` at the top level.
- **Tenant ID**: When `tenant_id` is set, SerOps includes the `X-Scope-OrgID` header on all requests to support multi-tenant deployments.

These can be combined (e.g., basic auth with a tenant ID).

## Extra Configuration

| Field | Type | Description |
|-------|------|-------------|
| `path_prefix` | string | Path prefix for the Prometheus-compatible API (e.g., `/prometheus`) |
| `tenant_id` | string | Tenant ID for multi-tenant Mimir; sent via `X-Scope-OrgID` header |

## Required metric labels

!!! warning "Without these labels SerOps finds nothing"
    SerOps locates your metrics by querying for specific label values.
    If your scrape config does not set them, every query matches zero
    series and batches come back empty — with no error to explain why.

Every series SerOps analyses must carry:

| Label | Example |
|---|---|
| `organisation_name` | `acme-cloud` |
| `project_name` | `checkout-api` |
| `service_name` | `checkout` |
| `environment` | `production` |

Because Mimir is Prometheus-compatible, the standard
`relabel_configs` approach applies:

```yaml
relabel_configs:
  - source_labels: [__meta_kubernetes_pod_label_app]
    target_label: service_name
  - source_labels: [__meta_kubernetes_namespace]
    target_label: environment
  - target_label: organisation_name
    replacement: acme-cloud
  - target_label: project_name
    replacement: checkout-api
```

See [Configure Data Collection](../how-to/configure-data-collection.md)
for the full reference, including the equivalent setup for logs.

## Health Check

```
POST /api/integrations/observability/{id}/health-check/
```

Response:
```json
{
  "integrations": [
    {
      "provider": "MimirMetricProvider",
      "provider_type": "metric",
      "healthy": true,
      "message": "OK"
    }
  ]
}
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Connection refused" | Verify `host` URL is reachable from SerOps backend |
| "401 Unauthorized" | Check `username` and `password` are correct |
| "Tenant not found" | Verify `tenant_id` in `extra_config` matches an existing tenant |
| "No data returned" | Verify the time range has data; check that `capabilities` includes `"metrics"` |

## Related Pages

- [Observability Overview](observability-overview.md)
- [API Reference](../api/observability.md)
