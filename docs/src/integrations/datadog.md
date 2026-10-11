# Datadog

Datadog is a cloud-based monitoring and analytics platform. SerOps integrates with Datadog as a dual provider supporting both log retrieval and metric queries in a single integration, using the Datadog API with API key and application key authentication.

| | |
|---|---|
| **Type** | Logs + Metrics |
| **Auth** | API Key + App Key |
| **Query Language** | Datadog query syntax |

## Prerequisites

- A Datadog account with API access
- A valid API key and application key with appropriate permissions
- Network access from the SerOps backend to the Datadog API endpoint

## Configuration

```json
{
  "provider": "datadog",
  "display_name": "Datadog Production",
  "capabilities": ["logs", "metrics"],
  "host": "https://api.datadoghq.com",
  "extra_config": {
    "site": "datadoghq.com",
    "api_key": "your-api-key",
    "app_key": "your-app-key"
  }
}
```

!!! note "EU Datadog"
    For EU regions, use `"site": "datadoghq.eu"` and `"host": "https://api.datadoghq.eu"`.

## Authentication Options

Datadog uses API key and application key authentication. Both keys must be provided in `extra_config`:

- **API Key** (`api_key`): Authenticates requests to the Datadog API.
- **App Key** (`app_key`): Grants access to specific Datadog resources and scopes.

No basic auth (`username`/`password`) is used for Datadog.

## Extra Configuration

| Field | Type | Description |
|-------|------|-------------|
| `site` | string | Datadog site identifier (e.g., `datadoghq.com`, `datadoghq.eu`). When `site` is provided, the `host` field is ignored and the API URL is derived from the site value. |
| `api_key` | string | Datadog API key |
| `app_key` | string | Datadog application key |

## Metric Mapping

SerOps automatically maps Prometheus-style metric names to Datadog metrics:

| SerOps Metric | Datadog Metric |
|--------------|----------------|
| `node_memory_MemTotal_bytes` | `system.mem.total` |
| `node_memory_MemFree_bytes` | `system.mem.free` |
| `node_memory_MemAvailable_bytes` | `system.mem.usable` |
| `node_cpu_seconds_total` | `system.cpu.user` |

!!! note "Unmapped Metrics"
    Metrics that do not appear in the mapping table above are passed through to Datadog using their original name.

## Kubernetes setup

Set the integration's `topology_mode` to `kubernetes` to switch SerOps from `system.*` metrics (host-level) to `kubernetes.*` metrics aggregated per service:

| Query | VM mode | Kubernetes mode |
|-------|---------|-----------------|
| CPU | `avg:system.cpu.user{...}` | `avg:kubernetes.cpu.usage.total{...} by {service_name}` |
| Memory total | `avg:system.mem.total{...}` | `avg:kubernetes.memory.limits{...} by {service_name}` |
| Memory usage | `avg:system.mem.free{...}` (inverse) | `avg:kubernetes.memory.usage{...} by {service_name}` |

**Prerequisites**: run the Datadog Agent as a DaemonSet on your cluster with the Kubernetes integration enabled (default). Add SerOps' canonical tags via `DD_TAGS` on the agent:

```yaml
# helm values.yaml for datadog/datadog chart
datadog:
  apiKey: <YOUR-DD-API-KEY>
  clusterName: prod-eks
  tags:
    - "organisation_name:<YOUR-ORG>"
    - "project_name:<YOUR-PROJECT>"
    - "environment:production"
  # Unified Service Tagging (USM) — DD's own convention. SerOps aliases
  # `service` → `service_name` at query time, so setting `service` here
  # via env vars or pod annotations works automatically.
  env: production
  # cluster-wide default; per-pod annotations override.
kubelet:
  tlsVerify: false     # only for kubeadm/minikube self-signed CAs
```

For **per-pod** service tagging (recommended), add DD's admission-controller annotations to your deployments:

```yaml
metadata:
  annotations:
    admission.datadoghq.com/service: "checkout"   # → aliased to service_name
    admission.datadoghq.com/env: "production"     # → aliased to environment
    admission.datadoghq.com/version: "v2.3.1"
```

SerOps' log-side aliases (`service` → `service_name`, `env` → `environment`) mean you don't have to add SerOps-specific tags — the standard USM tags work.

**APM tip**: if your DD agents send traces, the same tagging flows through — Batch 5+ of the launch plan (distributed traces) will correlate them with logs and metrics automatically.

## Health Check

```
POST /api/integrations/observability/{id}/health-check/
```

Response:
```json
{
  "integrations": [
    {
      "provider": "DatadogLogProvider",
      "provider_type": "log",
      "healthy": true,
      "message": "OK"
    },
    {
      "provider": "DatadogMetricProvider",
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
| "403 Forbidden" | Verify `api_key` and `app_key` are valid and have the required permissions |
| "No data returned" | Verify the time range has data; check that `capabilities` includes the expected type |

## Related Pages

- [Observability Overview](observability-overview.md)
- [API Reference](../api/observability.md)
