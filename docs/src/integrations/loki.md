---
seo_title: "Grafana Loki: AI log analysis and root cause"
description: "Connect Grafana Loki to SerOps: LogQL queries, labels, multi-tenant setups and troubleshooting for AI root cause analysis."
---
# Grafana Loki

Grafana Loki is a horizontally scalable, highly available log aggregation system designed to be cost-effective and easy to operate. SerOps uses it as a log provider supporting full-text search, regex queries, live tail, and multi-tenant isolation via the LogQL query language.

| | |
|---|---|
| **Type** | Logs |
| **Auth** | Basic / Bearer / Tenant ID |
| **Query Language** | LogQL |

## Prerequisites

- Grafana Loki 2.x or later
- Network access from the SerOps backend to the Loki endpoint
- Valid credentials (basic auth or bearer token)
- Tenant ID if using multi-tenant mode

## Configuration

```json
{
  "provider": "loki",
  "display_name": "Grafana Cloud Loki",
  "capabilities": ["logs"],
  "host": "https://logs-prod.grafana.net",
  "username": "user-id",
  "extra_config": {
    "bearer_token": "glc_xxx",
    "tenant_id": "my-tenant"
  }
}
```

!!! tip "Multi-Tenant Loki"
    If your Loki instance uses multi-tenancy, set the `tenant_id` in `extra_config`. SerOps sends it via the `X-Scope-OrgID` header.

## Authentication Options

Loki supports multiple authentication methods:

- **Basic Auth**: Provide `username` and `password` at the top level. Common with Grafana Cloud where the username is your user ID and the password is a Grafana Cloud API key.
- **Bearer Token**: Provide `bearer_token` in `extra_config`. Useful for token-based authentication.
- **Tenant ID**: When `tenant_id` is set, SerOps includes the `X-Scope-OrgID` header on all requests to support multi-tenant deployments.

These can be combined (e.g., basic auth with a tenant ID).

## Extra Configuration

| Field | Type | Description |
|-------|------|-------------|
| `bearer_token` | string | Bearer token for authentication |
| `tenant_id` | string | Tenant ID for multi-tenant Loki; sent via `X-Scope-OrgID` header |

## Kubernetes setup

Loki has a subtle limitation compared to Elasticsearch / Datadog / CloudWatch: **stream selectors AND across labels and can't easily OR the same value against different label names.** That means SerOps' adapter-side aliasing (Datadog USM `service` → `service_name`, OpenTelemetry `service.name` → `service_name`, Kubernetes `app` → `service_name`) works for logs from ES / DD / CW / OpenSearch — but **NOT for Loki**. Loki users must tag with SerOps' canonical names directly.

Recommended Promtail scrape config for a Kubernetes cluster. This block is
validated end-to-end on Kubernetes 1.31 / containerd with Promtail 3.5 —
copy it whole, and read the two notes below it before changing anything:

```yaml
scrape_configs:
  - job_name: kubernetes-pods
    kubernetes_sd_configs:
      - role: pod
    pipeline_stages:
      - cri: {}
    relabel_configs:
      # service_name, in TWO rules. Order and `regex` both matter — see
      # "Why the service_name rules look like that" below.
      # Fallback first: pods labelled app.kubernetes.io/name.
      - source_labels: [__meta_kubernetes_pod_label_app_kubernetes_io_name]
        regex: (.+)
        target_label: service_name
      # Canonical `app` second, so it wins when a pod carries both.
      - source_labels: [__meta_kubernetes_pod_label_app]
        regex: (.+)
        target_label: service_name
      # Namespace → environment (adjust to your convention).
      - source_labels: [__meta_kubernetes_namespace]
        target_label: environment
      # Constant labels — replace with your actual org + project names.
      - target_label: organisation_name
        replacement: <YOUR-ORG>
      - target_label: project_name
        replacement: <YOUR-PROJECT>
      # Pod + container labels for drill-down.
      - source_labels: [__meta_kubernetes_pod_name]
        target_label: pod
      - source_labels: [__meta_kubernetes_pod_container_name]
        target_label: container
      # REQUIRED — Promtail tails nothing without it. See "__path__ is
      # not optional" below.
      - source_labels: [__meta_kubernetes_pod_uid, __meta_kubernetes_pod_container_name]
        separator: /
        target_label: __path__
        replacement: /var/log/pods/*$1/*.log
```

!!! danger "`__path__` is not optional"
    Kubernetes service discovery finds pods; it does not tell Promtail
    which *file* to read. Without the `__path__` relabel, Promtail
    discovers every target and then drops each one, logging
    `msg="no path for target"`. Its `/ready` endpoint returns `500`
    forever, the pod never becomes Ready, and **Loki receives nothing at
    all** — no error surfaces in SerOps, because no data ever arrives.

    Check it in one command:

    ```bash
    kubectl logs -n observability daemonset/promtail | grep "no path for target"
    ```

    Any output means `__path__` is missing or wrong.

!!! warning "Why the `service_name` rules look like that"
    A relabel rule with `action: replace` (the default) **writes an empty
    value when its source label is absent**, and Prometheus deletes a
    label that is set to empty. Two consequences:

    * Without `regex: (.+)` on each rule, the second rule wipes the
      `service_name` the first one just set. A pod labelled only
      `app: checkout` ends up with **no `service_name` at all** — and
      per the warning below, that means zero results in SerOps.
    * Order is reversed from what reads naturally. Relabel rules apply
      top to bottom and the last writer wins, so the **fallback goes
      first** and `app` second. Put `app` first and a pod carrying both
      labels resolves to its `app.kubernetes.io/name` value instead.

    Verify what actually landed, per service:

    ```bash
    curl -s "http://<loki>/loki/api/v1/label/service_name/values"
    ```

!!! warning "Alias limitation on Loki"
    If your Promtail config only sets `service` (Datadog USM style) or `app` (K8s convention) without also setting `service_name`, SerOps' LogQL queries will return zero results. Add the relabel step above to promote whichever label you have to `service_name`. Every other log provider handles this transparently — Loki is the exception because of how LogQL stream selectors work.

!!! note "`log_level` is deliberately not a label"
    The config above sets four of SerOps' five canonical fields. The fifth,
    `log_level`, is intentionally left out: severity changes on almost every
    line, and promoting it to a stream label would multiply Loki's label
    cardinality — the one thing Loki asks you not to do.

    SerOps reads severity out of the log line instead, recognising bare
    (`ERROR ...`), bracketed (`[ERROR]`), logfmt (`level=error`) and JSON
    (`"level":"error"`) forms. Only the first ~200 characters are scanned,
    so the level must appear in the line prefix — where every common
    format puts it — and the word "error" inside a message body will not
    mislabel an otherwise-INFO line.

    If you *do* already have a low-cardinality `log_level` or `level`
    label, SerOps prefers it over parsing the line.

**Verify with the ingest validator**:

```bash
docker compose exec backend python manage.py check_ingest --integration <ID>
```

The report shows whether Loki streams have `service_name` / `project_name` /
`environment` as labels. Note that `log_level` is reported from SerOps'
line parsing, not from a Loki label, so it reads as present even though the
config above never sets it.

## Health Check

```
POST /api/integrations/observability/{id}/health-check/
```

Response:
```json
{
  "integrations": [
    {
      "provider": "LokiLogProvider",
      "provider_type": "log",
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
| "Tenant not found" | Verify `tenant_id` in `extra_config` matches an existing tenant |
| "No data returned" | Verify the time range has data; check that `capabilities` includes `"logs"` |

## Related Pages

- [Observability Overview](observability-overview.md)
- [API Reference](../api/observability.md)
