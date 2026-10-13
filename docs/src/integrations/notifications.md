# Post-RCA Notifications

Once SerOps finishes an incident analysis, forward the AI's root
cause + recommendation to wherever your on-call already looks —
Slack, Teams, a PagerDuty incident timeline, OpsGenie, or email.

Configure under **Settings → Delivery Channels**. Multiple channels
per kind are supported.

## Kinds

| Kind | Auth | Notes |
|---|---|---|
| **Slack** | Incoming Webhook URL | Block Kit message. Fallback text for mobile push. |
| **Microsoft Teams** | Incoming Webhook connector URL | MessageCard. Colour by severity. |
| **PagerDuty** | Events API v2 integration key | Emits a **change event** — attaches to existing incidents without creating new pages. |
| **OpsGenie** | API key + region (us/eu) | Creates a P4 note-style alert. Non-paging. |
| **Email** | None — uses the server's SMTP config | Recipients in `extra_config.to`. Plain-text summary with issue list. |

All secrets encrypted at rest via Fernet; write-only on the API
(reads return a `has_webhook_url` / `has_api_key` boolean, never
the plaintext).

Email channels need no secret but do need recipients:

```json
{
  "to": ["sre@example.com", "platform@example.com"],
  "from": "SerOps Alerts <alerts@example.com>",
  "reply_to": "oncall@example.com"
}
```

`from` and `reply_to` are optional and override `DEFAULT_FROM_EMAIL`.
SMTP itself is environment-only — see
[Email / SMTP configuration](../deployment/configuration.md#email-smtp).

## Routing

Channels are destinations; they do not decide what reaches them.
That is the job of **Settings → Routing Rules**, which pairs a matcher
with a set of target channels:

| Matcher axis | Values | Blank means |
|---|---|---|
| Minimum severity | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` | Any severity |
| Environments | List of environment names | All environments |
| Services | List of service names | All services |
| Event types | `batch_analyzed`, `alert_triggered`, `critical_issue` | All events |

All axes are ANDed. SerOps evaluates every active rule and notifies the
union of their targets, de-duplicated — a channel matched by several
rules is contacted once.

| Event | When |
|---|---|
| `batch_analyzed` | Every batch analysis completes (scheduled or alert-triggered) |
| `alert_triggered` | Only alert-triggered analyses (see [alerts guide](alerts.md)) |
| `critical_issue` | Batch produced at least one CRITICAL issue |

Severity is compared against the batch's **top** issue.

Typical setups:

* **Slack for general awareness**: rule with `min_severity=HIGH`, no other filter, targeting the SRE Slack channel.
* **PagerDuty timeline attach**: rule with `event_types=[alert_triggered]` and no severity filter — you want context on every alert-triggered incident.
* **OpsGenie for criticals only**: rule with `event_types=[critical_issue]`.
* **Per-team routing**: rule with `services=[checkout, billing]` targeting that team's Slack channel and email list.

!!! warning "No rules means no delivery"
    An organisation with delivery channels but no active routing rules
    sends nothing. Upgrades create a catch-all rule automatically, so
    this only bites organisations created afterwards or ones where
    every rule was deleted.

See [Notifications](../admin/notifications.md) for the full
configuration guide.

## Test send

Every channel row has a **Test send** button — SerOps posts a
synthetic "SerOps test message" so you can verify the URL / secret
before an incident happens. `last_sent_at` + `last_error` on the
row show the outcome.

## What lands where

The dispatcher fires from two points in the pipeline:

1. **After every batch analysis completes** (`ai_model/tasks.py`
   after issue dedup). Fires `batch_analyzed` + `critical_issue`
   (when applicable).
2. **After alert-triggered analyses** (`Data.tasks.analyze_alert_ondemand`
   after linking `AlertEvent.triggered_batch`). Fires
   `alert_triggered`.

## Failure model

Notification failures **never break the batch pipeline**. If your
Slack webhook returns 500, the batch analysis succeeds; the channel's
`last_error` records `HTTP 500: <body>` for you to investigate.

## API

Everything is available via `/api/notification/incident-channels/`:

```bash
# List (any authenticated org member)
curl -H "Authorization: Token $TOKEN" \
  https://your-serops-host/api/notification/incident-channels/

# Create (admin)
curl -X POST -H "Authorization: Token $ADMIN_TOKEN" -H "Content-Type: application/json" \
  https://your-serops-host/api/notification/incident-channels/ \
  -d '{
    "name": "SRE Slack",
    "kind": "slack",
    "webhook_url_input": "https://hooks.slack.com/services/...",
    "trigger_events": ["critical_issue"],
    "min_severity": "HIGH",
    "is_active": true
  }'

# Test send (admin)
curl -X POST -H "Authorization: Token $ADMIN_TOKEN" \
  https://your-serops-host/api/notification/incident-channels/1/test-send/
```
