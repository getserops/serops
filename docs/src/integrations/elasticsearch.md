---
seo_title: "Elasticsearch: AI root cause analysis on your logs"
description: "Connect Elasticsearch to SerOps as a log provider: authentication, index patterns, field mapping and troubleshooting."
---
# Elasticsearch

Elasticsearch is a distributed search and analytics engine used as a log provider in SerOps. It supports full-text search, regex queries, aggregations, and document indexing via the Elasticsearch DSL query language.

| | |
|---|---|
| **Type** | Logs |
| **Auth** | Basic / API Key |
| **Query Language** | ES DSL |

## Prerequisites

- Elasticsearch 7.17 or later (tested: 7.17.25, 8.15.3 — see [Compatibility](compatibility.md))
- Network access from the SerOps backend to the Elasticsearch cluster
- A user or API key with read permissions on the target indices

## Configuration

### Basic Authentication

```json
{
  "provider": "elasticsearch",
  "display_name": "Production ES Cluster",
  "capabilities": ["logs"],
  "host": "https://es.corp.example.com:9200",
  "username": "serops",
  "password": "secure_password"
}
```

### API Key Authentication

```json
{
  "provider": "elasticsearch",
  "display_name": "ES Cloud",
  "capabilities": ["logs"],
  "host": "https://my-cluster.es.cloud.com:9243",
  "extra_config": {
    "api_key": "base64-encoded-api-key"
  }
}
```

## Authentication Options

Elasticsearch supports two authentication methods:

- **Basic Auth**: Provide `username` and `password` at the top level of the configuration.
- **API Key**: Provide a base64-encoded API key in `extra_config.api_key`. When an API key is present, it takes precedence over basic auth credentials.

## Extra Configuration

