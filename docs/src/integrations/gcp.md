---
seo_title: "Google Cloud Logging and Monitoring integration"
description: "Connect Google Cloud Logging and Cloud Monitoring (formerly Stackdriver) to SerOps with one service account, including GKE."
---
# Google Cloud Operations

Google Cloud Operations (formerly Stackdriver) covers both **Cloud Logging** and **Cloud Monitoring**. A single SerOps integration serves both — one service-account key, one config record, both capabilities.

| | |
|---|---|
| **Type** | Logs + Metrics |
| **Auth** | Service-account JSON key |
| **Log Query Language** | Cloud Logging filter syntax |
| **Metric Query Language** | Cloud Monitoring filter |
| **SDK** | `google-cloud-logging` + `google-cloud-monitoring` |

## Prerequisites

- A **GCP project** where your workloads write logs and expose metrics
- A **service account** with these IAM roles on the target project:
  - `roles/logging.viewer` for Cloud Logging read access
  - `roles/monitoring.viewer` for Cloud Monitoring read access
- The service-account **JSON key** (Console → IAM → Service Accounts → Keys → Add Key → JSON)
- Network egress from the SerOps backend to `logging.googleapis.com` + `monitoring.googleapis.com`

!!! danger "Store the key file carefully"
    The service-account JSON is a full credential — anyone with a copy can read logs and metrics until you rotate the key. Never paste it into a screenshot or a public issue. SerOps encrypts it at rest with Fernet the moment you save the integration.

## Configuration

```json
{
  "provider": "gcp",
  "display_name": "GCP · production project",
  "capabilities": ["logs", "metrics"],
  "password": "{\"type\":\"service_account\",\"project_id\":\"prod-42\",...}",
  "extra_config": {
    "project_id": "prod-42"
  }
}
```

Notes:

- **`password`** must contain the *entire* JSON key file contents (a single JSON string). SerOps parses + validates it on save; a malformed or non-service-account key fails fast rather than blowing up on the first search.
- **`extra_config.project_id`** is required and must match the `project_id` inside the JSON key. Two separate fields because Cloud Logging + Cloud Monitoring endpoints take the project name in the request, not the credential.

## Authentication

SerOps deliberately loads credentials **only from the JSON key you paste**, never from Application Default Credentials, GCE metadata service, or any host-level auth. This matters for multi-tenant deployments: without the explicit-credential rule, a SerOps process running on a GCE VM would silently pick up whatever service account the VM has attached — which almost certainly is not the customer's project.

To rotate the key:

1. Create a new key in the GCP Console for the same service account
2. Update the `password` field on the integration (SerOps re-encrypts)
3. Delete the old key in the GCP Console

## What SerOps does with your query

**Logs (`GcpCloudLoggingProvider`):**

The canonical `LogQuery` translates via `to_gcp_filter()` into GCP filter syntax:

```
severity>=ERROR
AND labels.project_name="acme-checkout"
AND labels.environment="production"
AND (labels.service_name="backend-api" OR labels.service_name="payment-worker")
AND jsonPayload.message:"timeout"
AND timestamp>="2026-08-27T09:00:00Z"
AND timestamp<="2026-08-27T10:00:00Z"
```

- **Severity** is expressed as `>=THRESHOLD` using GCP's ordinal severity scale (DEBUG=100, INFO=200, NOTICE=300, WARNING=400, ERROR=500, CRITICAL=600, ALERT=700, EMERGENCY=800). Requesting `["ERROR", "WARNING"]` becomes `severity>=WARNING` — captures everything at or above the lowest requested level.
- **Time range** is embedded in the filter (unlike Splunk / CloudWatch which take it as a separate param) because Cloud Logging's `list_entries` API accepts only the filter as its selector.
- **Every user-supplied value** goes through `_gcp_escape` — backslash and double-quote are both escaped. Non-string inputs raise `TypeError` at build time.
- **Barewords** (severity thresholds, resource types) are validated against a strict `[A-Za-z0-9_]` allowlist. Any character outside that set fails loudly rather than being silently rewritten.

**Metrics (`GcpCloudMonitoringProvider`):**

The canonical `TimeSeries` query uses a filter like:

```
metric.type="compute.googleapis.com/instance/cpu/utilization"
AND metric.labels.env="prod"
```

Canonical Prometheus-style metric names (`node_cpu_seconds_total`, `container_memory_usage_bytes`) map to the corresponding GCP metric types via a small dictionary in the adapter. Unknown names pass through unchanged so you can query raw GCP types directly.

## Health Check

```
POST /api/integrations/observability/{id}/health-check/
```

Runs the cheapest authenticated call in each capability:

- **Logs**: single-entry `list_entries` iteration (forces the auth handshake to actually run)
- **Metrics**: single `list_metric_descriptors` iteration

A 200 response with `healthy: true` proves both the credentials *and* that the service account has read access to the target project's log/metric data.

## Async & Partial Results

Cloud Logging and Cloud Monitoring are both paged iterators. SerOps intentionally returns **partial results** if the iterator raises mid-stream (rate-limits, token refresh mid-stream, etc.) — partial context is more useful than an empty investigation.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "not valid JSON" on save | The `password` field is not a well-formed JSON string. Paste the whole file contents including the outer `{` and `}` |
| "expected a service-account JSON key" | The JSON is well-formed but is not a service-account key (probably a user credential or expired API key) |
| `project_id` missing / mismatch | The integration record's `extra_config.project_id` differs from the `project_id` inside the JSON key. They must match |
| 401 / 403 during search | The service account lacks `roles/logging.viewer` or `roles/monitoring.viewer` on the project |
| Empty results with no error | The time-range window has no matching entries, or the log labels differ from SerOps's canonical schema (`labels.project_name`, `labels.environment`, `labels.service_name`). Enrich your log shipper to add those labels |
| Invalid GCP bareword error | A severity string contains characters outside `[A-Za-z0-9_]` — usually a bad config value |
| Health check passes but searches return nothing | The service account can list metadata but has no data-read grant on the specific log names / metric types |

## Kubernetes (GKE) mode

!!! warning "Not yet validated on a live GKE cluster"
    This mode is implemented and unit-tested, but has not yet run against a
    live GKE cluster. See [Tested environments](overview.md#tested-environments).

For GKE clusters, set the integration's `topology_mode` to `kubernetes`.
SerOps will then:

- Route canonical `node_cpu_seconds_total` / `node_memory_*` metric
  names to their GKE equivalents (`kubernetes.io/container/cpu/core_usage_time`,
  `kubernetes.io/container/memory/used_bytes`, …).
- Filter by **resource labels** (`resource.labels.cluster_name`,
  `namespace_name`, `pod_name`, `container_name`) instead of
  `metric.labels.*`. Canonical SerOps labels are aliased
  automatically:

  | SerOps label | GKE resource label |
  |---|---|
  | `service_name` / `service` / `container` | `container_name` |
  | `namespace` | `namespace_name` |
  | `pod` | `pod_name` |
  | `cluster` | `cluster_name` |

- `discover_hosts` returns pods (as workload identity) instead of
  Compute Engine instances.

Prerequisite: GKE **Cloud Monitoring for GKE** must be enabled on
the cluster (default for standard GKE; check for Autopilot). The
service account needs `roles/monitoring.viewer`.

## Related Pages

- [Observability Overview](observability-overview.md)
- [API Reference](../api/observability.md)
