---
seo_title: "Settings reference"
description: "Reference for every SerOps settings page: organisation, team, AI providers, Sentinel, data, security, integrations and audit log."
---
# Settings Reference

Complete reference for all SerOps settings modules.

## User Preferences (Header Dropdown)

**Location**: Click your profile avatar in the top-right header

Personal preferences accessible from any page:

| Setting | Options |
|---------|---------|
| **Language** | English, Français |
| **Appearance** | Light, Dark, System |
| **Timezone** | Select from dropdown (shows current time) |
| **Density** | Comfortable, Compact |

> These settings are user-specific and stored in your browser.

---

## General Settings (Organisation)

**Location**: Settings → General

| Setting | Description |
|---------|-------------|
| Organisation Name | Read-only: shown, but it cannot be changed, because metrics and logs depend on it |
| Organisation Logo | PNG, JPEG, GIF or WebP up to 2 MB, shown next to the organisation name in the sidebar. Stored in the database, resized to at most 256 px. |
| Website | Organisation website URL |

---

## AI Settings

**Location**: Settings → AI Providers

### Model Selection

| Setting | Options |
|---------|---------|
| **Primary Model** | Gemini, Claude, OpenAI, DeepSeek, Ollama (any registered `AIModelProvider`) |
| **Fallback Model** | API only: `PUT /api/settings/ai/` with `fallback_provider` (a provider id, or `null` to disable fallback). The page has no control for it. |
| **Use Custom Keys** | API only: `PUT /api/settings/ai/` with `use_custom_keys`. The page has no control for it, and 1.5.5 does not read it when it picks a key. |

### Provider Configuration

Manage AI providers and private API keys in **Settings > AI Providers > Manage Providers**. Each organisation's admin sets its own API key and, when needed, its own base URL (for example a local Ollama endpoint).

The provider list itself (adding a provider, **Edit Config**, deleting one) is shared by every organisation on the install. It can be changed by platform staff (a Django staff user), or by the admin when the install has a single organisation.

#### Adding/Editing a Provider
1.  Click **Add Provider** or **Edit Config**.
2.  **Display Name**: Name shown in dropdowns.
3.  **Adapter Type**:
    *   **Google Gemini**: For Gemini models via the `google-genai` SDK.
    *   **Anthropic Claude**: Native adapter using the `anthropic` SDK. Supports prompt caching via `cache_control:ephemeral` on the batch-analysis system prefix.
    *   **OpenAI Compatible**: For OpenAI, DeepSeek, Ollama, Mistral, or any `v1/chat/completions`-compatible endpoint. Prompt caching on OpenAI + DeepSeek activates automatically when the system-role prefix crosses 1,024 tokens.
4.  **API Base URL**: Optional for cloud providers, required for local/self-hosted (e.g., `http://localhost:11434/v1`).
5.  **Default Model**: The model ID to send in requests (e.g., `llama3`, `claude-3-sonnet`).
6.  **Active**: Toggle to enable/disable.

#### Connection Testing
1.  Enter your API Key for a provider.
2.  Click the "Eye" icon to verify input.
3.  Click **Save**.
4.  Click **Test Connection** to verify the key works. 
    *   **Success**: Shows "Connected" badge.
    *   **Failed**: Check the error message (usually "Auth Error" or "Invalid Key").

#### Troubleshooting
*   **"Auth Error"**: Usually means the stored API Key is invalid or expired. Delete the key and re-enter it.
*   **"Encryption Reset"**: If the backend secret key changes, old keys become unreadable. You will need to re-enter them.
*   **System Defaults**: If no custom key is provided, the system may use environment variable defaults if configured.

---

## Delivery Channels

**Location**: Alerts & routing → Delivery Channels

One row per notification destination, following the Grafana contact
point model. Multiple channels of the same kind are supported.

