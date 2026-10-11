# VictoriaMetrics

VictoriaMetrics is a fast, cost-effective, and scalable time-series database and monitoring solution. It is API-compatible with Prometheus, and its query language MetricsQL is a superset of PromQL, providing additional functions and optimizations while remaining fully compatible with existing PromQL queries.

| | |
|---|---|
| **Type** | Metrics |
| **Auth** | Basic / Bearer |
| **Query Language** | MetricsQL (PromQL-compatible) |

## Prerequisites

- VictoriaMetrics (single-node or cluster)
- Network access from the SerOps backend to the VictoriaMetrics endpoint
- Valid credentials if authentication is enabled

## Configuration

```json
{
  "provider": "victoriametrics",
  "display_name": "VictoriaMetrics Cluster",
  "capabilities": ["metrics"],
  "host": "http://victoriametrics:8428"
}
```

## Authentication Options

VictoriaMetrics supports multiple authentication methods depending on your deployment:

- **No Auth**: Many VictoriaMetrics deployments run without authentication. Simply omit credentials.
- **Basic Auth**: Provide `username` and `password` at the top level for deployments using the built-in or proxy-based basic auth.
- **Bearer Token**: Provide `bearer_token` in `extra_config` for token-based authentication.

## Extra Configuration

| Field | Type | Description |
|-------|------|-------------|
| `bearer_token` | string | Bearer token for authentication |

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

Because VictoriaMetrics is Prometheus-compatible, the standard
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
      "provider": "VictoriaMetricsMetricProvider",
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
| "401 Unauthorized" | Check `username`/`password` or `bearer_token` are correct |
| "No data returned" | Verify the time range has data; check that `capabilities` includes `"metrics"` |

## Related Pages

- [Observability Overview](observability-overview.md)
- [API Reference](../api/observability.md)
