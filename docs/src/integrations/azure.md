---
seo_title: "Azure Monitor and Log Analytics integration"
description: "Connect Azure Log Analytics and Azure Monitor Metrics to SerOps with one service principal."
---
# Azure Monitor

Azure Monitor covers both **Log Analytics** (logs) and **Azure Monitor Metrics** (metrics). A single SerOps integration handles both — one service principal, one config record, both capabilities.

| | |
|---|---|
| **Type** | Logs + Metrics |
| **Auth** | Service principal (tenant + client + secret) |
| **Log Query Language** | KQL (Kusto Query Language) |
| **Metric Query Language** | Metric name + resource URI + aggregation |
| **SDK** | `azure-monitor-query` + `azure-identity` |

## Prerequisites

- An **Azure AD tenant** and an **App registration** (service principal) with a client secret
- The service principal must have these Azure RBAC roles on the target workspace / resources:
  - `Log Analytics Reader` on the Log Analytics workspace (for logs)
  - `Monitoring Reader` on the resource group or specific resources (for metrics)
- The **Log Analytics workspace ID** (a GUID from the workspace's Overview page)
- The **default resource URI** for metrics (an ARM-style `/subscriptions/…/resourceGroups/…/providers/…/…` path)
- Network egress from the SerOps backend to `login.microsoftonline.com`, `api.loganalytics.io`, and `management.azure.com`

## Configuration

```json
{
  "provider": "azure",
  "display_name": "Azure · production tenant",
  "capabilities": ["logs", "metrics"],
  "password": "your-client-secret",
  "extra_config": {
    "tenant_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "client_id": "11111111-2222-3333-4444-555555555555",
    "workspace_id": "66666666-7777-8888-9999-000000000000",
    "default_table": "AppTraces",
    "default_resource_uri": "/subscriptions/sub-id/resourceGroups/rg-name/providers/Microsoft.Compute/virtualMachines/vm-name"
  }
}
```

Notes:

- **`password`** is the client secret (encrypted at rest with Fernet). Rotate it in Azure AD → App registrations → Certificates & secrets, then update this field.
- **`tenant_id`** and **`client_id`** identify the service principal.
- **`workspace_id`** is required for logs. **`default_resource_uri`** is required for metrics — callers can override per-query by supplying `resource_uri` in the labels dict.
- **`default_table`** (optional, defaults to `AppTraces`) picks the KQL table for `LogQuery`-driven searches. Use `Perf` for VM performance, `Syslog` for Linux syslog, `ContainerLog` for AKS, or a custom table.

!!! warning "Service-principal-only auth"
    SerOps deliberately does **not** support `DefaultAzureCredential`, `ManagedIdentityCredential`, or CLI-cached tokens. A multi-tenant SerOps process must never inherit host-level credentials, which is exactly what those auth flows do.

## What SerOps does with your query

**Logs (`AzureLogAnalyticsProvider`):**

`LogQuery.to_azure_kql()` produces well-formed KQL:

```kql
AppTraces
| where TimeGenerated >= datetime(2026-08-27T09:00:00Z)
| where TimeGenerated <= datetime(2026-08-27T10:00:00Z)
| where Properties.project_name == "acme-checkout"
| where Properties.environment == "production"
| where Properties.service_name in ("backend-api", "payment-worker")
| where SeverityLevel >= 3
| where Message contains "timeout"
| top 5000 by TimeGenerated desc
```

- **Severity** maps to Azure's `SeverityLevel` ordinal (Verbose=0, Information=1, Warning=2, Error=3, Critical=4). Requesting `["ERROR", "WARNING"]` becomes `SeverityLevel >= 2`.
- **Labels** live under `Properties.<name>` in AppTraces — the canonical Application Insights schema. For `Perf`, `Syslog`, or `ContainerLog`, adjust the KQL manually via a raw-KQL query.
- **Time range** is embedded as `datetime(<iso>)` literals. The `<iso>` value is validated by `_kql_datetime` before interpolation — only digits, dashes, colons, `T`, `Z`, `.`, `+` are permitted. Any character outside that set fails loudly (an unquoted KQL identifier is executable code, so silent rewrites here are the highest-severity risk in the schema layer).

**Metrics (`AzureMonitorProvider`):**

Canonical Prometheus-style names map to Azure metric names via a small dictionary:

| Canonical | Azure metric |
|---|---|
| `node_cpu_seconds_total` | `Percentage CPU` |
| `node_memory_MemAvailable_bytes` | `Available Memory Bytes` |
| `container_cpu_usage_seconds_total` | `CPU Usage` |
| `container_memory_usage_bytes` | `Memory Usage` |

Unknown names pass through unchanged so you can query any native Azure metric directly.

**Granularity** is auto-picked based on the query time range — targeting ~200 data points to stay well under Azure's per-query cap.

## Health Check

```
POST /api/integrations/observability/{id}/health-check/
```

Runs the cheapest authenticated call in each capability:

- **Logs**: `print now()` KQL query — forces service-principal auth to actually run against the workspace
- **Metrics**: `list_metric_definitions(default_resource_uri)` — proves the SP can read the target resource

## KQL Table Selection

The `default_table` sets what `LogQuery`-driven searches query. The three you'll probably use:

| Table | Content | When to use |
|---|---|---|
| `AppTraces` | Application Insights `trace()` calls | Default. Best for OpenTelemetry / App Insights instrumented apps. |
| `ContainerLog` | Log lines from AKS pods | Kubernetes workloads |
| `Perf` | VM performance counters | VM CPU / memory / disk baselines |
| `Syslog` | Linux syslog | On-prem VMs, network devices |

Callers can always supply a raw KQL string instead — the adapter accepts `search(index="", query="AppExceptions | count")` and passes it through unchanged.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Azure adapter requires tenant_id + client_id + password" | One of the auth fields is missing. Confirm the service principal has a valid client secret and all three IDs are populated |
| 401 / 403 on search | Service principal lacks `Log Analytics Reader` on the workspace (or `Monitoring Reader` on the resource for metrics) |
| "Invalid KQL bareword" during search | The `default_table` or the `index=` parameter contains characters outside `[A-Za-z0-9_]`. This is intentional strictness — a stray character in an unquoted KQL identifier is a code-injection vector |
| "Invalid KQL datetime literal" | Time-range values weren't clean ISO timestamps. Usually a caller passed something else (a Unix epoch, a formatted string). Feed a `datetime` to `LogQuery.time_range` and let the translator format it |
| Empty results with no error | Time-range window is too narrow, the AppTraces table doesn't have `Properties.project_name`/`Properties.environment` set (your instrumentation isn't populating them yet), or the workspace has no data in that period |

