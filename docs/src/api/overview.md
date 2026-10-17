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
- **Auto-refresh**: Token is automatically extended on each authenticated request (at most once per hour)
- **Hard limit**: Re-login required after 30 days of inactivity

## Response Format

### Success Response

```json
{
  "results": [...],
  "count": 42,
  "next": "https://api.serops.ai/api/resource/?page=2",
  "previous": null
}
```

### Error Response

```json
{
  "error": "Short title",
  "detail": "Verbose description of what went wrong"
}
```

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

Sensitive authentication endpoints are throttled per client IP via DRF's `ScopedRateThrottle`. Other endpoints are not globally rate-limited today.

| Scope | Endpoint | Rate |
|-------|----------|------|
| `auth_login` | `POST /api/auth/login` | 10 / minute |
| `auth_register` | `POST /api/auth/register` | 5 / hour |
| `auth_password_reset` | `POST /api/auth/password/forget` | 5 / hour |
| `auth_sso_init` | `POST /api/auth/sso/init` | 20 / hour |

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
| [Settings & Admin](settings.md) | Organisation settings, security, audit |
| [Dashboard & Analytics](analytics.md) | Health scores, trends, MTTR, deployments |
