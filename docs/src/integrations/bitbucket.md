---
seo_title: "Bitbucket integration (code and Pipelines)"
description: "Connect Bitbucket Cloud or Server to SerOps for commits and Bitbucket Pipelines runs linked to incidents."
---
# Bitbucket Integration

Connect Bitbucket repositories to SerOps for code change tracking and pipeline monitoring.

## Prerequisites

- Bitbucket Cloud or Bitbucket Server/Data Center
- App Password with repository read access
- (Optional) Webhook configuration access

---

## Setup

Configuration is managed in **Settings → Global Integrations**.

### Bitbucket Cloud

1. In Bitbucket: **Personal Settings → App passwords**
2. Create an App Password with permissions:
   - `Repositories: Read`
   - `Pipelines: Read` (for CI/CD)
   - `Webhooks: Read and write` (optional, for auto-setup)
3. In SerOps: **Settings → Global Integrations**
4. Click **+ Add Integration** and select **Bitbucket**
5. Enter:
   - **Name**: Identifier (e.g., "Team Bitbucket")
   - **Bitbucket URL**: Leave blank for bitbucket.org
   - **Username**: Your Bitbucket username (not email)
   - **App Password**: The app password created above
6. Click **Test Connection** to verify
7. Click **Save**

### Bitbucket Server / Data Center

1. In Bitbucket Server: **Manage Account → HTTP Access Tokens**
2. Create a token with:
   - `Repository read`
   - `Project read`
3. In SerOps: Enter your server URL (e.g., `https://bitbucket.company.com`)

---

## What Gets Synced

| Data | Description | Method |
|------|-------------|--------|
| **Commits** | Recent commits with diffs | Webhook + API |
| **Pull Requests** | PR status and metadata | Webhook |
| **Pipelines** | Bitbucket Pipelines status | Webhook |

> **Note**: Bitbucket **Deployments** tracking is not currently supported. Use pipelines for deployment visibility.

---

## Webhook Configuration

### Automatic Setup

SerOps auto-generates a webhook secret when you create a CI/CD binding. To register the webhook with Bitbucket automatically:

1. Navigate to the service's CI/CD binding
2. Click **Setup Webhook** (or call `POST /api/projects/cicd-bindings/{id}/setup-webhook/`)

### Manual Setup

1. In SerOps, find the CI/CD binding for your service and copy the **Webhook URL**
   - URL format: `https://your-serops.com/api/webhooks/bitbucket/{binding_id}/`
2. In Bitbucket: **Repository Settings → Webhooks**
3. Add webhook:
   - **Title**: SerOps Integration
   - **URL**: The binding-specific URL from step 1
   - **Triggers**:
     - ✅ Repository: Push
     - ✅ Pull Request: Created, Updated, Merged
     - ✅ Build status: Created, Updated (for Pipelines)

---

## Workspace Configuration

For Bitbucket Cloud, you may need to specify the workspace:

```
Workspace: my-team
Repository: my-repo
Full path: my-team/my-repo
```

SerOps will prompt for workspace when listing repositories.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Invalid credentials" | Ensure username (not email) and app password are correct |
| "Repository not found" | Check workspace/repo path format |
| "Rate limit exceeded" | Use team-level credentials or wait |
| "SSL error" (Server) | Add Bitbucket Server CA to trust store |
