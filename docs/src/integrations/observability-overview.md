---
seo_title: "Log and metric providers"
description: "Connect SerOps to the log and metric backends you already run; capabilities, configuration and health checks per provider."
---
# Observability Providers

Connect SerOps to your existing Log and Metric storage providers.

## Overview

SerOps integrates with the observability stack you already run rather than
replacing it:

1.  **Retrieve Logs**: Fetch application and CI/CD logs for AI analysis.
2.  **Ingest Events**: Send enriched CI/CD event documents to your log store.
3.  **Query Metrics**: Fetch performance metrics for correlation.
4.  **Collect Traces**: Receive spans over OpenTelemetry OTLP, or query Jaeger,
    Zipkin or Datadog APM if your traces already live there.

SerOps does not store your logs or metrics — it queries them where they are.
**Traces are the one exception.** Spans pushed over OTLP are stored in SerOps'
own database under a retention window you control, because unlike a log store
there is no external system to read them back from. Choose the pull route
instead and nothing is stored. See [OTLP Traces](traces.md).

### Supported Providers

SerOps supports a wide range of providers, allowing you to mix and match per organisation.

| Category | Supported Providers |
|----------|---------------------|
| **Logs** | [Elasticsearch](elasticsearch.md), [OpenSearch](opensearch.md), [Grafana Loki](loki.md), [Splunk](splunk.md), [Datadog](datadog.md), [AWS CloudWatch](cloudwatch.md), [Google Cloud Logging](gcp.md), [Azure Log Analytics](azure.md) |
| **Metrics** | [Prometheus](prometheus.md), [VictoriaMetrics](victoriametrics.md), [Grafana Mimir](mimir.md), [Datadog](datadog.md), [AWS CloudWatch](cloudwatch.md), [Google Cloud Monitoring](gcp.md), [Azure Monitor](azure.md) |
| **Traces** | [OpenTelemetry OTLP](traces.md) (push, stored by SerOps) · [Jaeger](traces.md#alternative-pull-from-jaeger-zipkin-datadog-apm), [Zipkin](traces.md#alternative-pull-from-jaeger-zipkin-datadog-apm), [Grafana Tempo](traces.md#alternative-pull-from-jaeger-zipkin-datadog-apm), [Datadog APM](traces.md#alternative-pull-from-jaeger-zipkin-datadog-apm) (pull) |

### Provider Matrix

| Provider | Type | Auth Method | Query Language | Max Query Window | Features |
|----------|------|-------------|----------------|---------------|----------|
| **[Elasticsearch](elasticsearch.md)** | Logs | Basic / API Key | ES DSL | 30 days | Full-text, regex, aggregations, indexing |
| **[OpenSearch](opensearch.md)** | Logs | HTTP Auth | ES DSL | 30 days | Full-text, regex, aggregations, indexing, `verify_certs` default `false` |
| **[Grafana Loki](loki.md)** | Logs | Basic / Bearer / Tenant ID | LogQL | 30 days | Full-text, regex, live tail, multi-tenant |
| **[Splunk](splunk.md)** | Logs | Auth Token (bearer) | SPL | 30 days | Full-text, regex, aggregations, index scoping |
| **[Google Cloud](gcp.md)** | Logs + Metrics | Service account JSON | GCP filter | 30 days | Full-text, substring, live tail, high cardinality |
| **[Azure Monitor](azure.md)** | Logs + Metrics | Service principal | KQL | 30 days (logs), 93 days (metrics) | Full-text, regex, KQL power, high cardinality |
| **[Datadog](datadog.md)** | Logs + Metrics | API Key + App Key | Datadog query | 15 days | Full-text, regex, aggregations, live tail |
| **[CloudWatch](cloudwatch.md)** | Logs + Metrics | AWS Credentials | CloudWatch Insights | 14 days | Full-text, regex, aggregations |
| **[Prometheus](prometheus.md)** | Metrics | Basic / Bearer | PromQL | 30 days | High cardinality, histograms, exemplars |
| **[VictoriaMetrics](victoriametrics.md)** | Metrics | Basic / Bearer | MetricsQL | 90 days | High cardinality, histograms |
| **[Grafana Mimir](mimir.md)** | Metrics | Basic / Tenant ID | PromQL | 365 days | High cardinality, histograms, exemplars, multi-tenant |

---

## Configuration Levels

Providers can be configured at two levels:

!!! important "Agent Configuration Required"
    Connecting a provider is only the first step. Your log shippers and metric exporters must also tag every record with enrichment fields (organisation, project, service, environment) so that SerOps can query and filter your data correctly. See **[Configure Data Collection Agents](../how-to/configure-data-collection.md)** for the full field reference and examples.

### Per-Organisation Integrations

Each organisation must configure its own observability integrations. There is no system-wide fallback provider. Each integration is scoped to a single organisation and can be managed via API.

!!! note "Uniqueness"
    Uniqueness is sliced by `(organisation, provider, cluster, priority_tier)`. That means one Elasticsearch integration per cluster per tier — you can layer `primary` + `fallback` + `tertiary` rows of the same provider on the same cluster for HA. Two `primary` rows on the same cluster is rejected.

## Scope and Priority Tiers

Every integration carries four scope dimensions and a priority tier. The batch pipeline uses these to decide which integration to query for a given [deployment](../user-guide/deployments.md).

| Field | Purpose |
|-------|---------|
| `cluster` (parent field) | Pin to a Kubernetes cluster. `null` = unscoped fallback that serves any cluster. |
| `scope.environment`      | Env label (`production`, `staging`, `preview`). Empty = wildcard. |
| `scope.region`           | Free-text region tag (`us-east-1`, `europe-west1`, `dc1`). Empty = wildcard. |
| `scope.namespace`        | K8s namespace. Requires `cluster` set. Empty = wildcard. |
| `priority_tier`          | `primary`, `fallback`, or `tertiary`. |

### How matching works

For each deployment the pipeline processes, `_best_integration()` scores every candidate integration:

1. **Field precedence:** an explicit match on a more specific field beats a match on a less specific one — `cluster > environment > region > namespace`. A wildcard (empty) integration is still eligible, just lower priority.
2. **Tier tiebreak:** integrations with the same score are ranked `primary → fallback → tertiary`.
3. **Provider tiebreak:** self-hosted beats managed (SerOps prefers integrations closer to your data plane).

### Failover chain

If the top-ranked integration returns an adapter error (5xx, timeout, auth failure), the pipeline transparently retries on the next tier. Configuration:

- **Primary** — the golden path. Always tried first.
- **Fallback** — kicks in when primary errors. Typical shape: same cluster, different provider (Loki fallback for an ES primary).
- **Tertiary** — last resort. Typical shape: unscoped catch-all (CloudWatch across all clusters).

The Observability settings panel shows every registered integration as a row with tier badge + scope pills so operators can see the full chain at a glance.

---

## Configuration Reference

All providers share these common fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | string | required | Provider code (see provider matrix above) |
| `display_name` | string | required | Human-readable name |
| `capabilities` | list | required | `["logs"]`, `["metrics"]`, or `["logs", "metrics"]` |
| `host` | string | required | Provider endpoint URL |
| `username` | string | optional | Basic auth username |
| `password` | string | optional | Basic auth password (write-only, never returned in API) |
| `extra_config` | object | `{}` | Provider-specific options (see per-provider pages) |
| `timeout_seconds` | int | 30 | Request timeout |
| `max_retries` | int | 3 | Max retry attempts per request |
| `rate_limit_per_minute` | int | 60 | Rate limit for API calls |
| `is_active` | bool | true | Enable/disable this integration |

### Provider-Specific `extra_config` Fields

| Provider | Fields |
|----------|--------|
| **[Elasticsearch](elasticsearch.md)** | `api_key`, `verify_certs` (bool) |
| **[OpenSearch](opensearch.md)** | `verify_certs` (bool) |
| **[Loki](loki.md)** | `bearer_token`, `tenant_id` |
| **[Prometheus](prometheus.md)** | `bearer_token` |
| **[VictoriaMetrics](victoriametrics.md)** | `bearer_token` |
| **[Mimir](mimir.md)** | `path_prefix`, `tenant_id` |
| **[Datadog](datadog.md)** | `site`, `api_key`, `app_key` |
| **[CloudWatch](cloudwatch.md)** | `aws_region`, `aws_access_key_id`, `aws_secret_access_key`, `aws_session_token`, `default_log_group` |

---

## Health Checks

Test connectivity to a configured integration:

```
POST /api/integrations/observability/{id}/health-check/
```

Response:
```json
{
  "integrations": [
    {
      "provider": "ElasticsearchLogProvider",
      "provider_type": "log",
      "healthy": true,
      "message": "OK"
    }
  ]
}
```

The `last_health_check` and `last_health_status` fields on the integration are updated automatically.

---

## Troubleshooting

| Issue | Provider | Solution |
|-------|----------|----------|
| "Connection refused" | All | Verify `host` URL is reachable from SerOps backend |
| "401 Unauthorized" | ES, Prometheus | Check `username`/`password` or `bearer_token` |
| "403 Forbidden" | Datadog | Verify `api_key` and `app_key` are valid |
| "InvalidAccessKeyId" | CloudWatch | Check AWS credentials and region |
| "No data returned" | All | Verify the time range has data; check `capabilities` match provider type |
| "Tenant not found" | Loki, Mimir | Verify `tenant_id` in `extra_config` |
| "SSL certificate error" | ES, OpenSearch | Set `verify_certs: false` in `extra_config` (not recommended for production) |

---

## Provider Pages

- [Elasticsearch](elasticsearch.md) -- Log provider
- [OpenSearch](opensearch.md) -- Log provider
- [Grafana Loki](loki.md) -- Log provider
- [Prometheus](prometheus.md) -- Metric provider
- [VictoriaMetrics](victoriametrics.md) -- Metric provider
- [Grafana Mimir](mimir.md) -- Metric provider
- [Datadog](datadog.md) -- Log + Metric provider
- [AWS CloudWatch](cloudwatch.md) -- Log + Metric provider
