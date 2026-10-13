# Traces API

Endpoints for OTLP trace ingestion, ingest-key management, and reading
stored traces.

Traces are a first-class analysis input: a span that is slow or failing
inside the batch window is cited by ID in the resulting root-cause
hypothesis, which lets the analysis name a database lock or an upstream
timeout instead of stopping at the surface symptom.

## Ingestion

### OTLP Receiver

```
POST /api/traces/v1/traces
```

Accepts OpenTelemetry trace data over HTTP. Point any OTLP-capable
exporter — the OpenTelemetry Collector, an SDK exporter, or a sidecar
— at this path.

| Aspect | Value |
|--------|-------|
| Content types | `application/json` and `application/x-protobuf` |
| Content encodings | `gzip` (the Collector default), `deflate`, or none |
| Auth | `Authorization: Bearer <ingest-key>` |
| Note | No trailing slash on this route |

!!! note "Compression is handled for you"
    The Collector's `otlphttp` exporter sets `compression: gzip` unless you
    override it, so the payload arrives compressed. SerOps decompresses
    `gzip` and `deflate` before parsing — you do not need
    `compression: none`.

    `zstd` is permitted by the OTLP spec but not supported here; it returns
    `415` naming the encoding, rather than looking like a malformed payload.

Example Collector config:

```yaml
exporters:
  otlphttp/serops:
    endpoint: https://serops.example.com/api/traces
    headers:
      Authorization: "Bearer serops_otlp_..."

service:
  pipelines:
    traces:
      exporters: [otlphttp/serops]
```

The exporter appends `/v1/traces` to the configured `endpoint`, so set
`endpoint` to the `/api/traces` prefix rather than the full path.

## Ingest Keys

Bearer tokens that authorise OTLP ingestion, scoped to one
organisation.

```
GET    /api/traces/keys/
POST   /api/traces/keys/
DELETE /api/traces/keys/{id}/
```

**Create request:**

```json
{
  "name": "prod k8s collector"
}
```

**Create response:**

```json
{
  "id": 4,
  "name": "prod k8s collector",
  "key_prefix": "serops_otlp_NUku3h",
  "is_active": true,
  "plaintext": "serops_otlp_NUku3hWkjA4YRsusm-pZAJWnA10M9RROhdAC1EKJjVE",
  "message": "Copy this key now — SerOps will never show it again."
}
```

!!! warning "The plaintext is returned exactly once"
    SerOps stores only a SHA-256 hash of the key plus a short prefix
    for identification. There is no endpoint that reveals a stored key
    — if it is lost, revoke it and issue a new one.

`DELETE` is a soft-delete: the key is marked inactive and stops
authenticating immediately, but the row is kept for the audit trail.

## Reading Traces

### List Traces

```
GET /api/traces/traces/
```

Paginated, organisation-scoped. Supports filtering by service, time
range, and error status.

### Trace Detail

```
GET /api/traces/traces/{trace_id}/
```

Returns the trace with all of its spans, including parent-child
relationships, durations, and status codes.

### List Services

```
GET /api/traces/traces/services/
```

Distinct service names seen in stored traces. Intended to populate
filter dropdowns without scanning the full span table.

---

## Related

- [Distributed Traces](../integrations/traces.md) -- Collector setup and supported backends
- [OTEL-First Setup](../how-to/otel-first-setup.md) -- Starting from OpenTelemetry rather than an existing stack
- [Batches](batches.md) -- How trace evidence reaches the analysis
- [API Overview](overview.md) -- Base URL, response format, and error codes
