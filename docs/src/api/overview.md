---
seo_title: "REST API overview"
description: "The SerOps REST API: authentication headers, response format, pagination and error codes."
---
# API Overview

Complete REST API documentation for SerOps.

## Base URL

All endpoints are prefixed with `/api/`.

## Authentication

All API requests (except login and register) require a valid authentication token (Knox):

```
Authorization: Token <your-token>
```

Tokens are obtained via the [Login endpoint](authentication.md#login) and follow a sliding expiration policy:

- **Token lifetime**: 30 days from creation
- **Auto-refresh**: Token is automatically extended on each authenticated request (at most once per minute)
- **Idle timeout**: A token left unused for longer than the organisation's session timeout (default 8 hours) is deleted, and the next request returns `401`. 30 days is the ceiling, and the only limit when the timeout is set to "Never".

## Response Format

There is no single envelope: the shape is set per endpoint, and each page shows it.

- Batch lists return `{"results": [...], "pagination": {"total", "limit", "offset", "next_offset", "previous_offset"}}`.
- Issue lists return `{"results": [...], "pagination": {"total_issues", "page", "page_size", "total_pages", "next_page", "previous_page"}, "summary": {...}}`.
- Many other lists, such as notifications and escalation rules, return a bare JSON array.

### Error Response

Most errors return an `error` key:

```json
{
  "error": "Short description of what went wrong"
}
```

Serializer validation errors (`400`) return the DRF default: one list of messages per field.

### Common HTTP Status Codes

| Code | Meaning |
|------|---------|
| `200` | Success |
| `201` | Created |
| `204` | Deleted (no content) |
| `400` | Bad request (validation error) |
| `401` | Unauthorized (missing or invalid token) |
| `403` | Forbidden (insufficient permissions, disabled registration, etc.) |
| `404` | Resource not found |
| `429` | Rate limited (see below) |

## Rate Limiting

The endpoints below are throttled with DRF scoped rate limits, counted per client IP (the SCIM limit counts per SCIM token). Other endpoints are not rate-limited.

| Scope | Endpoint | Rate |
|-------|----------|------|
| `auth_login` | `POST /api/auth/login` | 10 / minute |
| `auth_register` | `POST /api/auth/register` | 5 / hour |
| `auth_password_reset` | `POST /api/auth/password/forget`, `POST /api/auth/accept/password` | 5 / hour |
| `auth_sso_init` | `POST /api/auth/sso/init` | 20 / hour |
| `auth_sso_exchange` | `POST /api/auth/sso/exchange` | 30 / hour |
| `auth_demo_login` | `POST /api/auth/demo-login` | 30 / minute |
| `auth_saml_acs` | `POST /api/ee/saml/{sp_id}/acs/` | 60 / minute |
| `scim` | `/api/ee/scim/v2/*` | 600 / minute |
| `otlp_ingest` | `POST /api/traces/v1/traces` | 3000 / minute |
| `alert_webhook` | `POST /api/webhooks/alerts/{source}/{org_id}/` | 300 / minute |
| `webhook_deployment` | `POST /api/providers/webhook/{deployment,argocd,flux}/{binding_id}/` | 600 / hour |

Login also returns `429` after repeated failed sign-ins for one account: 10 from one address, or 100 in all, within 15 minutes.

When rate-limited the API returns `429 Too Many Requests` with a `Retry-After` header telling the client when it may try again.

## API Sections

| Section | Description |
|---------|-------------|
| [Authentication](authentication.md) | Login, register, SSO, password management |
| [Projects & Services](projects.md) | Projects CRUD, services, SCM/CI-CD bindings |
| [Batches & Data](batches.md) | Batch listing, details, redaction |
| [Issues](issues.md) | Issue management, muting, resolution |
| [AI & Chat](ai.md) | AI generation, batch analysis, chat sessions |
| [Notifications](notifications.md) | Alerts, preferences, escalation rules |
| [Integrations](integrations.md) | Global SCM/CI-CD provider integrations |
| [Observability](observability.md) | Log and metric provider connections |
| [Clusters](clusters.md) | Kubernetes cluster registration |
| [Traces](traces.md) | OTLP trace ingestion, ingest keys, stored traces |
| [Settings & Admin](settings.md) | Organisation settings, security, audit |
| [Dashboard & Analytics](analytics.md) | Health scores, trends, MTTR, deployments |
