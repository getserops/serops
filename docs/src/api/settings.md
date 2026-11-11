---
seo_title: "Settings and admin API"
description: "API endpoints for organisation settings, onboarding, security, audit log and data management."
---
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
  "active_mode": true,
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

Sends an invitation email to the specified address and creates a pending user account. `role` is a role key: `viewer`, `user`, `admin`, or `custom:<id>` for a [custom role](#custom-roles).

You can only give a role whose permissions you hold (`403` otherwise), and only change or remove members whose permissions you hold.

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

Updates the team member's profile and/or role. Only fields included in the request body are changed. `role` takes a role key as above; members are returned with `role` (`viewer`, `user`, `admin` or `custom`), `role_key` and `role_name`.

### Remove Team Member

```
DELETE /api/organisation/member/{id}/
```

### Teams

```
GET /api/organisation/teams/
POST /api/organisation/teams/
PUT /api/organisation/teams/{id}/
DELETE /api/organisation/teams/{id}/
```

`GET` (every member) returns `teams` with `members` (`id`, `email`, `name`, `source`: `manual` or `sso`) and the `projects` it has access to (only those the caller can see). Writes need `team.manage`:

```json
{ "name": "Payments", "description": "", "member_ids": [12, 15] }
```

`member_ids` replaces the members. You can only change or delete a team whose project grants you hold yourself (`403` otherwise), so joining a team is never a way to gain access. A team named by an SSO rule can't be deleted (`409`). Audited as `TEAM_CREATE`, `TEAM_UPDATE`, `TEAM_DELETE`.

### Custom Roles

```
GET /api/organisation/roles/
POST /api/ee/roles/
PUT /api/ee/roles/{id}/
DELETE /api/ee/roles/{id}/
```

Listing is Community. Writes are Enterprise: available when the Enterprise directories are installed; `POST` and `PUT` need the *Custom roles* license feature (`403` with `"code": "enterprise_license_required"` otherwise), `DELETE` never does. Without the license, inviting or moving a member to a custom role they don't already have, and adding an SSO rule that names one, are refused the same way.

`GET` (every member) returns `builtin` (the three built-in roles and their permissions), `custom` (`id`, `key`, `name`, `description`, `permissions`, `member_count`), `catalogue` (the permissions a custom role can hold, with descriptions), `always_granted` and `implies`. Writes need `team.manage`.

```json
{ "name": "On-call", "description": "Resolves issues, re-runs analyses", "permissions": ["issue.update", "batch.analyze"] }
```

The saved permissions always include `self.manage` and `org.read`, and each permission's prerequisite (`batch.analyze` adds `batch.read`). Platform permissions can't be granted. You can only create, change or delete a role whose permissions you hold. A role still assigned to a member, or named by an SSO rule, can't be deleted (`409`).

### Organisation List

```
GET /api/organisation/list/
```

Returns the caller's own organisation (id and name), whatever their role.

---

## Edition and Enterprise license

### Get the Edition

```
GET /api/organisation/edition/
```

Any member (`org.read`). Whether the Enterprise code is installed and which Enterprise features the license key enables. Without the `ee/` directories, or without a valid key, `features` is empty and SerOps is the complete Community edition.

```json
{
  "enterprise_available": true,
  "features": ["saml"],
  "license": {"status": "valid", "licensee": "Acme Corp", "expires": "2027-10-21", "features": ["saml"]}
}
```

### Enterprise License Key

```
GET    /api/ee/license/
PUT    /api/ee/license/
DELETE /api/ee/license/
```

Requires `license.manage` (platform staff, or the admin of a single-organisation install), and only exists when the Enterprise code is installed. `GET` describes the installed license (`status`: `none`, `valid`, `expired` or `invalid`), never the key itself. `PUT` installs a key, as JSON `{"license": "<key>"}` or a multipart `file` upload, replacing any previous one; a key that is not genuine or already expired is refused with `400` and the reason. `DELETE` removes it. Both are recorded in the audit log (`SETTINGS_CHANGE`, `setting: enterprise_license`).

The key is a JSON document signed with Ed25519, verified offline on the server: no license server, no network call, no telemetry. When it expires, Enterprise features switch off; no data is deleted.

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
