---
seo_title: "Issues API"
description: "API endpoints to list, filter, resolve, mute and acknowledge SerOps issues, with project, environment, service and time filters."
---
# Issues API

Endpoints for listing, filtering, and managing issues detected in log batches.

Issues are automatically created when SerOps detects problems during batch analysis. Each issue has a severity, status, and occurrence count.

## List All Issues

```
GET /api/data/issues/
```

**Query parameters:**

| Parameter | Description |
|-----------|-------------|
| `page` | Page number (default: 1) |
| `page_size` | Results per page (default: 20) |
| `severity` | Filter by `CRITICAL`, `WARNING` |
| `status` | Filter by `OPEN`, `MUTED`, `RESOLVED` |

**Response fields:**

| Field | Description |
|-------|-------------|
| `issue_type` | `MEMORY_HIGH`, `CPU_HIGH`, `DATABASE_ERROR`, etc. |
| `component` | Affected service or module |
| `status` | `OPEN`, `MUTED`, `RESOLVED` |
| `occurrence_count` | Times this issue was detected |
| `severity` | `CRITICAL`, `WARNING` |

## Issues by Batch

```
GET /api/data/issues/{batch_id}/
```

Returns all issues detected within a specific batch.

## Resolve Issue

```
POST /api/data/issues/{issue_id}/resolve/
```

Sets the issue status to `RESOLVED`. Returns the updated issue object.

## Mute Issue

```
POST /api/data/issues/{issue_id}/mute/
```

**Request body:**

```json
{
  "days": 7
}
```

Sets the issue status to `MUTED`. The `days` parameter controls how long the issue stays muted:

| Value | Duration |
|-------|----------|
| `1` | 1 day |
| `7` | 7 days |
| `30` | 30 days |
| `90` | 90 days |
| `0` | Forever |

## Reopen Issue

```
POST /api/data/issues/{issue_id}/reopen/
```

Sets the issue status back to `OPEN` and clears the `muted_until` timestamp. Works for both muted and resolved issues.

!!! note "Action name"
    The endpoint is `reopen`, not `unmute`. The single URL pattern `POST /api/data/issues/{issue_id}/{action}/` accepts `resolve`, `mute`, or `reopen`.

## Bulk Actions

```
POST /api/data/issues/bulk-action/
```

**Request body:**

```json
{
  "issue_ids": [1, 2, 3],
  "action": "resolve"
}
```

Performs a bulk action on multiple issues at once. Supported actions: `resolve`, `mute`, `reopen`. When `action` is `mute`, include a `days` field (same semantics as the single-issue mute).

---

## Related

- [Batches & Data](batches.md) -- Batch listing and details
- [Notifications](notifications.md) -- Issue acknowledgement and escalation rules
- [Dashboard & Analytics](analytics.md) -- Issue statistics and trend analysis
- [API Overview](overview.md) -- Base URL, response format, and error codes
