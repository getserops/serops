# Notifications

SerOps splits notification configuration into two pages, matching the
model used by Grafana Alerting and Prometheus Alertmanager:

| Page | Answers | Backed by |
|------|---------|-----------|
| **Settings → Delivery Channels** | *Where* can SerOps send? | `IncidentNotificationChannel` |
| **Settings → Routing Rules** | *Which* incidents go *where*? | `NotificationRoutingRule` |

If you have configured Grafana contact points and notification
policies, this is the same separation under different names. Channels
are destinations; rules decide which destinations fire.

!!! note "Upgrading from an earlier version"
    Earlier releases had a single **Settings → Notifications** page with
    one email toggle, one Slack webhook, and one Teams webhook. That
    page is gone. Your existing configuration was migrated into
    Delivery Channels automatically, and a catch-all routing rule was
    created for your organisation targeting every channel — so delivery
    behaviour is unchanged until you narrow it.

    The old `/dash/settings/notifications` and
    `/dash/settings/incident-channels` URLs redirect to
    `/dash/settings/delivery`.

---

## Delivery Channels

**Location**: Settings → Delivery Channels

One table, one row per destination. Unlike the old page, you can
create as many channels of each kind as you need — separate Slack
channels per team, a PagerDuty key per service, several email
recipient lists.

### Channel kinds

| Kind | Auth | Notes |
|------|------|-------|
| **Slack** | Incoming Webhook URL | Block Kit message with fallback text for mobile push |
| **Microsoft Teams** | Incoming Webhook connector URL | MessageCard, coloured by severity |
| **PagerDuty** | Events API v2 integration key | Emits a *change event* — attaches to existing incidents without paging |
| **OpsGenie** | API key + region (`us` / `eu`) | Creates a note-style alert. Non-paging |
| **Email** | None — uses your SMTP config | Recipients configured per channel |

Webhook URLs and API keys are encrypted at rest and write-only on the
API: reads return `has_webhook_url` / `has_api_key` booleans, never the
plaintext.

### Creating an email channel

Email has no secret to store, but it does need recipients. Set them in
the channel's `extra_config`:

```json
{
  "to": "oncall@example.com"
}
```

`to` accepts a single address, a list, or a comma-separated string:

```json
{
  "to": ["sre@example.com", "platform@example.com"],
  "from": "SerOps Alerts <alerts@example.com>",
  "reply_to": "oncall@example.com"
}
```

`from` and `reply_to` are optional and override the system-wide
`DEFAULT_FROM_EMAIL`.

