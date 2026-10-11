# Notifications API

Endpoints for delivery channels, routing rules, in-app notifications,
per-user preferences, project subscriptions, issue acknowledgement,
and escalation rules.

!!! note "Mount path is singular"
    Every route below lives under `/api/notification/` — singular.
    `/api/notifications/` returns 404.

## Delivery Channels

A delivery channel is one outbound destination: a Slack webhook, a
PagerDuty integration key, an email recipient list. Channels are
uniform — email is a channel kind like any other, not a special case.

Standard DRF ViewSet routes:

```
GET    /api/notification/incident-channels/
POST   /api/notification/incident-channels/
GET    /api/notification/incident-channels/{id}/
PATCH  /api/notification/incident-channels/{id}/
DELETE /api/notification/incident-channels/{id}/
```

Reads require authentication; writes require an admin role. Results are
scoped to the caller's organisation.

**Create request:**

```json
{
  "name": "SRE Slack",
  "kind": "slack",
  "webhook_url_input": "https://hooks.slack.com/services/T000/B000/XXXX",
  "min_severity": "HIGH",
  "is_active": true
}
```

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Human-readable label. |
| `kind` | string | `slack`, `teams`, `pagerduty`, `opsgenie`, or `email`. |
| `webhook_url_input` | string | Write-only. Slack/Teams incoming-webhook URL. |
| `api_key_input` | string | Write-only. PagerDuty integration key or OpsGenie API key. |
| `extra_config` | object | Provider extras. For `email`: `to` (string, list, or comma-separated), optional `from` and `reply_to`. For OpsGenie: `region`. |
| `min_severity` | string | Per-channel floor, applied after routing. Empty = any. |
| `is_active` | boolean | Inactive channels are never contacted. |

!!! warning "Secrets are write-only"
    `webhook_url_input` and `api_key_input` are accepted on write and
    never returned on read. Responses expose only the booleans
    `has_webhook_url` and `has_api_key`. There is no endpoint that
    reveals a stored secret — rotate by writing a new value.

## Routing Rules

A routing rule decides which channels fire for a given incident. The
dispatcher walks every active rule, takes the **union** of targets from
all matching rules, and de-duplicates — a channel matched by three
rules is still contacted once.

```
GET    /api/notification/routing-rules/
POST   /api/notification/routing-rules/
GET    /api/notification/routing-rules/{id}/
PATCH  /api/notification/routing-rules/{id}/
DELETE /api/notification/routing-rules/{id}/
```

**Create request:**

```json
{
  "name": "Prod criticals to on-call",
  "min_severity": "CRITICAL",
  "environments": ["production"],
  "services": [],
  "event_types": ["alert_triggered"],
  "target_ids": [3, 7],
  "priority": 50,
  "is_active": true
}
```

| Field | Type | Description |
|-------|------|-------------|
| `min_severity` | string | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`. Empty = any severity. |
| `environments` | array | Environment names. Empty = every environment. |
| `services` | array | Service names. Empty = every service. |
| `event_types` | array | Subset of `batch_analyzed`, `alert_triggered`, `critical_issue`. Empty = every event. |
| `target_ids` | array | Delivery channel IDs to notify. Validated against your own organisation. |
| `priority` | integer | Lower is evaluated first. Informational today, since matching is a union. |

Matcher axes are **AND-ed**, and an empty value means "no filter on
this axis". A rule with every axis empty matches every incident.

!!! warning "No rules means no notifications"
    The dispatcher sends nothing when no active rule matches. Upgrading
    from a pre-routing release creates one catch-all rule per
    organisation targeting all existing channels, so delivery is
    unchanged until you narrow it.

## Notifications

### List Notifications

```
GET /api/notification/noti/
```

Returns all notifications for the authenticated user.

### Get Notification Detail

```
GET /api/notification/{id}/
```

Returns a single notification by ID.

### Mark All as Read

```
POST /api/notification/mark-all-as-read/
```

Marks all unread notifications as read for the authenticated user.

### Unread Count

```
GET /api/notification/unread-count/
```

**Response:**

```json
{
  "unread_count": 5
}
```

### List Read Notifications

```
GET /api/notification/notifications/read/
```

Returns notifications that have already been marked as read. Useful for building a "History" tab that is separate from the unread inbox.

### Delete All Notifications

```
DELETE /api/notification/notifications/delete-all/
```

Permanently deletes all notifications for the authenticated user.

---

## Preferences

### Get Notification Preferences

```
GET /api/notification/preferences/
```

Returns the user's notification preference settings.

### Update Notification Preferences

```
PATCH /api/notification/preferences/
```

**Request body:**

```json
{
  "email_enabled": true,
  "severity_filter": ["CRITICAL", "WARNING"],
  "quiet_hours_start": "22:00",
  "quiet_hours_end": "08:00",
  "digest_frequency": "daily"
}
```

---

## Project Subscriptions

### List Project Subscriptions

```
GET /api/notification/subscriptions/
```

Returns all project subscriptions for the authenticated user.

### Subscribe to Project

```
POST /api/notification/subscriptions/
```

**Request body:**

```json
{
  "project_id": 1
}
```

### Unsubscribe from Project

```
DELETE /api/notification/subscriptions/{id}/
```

---

## Issue Acknowledgement

### Acknowledge Issue

```
POST /api/notification/issues/{issue_id}/acknowledge/
```

Stops the escalation chain for this issue. Once acknowledged, no further escalation notifications will be sent.

---

## Escalation Rules

### List Escalation Rules

```
GET /api/notification/escalation-rules/
```

Returns all configured escalation rules for the organisation.

### Create Escalation Rule

```
POST /api/notification/escalation-rules/
```

**Request body:**

```json
{
  "level": 1,
  "delay_minutes": 15,
  "target_role": "admin"
}
```

Defines an escalation step. When an issue goes unacknowledged for `delay_minutes`, the notification escalates to users with `target_role`.

---

## Related

- [Delivery Channels & Routing Rules](../admin/notifications.md) -- Concepts and UI walkthrough
- [Alert Ingestion](../integrations/alerts.md) -- Inbound webhooks from Alertmanager, Grafana, Datadog
- [Issues](issues.md) -- Issue management and resolution
- [Settings & Admin](settings.md) -- Webhook test endpoint
- [API Overview](overview.md) -- Base URL, response format, and error codes
