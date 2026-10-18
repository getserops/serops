---
seo_title: "Azure DevOps integration (Repos and Pipelines)"
description: "Connect Azure DevOps Repos and Pipelines to SerOps for code changes, pipeline runs and deployment visibility."
---
# Azure DevOps Integration

Connect Azure DevOps to SerOps for repository tracking, pipeline monitoring, and deployment visibility.

## Prerequisites

- Azure DevOps organization access
- Personal Access Token (PAT) with appropriate scopes
- (Optional) Service hook configuration access

---

## Setup

Configuration is managed in **Integrations**.

1. In Azure DevOps: **User Settings → Personal Access Tokens**
2. Create a new token with scopes:
   - `Code: Read`
   - `Build: Read`
   - `Release: Read`
   - `Project and Team: Read`
3. In SerOps: **Integrations**
4. Click **+ Add Integration** and select **Azure DevOps**
5. Enter:
   - **Name**: Identifier (e.g., "Corporate Azure DevOps")
   - **Organisation**: Your Azure DevOps organization name
   - **Access Token**: The PAT created above
6. Click **Test Connection** to verify
7. Click **Save**

### Organisation Parameter

The **Organisation** field is critical for Azure DevOps:

```
URL: https://dev.azure.com/{organisation}
Example: https://dev.azure.com/my-company
Organisation: my-company
```

SerOps uses this to construct API URLs and token generation links.

### Choosing the repository

An Azure DevOps project can hold several Git repositories, and they are often named differently from the project. When you link a service, the picker lists every repository in the organisation as **project / repository**.

If you enter the repository by hand (onboarding), use:

```
organisation/project/repository
Example: my-company/Shop/payments-api
```

`organisation/project` still works and means the repository named like the project (Azure's default repository).

### How diffs are read

Azure DevOps has no API that returns a commit's diff, so SerOps fetches each changed file before and after the commit and computes the diff itself. This takes one request for the commit plus two per file, for the first 10 files of each commit; binary files and files over 200 KB are skipped. Only the diff is kept. See [What SerOps reads from your repositories](../security/data-protection.md#what-serops-reads-from-your-repositories).

---

## What Gets Synced

| Data | Description | Method |
|------|-------------|--------|
| **Commits** | Recent commits with diffs | Webhook + API |
| **Pull Requests** | PR status and reviews | Webhook |
| **Build Pipelines** | Azure Pipelines status | Webhook |
| **Deployments** | Release pipeline deployments | Webhook |

---

## Webhook / Service Hook Configuration

### Automatic Setup

SerOps auto-generates a webhook secret when you create a CI/CD binding. To get the webhook URL:

1. Navigate to the service's CI/CD binding
2. Click **Setup Webhook** (or call `POST /api/projects/cicd-bindings/{id}/setup-webhook/`)
3. Copy the returned URL for manual configuration in Azure DevOps

> **Note**: Azure DevOps does not support programmatic webhook creation, so the URL must be configured manually in Service Hooks.

### Manual Setup

1. In SerOps, find the CI/CD binding for your service and copy the **Webhook URL** and **Secret**
   - URL format: `https://your-serops.com/api/webhooks/azure-devops/{binding_id}/`
   - Secret is auto-generated on binding creation (used as Basic Auth password)
2. In Azure DevOps: **Project Settings → Service hooks**
3. Create a new subscription:
   - **Service**: Web Hooks
   - **Trigger events**:
     - ✅ Code pushed
     - ✅ Pull request created/updated
     - ✅ Build completed
     - ✅ Release deployment completed
   - **URL**: The binding-specific URL from step 1
   - **Basic authentication password**: The auto-generated secret from step 1
   - **Resource details to send**: All

---

## Azure DevOps Server (On-Premises)

For Azure DevOps Server (formerly TFS):

1. Enter your server URL (e.g., `https://tfs.company.com/tfs`)
2. Include the collection name if required
3. Ensure network access from SerOps instance

---

## Project Selection

When creating a service, you'll select:

1. **Integration**: Your Azure DevOps integration
2. **Project**: Azure DevOps project (e.g., "MyProject")
3. **Repository**: Repository within the project

SerOps lists available projects and repos via the API.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "401 Unauthorized" | PAT expired or missing scopes |
| "TF400813: Resource not available" | Check organisation name spelling |
| "Project not found" | Verify project access for your user |
| "No repositories listed" | Check `Code: Read` scope on PAT |
| "Webhook not triggering" | Verify service hook is enabled and URL accessible |

### Common PAT Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Works initially, then fails | PAT expired | Set longer expiration or renew |
| Can see projects but not repos | Missing `Code: Read` | Regenerate PAT with correct scopes |
| "VS30063: Not authorized" | Wrong organisation | Check org name matches your Azure DevOps URL |
