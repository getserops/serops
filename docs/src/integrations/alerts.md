---
seo_title: "Alertmanager, Grafana, Datadog and Sentry alerts: instant RCA"
description: "Forward Alertmanager, Grafana, Datadog or Sentry alerts to SerOps and get an AI root cause for the affected service within about 30 seconds."
---
# Real-time Alerts

SerOps can ingest alerts from your existing alert manager and run
Root Cause Analysis on-demand — the alert fires, SerOps immediately
opens a batch analysis for the impacted service, and the RCA
recommendation lands in your dashboard within ~30 seconds.

Four sources are supported:

| Source | Protocol | Format |
|---|---|---|
| Prometheus Alertmanager | HTTP POST | Alertmanager webhook v4 |
| Grafana Alerts (v9+) | HTTP POST | Alertmanager-compatible |
| Datadog Monitors | HTTP POST | Datadog Monitor webhook |
| Sentry | HTTP POST, signed | Internal integration webhooks (issue alerts, metric alerts, new issues) |

The alert itself is part of the evidence: its title, summary and, for
Sentry, the exception, release and stack frames go into the analysis
alongside the logs, metrics and traces of the window. An alert alone is
enough for an analysis, so a team that only has Sentry still gets one.

## 1. Get a webhook secret

Inbound alerts authenticate with a bearer token. There are two ways to
provide one; the per-organisation secret is the recommended path.

### Per-organisation secret (recommended)

Go to **Alerts & routing → Delivery Channels** and use **Generate ingest
secret** (or **Rotate ingest secret** if one already exists).

The plaintext is shown **exactly once**, in that dialog. SerOps stores
only a SHA-256 hash and a short display prefix — there is no endpoint,
admin page, or database column from which the original can be
recovered. Copy it into your secret manager before closing the modal.

```
serops_alert_<43 url-safe characters>
```

This scopes the credential to one organisation, so a leaked token
cannot be replayed against another tenant, and rotation is a single
click that takes effect immediately. **Rotating invalidates the
previous secret at once** — update your senders in the same
maintenance window.

Programmatic equivalents:

```
GET  /api/organisation/alert-secret/          # metadata only, no plaintext
POST /api/organisation/alert-secret/rotate/   # returns plaintext once
```

### Global env-var secrets (fallback)

Single-tenant deployments can keep using per-source environment
variables. These apply instance-wide and are consulted only when the
organisation has no secret of its own:

```bash
export SEROPS_ALERTMANAGER_SECRET=$(openssl rand -hex 32)
export SEROPS_GRAFANA_ALERT_SECRET=$(openssl rand -hex 32)
export SEROPS_DATADOG_MONITOR_SECRET=$(openssl rand -hex 32)
```

Inject at container start from Vault, AWS Secrets Manager, or a
Kubernetes Secret. Rotate by setting a new value and reconfiguring the
sender.

!!! note "Unset means rejected, never open"
    A source with neither a per-org secret nor its env var returns 401.
    SerOps has no un-authenticated ingest path.

## 2. Point your alerter at SerOps

The webhook URL includes your **org ID** so a leaked secret only
affects one tenant's analyses:

```
POST https://your-serops-host/api/webhooks/alerts/<source>/<org_id>/
Authorization: Bearer <secret>
Content-Type: application/json
```

### Prometheus Alertmanager

Add a receiver to `alertmanager.yml`:

```yaml
receivers:
  - name: serops
    webhook_configs:
      - url: https://your-serops-host/api/webhooks/alerts/alertmanager/42/
        http_config:
          authorization:
            type: Bearer
            credentials_file: /etc/alertmanager/serops.token

route:
  receiver: serops
  group_wait: 10s
  repeat_interval: 4h   # SerOps dedups within 5min anyway
```

### Grafana Alerts (v9+)

*Alerting → Contact points → New*. Type = Webhook.

- URL: `https://your-serops-host/api/webhooks/alerts/grafana/42/`
- Auth: HTTP header, `Authorization: Bearer <secret>`

Grafana emits the Alertmanager v4 payload, so it lands through the
same parser.

### Datadog Monitors

*Monitors → New Monitor → Notifications → @webhook-serops*, then
create the webhook integration:

- URL: `https://your-serops-host/api/webhooks/alerts/datadog/42/`
- Custom headers: `Authorization: Bearer <secret>`

Add `service:<name>` and `env:<name>` tags to the monitor so SerOps
can route the analysis to the right project.

### Sentry

Sentry can't add a bearer token to a webhook; it signs each one with the
client secret of an **internal integration**, and SerOps checks that
signature.

1. In Sentry: *Settings → Developer Settings → Custom Integrations →
   Create New Integration → Internal Integration*.
2. **Webhook URL**: `https://your-serops-host/api/webhooks/alerts/sentry/42/`
   (your organisation id in place of 42).
3. Turn on **Alert Rule Action**, and under **Webhooks** subscribe to
   **issue** if you also want new issues to trigger an analysis.
   Permissions can stay at *No Access*: SerOps doesn't call Sentry.
4. Save, then copy the integration's **Client Secret** into SerOps:
   `SEROPS_SENTRY_CLIENT_SECRET` in `.env` (Docker Compose) or
   `alertSecrets.sentry` (Helm), and restart the backend.
5. In an alert rule (*Alerts → Create Alert*, issue or metric), add the
   action **Send a notification via** your integration.

Routing: SerOps matches the event's `service` tag, then the Sentry
project slug, against your services' names. Set a `service` tag in your
SDK (`sentry_sdk.set_tag("service", "checkout-api")`) or name the Sentry
project like the service. The environment comes from the event's
`environment`.

The secret is install-wide: every organisation on the install uses the
same Sentry integration. Pulling Sentry errors into scheduled analyses
(without an alert) is not available yet.

## 3. What happens when an alert fires

1. Webhook lands, secret or Sentry signature is verified (constant-time compare).
2. Payload is parsed → `(alertname, service, environment, severity, summary)`.
3. **Idempotency:** duplicates within 5 minutes (same fingerprint
   for Alertmanager, same event ID for Datadog and Sentry) return `200
   deduplicated` — no re-analysis. Handles Alertmanager retries
   safely.
4. `AlertEvent` row is created (audit trail).
5. **On-demand analysis** enqueues at highest priority
   (`queue=high_priority, priority=10`). Alert-triggered batches
   jump ahead of scheduled ones.
6. Batch pipeline runs against the alert's service + environment,
   producing issues + AI recommendation.
7. `AlertEvent.triggered_batch` is populated so you can trace back
   from the incident to the alert that opened it.

## Rate limits + audit

- **300 requests/min per source** via
  `DEFAULT_THROTTLE_RATES["alert_webhook"]`. Sized for a noisy
  incident storm; bump in `settings.py` if you have more than that
  legitimately.
- Raw payloads are stored on `AlertEvent.raw_payload` for support
  debugging — inspect via your DB directly, or via the Django admin if you enabled it (`DJANGO_ADMIN_ENABLED=True`).
