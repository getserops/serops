---
seo_title: "Prometheus: correlate metrics with incidents"
description: "Connect Prometheus to SerOps so PromQL metrics are correlated with errors, deployments and code changes during analysis."
---
# Prometheus

Prometheus is an open-source monitoring and alerting toolkit designed for reliability and scalability. SerOps uses it as a metric provider, querying time-series data via PromQL to fetch performance metrics for correlation with CI/CD events.

| | |
|---|---|
| **Type** | Metrics |
| **Auth** | Basic / Bearer |
| **Query Language** | PromQL |

## Prerequisites

- Prometheus 2.x or later
- Network access from the SerOps backend to the Prometheus server
- Valid credentials if authentication is enabled

## Configuration

```json
{
  "provider": "prometheus",
  "display_name": "Production Prometheus",
  "capabilities": ["metrics"],
  "host": "http://prometheus:9090",
  "extra_config": {
    "bearer_token": "optional-auth-token"
  }
}
```

## Authentication Options

Prometheus supports multiple authentication methods depending on your deployment:

- **No Auth**: Many Prometheus deployments run without authentication behind a VPN or network policy. Simply omit credentials.
- **Basic Auth**: Provide `username` and `password` at the top level for deployments using a reverse proxy with basic auth.
- **Bearer Token**: Provide `bearer_token` in `extra_config` for token-based authentication.

## Extra Configuration

| Field | Type | Description |
|-------|------|-------------|
| `bearer_token` | string | Bearer token for authentication |

## Kubernetes setup

Set the integration's `topology_mode` to `kubernetes` (Integrations → your Prometheus integration → Topology Mode, or `PATCH` the API) to switch SerOps from node-level PromQL to container-level metrics aggregated by service:

| Query | VM mode | Kubernetes mode |
|-------|---------|-----------------|
| CPU | `node_cpu_seconds_total{...}` | `sum by (service_name) (rate(container_cpu_usage_seconds_total{...}[5m]))` |
| Memory total | `node_memory_MemTotal_bytes{...}` | `sum by (service_name) (container_spec_memory_limit_bytes{...} > 0)` |
| Memory free | `node_memory_MemFree_bytes{...}` | `sum by (service_name) (clamp_min(container_spec_memory_limit_bytes{...} - container_memory_working_set_bytes{...}, 0))` |

!!! info "Services with no memory limit report no total"
    `container_spec_memory_limit_bytes` is `0` for a container with no
    memory limit, which is the majority of real workloads — requests are
    common, limits are not. The `> 0` filter means such services are
    **absent** from the memory-total series rather than reported as having
    zero memory, and `clamp_min` keeps free memory from going negative.
    If a service you expect is missing from memory charts, it has no
    memory limit set; add one, or read its usage from
    `container_memory_working_set_bytes` directly.

**Prerequisites**: your Prometheus must scrape cAdvisor / kubelet metrics
(standard in `kube-prometheus-stack`) AND have a `service_name` label on the
**container metrics themselves**. That second part is the one people get
wrong, so read the next warning before copying anything.

!!! danger "`service_name` must be attached to the cAdvisor job, not the pods job"
    `container_cpu_usage_seconds_total` and `container_memory_*` are
    produced by **cAdvisor**, scraped through the kubelet. They are *not*
    produced by the job that scrapes your pods' own `/metrics` endpoints.

    So relabeling on a `role: pod` job does nothing for them: cAdvisor
    samples arrive carrying only `namespace`, `pod` and `container`, and
    `sum by (service_name)` then collapses everything into a **single
    series with an empty `service_name`** — which looks exactly like
    "node-level metrics" and is the most common cause of
    "my Kubernetes metrics aren't per-service".

    The fix is `metric_relabel_configs` on the cAdvisor job.
    `relabel_configs` act on the *target* (one per node, which knows
    nothing about pods); `metric_relabel_configs` act on each *sample*,
    after cAdvisor has already labelled it.

    Verify in one query — it must return one series per service, not one
    series total:

    ```promql
    sum by (service_name) (rate(container_cpu_usage_seconds_total{container!=""}[5m]))
    ```

### Raw Prometheus config

Validated end-to-end on Kubernetes 1.31 / containerd:

