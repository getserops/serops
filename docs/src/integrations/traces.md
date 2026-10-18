---
seo_title: "OpenTelemetry (OTLP) traces"
description: "Send OpenTelemetry traces to SerOps over OTLP/HTTP from any SDK, agent or collector; slow and failing spans feed the root cause."
---
# OpenTelemetry (OTLP) Traces

SerOps ingests distributed traces via the [OpenTelemetry Protocol
(OTLP)](https://opentelemetry.io/docs/specs/otlp/) over HTTP/JSON. Any
OTEL-compliant SDK, agent, or collector can point at your SerOps
tenant and start streaming spans — no vendor lock-in, no custom
instrumentation.

Traces are used to:

- Enrich AI Root Cause Analysis with the exact request path across
  services when an incident occurs.
- Correlate logs, metrics, and spans on a unified timeline in the
  Incident view.
- Pinpoint slow spans, high-error services, and cross-service latency
  in the Traces dashboard.

## 1. Create an Ingest Key

Ingest keys authenticate your OTEL Collector (or SDK) to SerOps.
They are org-scoped and follow the GitHub-style Personal Access Token
model — the plaintext is shown **once**, then only a fingerprint.

**UI:** *Settings → Distributed Traces → New Ingest Key.* The plaintext
is displayed in a modal with a one-click copy button; once dismissed
it cannot be retrieved. Revocations are soft-deletes (audit trail
preserved) — revoked keys immediately start returning 401 to any
collector still using them.

**API:**

```bash
curl -X POST https://your-serops-host/api/traces/keys/ \
  -H "Authorization: Token $SEROPS_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"prod-otel-collector"}'
```

Response (only time you see `plaintext`):

```json
{
  "id": 42,
  "name": "prod-otel-collector",
  "key_prefix": "serops_otlp_kJ",
  "is_active": true,
  "plaintext": "serops_otlp_kJ8xR...c2Q",
  "message": "Copy this key now — SerOps will never show it again."
}
```

Store it in a secret manager (Vault, AWS Secrets Manager, Kubernetes
Secret). If leaked, revoke it from the UI and issue a new one —
soft-delete keeps the audit trail.

## 2. Point Your Collector

The receiver endpoint is:

```
POST https://your-serops-host/api/traces/v1/traces
Authorization: Bearer serops_otlp_...
Content-Type: application/json
```

### OpenTelemetry Collector (recommended)

Add a SerOps `otlphttp` exporter to your collector config:

```yaml
exporters:
  otlphttp/serops:
    endpoint: https://your-serops-host/api/traces
    headers:
      Authorization: "Bearer ${env:SEROPS_INGEST_KEY}"

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlphttp/serops]
```

Set `SEROPS_INGEST_KEY` from your secret store; never commit it to
Git.

### Direct from SDK (Node.js example)

```javascript
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';

const exporter = new OTLPTraceExporter({
  url: 'https://your-serops-host/api/traces/v1/traces',
  headers: { Authorization: `Bearer ${process.env.SEROPS_INGEST_KEY}` },
});
```

Most production deployments use a collector between the SDKs and
SerOps for batching, retry, and multi-backend fan-out. Direct-from-SDK
is fine for early testing.

## 3. Verify Ingest

Once your collector is sending, go to **Settings → Distributed Traces** and click **View received
traces** (or press ⌘K / Ctrl K and type "traces"). The page lists the most recent traces with filters
for service, status (OK / ERROR / UNSET), minimum duration, and time
window. Click any row to open the trace detail view — a proportional
span waterfall with an attribute + events inspector.

You can also verify by inspecting the ingest key's `last_used_at`:

```bash
curl https://your-serops-host/api/traces/keys/ \
  -H "Authorization: Token $SEROPS_ADMIN_TOKEN"
```

## Field Aliases

SerOps auto-detects the service name from any of the following
resource attributes, in this order:

- `service.name` (OTEL semantic convention — preferred)
- `service` (Datadog USM)
- `app` (Kubernetes label convention)

Environment is auto-detected from `deployment.environment`,
`env`, or `environment`. If none are present, spans fall back to
`unknown`.

## Rate Limits

The OTLP receiver is throttled at **3000 requests/minute per client
IP**. This is per-collector, not per-span — a batch of 500 spans is
one request. Bump the `otlp_ingest` scope in `DEFAULT_THROTTLE_RATES`
(backend `api/settings.py`) if you run multiple collectors behind
NAT.

## Retention

Traces follow the same tenant retention policy as logs and metrics
(configurable in Settings → Data Management). Sampled-out spans at the
SDK level never reach SerOps, so head-based sampling is the standard
knob for controlling volume.

## Troubleshooting

**401 Unauthorized** — the ingest key is missing, expired, or belongs
to a different tenant. Recreate it under the correct org.

**429 Too Many Requests** — you exceeded the `otlp_ingest` rate
limit. Batch more aggressively in the collector (`batch` processor
with `send_batch_size: 512`) or raise the ceiling.

**200 OK but no spans in the UI** — check the response body for
`accepted_spans`. If it's 0, your payload had malformed span IDs or
trace IDs. OTLP requires 32-hex-char trace IDs and 16-hex-char span
IDs.

## Alternative: pull from Jaeger / Zipkin / Datadog APM

If you already ship traces to Jaeger, Zipkin, or Datadog APM and don't
want to change your pipeline, SerOps can **pull** traces from them at
RCA time instead of receiving them via OTLP. Configure a trace
provider under *Integrations*:

| Provider       | Host / endpoint                        | Auth                       |
|----------------|----------------------------------------|----------------------------|
| Grafana Tempo  | `http://tempo:3200`                    | Optional basic / bearer + `X-Scope-OrgID` via `extra_config.tenant_id` |
| Jaeger         | `http://jaeger-query:16686`            | Optional basic / bearer    |
| Zipkin         | `http://zipkin:9411`                   | Optional basic / bearer    |
| Datadog APM    | (uses site + API + APP keys)           | `extra_config.api_key`, `extra_config.app_key` |

**Grafana Tempo:** Same `X-Scope-OrgID` tenant model as Loki + Mimir,
so if you're already on the LGTM stack you can reuse the tenant IDs
your existing SerOps Loki/Mimir integrations use. Tempo returns
spans in OTLP JSON format, so IDs from Tempo-pulled traces match
IDs from spans SerOps received directly via OTLP — no dedup work
needed if you happen to feed both.

Set the integration's `capabilities` to include `"traces"`. During
incident analysis, SerOps prefers the native OTLP store; if no OTLP
spans exist for the incident window, it falls back to the pull adapter
and enriches the RCA prompt with the top-slow and top-error spans it
finds.

Pull adapters are **read-only**. Nothing is pushed to the trace
backend, and no state is stored in SerOps beyond the transient
summary in the AI prompt for that one analysis.

## What the AI sees

When traces are available, the RCA prompt gains a compact
`Distributed Traces` section:

```
Distributed Traces:
-------------
Source: otlp  Traces: 4  Spans: 27  Errors: 3
Services in window: api, checkout, db-proxy

Top 5 slowest spans:
  [1240ms] checkout :: POST /checkout (trace a1b2c3d4e5f6...)
  ...

Top 5 error spans:
  db-proxy :: SELECT users — connection timeout (trace bbaa...)
  ...
```

The AI uses this to trace latency to its origin span and to link
errors across services — a step it can't reliably infer from logs
alone.
