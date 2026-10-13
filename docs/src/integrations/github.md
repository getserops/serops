# GitHub Integration

Connect GitHub repositories to SerOps for code change tracking and CI/CD monitoring.

## Prerequisites

- GitHub repository access
- Personal Access Token with `repo` scope
- (Optional) Admin access for webhook configuration

---

## Setup

Configuration is managed in **Settings → Global Integrations**.

1. In GitHub: **Settings → Developer settings → Personal access tokens → Tokens (classic)**
2. Generate token with scopes:
   - `repo` - Full repository access
   - `workflow` - (Optional) For GitHub Actions
3. In SerOps: **Settings → Global Integrations**
4. Click **+ Add Integration** and select **GitHub**
5. Enter:
   - **Name**: Identifier (e.g. "My GitHub")
   - **GitHub URL**: Leave blank for github.com, or enter GitHub Enterprise URL
   - **Access Token**: Your PAT
6. Click **Test Connection** to verify
7. Click **Save**

Once added, you can select this integration when creating services via the **Add Service Wizard**.

---

## What Gets Synced

| Data | Description | Method |
|------|-------------|--------|
| **Commits** | Recent commits with diffs | Webhook + API |
| **Pull Requests** | PR details and status | Webhook |
| **Pipelines** | GitHub Actions workflows | Webhook |
| **Deployments** | Deployment events | Webhook |

---

## Webhook Configuration

### Automatic Setup

SerOps auto-generates a webhook secret when you create a CI/CD binding. To register the webhook with GitHub automatically:

1. Navigate to the service's CI/CD binding
2. Click **Setup Webhook** (or call `POST /api/projects/cicd-bindings/{id}/setup-webhook/`)

### Manual Setup

1. In SerOps, find the CI/CD binding for your service and copy the **Webhook URL** and **Secret**
   - URL format: `https://your-serops.com/api/webhooks/github/{binding_id}/`
   - Secret is auto-generated on binding creation
2. In GitHub: **Settings → Webhooks**
3. Add webhook:
   - **Payload URL**: The binding-specific URL from step 1
   - **Content type**: `application/json`
   - **Secret**: The auto-generated secret from step 1
   - **Events**:
     - ✅ Push
     - ✅ Pull requests
     - ✅ Workflow runs
     - ✅ Deployments

---

## GitHub Enterprise

For GitHub Enterprise Server:

1. Enter your enterprise URL (e.g., `https://github.company.com`)
2. Ensure API endpoint is accessible from SerOps
3. Use a token generated on the Enterprise instance

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Bad credentials" | Token expired or invalid scope |
| "Not found" | Check repository name format (`owner/repo`) |
| "Rate limit exceeded" | Wait 1 hour or use organisation token |
| "SSL certificate verify failed" | Add enterprise CA cert to trust store |
| "Webhook not receiving" | Check firewall allows inbound from GitHub IPs |