```yaml
scrape_configs:
  # Your application pods' own /metrics endpoints.
  - job_name: 'kubernetes-pods'
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      # Fallback first, canonical `app` second — the last rule to write
      # wins, and `regex: (.+)` stops an absent label from blanking the
      # value the previous rule set.
      - source_labels: [__meta_kubernetes_pod_label_app_kubernetes_io_name]
        regex: (.+)
        target_label: service_name
      - source_labels: [__meta_kubernetes_pod_label_app]
        regex: (.+)
        target_label: service_name
      - source_labels: [__meta_kubernetes_namespace]
        target_label: environment
      - target_label: organisation_name
        replacement: <YOUR-ORG>
      - target_label: project_name
        replacement: <YOUR-PROJECT>
      # Keep only pods you want scraped (add pod annotations to opt in).
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true

  # cAdvisor — this is where container_cpu_* / container_memory_* come from.
  - job_name: 'kubernetes-cadvisor'
    scheme: https
    tls_config:
      ca_file: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
    bearer_token_file: /var/run/secrets/kubernetes.io/serviceaccount/token
    kubernetes_sd_configs:
      - role: node
    relabel_configs:
      - action: labelmap
        regex: __meta_kubernetes_node_label_(.+)
      - target_label: __address__
        replacement: kubernetes.default.svc:443
      - source_labels: [__meta_kubernetes_node_name]
        regex: (.+)
        target_label: __metrics_path__
        replacement: /api/v1/nodes/${1}/proxy/metrics/cadvisor
    # THIS is what makes `sum by (service_name)` work.
    metric_relabel_configs:
      - source_labels: [container]
        regex: (.+)
        target_label: service_name
      - source_labels: [namespace]
        regex: (.+)
        target_label: environment
      - target_label: organisation_name
        replacement: <YOUR-ORG>
      - target_label: project_name
        replacement: <YOUR-PROJECT>
```

This maps the **container name** to `service_name`, which is correct when
your container name matches your service name — the usual case. If they
differ, or you run sidecars you want folded into the parent service, join
against `kube_pod_labels` from
[kube-state-metrics](https://github.com/kubernetes/kube-state-metrics)
with a recording rule instead, and have it emit `service_name`.

### With kube-prometheus-stack

The chart manages the kubelet/cAdvisor scrape job for you, so set the same
sample-level relabeling through its values rather than writing the job
yourself. Note the field names are **camelCase** here, not snake_case —
see the warning below:

```yaml
kubelet:
  serviceMonitor:
    cAdvisorMetricRelabelings:
      - sourceLabels: [container]
        regex: (.+)
        targetLabel: service_name
      - sourceLabels: [namespace]
        regex: (.+)
        targetLabel: environment
      - targetLabel: organisation_name
        replacement: <YOUR-ORG>
      - targetLabel: project_name
        replacement: <YOUR-PROJECT>
```

!!! danger "camelCase here, snake_case in raw Prometheus config"
    These values become a `ServiceMonitor` custom resource, and the
    Prometheus Operator CRD spells the fields `sourceLabels` and
    `targetLabel`. Raw Prometheus config uses `source_labels` and
    `target_label`. The two are not interchangeable, and getting it wrong
    fails in the worst possible way:

    Kubernetes **silently discards** the unknown snake_case keys, leaving
    `action: replace` with no target. The operator then rejects the entire
    kubelet ServiceMonitor, so you lose **every** container metric — not
    just `service_name`. Prometheus simply has no `kubelet` job, with no
    error in Prometheus itself.

    The rejection is only visible in the operator's log:

    ```bash
    kubectl logs -n monitoring -l app=kube-prometheus-stack-operator \
      | grep -i 'rejected due to invalid configuration'
    ```

    Expected output when correct: nothing. When wrong you get
    `metricRelabelConfigs: [0]: relabel configuration for replace action
    needs targetLabel value`.

    Confirm the job exists and container metrics carry the label:

    ```bash
    # must be non-zero
    curl -s 'http://<prometheus>/api/v1/query?query=count(container_cpu_usage_seconds_total{service_name!=""})'
    ```

**Verify with the ingest validator**:

```bash
docker compose exec backend python manage.py check_ingest --integration <ID>
```

The report shows what tags SerOps sees in your host discovery — flags any missing `service_name` / `organisation_name` / `project_name`.

## Health Check

```
POST /api/integrations/observability/{id}/health-check/
```

Response:
```json
{
  "integrations": [
    {
      "provider": "PrometheusMetricProvider",
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