!!! warning "SMTP must be configured first"
    Email channels use the server's SMTP settings, which are
    environment-only — there is no UI editor, following the same model
    as Grafana. See
    [Email / SMTP configuration](../deployment/configuration.md#email-smtp).
    Without it, email channels fail with a delivery error recorded in
    `last_error`.

### Testing a channel

Each row has a **Test send** button. SerOps posts a synthetic message
so you can verify the URL or secret before a real incident depends on
it. The row's `last_sent_at` and `last_error` fields record the
outcome.

### Failure handling

Notification failures never break the analysis pipeline. If a Slack
webhook returns 500, the batch analysis still succeeds and the
channel's `last_error` records the response for you to investigate.

Channels that fail with a permanent error (4xx — invalid URL, revoked
key) are automatically deactivated, since the same request will fail
identically every time. Fix the configuration and re-enable the
channel.

---

## Routing Rules

**Location**: Settings → Routing Rules

A rule pairs a *matcher* — which incidents it applies to — with a set
of *target channels*.

### Matcher

All four axes are ANDed together. Leaving one empty means "no filter on
this axis", so an entirely empty matcher matches every incident.

| Axis | Values | Empty means |
|------|--------|-------------|
| **Minimum severity** | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` | Any severity |
| **Environments** | List of environment names | All environments |
| **Services** | List of service names | All services |
| **Event types** | `batch_analyzed`, `alert_triggered`, `critical_issue` | All events |

Severity is compared against the batch's highest-severity issue.

| Event type | Fires when |
|------------|-----------|
| `batch_analyzed` | Any batch analysis completes, scheduled or alert-triggered |
| `alert_triggered` | Only analyses started by an inbound alert — see [Real-time Alerts](../integrations/alerts.md) |
| `critical_issue` | The batch produced at least one `CRITICAL` issue |

### How rules are evaluated

SerOps walks **every active rule**, collects the targets from each one
that matches, and takes the union — de-duplicated, so a channel matched
by three rules is still contacted once.

There is no first-match-wins, and no rule stops evaluation of the
others. `priority` exists on each rule and orders evaluation, but since
the result is a union it is currently informational.

!!! warning "No rules means no notifications"
    If an organisation has zero active routing rules, nothing is sent —
    regardless of how many delivery channels exist. This is the same
    behaviour as Alertmanager with an empty route tree.

    Upgrades create a catch-all rule automatically, so this only
    affects organisations created after the upgrade or ones where every
    rule has been deleted.

### Example rules

A typical setup separates paging from awareness:

| Rule | Matcher | Targets |
|------|---------|---------|
| Page on-call | severity `CRITICAL`, env `production` | PagerDuty |
| SRE awareness | severity `HIGH` | SRE Slack |
| Payments team | services `checkout`, `billing` | Payments Slack, payments-oncall email |
| Alert context | event `alert_triggered` | PagerDuty |

The third and fourth rules can both match the same incident; the
Payments Slack channel is contacted once, and PagerDuty once.

---

## Inbound alert authentication

The Delivery Channels page also manages the secret used for *inbound*
alerts — the direction opposite to everything above. Alertmanager,
Grafana, and Datadog authenticate to SerOps with a per-organisation
bearer token.

Click **Rotate ingest secret** to generate one. The plaintext is shown
exactly once; SerOps stores only a SHA-256 hash and a short display
prefix, so it cannot be recovered afterwards.

```
serops_alert_<43 url-safe base64 characters>
```

Use it as a bearer token:

```
POST https://your-serops-host/api/webhooks/alerts/<source>/<org_id>/
Authorization: Bearer serops_alert_...
```

`<source>` is `alertmanager`, `grafana`, or `datadog`.

!!! warning "Rotation takes effect immediately"
    The previous secret stops working the moment a new one is
    generated. Update your alert senders before rotating, or expect a
    gap during which inbound alerts are rejected with 401.

If no per-organisation secret is set, SerOps falls back to the global
`ALERT_WEBHOOK_SECRETS` Django setting, so existing single-tenant
deployments keep working unchanged. See
[Real-time Alerts](../integrations/alerts.md) for the full sender
configuration.

---

## Escalation

Escalation is configured separately, under escalation rules, and is
driven purely by whether a matching rule exists — there is no
organisation-wide on/off switch.

| Level | Default delay | Notifies |
|-------|---------------|----------|
| Level 1 | 15 minutes | Project admins |
| Level 2 | 45 minutes | All organisation admins |

Acknowledging or resolving the issue stops the chain. See
[Set Up Escalation Rules](../how-to/escalation-rules.md).

---

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| Nothing is sent at all | No active routing rule matches. Check Settings → Routing Rules |
| One channel silent, others fine | Channel auto-deactivated after a permanent failure — check its `last_error` |
| No email received | SMTP not configured, or the channel's `extra_config.to` is empty |
| Slack returns 404 | Webhook URL revoked or expired — regenerate it in Slack |
| Teams returns an error | Regenerate the Incoming Webhook connector |
| Inbound alerts rejected with 401 | Ingest secret rotated without updating the sender |

---

## API

Both surfaces are full CRUD ViewSets. Note the mount point is
`/api/notification/` — singular.

```bash
# List delivery channels
curl -H "Authorization: Token $TOKEN" \
  https://your-serops-host/api/notification/incident-channels/

# Create an email channel (admin)
curl -X POST -H "Authorization: Token $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  https://your-serops-host/api/notification/incident-channels/ \
  -d '{
    "name": "On-call email",
    "kind": "email",
    "extra_config": {"to": "oncall@example.com"},
    "is_active": true
  }'

# Create a routing rule (admin)
curl -X POST -H "Authorization: Token $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  https://your-serops-host/api/notification/routing-rules/ \
  -d '{
    "name": "Page on-call for prod criticals",
    "min_severity": "CRITICAL",
    "environments": ["production"],
    "services": [],
    "event_types": [],
    "target_ids": [3],
    "is_active": true
  }'

# Rotate the inbound alert secret (admin) — plaintext returned once
curl -X POST -H "Authorization: Token $ADMIN_TOKEN" \
  https://your-serops-host/api/organisation/alert-secret/rotate/
```

Testing a webhook before saving it uses the settings endpoint:

```bash
curl -X POST -H "Authorization: Token $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  https://your-serops-host/api/settings/notifications/test/ \
  -d '{
    "webhook_type": "slack",
    "webhook_url": "https://hooks.slack.com/services/..."
  }'
```

!!! note "Removed endpoints"
    `GET` and `PUT` on `/api/settings/notifications/` no longer exist —
    they configured the deleted per-organisation settings model. Only
    the `/test/` sub-path survives.

---

## See also

- [Post-RCA Notifications](../integrations/notifications.md) — what the messages look like per channel kind
- [Real-time Alerts](../integrations/alerts.md) — inbound alert ingestion
- [Set Up Escalation Rules](../how-to/escalation-rules.md)
- [Notification Preferences](../user-guide/notifications.md) — per-user settings
