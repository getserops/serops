# Self-metrics (`/metrics/`)

SerOps exposes its own operational metrics in **Prometheus text
format** so on-call SREs can scrape it with their own Prometheus /
VictoriaMetrics / Grafana Agent — standard SRE table-stakes.

## Endpoint

```
GET /metrics/
Content-Type: text/plain; version=0.0.4
```

No auth by default (safe when scraped from a private network).
Enable basic-auth via env:

```bash
export SEROPS_METRICS_BASIC_AUTH="scraper:$(openssl rand -hex 24)"
```

Prometheus scrape config:

```yaml
scrape_configs:
  - job_name: serops
    metrics_path: /metrics/
    static_configs:
      - targets: ['serops.internal:8000']
    # If SEROPS_METRICS_BASIC_AUTH is set:
    basic_auth:
      username: scraper
      password: <the-hex-you-generated>
```

## Metrics exposed

| Metric | Type | Labels | What it measures |
|---|---|---|---|
| `serops_up` | Gauge | — | 1 while the process serves traffic. Liveness. |
| `serops_batch_created_total` | Counter | `outcome=created|skipped` | Batches produced by the scheduler / on-demand pipeline. |
| `serops_batch_analyzed_total` | Counter | `provider`, `outcome` | AI analysis attempts per provider. |
| `serops_ai_tokens_total` | Counter | `provider`, `direction=input|output` | Token consumption (cost signal). |
| `serops_alert_received_total` | Counter | `source`, `outcome=accepted|deduplicated|rejected` | Alert webhook ingestion (Alertmanager / Grafana / Datadog). |
| `serops_otlp_spans_received_total` | Counter | — | Spans persisted via the OTLP receiver. |
| `serops_http_requests_total` | Counter | `method`, `endpoint_group`, `status_class=2xx|3xx|4xx|5xx` | Request throughput by bucketed endpoint. |

### On cardinality

`endpoint_group` is deliberately bucketed — every `/api/data/batches/<id>/`
collapses to `data_batch_detail`, all analytics collapse to
`data_analytics`, and so on. Total cardinality stays under ~50
series. **No user IDs, org IDs, or trace IDs are exposed as labels**
— that would explode cardinality and leak tenant identity to
whoever scrapes the endpoint.

### On multi-worker deployments

SerOps runs gunicorn with N workers per pod. Each worker exposes its
own metric registry — the numbers you see are **per-worker**, not
per-pod. Aggregation happens naturally in Prometheus (rate / sum by
pod). If you need process-shared exposition (Prometheus
multi-process mode), file an issue — it's not enabled by default
because it's an extra deployment artefact.

## Suggested alerts

```yaml
# SerOps not serving.
- alert: SeropsDown
  expr: up{job="serops"} == 0
  for: 2m

# AI provider errors.
- alert: SeropsAiErrorsHigh
  expr: |
    sum(rate(serops_batch_analyzed_total{outcome="error"}[5m]))
    /
    sum(rate(serops_batch_analyzed_total[5m]))
    > 0.1
  for: 10m

# Alert webhook 5xx from SerOps itself.
- alert: SeropsAlertWebhookFailing
  expr: |
    sum by (endpoint_group) (
      rate(serops_http_requests_total{endpoint_group="alert_webhook",status_class="5xx"}[5m])
    ) > 0
  for: 5m
```
