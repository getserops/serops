---
seo_title: "Prometheus: correlate metrics with incidents"
description: "Connect Prometheus to SerOps so CPU, memory and Kubernetes state metrics are correlated with errors, deployments and code changes during analysis."
---
# Prometheus

Prometheus is an open-source monitoring and alerting toolkit designed for reliability and scalability. SerOps uses it as a metric provider, querying a fixed set of series via PromQL: CPU and memory per node and container, CPU throttling, kube-state-metrics and JVM garbage collection (each is described below). It runs no query of your own and does not read request-rate, error-rate or latency metrics; see [what SerOps reads](../user-guide/metrics.md#what-serops-reads).

| | |
|---|---|
| **Type** | Metrics |
| **Auth** | Basic / Bearer |
| **Query Language** | PromQL |

## Prerequisites

- Prometheus 2.x or 3.x (tested: 2.55.1, 3.1.0 — see [Compatibility](compatibility.md))
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

!!! warning "First: set Topology Mode to Kubernetes"
    A new Prometheus integration starts in VM mode, which reads node
    metrics (`node_*`). On a cluster that only has container metrics it
    reads nothing, while the health check says OK. Set **Topology Mode →
    Kubernetes** on the integration (or `PATCH` `topology_mode:
    kubernetes`) before anything else; since this release the health check
    also says so when it sees container metrics and no node metrics.

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
your container name matches your service name. Check it first: many charts
use a generic container name. Online Boutique names nearly every container
`server`, so this rule makes ten services one (found on a client install,
2026-11-16). Then take the workload name from the pod name instead (the rule
below, which also works for Deployments with a `container` label), or join
against `kube_pod_labels` from
[kube-state-metrics](https://github.com/kubernetes/kube-state-metrics)
with a recording rule and have it emit `service_name`.

```yaml
      # Deployment pods are <name>-<replicaset hash>-<suffix>
      - source_labels: [pod]
        regex: (.+)-[a-z0-9]{6,10}-[a-z0-9]{5}
        target_label: service_name
```

#### Docker runtime

With the Docker runtime (cri-dockerd, minikube's default driver), cAdvisor
reports pod-level series without a `container` label, so the
`container → service_name` rule above sets nothing. Derive the service from
the pod name of a Deployment instead (`name-<hash>-<suffix>`):

```yaml
      - source_labels: [container, pod]
        regex: ;(.+?)-[a-z0-9]{6,10}-[a-z0-9]{5}
        target_label: service_name
        replacement: $1
```

**Which series SerOps sums.** In Kubernetes mode SerOps reads only
container-level series (`container` set, not `POD`) under `/kubepods`. For a
service that has none, which is the Docker-runtime case above, it reads the
pod-level series instead (`container=""` with a `pod`). The QoS and root
cgroups (`/kubepods`, `/kubepods/burstable`) carry no pod and are never
summed, so fixed `organisation_name` / `project_name` labels on every sample
are safe: they no longer add node-wide figures to a service or to
"unlabelled containers".

### With kube-prometheus-stack

The chart manages the kubelet/cAdvisor scrape job for you, so set the same
sample-level relabeling through its values rather than writing the job
yourself. Note the field names are **camelCase** here, not snake_case —
see the warning below:

```yaml
kubelet:
  serviceMonitor:
    cAdvisorMetricRelabelings:
      # The workload (Deployment) name, from the pod name. Use
      # sourceLabels: [container] only when every container is named
      # after its service (see the note in "Raw Prometheus config").
      - sourceLabels: [pod]
        regex: (.+)-[a-z0-9]{6,10}-[a-z0-9]{5}
        targetLabel: service_name
      - sourceLabels: [namespace]
        regex: shop                     # the namespace your services run in
        targetLabel: environment
        replacement: production
      - targetLabel: organisation_name
        replacement: <YOUR-ORG>
      - sourceLabels: [namespace]
        regex: shop
        targetLabel: project_name
        replacement: <YOUR-PROJECT>
```

These are the values a client applied with
`helm upgrade kps prometheus-community/kube-prometheus-stack --reuse-values -f kps-relabel.yaml`
on GKE (2026-11-16); every service then had its own CPU and memory series.

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

### With Grafana Alloy

Alloy scrapes cAdvisor and kube-state-metrics itself and relabels each sample
with `prometheus.relabel`, the Alloy form of `metric_relabel_configs`. This is
the metrics part of a client's Alloy configuration (a DaemonSet in clustering
mode, remote-writing to Mimir), checked on GKE on 2026-11-16: every service had
its own CPU and memory series.

```hcl
discovery.kubernetes "nodes" {
  role = "node"
}

// cAdvisor through the API server's node proxy: Alloy's ServiceAccount needs
// `get` on `nodes/proxy`.
discovery.relabel "cadvisor" {
  targets = discovery.kubernetes.nodes.targets
  rule {
    target_label = "__address__"
    replacement  = "kubernetes.default.svc:443"
  }
  rule {
    source_labels = ["__meta_kubernetes_node_name"]
    regex         = "(.+)"
    target_label  = "__metrics_path__"
    replacement   = "/api/v1/nodes/$1/proxy/metrics/cadvisor"
  }
}

prometheus.scrape "cadvisor" {
  targets           = discovery.relabel.cadvisor.output
  scheme            = "https"
  bearer_token_file = "/var/run/secrets/kubernetes.io/serviceaccount/token"
  tls_config {
    insecure_skip_verify = true
  }
  clustering {
    enabled = true
  }
  forward_to = [prometheus.relabel.serops.receiver]
}

// kube-state-metrics (restarts, OOM kills, rollouts), labelled the same way.
prometheus.scrape "ksm" {
  targets    = [{"__address__" = "<kube-state-metrics-service>:8080"}]
  forward_to = [prometheus.relabel.serops.receiver]
}

// The SerOps labels, on every sample.
prometheus.relabel "serops" {
  rule {
    // `container` only when every container is named after its service;
    // otherwise take the workload from `pod`, as in the kube-prometheus-stack
    // values above.
    source_labels = ["container"]
    regex         = "(.+)"
    target_label  = "service_name"
  }
  rule {
    source_labels = ["namespace"]
    regex         = "ledger"            // the namespace your services run in
    target_label  = "environment"
    replacement   = "production"
  }
  rule {
    target_label = "organisation_name"
    replacement  = "<YOUR-ORG>"
  }
  rule {
    source_labels = ["namespace"]
    regex         = "ledger"
    target_label  = "project_name"
    replacement   = "<YOUR-PROJECT>"
  }
  forward_to = [prometheus.remote_write.default.receiver]
}

prometheus.remote_write "default" {
  endpoint {
    url = "http://<mimir-or-prometheus>/api/v1/push"
  }
}
```

The same labels then reach Mimir, VictoriaMetrics or a Prometheus with remote
write enabled; point the SerOps integration at that store.

**Verify with the ingest validator**:

```bash
# Docker Compose
docker compose exec backend python manage.py check_ingest --integration <ID>
# Kubernetes (Helm chart)
kubectl -n serops exec deploy/serops-backend -- python manage.py check_ingest --integration <ID>
```

The report shows what tags SerOps sees in your host discovery — flags any missing `service_name` / `organisation_name` / `project_name`.

### Metrics your applications push over OTLP

`prometheus.relabel` and `metric_relabel_configs` only label what Prometheus
or Alloy **scrape**. Metrics an application pushes over OTLP (for example the
OpenTelemetry Java agent, through an OpenTelemetry Collector, into Mimir or a
Prometheus with its OTLP receiver on) never pass through them, so they arrive
without `organisation_name`, `project_name`, `environment` and
`service_name`, and SerOps does not find them. The OTLP path turns
`service.name` into `job` only.

Add the labels in the collector, with the
[transform processor](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/processor/transformprocessor/README.md)
(OTTL statements in the `datapoint` and `resource` contexts):

```yaml
processors:
  transform/serops:
    error_mode: ignore
    metric_statements:
      - set(datapoint.attributes["service_name"], resource.attributes["service.name"])
      - set(datapoint.attributes["namespace"], resource.attributes["k8s.namespace.name"])
      - set(datapoint.attributes["organisation_name"], "<YOUR-ORG>") where resource.attributes["k8s.namespace.name"] == "ledger"
      - set(datapoint.attributes["project_name"], "<YOUR-PROJECT>") where resource.attributes["k8s.namespace.name"] == "ledger"
      - set(datapoint.attributes["environment"], "production") where resource.attributes["k8s.namespace.name"] == "ledger"

service:
  pipelines:
    metrics:
      processors: [transform/serops]   # add to the processors you already have
```

**Restart the collector after this change.** The labels apply only once the
collector runs the new configuration, and many Helm charts (the OpenTelemetry
demo's among them) do not restart the collector when only its configuration
changes. On Kubernetes: `kubectl -n <namespace> rollout restart
daemonset/<collector>` (or `deployment/<collector>`), then check that new
series carry `project_name`. Series written before the restart keep their old
labels.

The same statements in Grafana Alloy go in
[`otelcol.processor.transform`](https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.processor.transform/):

```alloy
otelcol.processor.transform "serops" {
  error_mode = "ignore"
  metric_statements {
    context    = "datapoint"
    statements = [
      `set(datapoint.attributes["service_name"], resource.attributes["service.name"])`,
      `set(datapoint.attributes["namespace"], resource.attributes["k8s.namespace.name"])`,
      `set(datapoint.attributes["organisation_name"], "<YOUR-ORG>") where resource.attributes["k8s.namespace.name"] == "ledger"`,
      `set(datapoint.attributes["project_name"], "<YOUR-PROJECT>") where resource.attributes["k8s.namespace.name"] == "ledger"`,
      `set(datapoint.attributes["environment"], "production") where resource.attributes["k8s.namespace.name"] == "ledger"`,
    ]
  }
  output {
    metrics = [otelcol.exporter.otlphttp.mimir.input]
  }
}
```

`k8s.namespace.name` is set by the collector's `k8sattributes` processor (the
`kubernetesAttributes` preset of the collector Helm chart). Replace `ledger`
with the namespace your services run in. Checked on 18 Nov 2026 with
OpenTelemetry Collector Contrib 0.140.0 and Alloy 1.11.3: a JVM histogram
pushed with `service.name=ad` and `k8s.namespace.name=ledger` reached
Prometheus 3.5 with all five labels.

### JVM garbage collection

When a store holds JVM garbage-collection metrics, SerOps reads, per service,
the share of wall time its worst JVM spent in garbage collection and its
collections per minute. It reads the first of these that answers:

| Metric | Exported by |
|--------|-------------|
| `jvm_gc_duration_seconds` | OpenTelemetry Java agent 2.x |
| `process_runtime_jvm_gc_duration_seconds`, `process_runtime_jvm_gc_duration_milliseconds` | older OpenTelemetry Java agents |
| `jvm_gc_collection_seconds` | Prometheus `simpleclient_hotspot` |
| `jvm_gc_pause_seconds` | Micrometer |

The figure includes pauses, plus concurrent collector phases where the agent
does not separate them; series labelled as concurrent (an action, collector
or cause label containing "concurrent") are left out. A JVM above **10 %**
is flagged to the AI. The default collector, G1, aims for about 8 % (the
`GCTimeRatio` default of 12, see the
[Java GC tuning guide](https://docs.oracle.com/en/java/javase/21/gctuning/garbage-first-garbage-collector-tuning.html)),
so a JVM past 10 % spends more time collecting than its collector is tuned
for. Under the threshold the analysis gets one line saying so; without JVM
metrics, nothing.

The series need the project's labels like any other. When they have none
(pushed over OTLP without the step above), SerOps also looks for them by the
project's namespace and service names, only when the series carry a
`namespace` label and the project declares a namespace (log rules or
deployments); otherwise they are not read.

**VictoriaMetrics:** the names above are the Prometheus-style ones. Metrics
sent to VictoriaMetrics' own OpenTelemetry endpoint keep their OpenTelemetry
names (`jvm.gc.duration_sum`), and SerOps does not find them. Send them with
the collector's `prometheusremotewrite` exporter, or start VictoriaMetrics
with `-opentelemetry.usePrometheusNaming`, which converts OpenTelemetry names
and labels to the Prometheus form
([VictoriaMetrics: OpenTelemetry](https://docs.victoriametrics.com/victoriametrics/integrations/opentelemetry/)).

### What Kubernetes did: kube-state-metrics

In Kubernetes mode SerOps also reads
[kube-state-metrics](https://github.com/kubernetes/kube-state-metrics)
(part of `kube-prometheus-stack`) for every analysis, and gives the AI what
logs and container metrics cannot show:

| Signal | From |
|--------|------|
| Restarts in the window, and why the container last stopped (`OOMKilled`, `Error`) | `kube_pod_container_status_restarts_total`, `kube_pod_container_status_last_terminated_reason` |
| Containers that cannot start (`ImagePullBackOff`, `CrashLoopBackOff`, `CreateContainerConfigError`, ...) | `kube_pod_container_status_waiting_reason` |
| Rollouts in the window and the 30 minutes before it, with the image, memory limit and CPU limit changes, or "image unchanged" for a configuration or environment change | `kube_deployment_metadata_generation` (StatefulSets and DaemonSets too), `kube_pod_container_info` |
| Scale changes (`replicas 1 -> 0`) | `kube_deployment_spec_replicas`, `kube_statefulset_replicas` |
| Deployments short of available replicas | `kube_deployment_status_replicas_available` |
| Rollouts not completing while the previous version still serves (rated WARNING, not an outage) | `kube_deployment_status_replicas_updated` |
| CPU throttling per service: share of time the kernel paused it for exceeding its CPU limit (25% or more) | cAdvisor `container_cpu_cfs_throttled_periods_total` / `container_cpu_cfs_periods_total` |

They appear on the analysis page under **Metrics**, and a restart, a
container that cannot start or a missing replica makes Sentinel analyse a
window that has no new error line.

Nothing to relabel: kube-state-metrics series keep their own `namespace`,
`pod` and `container` labels. SerOps finds the project's namespaces from its
cAdvisor series (the `namespace` label next to `project_name` /
`environment`), and falls back to a namespace named like the environment.
Names are reported per workload, from the pod name, so containers that are
all called `server` or `app` still read as `checkoutservice` or `payments`.

Check it is scraped:

```promql
count by (namespace) (kube_deployment_metadata_generation)
```

When kube-state-metrics is not there, these signals are simply missing from
the analysis.

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
