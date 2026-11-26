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
3.  **Query Metrics**: Fetch CPU and memory (and, from Prometheus-compatible stores, Kubernetes state) for correlation.
4.  **Collect Traces**: Receive spans over OpenTelemetry OTLP, or query Jaeger,
    Zipkin, Grafana Tempo or Datadog APM if your traces already live there.

SerOps does not store your logs or metrics — it queries them where they are.
**Traces are the one exception.** Spans pushed over OTLP are stored in SerOps'
own database until the organisation is deleted, because unlike a log store
there is no external system to read them back from. Choose the pull route
instead and nothing is stored. See [OTLP Traces](traces.md).

### Supported Providers

SerOps supports a wide range of providers, allowing you to mix and match per organisation.

| Category | Supported Providers |
|----------|---------------------|
| **Logs** | [Elasticsearch](elasticsearch.md), [OpenSearch](opensearch.md), [Grafana Loki](loki.md), [Splunk](splunk.md), [Datadog](datadog.md), [AWS CloudWatch](cloudwatch.md), [Google Cloud Logging](gcp.md), [Azure Log Analytics](azure.md) |
| **Metrics** | [Prometheus](prometheus.md), [VictoriaMetrics](victoriametrics.md), [Grafana Mimir](mimir.md), [Datadog](datadog.md), [AWS CloudWatch](cloudwatch.md), [Google Cloud Monitoring](gcp.md), [Azure Monitor](azure.md) |
| **Traces** | [OpenTelemetry OTLP](traces.md) (push, stored by SerOps) · [Jaeger](traces.md#alternative-pull-from-jaeger-zipkin-tempo-datadog-apm), [Zipkin](traces.md#alternative-pull-from-jaeger-zipkin-tempo-datadog-apm), [Grafana Tempo](traces.md#alternative-pull-from-jaeger-zipkin-tempo-datadog-apm), [Datadog APM](traces.md#alternative-pull-from-jaeger-zipkin-tempo-datadog-apm) (pull) |

### Provider Matrix

| Provider | Type | Auth Method | Query Language | Max Query Window | Features |
|----------|------|-------------|----------------|---------------|----------|
| **[Elasticsearch](elasticsearch.md)** | Logs | Basic / API Key | ES DSL | 30 days | Full-text, regex, aggregations, indexing |
| **[OpenSearch](opensearch.md)** | Logs | HTTP Auth | ES DSL | 30 days | Full-text, regex, aggregations, indexing, `verify_certs` default `true` |
| **[Grafana Loki](loki.md)** | Logs | Basic / Bearer / Tenant ID | LogQL | 30 days | Full-text, regex, live tail, multi-tenant |
| **[Splunk](splunk.md)** | Logs | Auth Token (bearer) | SPL | 30 days | Full-text, regex, aggregations, index scoping |
| **[Google Cloud](gcp.md)** | Logs + Metrics | Service account JSON | GCP filter | 30 days | Full-text, substring, live tail, high cardinality |
| **[Azure Monitor](azure.md)** | Logs + Metrics | Service principal | KQL | 30 days (logs), 93 days (metrics) | Full-text, regex, KQL power, high cardinality |
| **[Datadog](datadog.md)** | Logs + Metrics + Traces | API Key + App Key | Datadog query | 15 days | Full-text, regex, aggregations, live tail |
| **[CloudWatch](cloudwatch.md)** | Logs + Metrics | AWS Credentials | CloudWatch Insights | 30 days (logs), 14 days (metrics) | Full-text, regex, aggregations |
| **[Prometheus](prometheus.md)** | Metrics | Basic / Bearer | PromQL | 30 days | High cardinality, histograms, exemplars |
| **[VictoriaMetrics](victoriametrics.md)** | Metrics | Basic / Bearer | MetricsQL | 90 days | High cardinality, histograms |
| **[Grafana Mimir](mimir.md)** | Metrics | Basic / Bearer / Tenant ID | PromQL | 365 days | High cardinality, histograms, exemplars, multi-tenant |
| **[Jaeger](traces.md#alternative-pull-from-jaeger-zipkin-tempo-datadog-apm)** | Traces | Basic / Bearer | Jaeger query API | Store retention | Search by service name, fetch by trace ID |
| **[Zipkin](traces.md#alternative-pull-from-jaeger-zipkin-tempo-datadog-apm)** | Traces | Basic / Bearer | Zipkin v2 API | Store retention | Search by service name, fetch by trace ID |
| **[Grafana Tempo](traces.md#alternative-pull-from-jaeger-zipkin-tempo-datadog-apm)** | Traces | Basic / Bearer / Tenant ID | Tempo search API | Store retention | Search by service name, fetch by trace ID, multi-tenant |

---

## Configuration Levels

Providers can be configured at two levels:

!!! important "Agent Configuration Required"
    Connecting a provider is only the first step. Your log shippers and metric exporters must also tag every record with enrichment fields (organisation, project, service, environment) so that SerOps can query and filter your data correctly. See **[Configure Data Collection Agents](../how-to/configure-data-collection.md)** for the full field reference and examples.

### Per-Organisation Integrations

Each organisation must configure its own observability integrations. There is no system-wide fallback provider. Each integration is scoped to a single organisation and can be managed via API.

!!! note "One primary per capability"
    For a given cluster and scope (environment, region, namespace) there is one **primary** integration per capability: Loki and Elasticsearch cannot both be the primary log source, otherwise which one an analysis reads is ambiguous. Add the second one as `fallback` or `tertiary`. The same provider can also be layered `primary` + `fallback` + `tertiary` on one cluster for HA.

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

If the top-ranked integration's adapter cannot be loaded (a missing optional library, or a configuration the adapter rejects), SerOps uses the next one in the same order. A query that fails on a loaded adapter (5xx, timeout, auth failure) is not retried on the next tier: that read fails. Configuration:

- **Primary** — the golden path. Always tried first.
- **Fallback** — used when the primary cannot be loaded. Typical shape: same cluster, different provider (Loki fallback for an ES primary).
- **Tertiary** — last resort. Typical shape: unscoped catch-all (CloudWatch across all clusters).

The Observability settings panel shows every registered integration as a row with tier badge + scope pills so operators can see the full chain at a glance.

!!! warning "One log store per analysis"
    An analysis reads logs from one integration: the best match for its cluster and scope. A fallback is only read when that one cannot be loaded, not merged with it. If one project's services log to two stores (Kubernetes services in Cloud Logging and an AWS Lambda in CloudWatch, for example), the analysis sees only the services in the matching store. Until a project can read several stores, ship the other services' logs to the same store, or give them their own project.

---

## Configuration Reference

All providers share these common fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | string | required | Provider code (see provider matrix above) |
| `display_name` | string | required | Human-readable name |
| `capabilities` | list | all of the provider's | Any of `"logs"`, `"metrics"`, `"traces"` the provider supports |
| `host` | string | optional | Provider endpoint URL (not used by CloudWatch, Google Cloud or Azure Monitor) |
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
| **[Elasticsearch](elasticsearch.md)** | `api_key`, `verify_certs` (bool), `index_pattern` |
| **[OpenSearch](opensearch.md)** | `verify_certs` (bool), `index_pattern` |
| **[Loki](loki.md)** | `bearer_token`, `tenant_id` |
| **[Prometheus](prometheus.md)** | `bearer_token` |
| **[VictoriaMetrics](victoriametrics.md)** | `bearer_token` |
| **[Mimir](mimir.md)** | `path_prefix`, `tenant_id`, `bearer_token` |
| **[Datadog](datadog.md)** | `site`, `api_key`, `app_key` |
| **[CloudWatch](cloudwatch.md)** | `aws_region`, `log_groups`, `default_log_group` (the access key goes in `username` and `password`) |
| **[Splunk](splunk.md)** | `index`, `app`, `owner`, `verify_ssl` |
| **[Google Cloud](gcp.md)** | `project_id` |
| **[Azure Monitor](azure.md)** | `tenant_id`, `client_id`, `workspace_id`, `default_table`, `default_resource_uri` |
| **[Jaeger, Zipkin](traces.md#alternative-pull-from-jaeger-zipkin-tempo-datadog-apm)** | `bearer_token` |
| **[Grafana Tempo](traces.md#alternative-pull-from-jaeger-zipkin-tempo-datadog-apm)** | `bearer_token`, `tenant_id` |

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
- [Splunk](splunk.md) -- Log provider
- [Prometheus](prometheus.md) -- Metric provider
- [VictoriaMetrics](victoriametrics.md) -- Metric provider
- [Grafana Mimir](mimir.md) -- Metric provider
- [Datadog](datadog.md) -- Log + Metric + Trace provider
- [AWS CloudWatch](cloudwatch.md) -- Log + Metric provider
- [Google Cloud](gcp.md) -- Log + Metric provider
- [Azure Monitor](azure.md) -- Log + Metric provider
- [Distributed Traces](traces.md) -- OTLP receiver, and pull from Jaeger, Zipkin, Grafana Tempo and Datadog APM
