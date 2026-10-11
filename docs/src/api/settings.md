# Settings & Admin API

Endpoints for organisation settings, onboarding, security configuration, audit logging, data management, and utility functions.

## Organisation Settings

!!! warning "Notification settings moved"
    `GET` and `PUT /api/settings/notifications/` were **removed**. The
    single org-level notification record they served no longer exists.

    Delivery destinations are now individual channel records at
    [`/api/notification/incident-channels/`](notifications.md), and
    which incidents reach which destination is decided by
    [`/api/notification/routing-rules/`](notifications.md).

    This mirrors the Grafana contact-point / notification-policy split.
    See [Delivery Channels](../admin/notifications.md) for the concepts.

### Test Notification Webhook

```
POST /api/settings/notifications/test/
```

Sends a test payload to a webhook URL so you can verify delivery
before saving it as a channel. This is the one endpoint from the old
notification-settings group that survives.

**Request body:**

```json
{
  "webhook_type": "slack",
  "webhook_url": "https://hooks.slack.com/services/T000/B000/XXXX"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `webhook_type` | string | `slack` or `teams`. |
| `webhook_url` | string | The incoming-webhook URL to test. |

Requires an admin role. The URL is not persisted — pass it here to
validate it, then create the channel with it.

### Get AI Settings

```
GET /api/settings/ai/
```

Returns the organisation-level AI configuration (enabled models, default provider).

### List AI Providers

```
GET /api/settings/ai/providers/
```

Returns all configured AI providers for the organisation.

### Add AI Provider

```
POST /api/settings/ai/providers/
```

**Request body:**

```json
{
  "provider": "anthropic",
  "api_key": "sk-ant-...",
  "is_default": false
}
```

Stores the API key encrypted at rest (Fernet). Once created, the key is never returned by the API.

### Get AI Provider Detail

```
GET /api/settings/ai/providers/{id}/
```

### Update AI Provider

```
PATCH /api/settings/ai/providers/{id}/
```

**Request body (partial update):**

```json
{
  "api_key": "sk-ant-new-value",
  "is_default": true
}
```

Send `api_key` only if you want to rotate the key. Omit to keep the current value.

### Delete AI Provider

```
DELETE /api/settings/ai/providers/{id}/
```

Removes the provider from the organisation. The provider's API key is deleted; other providers remain unaffected.

### Get Available AI Models

```
GET /api/settings/ai/available-models/
```

Returns AI models available for the current user's organisation. Only providers that are both system-wide active **and** have an API key configured for the organisation (or an environment variable fallback) are included. Returns an empty list if no models are available.

**Response:**

```json
{
  "models": [
    {"id": "gemini", "name": "Google Gemini"},
    {"id": "deepseek", "name": "DeepSeek"}
  ]
}
```

### Test AI Provider

```
POST /api/settings/ai/test/
```

Tests connectivity to a specific AI provider.

### Get Issue Settings

```
GET /api/settings/issues/
```

Returns the organisation-level issue settings (deduplication, muting, auto-resolution).

### Update Issue Settings

```
PUT /api/settings/issues/
```

### Get Sentinel Config

```
GET /api/settings/sentinel/
```

Returns the organisation's Sentinel configuration. Creates default config on first access.

**Response:**

```json
{
  "id": 1,
  "active_mode": false,
  "error_spike_multiplier": 0,
  "z_score_threshold": 0,
  "max_quiet_batches": 12,
  "updated_at": "2026-02-19T22:00:00Z"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `active_mode` | boolean | `true` = quiet batches skip AI, `false` = shadow mode |
| `error_spike_multiplier` | float | Override for error spike detection (0 = use default 2.0) |
| `z_score_threshold` | float | Override for anomaly z-score (0 = use default 3.0) |
| `max_quiet_batches` | integer | Force AI after this many consecutive quiet batches |

### Update Sentinel Config

```
PUT /api/settings/sentinel/
```

**Request body (partial update supported):**

```json
{
  "active_mode": true,
  "max_quiet_batches": 6
}
```

**Response:** Updated config object (same shape as GET).

!!! note "Admin Only"
    Both Sentinel endpoints require `admin` role.

!!! info "SMTP configuration is env-only"
    SerOps configures SMTP through environment variables (`EMAIL_HOST` etc.). There is no `/api/settings/mail/` endpoint — the previous UI-editable mail settings were removed 2026-09-01. See [Email / SMTP](../deployment/configuration.md#email-smtp) for the env var reference. Verify with `python manage.py check_smtp <recipient>`.

### List API Keys

```
GET /api/settings/api-keys/
```

Returns the API keys configured for external integrations. Keys themselves are never returned — only the provider ID and a masked hint.

### Create or Rotate an API Key

```
POST /api/settings/api-keys/
```

**Request body:**

```json
{
  "provider_id": 3,
  "api_key": "secret-value"
}
```

Stores the key encrypted at rest. Reusing the same `provider_id` overwrites the previous value (used for rotation).

### Delete an API Key

```
DELETE /api/settings/api-keys/{provider_id}/
```

Removes the stored key for the specified provider.

---

## Organisations

### Get Organisation Info

```
GET /api/organisation/info/
```

### Create Organisation

```
POST /api/organisation/create/
```

**Request body:**

```json
{
  "name": "My Organisation"
}
```

### Update Organisation

```
PUT /api/organisation/update/{id}/
```

**Request body:**

```json
{
  "name": "New Name",
  "website": "https://example.com"
}
```

### Delete Organisation

```
DELETE /api/organisation/delete/{id}/
```

### List Team Members

```
GET /api/organisation/team/
```

### Invite Team Member

```
POST /api/organisation/team/
```

**Request body:**

```json
{
  "user": {
    "email": "newmember@example.com",
    "role": "user"
  }
}
```

Sends an invitation email to the specified address and creates a pending user account.

### Update Team Member

```
PUT /api/organisation/member/{id}/
```

**Request body:**

```json
{
  "role": "admin",
  "first_name": "Jane",
  "last_name": "Doe"
}
```

Updates the team member's profile and/or role. Only fields included in the request body are changed.

### Remove Team Member

```
DELETE /api/organisation/member/{id}/
```

### Public Organisation List

```
GET /api/organisation/list/
```

Returns a minimal public list of organisation names (id + display name only). Used by the login / invitation flow so users can pick the right organisation before entering credentials. Does not require authentication and never exposes internal fields.

---

## Onboarding

### Get Onboarding Status

```
GET /api/organisation/onboarding/status/
```

Returns the current onboarding progress for the organisation.

!!! note "There is no endpoint to mark a step complete"
    `/onboarding/status/` is **GET-only**. Onboarding progress is
    computed from real database state on every read — a step counts as
    done when the thing it asks for actually exists.

    Earlier releases had a self-attested checklist where the client
    `PUT` a step as complete. That let a wizard report 100% on an
    organisation where nothing had been configured, so it was replaced
    by computed state. To advance onboarding, perform the underlying
    action (add an API key, connect an integration, create a project)
    and re-read the status.

    `POST /onboarding/skip/`, `/resume/`, and `/reset/` remain, since
    those express user intent rather than claiming completion.

### Skip Onboarding

```
POST /api/organisation/onboarding/skip/
```

Marks the onboarding flow as skipped. The user can resume later.

### Reset Onboarding

```
POST /api/organisation/onboarding/reset/
```

Resets the onboarding flow back to the first step.

---

## Security Settings

### Get / Update Security Settings

```
GET /api/data/settings/security/
```

```
PATCH /api/data/settings/security/
```

---

## Audit Log

### List Audit Log Entries

```
GET /api/data/settings/audit-log/
```

**Query parameters:**

| Parameter | Description |
|-----------|-------------|
| `action` | Filter by action type (`LOGIN`, `SETTINGS_CHANGE`, etc.) |
| `user` | Filter by user |
| `start_date` | Start of date range |
| `end_date` | End of date range |

### Export Audit Log

```
GET /api/data/settings/audit-log/export/
```

Returns a CSV or JSON export of audit entries.

---

## Data Management

### Data Usage

```
GET /api/data/settings/data-usage/
```

Returns storage usage statistics for the organisation.

### Retention Policy

```
GET /api/data/settings/retention-policy/
```

**Response includes:**

| Field | Type | Description |
|-------|------|-------------|
| `batch_generation_interval` | int | Current batch interval in minutes (5–720) |
| `batch_interval_choices` | object | Valid interval options (`{5: "5 minutes", ..., 720: "12 hours"}`) |
| `auto_cleanup_enabled` | bool | Whether auto-cleanup is active |
| `retention_days` | int | Batch retention period |
| `cleanup_frequency` | string | `daily`, `weekly`, or `monthly` |

```
PUT /api/data/settings/retention-policy/
```

**Request body (PUT):**

All fields are optional — include only the ones you want to change.

```json
{
  "batch_generation_interval": 10,
  "auto_cleanup_enabled": true,
  "retention_days": 30,
  "cleanup_frequency": "daily"
}
```

### Delete Old Batches

```
POST /api/data/delete-old-batches/
```

Triggers manual cleanup of batches older than the configured retention period.

---

## Utilities

### Scan Message

```
POST /api/utils/scan-message/
```

**Request body:**

```json
{
  "message": "Check this API key: sk-live-abc123"
}
```

**Response:**

```json
{
  "has_sensitive_data": true,
  "findings": [...],
  "critical_count": 1
}
```

Scans a message for sensitive data (API keys, passwords, tokens) without storing it.

---

## Related

- [Authentication](authentication.md) -- Login, SSO, and password management
- [Notifications](notifications.md) -- User-level notification preferences
- [AI & Chat](ai.md) -- AI admin endpoints for provider health
- [API Overview](overview.md) -- Base URL, response format, and error codes
