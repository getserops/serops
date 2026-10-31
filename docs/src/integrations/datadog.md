---
seo_title: "Datadog logs and metrics: AI root cause analysis"
description: "Connect Datadog to SerOps for both logs and metrics with one API and application key, and get root causes across your stack."
---
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

Create the application key under **Organization Settings → Application Keys → New Key** (not a Personal Access Token, whose key starts with `ddpat_`). SerOps only reads, so scope it down to:

| Scope | Used for |
|-------|----------|
| `logs_read_data` | Searching logs (analyses, Check my data) |
| `logs_read_index_data` | Listing your log indexes. Without it SerOps searches every index |
| `timeseries_query` | Querying metrics, when Datadog is also your metrics provider |

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

!!! note "Tested with a real Datadog Agent"
    Checked in October 2026 with the `datadog/datadog` Helm chart (Agent 7)
    on a local Kubernetes cluster, sending to a Datadog EU account: logs,
    Check my data, metrics per service and an investigation.
    See [Tested environments](overview.md#tested-environments).

Set the integration's **Topology mode** to **Kubernetes** (Settings →
Integrations, in the integration's form) to read container metrics per
service instead of host metrics:

| Query | VM mode | Kubernetes mode |
|-------|---------|-----------------|
| CPU | `avg:system.cpu.user{...} by {host}` | `sum:container.cpu.usage{...} by {service}`, in cores |
| Memory total | `avg:system.mem.total{...} by {host}` | `sum:container.memory.limit{...} by {service}` |
| Memory free | `avg:system.mem.free{...} by {host}` | limit minus `container.memory.usage`, by service |

The Agent tags every container with `service` (the deployment name, unless
[Unified Service Tagging](https://docs.datadoghq.com/getting_started/tagging/unified_service_tagging/)
sets another), so the services SerOps lists match your deployments.

**Prerequisites**: run the Datadog Agent with the `datadog/datadog` Helm
chart. Turn on log collection (it is off by default) and give your logs the
project and environment from labels on the project's namespace:

```yaml
# values.yaml for the datadog/datadog chart
datadog:
  apiKeyExistingSecret: datadog-keys   # a Secret with api-key (and app-key)
  clusterName: prod-eks
  tags:
    - "organisation_name:<YOUR-ORG>"   # every pod on the node gets this one
  namespaceLabelsAsTags:
    project_name: project_name
    environment: environment
  logs:
    enabled: true
    containerCollectAll: true
  kubelet:
    tlsVerify: false     # only for kubeadm/minikube self-signed CAs
```

```bash
kubectl label namespace <project-namespace> project_name=<YOUR-PROJECT> environment=production
```

!!! warning "Agent-level tags land on every pod"
    A tag under `datadog.tags` is added to every container on the node:
    coredns, the Agent itself, other projects. Put `project_name` and
    `environment` on the project's namespace as above, not under
    `datadog.tags`. Logs that carry no project tag can also be joined to a
    project from **Check my data** (it offers `kube_namespace` and
    `kube_app_part_of` as project rules).

**APM tip**: if your DD agents send traces, the same tagging flows through, so SerOps can correlate them with logs and metrics. See [Distributed Traces](traces.md).

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
| Analyses find nothing although logs arrive | Open **Projects → [project] → Data → Check my data**: it shows where logs drop out (project tag, environment, level, services) and what Datadog answered |

## Related Pages

- [Observability Overview](observability-overview.md)
- [API Reference](../api/observability.md)