| Kind | Auth | Configuration |
|------|------|---------------|
| Slack | Incoming Webhook URL | Paste the webhook URL |
| Microsoft Teams | Incoming Webhook connector URL | Paste the connector URL |
| PagerDuty | Events API v2 integration key | Paste the integration key |
| OpsGenie | API key + region | Key plus `us` or `eu` |
| Email | None | Recipients in `extra_config.to` |

Secrets are encrypted at rest and never returned by the API.

This page also holds **Rotate ingest secret**, the per-organisation
bearer token that inbound Alertmanager, Grafana, and Datadog webhooks
authenticate with. The plaintext is displayed once only. Sentry signs its webhooks with its own client secret instead (see [Real-time Alerts](../integrations/alerts.md#sentry)).

See [Notifications](notifications.md) for the full guide.

---

## Routing Rules

**Location**: Alerts & routing → Routing Rules

Decides which delivery channels fire for which incidents — the
Alertmanager route table, flattened.

| Field | Description |
|-------|-------------|
| Minimum severity | `INFO`, `WARNING`, `CRITICAL`, or blank for any: see [Notifications](notifications.md#matcher) |
| Environments | List of environment names, blank for all |
| Services | List of project names (compared with the batch's project name), blank for all |
| Event types | `batch_analyzed`, `alert_triggered`, `critical_issue`, blank for all |
| Targets | Which delivery channels this rule notifies |
| Priority | Evaluation order (informational — results are unioned) |

All matcher axes are ANDed. Every matching rule contributes its
targets; the union is de-duplicated so a channel is contacted once.

!!! warning
    With no active routing rules, nothing is sent regardless of how
    many delivery channels exist.

---

## Notification Preferences (Per User)

**Location**: Avatar menu → Notification preferences

Personal delivery preferences — channels, severity filters, quiet
hours, and digest frequency. These are per-user and independent of the
organisation-wide Delivery Channels above.

See [Notification Preferences](../user-guide/notifications.md).

---

## Security Settings

**Location**: Settings → Security

### Password Validation

Every new password (sign-up, invitation, reset, change) goes through the
same checks, in the spirit of NIST 800-63B (length over composition rules):

| Check | Rule |
|---------|-------|
| Minimum length | 8 characters |
| Common passwords | Refused (Django's list of 20,000 common passwords) |
| Similarity | Refused when too close to the user's name, username or email |
| All digits | Refused |
| Complexity rules (upper case, symbols…) | None |
| Expiry | Never |

The sign-up form and the first-admin command (`create_superadmin`) also
require at least 10 characters, with an upper-case letter, a lower-case
letter and a number.

The rules are fixed: there is no password-policy setting in the UI or the
API. Organisations that need stricter rules can require single sign-on
(Settings → Security) and set them in their identity provider.

### Session Settings
| Setting | Description |
|---------|-------------|
| Session Timeout | 30m / 1h / 4h / 8h / 24h / Never |
| Token TTL | 30 days (auto-refresh on activity, at most once per minute) |

### SSO Configuration
OpenID Connect with Keycloak, Okta, Azure AD / Entra ID, Google Workspace or any OIDC provider. Roles can come from the provider's groups, and people of listed email domains can join without an invitation: see [Authentication & SSO](../security/authentication.md#roles-from-your-identity-providers-groups).

---

## Users, Roles and Teams

**Location**: Settings → Users, Settings → Teams, and Settings → Roles (SerOps Enterprise)

### Roles

**Viewer** (read only), **User** (read, run analyses, edit projects, update issues) and **Admin** (everything in the organisation, including credentials, team and settings). The full list of permissions per role is on [Users, roles and teams](team.md#roles). The Settings menu only lists the pages your role can open.

### Actions
- Invite user
- Change role
- Remove user

---

## Integration Settings

**Location**: Integrations (sidebar)

Manage global provider integrations:

| Provider | Status |
|----------|--------|
| GitLab | Connected/Not configured |
| GitHub | Connected/Not configured |
| Azure DevOps | Connected/Not configured |

---

## Observability Configuration

**Location**: Integrations (sidebar)

Log, metric, and trace providers are configured alongside SCM and
CI/CD providers on the Integrations page — there is no separate
Observability page.

SerOps supports a hybrid model for Logs and Metrics storage (Internal vs External).
See [Observability Providers](../integrations/observability-overview.md) for details.

---

## Sentinel Settings

**Location**: Settings → Sentinel

Controls the Sentinel tiered intelligence system that evaluates batches before AI analysis.

### Gating Mode

| Setting | Description |
|---------|-------------|
| **Enable Active Mode** | When ON, quiet batches skip AI analysis (saves cost). When OFF, shadow mode — all batches run AI. |

!!! info "Active mode is the default"
    Active mode is the default for new installations and organisations (shadow mode was the default up to v1.2.13). Switch to shadow mode to compare Sentinel's decisions with a full analysis of every window, at the cost of an AI call per window. Check the Sentinel figures at the top of **Settings → Sentinel** to verify decisions are accurate.

### Threshold Overrides

Fine-tune detection sensitivity. Set to 0 to use system defaults.

| Setting | Default | Description |
|---------|---------|-------------|
| **Error Spike Multiplier** | 2.0 | How many times above baseline error rate triggers an alert. Lower = more sensitive. |
| **Z-Score Threshold** | 3.0 | Standard deviations from mean for memory/CPU anomaly detection. Lower = more sensitive. |
| **Max Quiet Batches** | 12 | Force AI analysis after this many consecutive quiet batches (safety net). |

!!! tip "Tuning Tips"
    - For critical production services, use a lower multiplier (e.g., 1.5) to catch smaller error spikes.
    - Keep max quiet batches at 12 or below to ensure periodic AI review.

See [Sentinel How-To](../how-to/sentinel.md) for the full guide.

---

## Mail Server (SMTP)

SMTP is configured via **environment variables** (`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL`). There is no UI editor — SerOps follows the Grafana pattern: change `.env`, restart the backend.

Verify a config end-to-end:

```bash
docker compose exec backend python manage.py check_smtp your-address@example.com
```

The command prints which values are currently in effect and sends a test message.

See the [Configuration Reference](../deployment/configuration.md#email-smtp) for the full env-var list.

!!! info "Removed in 2026-09-01"
    An earlier release exposed a `Settings → Mail Server` UI backed by a `SystemMailSettings` DB row. It was removed on 2026-09-01 to eliminate a per-instance lifecycle-email hijack surface. If you're upgrading and had SMTP configured through the UI, copy those values into your `.env` before applying migration `0013_remove_systemmailsettings`.

---

## Data Settings

**Location**: Settings → Data retention

### Retention Policy
| Setting | Options |
|---------|---------|
| Auto-Cleanup | Enabled/Disabled |
| Retention Days | 7-365 days |
| Frequency | Daily/Weekly/Monthly |

### Batch Settings
| Setting | Default |
|---------|---------|
| Generation Interval | 15 minutes |

---

## Audit Log Settings

**Location**: Settings → Audit Log

| Setting | Options |
|---------|---------|
| Retention Days | 30/90/365/Forever (default 90). API only: `PUT /api/data/settings/retention-policy/` with `audit_log_retention_days` (`0` = forever). No screen has a control for it. |
| Export Format | CSV |

---

## Clusters

**Location**: Settings → Clusters

Register the Kubernetes clusters your projects run on. Clusters scope
observability integrations and are one dimension of the deployment
filter used across the Analyses and Issues pages.

See [Clusters](clusters.md).

---

## Traces

**Location**: Settings → Trace ingest keys

Manage OTLP ingest keys for distributed tracing. Each key is shown
once on creation and stored as a hash afterwards, following the same
model as the alert ingest secret.

See [Distributed Traces](../integrations/traces.md).
