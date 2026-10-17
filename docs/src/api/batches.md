---
seo_title: "Batches API"
description: "API endpoints to list, inspect, re-analyse and delete SerOps batches of logs, metrics and traces."
---
# Batches & Data API

Endpoints for listing, inspecting, re-analysing, and deleting log batches.

Batches represent collected log data from a specific time window. Each batch is associated with a project and environment, and carries the AI analysis produced for that window.

## List Batches

```
GET /api/data/batches
```

!!! note "No trailing slash"
    This route, along with `GET /api/data/metrics` and `POST /api/data/logs`, is registered without a trailing slash. Requesting `/api/data/batches/` will not match.

**Query parameters:**

| Parameter | Description |
|-----------|-------------|
| `limit` | Results per page (default: 5) |
| `offset` | Pagination offset |
| `with_analysis` | Include analysis payload (default: `true`) |
| `order_by` | Sort field (default: `-timestamp`) |
| `environment` | Filter by environment |
| `project` | Filter by project name |
| `cluster` | Filter by cluster ID |

## Get Batch Details

```
GET /api/data/batches/{batch_id}/
```

Returns full details for a single batch, including summary statistics, the primary AI analysis, and associated issues. Scoped to the caller's organisation.

This route is read-only. To remove batches, see [Delete Old Batches](#delete-old-batches).

## Re-analyse Batch

```
POST /api/data/batches/reanalyze/
```

**Request body:**

```json
{
  "batch_ids": ["batch-abc-123"],
  "model": "claude",
  "mode": "compare"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `batch_ids` | yes | One or more batch IDs to re-analyse |
| `model` | yes | Any active AI provider name (`claude`, `gemini`, `deepseek`, `openai`, `ollama`) |
| `mode` | no | `compare` (default) or `primary` — see below |

**The `mode` field decides what happens to the batch:**

| Mode | Effect |
|------|--------|
| `compare` | Appends the result to the batch's analysis history (up to 5 entries) for side-by-side model comparison. The primary analysis and the batch's issues are **left untouched**. |
| `primary` | Promotes the new result to the batch's primary analysis **and** refreshes its issues through fingerprint de-duplication, so existing triage state (acknowledged, resolved, muted) survives. |

Analysis runs asynchronously. The endpoint returns as soon as the work is queued:

```json
{
  "status": "queued",
  "message": "Comparison analysis queued for 1 batch(es) with model claude",
  "batch_ids": ["batch-abc-123"],
  "model": "claude",
  "mode": "compare"
}
```

Requires the `user` role or above. Viewers cannot trigger analysis.

## Promote an Analysis to Primary

```
POST /api/data/batches/{batch_id}/promote-analysis/
```

Takes an existing entry from the batch's analysis history and makes it the primary analysis. Runs synchronously — no AI call is made, since the analysis already exists.

**Request body:**

```json
{
  "analyzed_at": "2026-09-20T05:16:32.417Z"
}
```

`analyzed_at` must exactly match the timestamp of an entry returned by [Get Analysis History](#get-analysis-history). Any other value returns `404`.

**Response:**

```json
{
  "status": "promoted",
  "batch_id": "batch-abc-123",
  "analyzed_at": "2026-09-20T05:16:32.417Z",
  "issues_created": 2,
  "issues_updated": 1,
  "issue_count": 3
}
```

Promotion re-runs issue de-duplication against the promoted analysis, so issues whose fingerprint already exists are updated rather than recreated. Sibling history entries are demoted.

Requires the `user` role or above.

## Get Analysis History

```
GET /api/data/batches/{batch_id}/history/
```

Returns every AI analysis performed on this batch, including the model used, token counts, the `mode` it ran in, and whether it is the current primary.

## Get Metric Correlations

```
GET /api/data/batches/{batch_id}/correlations/
```

Returns metric correlations detected for the batch, showing which infrastructure metrics (CPU spikes, memory pressure, etc.) coincided with the issues found.

## Get Batch Timeline

```
GET /api/data/batches/{batch_id}/timeline/
```

Returns a chronological overlay of every data source in the batch window — logs, metric anomalies, deployments, CI/CD events, and trace spans — merged onto one time axis.

Paginated; the response carries `total_events` and `has_more` so large incidents can be walked in pages.

## Get Post-mortem Draft

```
GET /api/data/batches/{batch_id}/postmortem/
```

Generates a post-mortem draft from the batch's analysis: timeline, root cause, contributing factors, and remediation steps, ready to paste into an incident report.

## Delete Old Batches

```
DELETE /api/data/delete-old-batches/?days=30
```

Deletes every batch older than `days` (positive integer, default `30`) within the caller's organisation. Returns the number of deleted rows.

For automatic cleanup, configure a retention policy instead — see [Settings & Admin](settings.md).

## Ingest Logs

```
POST /api/data/logs
```

Direct log ingestion endpoint used by Fluentd-style shippers. Most deployments send logs to a provider (Elasticsearch, Loki, Datadog…) and let SerOps query it instead — see [Configure Data Collection](../how-to/configure-data-collection.md).

## Raw Metrics

```
GET /api/data/metrics
GET /api/data/cpu/raw/
```

Return raw node memory and CPU series for the caller's organisation.

---

## Investigations

Run an analysis now for one scope and time window. See
[Investigate](../user-guide/investigate.md).

```
POST /api/data/investigations/
```

Role `user` or `admin`. Returns `202` with the run, or `200` with the
existing run when the same request was made in the last 2 minutes.

```json
{
  "project_id": 7,
  "environment_id": 3,
  "deployment_id": null,
  "services": ["checkout"],
  "window_start": "2026-10-14T10:00:00Z",
  "window_end": "2026-10-14T10:30:00Z",
  "hint": "Checkout is slow for customers in Europe",
  "notify_routing": false
}
```

| Field | Rules |
|---|---|
| `project_id` | A project of your organisation. Required. |
| `environment_id`, `deployment_id` | Optional; must belong to the project. A deployment implies its environment. |
| `services` | Optional list of up to 20 service names of the project. Empty means all. |
| `window_start`, `window_end` | ISO-8601 with a time zone. 5 minutes to 6 hours, ending no later than now, starting within the last 30 days. |
| `hint` | Optional, up to 500 characters. Passed to the AI as a reported symptom. |
| `notify_routing` | Optional, default `false`. `true` sends new issues through routing rules like a scheduled batch. |

Errors return `{"error": "<code>", "message": "..."}`: `400` for
`invalid_project`, `invalid_environment`, `invalid_deployment`,
`invalid_services`, `invalid_window`, `invalid_hint`; `403` for viewers and
the demo; `409 over_budget`; `429 too_many_running` (two at a time) or
`rate_limited` (ten an hour).

```
GET /api/data/investigations/?project_id=&limit=20&offset=0
GET /api/data/investigations/<id>/
GET /api/data/investigations/options/
```

A run has `status` (`queued`, `collecting`, `analyzing`, `done`, `no_data`,
`failed`), `counts` per source, `error_code` and `error` when it failed, and
`batch_id` and `issue_count` once it is done. `options` lists the projects
with their environments, deployments, services and last deploy time.

Batches carry `trigger`: `scheduled`, `alert` or `manual` (an investigation).

## Related

- [Issues](issues.md) -- Issues detected within batches
- [AI & Chat](ai.md) -- Trigger AI analysis on a batch
- [Traces](traces.md) -- Distributed trace evidence correlated into batches
- [Settings & Admin](settings.md) -- Data retention policies and security settings
- [API Overview](overview.md) -- Base URL, response format, and error codes
