---
seo_title: "OpenSearch: AI root cause analysis on your logs"
description: "Connect OpenSearch to SerOps as a log provider, including Amazon OpenSearch Service: authentication, indices and troubleshooting."
---
# OpenSearch

OpenSearch is an open-source search and analytics engine, fully compatible with the Elasticsearch DSL query language. SerOps uses it as a log provider supporting full-text search, regex queries, aggregations, and document indexing.

| | |
|---|---|
| **Type** | Logs |
| **Auth** | Basic (HTTP Auth) |
| **Query Language** | ES DSL |

## Prerequisites

- OpenSearch 1.3 or later (tested: 1.3.20, 2.17.1, 3.1.0 — see [Compatibility](compatibility.md))
- Network access from the SerOps backend to the OpenSearch cluster
- A user with read permissions on the log indices (`read` on `logs-*` or your own pattern).
  `cluster:monitor/health` is optional: without it the health check counts the log indices instead.
- The same user must also be able to write SerOps' own CI/CD index. SerOps stores the
  CI/CD events it receives (deploys, builds) in this cluster, in `serops-cicd-<organisation>`,
  and reads them back during an analysis. A read-only role on the log indices gets a 403
  there: the events are lost and analyses see no CI/CD deploys. Grant, on `serops-cicd-*`,
  the index permissions `read`, `index` and `create_index`, and the cluster permission
  `indices:data/write/bulk` (part of `cluster_composite_ops`; see
  [OpenSearch default action groups](https://docs.opensearch.org/latest/security/access-control/default-action-groups/)).

  ```json
  PUT _plugins/_security/api/roles/serops
  {
    "cluster_permissions": ["indices:data/write/bulk"],
    "index_permissions": [
      {"index_patterns": ["logs-*"], "allowed_actions": ["read"]},
      {"index_patterns": ["serops-cicd-*"], "allowed_actions": ["read", "index", "create_index"]}
    ]
  }
  ```

  Replace `logs-*` with your log index pattern (`ss4o_logs-*` for the Collector's default).

## Configuration

```json
{
  "provider": "opensearch",
  "display_name": "AWS OpenSearch",
  "capabilities": ["logs"],
  "host": "https://search-my-domain.us-east-1.es.amazonaws.com",
  "username": "admin",
  "password": "password",
  "extra_config": {
    "verify_certs": true
  }
}
```

## Required log fields

!!! warning "Untagged logs produce empty batches"
    SerOps finds your logs by querying OpenSearch for specific field
    values. If your documents don't carry them, every query matches
    zero documents and each batch comes back empty.

Your log shipper must index these fields on every document:

| Field | Example | Purpose |
|---|---|---|
| `organisation_name` | `acme-cloud` | Scopes logs to your organisation |
| `project_name` | `checkout-api` | Maps to a SerOps project |
| `service_name` | `checkout` | Maps to a service within the project |
| `environment` | `production` | The environment under analysis |
| `log_level` | `ERROR` | Severity, used by Sentinel triage |

Like Elasticsearch, OpenSearch benefits from SerOps' adapter-side
aliasing — OpenTelemetry's `service.name`, Datadog's `service` / `env`,
the Kubernetes `app` label, and `level` / `severity` / `status` for the
level field are all recognised automatically. You only need the
canonical names if you're starting from scratch.

Verify what actually landed:

```bash
# Docker Compose
docker compose exec backend python manage.py check_ingest --integration <ID>
# Kubernetes (Helm chart)
kubectl -n serops exec deploy/serops-backend -- python manage.py check_ingest --integration <ID>
```

See [Configure Data Collection](../how-to/configure-data-collection.md)
for shipper-specific configuration.

### OpenTelemetry Collector

The Collector's `opensearch` exporter writes the OpenSearch observability
shape (SS4O) by default: attributes under `attributes.*` and
`resource.*`, the text under `body`. SerOps reads top-level fields, so
it sees no service, environment or level in that shape. Two settings fix
it: `mapping.mode: flatten_attributes` puts the attributes at the top
level, and a `transform` processor sets the canonical fields, including
`message` (the body otherwise lands as `Body.value`).

```yaml
processors:
  transform/serops:
    log_statements:
      - context: log
        statements:
          - set(attributes["message"], body) where IsString(body)
          - set(attributes["organisation_name"], "acme-cloud")
          - set(attributes["project_name"], "checkout-api")
          - set(attributes["service_name"], resource.attributes["service.name"])
          - set(attributes["environment"], "production")
          # From the severity number: numeric levels (pino's 30, 50) stay
          # numbers in the severity text.
          - set(attributes["log_level"], "INFO") where severity_number >= 9 and severity_number < 13
          - set(attributes["log_level"], "WARNING") where severity_number >= 13 and severity_number < 17
          - set(attributes["log_level"], "ERROR") where severity_number >= 17
exporters:
  opensearch:
    http:
      endpoint: https://opensearch:9200
    mapping:
      mode: flatten_attributes
service:
  pipelines:
    logs:
      receivers: [filelog]
      processors: [transform/serops, batch]
      exporters: [opensearch]
```

The exporter writes to `ss4o_logs-<dataset>-<namespace>`: set the
integration's **Index pattern** to `ss4o_logs-*`. Tested with the
Collector contrib distribution on OpenSearch 2.17 (2026-11-16).

## Authentication Options

OpenSearch uses HTTP basic authentication. Provide `username` and `password` at the top level of the configuration.

## Extra Configuration

| Field | Type | Description |
|-------|------|-------------|
| `verify_certs` | bool | Whether to verify the TLS certificate when connecting. Defaults to `true` (it was `false` up to 1.4.0); set `false` only for a self-signed certificate you trust. |
| `index_pattern` | string | Indices to search, comma-separated (e.g. `logs-*`). Same rules as [Elasticsearch](elasticsearch.md#where-serops-looks-for-logs) |


## Health Check

```
POST /api/integrations/observability/{id}/health-check/
```

Response:
```json
{
  "integrations": [
    {
      "provider": "OpenSearchLogProvider",
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
| "401 Unauthorized" | Check `username` and `password` are correct |
| "403" on `serops-cicd-<organisation>` in the logs | The role cannot write or read SerOps' CI/CD index: add the `serops-cicd-*` permissions from [Prerequisites](#prerequisites) |
| "403" on the health check | The user may not read the log indices. Grant `read` on them; `cluster:monitor/health` is optional |
| Logs arrive but no service, environment or level | The Collector's default SS4O shape: see [OpenTelemetry Collector](#opentelemetry-collector) |
| "SSL certificate error" | Set `verify_certs: false` in `extra_config` (not recommended for production) |
| "No data returned" | Verify the time range has data; check that `capabilities` includes `"logs"`; set **Index pattern** if your logs are not in `logs-*`, `filebeat-*`, `logstash-*` or SerOps-named indices |
| Batches are empty | Documents are missing the [required fields](#required-log-fields). Run `check_ingest` to confirm what's actually indexed |

## Related Pages

- [Configure Data Collection](../how-to/configure-data-collection.md)
- [Observability Overview](observability-overview.md)
- [API Reference](../api/observability.md)
