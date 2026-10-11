# GitLab Integration

Connect GitLab to SerOps for pipeline logs, code changes, and deployment tracking.

## Prerequisites

- GitLab project with API access
- Access token with `api` scope
- Admin access to configure webhooks

---

## Setup

All integrations must be configured in **Settings** before they can be used in projects.

1. Navigate to **Settings → Integrations**
2. Click **+ Add Integration** and select **GitLab**
3. Enter:
    *   **Name**: Identifier for this integration (e.g. "Corporate GitLab")
    *   **GitLab URL**: e.g., `https://gitlab.com` or your self-hosted instance
    *   **Access Token**: Token with `api` scope (Admin or Project level)
4. Click **Connect**

Once added, this integration will be available to select when creating services in any project/

---

## Webhook Configuration

Webhooks enable real-time updates.

### Automatic Setup

SerOps auto-generates a webhook secret when you create a CI/CD binding. To register the webhook with GitLab automatically:

1. Navigate to the service's CI/CD binding
2. Click **Setup Webhook** (or call `POST /api/cicd-bindings/{id}/setup-webhook/`)
3. SerOps registers the webhook URL and secret with GitLab via API

### Manual Setup

1. In SerOps, find the CI/CD binding for your service and copy the **Webhook URL** and **Secret Token**
   - URL format: `https://your-serops.com/api/webhooks/gitlab/{binding_id}/`
   - Secret is auto-generated on binding creation
2. In GitLab: **Settings → Webhooks**
3. Add webhook:
   - **URL**: The binding-specific URL from step 1
   - **Secret Token**: The auto-generated secret from step 1
   - **Triggers**:
     - ✅ Push events
     - ✅ Pipeline events
     - ✅ Deployment events

---

## What Gets Synced

| Data | Description | Frequency |
|------|-------------|-----------|
| **Pipelines** | CI/CD pipeline status | Real-time (webhook) |
| **Jobs** | Individual job logs + **traces** | On job complete |
| **Deployments** | Deployment events | Real-time (webhook) + 10min sync |
| **Code Changes** | Commits and diffs | On push/pipeline |

### CI/CD Trace Capture

For **failed jobs**, SerOps automatically fetches the full job trace:

1. Webhook notifies SerOps of job failure
2. SerOps calls GitLab API to fetch job trace
3. Trace stored as an **Enriched Event Document** in your configured Log Provider (Elasticsearch, Loki, Datadog, etc.):
   - `serops_meta` - Standardized metadata for correlation
   - `error_lines` - Filtered error summary (max 20 lines) used for AI analysis
   - `trace` - Full output (truncated) attached to the event document
   - `environment` - Detected from branch (develop → development)

### Deployment Sync Fallback

If webhooks fail, SerOps has automatic fallback:

- **Celery beat** syncs deployments every 10 minutes
- Fetches recent pipelines (last 2 hours) directly from GitLab API
- Creates deployment records for any missed webhooks

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Invalid token" | Regenerate token with correct scopes |
| "Project not found" | Check project ID is correct |
| "Webhook timeout" | Verify SerOps URL is accessible |
| "No data syncing" | Check webhook events are enabled |

---

## API Reference

### Create Global Integration
```
POST /api/providers/integrations/
{
  "name": "Corporate GitLab",
  "provider_type": "gitlab",
  "base_url": "https://gitlab.com",
  "credentials": {
    "access_token": "glpat-xxx"
  }
}
```

### Test Connection (Before Saving)
```
POST /api/providers/integrations/test/
{
  "provider_type": "gitlab",
  "base_url": "https://gitlab.com",
  "access_token": "glpat-xxx",
  "credentials": {}
}
```

### Verify Existing Integration
```
POST /api/providers/integrations/{id}/verify/
```

### List Repositories
```
GET /api/providers/integrations/{id}/repos/
```

See the full [Integrations API](../api/integrations.md) for all integration endpoints.