| Field | Type | Description |
|-------|------|-------------|
| `api_key` | string | Base64-encoded Elasticsearch API key for authentication |
| `index_pattern` | string | Indices or data streams to search, comma-separated (e.g. `logs-*, filebeat-*`). See [Where SerOps looks for logs](#where-serops-looks-for-logs) |

## Where SerOps looks for logs

Set **Index pattern** on the integration (`extra_config.index_pattern`) to the
indices or data streams that hold your logs, comma-separated, for example
`logs-*, filebeat-*`. Records are still filtered by their `project_name` and
`environment` fields, so a broad pattern is safe.

Left empty, SerOps searches:

1. indices named the SerOps way, if any exist: `application-logs-<project>*`,
   `serops-*-<project>*`, `serops-application-<organisation>*`;
2. otherwise the shippers' default patterns that hold data: `logs-*`
   (Elastic Agent, the OpenTelemetry Collector), `filebeat-*` and `logstash-*`.

Records shaped by Filebeat, Elastic Agent or the OpenTelemetry Collector
(Elastic Common Schema: `log.level`, `service.name`, `service.environment`)
are read as they are; see [field aliases](../how-to/configure-data-collection.md#alias-support-datadog-usm-opentelemetry-kubernetes).


## Health Check

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

## Recommended index template

SerOps filters logs by the canonical fields `organisation_name`, `project_name`, `service_name`, `environment`, and `log_level`. On indices created without an explicit mapping, Elasticsearch dynamic-maps these as `text` and tokenises values (so `"acme-checkout"` is indexed as `["acme", "checkout"]`), which makes exact-match filters return zero results.

SerOps' adapter emits both the plain field and the `.keyword` sub-field for each filter, so dynamic-mapped indices work out of the box. For strict environments where you disable dynamic sub-fields, apply this component template before creating your log indices:

```json
PUT _component_template/serops-logs-mappings
{
  "template": {
    "mappings": {
      "properties": {
        "organisation_name": { "type": "keyword" },
        "project_name":      { "type": "keyword" },
        "service_name":      { "type": "keyword" },
        "environment":       { "type": "keyword" },
        "log_level":         { "type": "keyword" },
        "message":           { "type": "text" },
        "@timestamp":        { "type": "date" }
      }
    }
  }
}

PUT _index_template/serops-logs
{
  "index_patterns": ["logs-*"],
  "composed_of":   ["serops-logs-mappings"],
  "priority": 200
}
```

Ingest documents with these canonical field names to enable dashboard filtering, correlation, and dedup.

## Kubernetes setup

The [Fluentd config](../how-to/configure-data-collection.md) elsewhere in these
docs is written for VMs: it tags each source and adds `service_name` with one
filter per service. That does not scale on Kubernetes, where pods come and go
and the service is already named in the pod's labels — you want the shipper to
derive the field, not a hand-written filter per workload.

This Fluent Bit configuration is validated end-to-end on Kubernetes 1.31 /
containerd against Elasticsearch 8.15, and produces all five canonical fields:

```yaml
[INPUT]
    Name              tail
    Tag               kube.*
    Path              /var/log/containers/*.log
    multiline.parser  cri
    Mem_Buf_Limit     16MB
    Skip_Long_Lines   On

# Labels On is REQUIRED — service_name is derived from pod labels below.
[FILTER]
    Name                kubernetes
    Match               kube.*
    Kube_Tag_Prefix     kube.var.log.containers.
    Merge_Log           Off
    Keep_Log            On
    Labels              On

# Your own org and project — these are constants, like the Loki recipe.
[FILTER]
    Name    modify
    Match   kube.*
    Set     organisation_name <YOUR-ORG>
    Set     project_name      <YOUR-PROJECT>

[FILTER]
    Name    lua
    Match   kube.*
    script  /fluent-bit/scripts/serops.lua
    call    set_canonical

[OUTPUT]
    Name               es
    Match              kube.*
    Host               elasticsearch.observability.svc.cluster.local
    Port               9200
    Index              logs-serops
    Suppress_Type_Name On
    Time_Key           @timestamp
    Generate_ID        On
    # Pod labels contain dots (app.kubernetes.io/name). Without this, ES
    # rejects the document on mappings that disallow dots in field names.
    Replace_Dots       On
```

And the Lua script it references:

```lua
local LEVELS = { "CRITICAL", "FATAL", "ERROR", "WARNING", "WARN", "DEBUG", "TRACE", "INFO" }

local function canonical_level(raw)
  if raw == "CRIT" or raw == "FATAL" or raw == "CRITICAL" then return "ERROR" end
  if raw == "ERR"  or raw == "ERROR" then return "ERROR" end
  if raw == "WARN" or raw == "WARNING" then return "WARN" end
  if raw == "TRACE" or raw == "DEBUG" then return "DEBUG" end
  return "INFO"
end

function set_canonical(tag, timestamp, record)
  local k = record["kubernetes"] or {}
  local labels = k["labels"] or {}

  -- `app` first, then app.kubernetes.io/name, then the container name.
  local svc = labels["app"]
  if svc == nil or svc == "" then svc = labels["app_kubernetes_io/name"] end
  if svc == nil or svc == "" then svc = labels["app.kubernetes.io/name"] end
  if svc == nil or svc == "" then svc = k["container_name"] end
  record["service_name"] = svc

  record["environment"] = k["namespace_name"]

  -- SerOps reads `message`; the CRI parser produces `log`.
  local msg = record["log"] or record["message"] or ""
  record["message"] = msg

  local head = string.upper(string.sub(msg, 1, 200))
  local found = nil
  for _, lvl in ipairs(LEVELS) do
    if string.find(head, lvl, 1, true) then found = lvl break end
  end
  record["log_level"] = canonical_level(found)

  return 2, timestamp, record
end
```

!!! note "Why `log_level` is parsed, not labelled"
    Severity changes on almost every line, so it does not belong in pod
    labels. The script reads it from the text instead, scanning only the first
    200 characters — the same window the backend uses — so the word "error"
    inside a stack trace cannot promote an otherwise-INFO line.

!!! warning "`service_name` falls back to the container name"
    The last fallback means every pod gets a `service_name`, including
    cluster components that carry no `app` label (CoreDNS uses `k8s-app`).
    That reads as 100% coverage in `check_ingest`. If you would rather see an
    honest gap for unlabelled workloads, drop the `container_name` fallback —
    then only pods you have actually labelled are attributed.

**Verify with the ingest validator**:

```bash
kubectl exec -n serops deploy/serops-backend -- \
  python manage.py check_ingest --integration <ID>
```

All five fields should report `ok`. Anything missing points at the filter
that should have set it, in the order above.

### Docker runtime

The Fluent Bit configuration above is written for containerd. On nodes
that use the Docker runtime (cri-dockerd, minikube's default driver), log
files are Docker JSON; let the tail input try that parser first:

```ini
[INPUT]
    Name              tail
    Tag               kube.*
    Path              /var/log/containers/*.log
    multiline.parser  docker, cri
```

The same applies when shipping to OpenSearch or to Splunk through HEC.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Connection refused" | Verify `host` URL is reachable from SerOps backend |
| "401 Unauthorized" | Check `username`/`password` or `api_key` are correct |
| "SSL certificate error" | Ensure the cluster certificate is trusted, or set `verify_certs: false` in `extra_config` (not recommended for production) |
| "No data returned" | Verify the time range has data; check that `capabilities` includes `"logs"`; set **Index pattern** if your logs are not in `logs-*`, `filebeat-*`, `logstash-*` or SerOps-named indices |
| Filters return 0 hits on a fresh index | Apply the recommended index template above — or upgrade to a SerOps build ≥ `ce1f9aa` (Sept 2026) whose adapter auto-uses `.keyword` sub-fields |

## Related Pages

- [Observability Overview](observability-overview.md)
- [API Reference](../api/observability.md)
