---
seo_title: "Splunk: AI root cause analysis on your logs"
description: "Connect Splunk Enterprise or Splunk Cloud to SerOps through the REST search API, with no SDK: tokens, SPL queries and troubleshooting."
---
# Splunk

Splunk Enterprise and Splunk Cloud both work as SerOps log providers. SerOps uses Splunk's REST search API (no Splunk SDK dependency), translates every query through the canonical `LogQuery` object into SPL, and normalises the results into the same `LogEntry` shape every other adapter returns.

| | |
|---|---|
| **Type** | Logs |
| **Auth** | Auth Token (bearer) |
| **Query Language** | SPL (Search Processing Language) |
| **Async Model** | REST search jobs (start → poll → results) |

## Prerequisites

- Splunk Enterprise 8.2 or later (tested: 8.2.12, 9.3.2), or Splunk Cloud (not yet tested) — see [Compatibility](compatibility.md)
- Network access from the SerOps backend to your Splunk management port (default `8089`)
- A **Splunk auth token** with search access — create one under **Settings → Tokens** and copy the token value (you only see it once)
- Optional: a dedicated search user + role so the token can be scoped to specific indexes / apps

## Configuration

In the UI: **Settings → Integrations → Log Providers → Add**, then pick the provider. The same fields through the API:

```json
{
  "provider": "splunk",
  "display_name": "Splunk · production",
  "capabilities": ["logs"],
  "host": "https://splunk.example.com:8089",
  "password": "eyJhbGciOi...your-splunk-auth-token...",
  "extra_config": {
    "index": "main",
    "app": "-",
    "owner": "-",
    "verify_ssl": true
  }
}
```

`verify_ssl` is **Verify TLS certificate** in the UI: turn it off only for a self-signed management port.

!!! warning "Password field is the auth token"
    Store the Splunk auth token in the `password` field, not the `username` field. It is encrypted at rest with Fernet (same treatment as every other credential) and used as `Authorization: Bearer <token>` on every API request.

## Authentication

Splunk supports two token types; use the **long-lived auth token** for headless integrations:

- **Auth Token** (recommended for SerOps): create under **Settings → Tokens** in Splunk. Long-lived, not tied to a session, easy to rotate. This is what the `password` field expects.
- **Session token**: interactive-login token. Short-lived. Not suitable here.

To rotate the token: create a new one in Splunk, update the `password` field on this integration (SerOps re-encrypts it), and delete the old one in Splunk.

## Extra Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `index` | string | `main` | Default Splunk index to search. Overridden per query. Must be a bareword (letters, digits, `-`, `_`) — invalid values are rejected to prevent SPL injection. |
| `app` | string | `-` | Splunk app context for the search namespace. `-` means any app. |
| `owner` | string | `-` | Splunk owner context. `-` means any owner. |
| `verify_ssl` | bool | `true` | Whether to verify the Splunk TLS certificate. Set to `false` only for lab / self-signed environments — never in production. |

## What SerOps does with your query

SerOps builds SPL by translating the canonical `LogQuery` object:

- Filters (`project`, `environment`, `service_name`, `severity`) become `field="value"` clauses
- Multi-value filters (`services: ["api", "worker"]`) become `service_name IN ("api", "worker")`
- Severity lists (`severity: ["ERROR", "WARNING"]`) become an OR-joined group
- Free-text search becomes a bare quoted phrase
- Time range is passed as `earliest_time` / `latest_time` params — **not** embedded in the SPL string (avoids lex-quoting timestamps and prevents time-based injection)

Every user-supplied value is escaped for the SPL string literal (both `\` and `"` are backslash-escaped). Values that reach a bareword position (like the index name) are validated against a strict character set and **rejected on any invalid character** — never silently rewritten. A silent rewrite could route a query to the wrong index, which is worse than failing loudly.

## Health Check

```
POST /api/integrations/observability/{id}/health-check/
```

Pings the Splunk `/services/data/indexes` endpoint — the cheapest authenticated call. A 200 response means both "the token is valid" and "the token has permission to read index metadata" (which every search user does).

Response:

```json
{
  "integrations": [
    {
      "provider": "SplunkLogProvider",
      "provider_type": "log",
      "healthy": true,
      "message": "OK"
    }
  ]
}
```

## Async Search Flow

Splunk search jobs are asynchronous. SerOps hides this from callers but the underlying steps are worth understanding for troubleshooting:

1. **Start** — `POST /servicesNS/{owner}/{app}/search/jobs` with the SPL. Splunk replies with a `sid` (search ID).
2. **Poll** — every 0.5s, `GET /jobs/{sid}` until `dispatchState=DONE`. Fails fast on `FAILED`, `USER_CANCEL`, `BAD_INPUT_CANCEL`, or if the job vanishes (404).
3. **Fetch** — `GET /jobs/{sid}/results?output_mode=json&count=N`. Results are normalised into canonical `LogEntry` objects.

Total budget: ~60 seconds. If a search doesn't complete in that window, SerOps abandons it and returns an empty list. For very large historical searches, run them from Splunk directly and let SerOps analyse the recent windows.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Connection refused" | Verify `host` URL and management port (default `8089`) are reachable from the SerOps backend |
| "401 Unauthorized" | Auth token expired or revoked. Create a new one in Splunk → Settings → Tokens and update `password` |
| "403 Forbidden" | Token is valid but lacks search or index-read capability. Check the role attached to the token's user |
| "Splunk job … ended in state=FAILED" | The SPL was rejected by Splunk. Check the token's app + owner context — the default `-` gives broad access; a scoped token might not see your target index |
| Silent empty results | The requested `index` doesn't exist for this token's user, or the `earliest_time` / `latest_time` window contains no matching events. Verify by running the same SPL directly in Splunk |
| "Invalid SPL token" (validation error) | The `index` field contains characters outside `[a-zA-Z0-9_-]`. Rename the index or fix the config |
| SSL certificate error | For a lab environment only, set `verify_ssl: false` in `extra_config`. Never do this in production |

## Related Pages

- [Observability Overview](observability-overview.md)
- [API Reference](../api/observability.md)
