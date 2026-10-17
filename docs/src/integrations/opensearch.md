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

- OpenSearch 1.x or 2.x
- Network access from the SerOps backend to the OpenSearch cluster
- A user with read permissions on the target indices

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
    "verify_certs": false
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
docker compose exec backend python manage.py check_ingest --integration <ID>
```

See [Configure Data Collection](../how-to/configure-data-collection.md)
for shipper-specific configuration.

## Authentication Options

OpenSearch uses HTTP basic authentication. Provide `username` and `password` at the top level of the configuration.

## Extra Configuration

| Field | Type | Description |
|-------|------|-------------|
| `verify_certs` | bool | Whether to verify SSL certificates when connecting. Defaults to `false`. |

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
| "SSL certificate error" | Set `verify_certs: false` in `extra_config` (not recommended for production) |
| "No data returned" | Verify the time range has data; check that `capabilities` includes `"logs"` |
| Batches are empty | Documents are missing the [required fields](#required-log-fields). Run `check_ingest` to confirm what's actually indexed |

## Related Pages

- [Configure Data Collection](../how-to/configure-data-collection.md)
- [Observability Overview](observability-overview.md)
- [API Reference](../api/observability.md)
