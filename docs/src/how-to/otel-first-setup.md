# Setting up SerOps for OTEL-forward stacks

SerOps is **log-centric by design**. The onboarding wizard requires at
least one observability integration with the `logs` capability before
step 3 (Connect Observability) can complete. If you're running an
OTEL-forward stack — OTLP traces to SerOps, Prometheus for metrics,
no dedicated log store — you'll hit this early:

> `connect_observability` — Not Complete
> Waiting for at least one active log source (Loki, Elasticsearch,
> Datadog, CloudWatch, etc.)

This page explains why that gate exists, and the two clean ways to get
past it.

## Why SerOps needs logs

The RCA pipeline builds its narrative from the source that carries the
richest human-readable context — the ERROR / WARNING log line an
application shipped with its exception. Traces and metrics tell you
*where* and *when*; logs tell you *what happened, in the developer's
own words*. Without at least one log source, the AI is reasoning
about span error names and metric anomalies with no natural-language
description of the failure, and the RCA quality drops sharply.

Logs are also what most self-hosters already have. Making the whole
product optional-on-logs would let onboarding complete on a stack that
produces a much worse experience — we'd rather block the wizard now
than give you a bad first RCA.

## Option 1 — Bridge OTEL logs into Loki (recommended)

The OpenTelemetry Collector ships a Loki exporter. If you already run
the OTel Collector for traces + metrics, adding logs is one exporter
block. Loki runs anywhere; add it to the same compose file that runs
your Collector.

```yaml
# collector-config.yaml
exporters:
  otlphttp:
    endpoint: https://serops.example.com/api/traces
    headers:
      Authorization: Bearer ${SEROPS_INGEST_KEY}

  loki:
    endpoint: http://loki:3100/loki/api/v1/push
    default_labels_enabled:
      exporter: false
      job: true

  prometheusremotewrite:
    endpoint: http://mimir:9009/api/v1/push

service:
  pipelines:
    logs:
      receivers: [otlp]
      processors: [batch]
      exporters: [loki]

    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlphttp]

    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [prometheusremotewrite]
```

Then in SerOps → Settings → Global Integrations → Add Observability:

- **Provider**: Grafana Loki
- **URL**: `http://loki:3100`
- **Capabilities**: ✅ logs
- **Labels**: leave the defaults — SerOps' Loki adapter maps the OTel
  resource attributes automatically.

Once saved, the onboarding wizard's `connect_observability` step turns
green and you can proceed.

## Option 2 — Bridge OTEL logs into Elasticsearch

Same pattern via the Collector's `elasticsearch` exporter:

```yaml
exporters:
  elasticsearch:
    endpoints: [https://elastic:9200]
    index: logs-otel
    tls:
      insecure: false
```

Then wire an Elasticsearch integration in SerOps with the `logs`
capability. The default field mappings work — SerOps' ES adapter
recognises OTel's `resource.attributes.service.name` alongside
Datadog USM and Kubernetes labels.

## What NOT to do

**Don't** flip the demo user off, hand-edit the DB, or treat "waiting
on connect_observability" as the definition of "ready to use SerOps".
Those workarounds get past the wizard but leave you with a pipeline
that can't produce a useful RCA for your workload.

**Don't** rely on trace spans as a substitute for logs. OTel span
events *can* carry structured payloads, and SerOps' correlation
engine will surface `span_error_to_log_error` matches when both
exist — but the RCA prompt still fundamentally reads log content
first. A traces-only setup produces valid analyses but they're
weaker than the equivalent log+trace analyses.

## Long-term direction

Making SerOps first-class for OTEL-forward stacks means teaching the
RCA prompt to reason from span events alone when logs are absent, and
adjusting the correlation engine to elevate trace evidence when logs
are empty. That's on the roadmap for post-v1.0. Until then, the
Loki-bridge or ES-bridge above is the recommended path — both are
one exporter block, both give you the full RCA quality SerOps was
designed for.