## Kubernetes (AKS) mode

!!! warning "Not yet validated on a live AKS cluster"
    This mode is implemented and unit-tested, but has not yet run against a
    live AKS cluster. See [Tested environments](overview.md#tested-environments).

For AKS clusters, set the integration's `topology_mode` to
`kubernetes` and point `default_resource_uri` at the **AKS cluster**
resource (not a VM). SerOps will then:

- Route canonical `node_cpu_seconds_total` / `container_*` names to
  the Azure Monitor Container Insights metric names
  (`node_cpu_usage_percentage`, `container_cpu_usage_percentage`,
  `container_memory_working_set_bytes`, …).
- Build an Azure dimension `filter` string per query so metric
  results narrow to the right workload. Canonical SerOps labels are
  aliased automatically:

  | SerOps label | Azure dimension |
  |---|---|
  | `service_name` / `service` | `controllerName` |
  | `namespace` | `kubernetesNamespace` |
  | `pod` | `podName` |
  | `container` | `containerName` |
  | `node` | `node` |

- Values are quoted; any value containing a double-quote is
  **silently dropped** rather than sent into the filter (defence in
  depth against a hostile label).

Prerequisite: **Azure Monitor Container Insights** must be enabled
on the AKS cluster (portal → *Insights* → *Enable*, or via
`az aks enable-addons -a monitoring`). The service principal needs
`Monitoring Reader` on the AKS resource.

## Related Pages

- [Observability Overview](observability-overview.md)
- [API Reference](../api/observability.md)
