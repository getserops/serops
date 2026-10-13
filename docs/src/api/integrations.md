# Integrations API

Endpoints for managing global SCM and CI/CD provider integrations at the organisation level.

Global integrations define the connection to an external provider (e.g., GitLab, GitHub, Jenkins). Individual services are then linked to these integrations via [integration bindings](projects.md#integration-bindings).

## List Supported Provider Types

```
GET /api/providers/integrations/provider-types/
```

Returns the catalogue of supported SCM/CI-CD provider types and their required credential fields. Use this to render the "Add Integration" form.

**Response:**

```json
{
  "types": [
    {"code": "gitlab", "name": "GitLab", "fields": ["base_url", "access_token"]},
    {"code": "github", "name": "GitHub", "fields": ["access_token"]}
  ]
}
```

## List Integrations

```
GET /api/providers/integrations/
```

Returns all configured integrations for the organisation.

## Create Integration

```
POST /api/providers/integrations/
```

**Request body:**

```json
{
  "name": "Corporate GitLab",
  "provider_type": "gitlab",
  "base_url": "https://gitlab.company.com",
  "credentials": {
    "access_token": "glpat-xxx"
  }
}
```

## Test Connection (Before Saving)

```
POST /api/providers/integrations/test/
```

**Request body:**

```json
{
  "provider_type": "gitlab",
  "base_url": "https://gitlab.company.com",
  "access_token": "glpat-xxx",
  "credentials": {}
}
```

**Response:**

```json
{
  "success": true,
  "message": "Connection verified successfully",
  "user_info": {"username": "admin", "name": "Admin User"}
}
```

Tests the connection without persisting the integration. Use this to validate credentials before creating.

## Verify Existing Integration

```
POST /api/providers/integrations/{id}/verify/
```

Re-tests the stored credentials and updates the `verified_at` timestamp.

## Health Check (Single Integration)

```
POST /api/providers/integrations/{id}/health-check/
```

Runs a live connectivity check against the stored credentials and updates `last_health_check` + `last_health_status` on the record.

## Health Check (All Integrations)

```
GET /api/providers/integrations/health-check-all/
```

Runs a connectivity check against every configured SCM/CI-CD integration for the organisation and returns their statuses in one call. Useful for a status dashboard.

## Usage Summary (All Integrations)

```
GET /api/providers/integrations/usage-summary/
```

Returns a compact summary across all integrations — how many services each one backs, when it was last synced, and whether it's healthy. Powers the Integrations index page.

## Get Usage Statistics (Single Integration)

```
GET /api/providers/integrations/{id}/usage/
```

**Response:**

```json
{
  "services_count": 3,
  "services": [
    {"id": 1, "name": "backend", "project": "demo"},
    {"id": 2, "name": "frontend", "project": "demo"}
  ],
  "last_sync": "2026-01-21T10:30:00Z"
}
```

Returns which services are using this integration.

## Sync Integration

```
POST /api/providers/integrations/{id}/sync/
```

Forces a refresh of the connection status and repository list.

## Update Integration

```
PATCH /api/providers/integrations/{id}/
```

**Request body:**

```json
{
  "name": "New Name",
  "credentials": {"access_token": "new-token"}
}
```

## Delete Integration

```
DELETE /api/providers/integrations/{id}/
```

Removes the integration. This will fail if any services still have bindings referencing it.

## List Repositories

```
GET /api/providers/integrations/{id}/repos/
```

Returns the list of repositories accessible via this integration. Use this when creating SCM bindings to discover available repositories.

---

## Related

- [Projects & Services](projects.md) -- SCM/CI-CD bindings that reference these integrations
- [Observability](observability.md) -- Log and metric provider connections
- [API Overview](overview.md) -- Base URL, response format, and error codes
