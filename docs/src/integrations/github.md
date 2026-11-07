---
seo_title: "GitHub integration (code, Actions, deploys)"
description: "Connect GitHub to SerOps for commits, pull requests, GitHub Actions runs and deployments, including GitHub Enterprise."
---
# GitHub Integration

Connect GitHub repositories to SerOps for code change tracking and CI/CD monitoring.

## Prerequisites

- Access to the repositories you want SerOps to read
- A fine-grained personal access token, read-only (see below)
- (Optional) Admin access to the repository, to set up a webhook

---

## Create the token

Use a **fine-grained** token limited to the repositories SerOps needs. A classic
token with the `repo` scope can read and write every private repository of the
account; SerOps never writes to GitHub.

1. In GitHub: **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
2. **Repository access**: *Only select repositories*, and pick yours
3. **Repository permissions**, all **Read-only**:
   - Contents (commits and diffs)
   - Pull requests
   - Actions (workflow runs)
   - Deployments
   - Metadata is added by GitHub
4. Only if you want SerOps to register the webhook for you: Webhooks, **Read and write**

---

## Setup

1. In SerOps: **Settings → Integrations → Source Control**
2. Click **Add Integration** and select **GitHub**
3. Enter:
   - **Integration Name**: e.g. "My GitHub"
   - **GitHub URL**: leave blank for github.com, or enter your GitHub Enterprise URL
   - **Personal Access Token**: the token from above
4. Click **Test Connection**, then **Create Integration**

### Connect a repository to a service

Pick the repository when you create a service in the **Add Service Wizard**, or
later for an existing service: **Projects → Services → View Details → Connect
repository**, choose the integration and the repository, then **Connect**.

### Add the GitHub Actions pipeline

In the same service details, click **Add Pipeline**, choose the GitHub
integration and the type (e.g. *Deploy*), and enter the repository as the
pipeline ID: `owner/repo`. SerOps follows the workflow runs of that repository.

---

## What Gets Synced

| Data | Description | Without a webhook | With a webhook |
|------|-------------|-------------------|----------------|
| **Commits** | Message, author, diff | **Sync** button in the service details, and the deploy commits found by polling | On every push |
| **Pull Requests** | PR details and status | — | On every PR event |
| **Pipelines** | GitHub Actions workflow runs | Polled every 10 minutes | On every run |
| **Deployments** | Successful deploy runs, with their commit | Polled every 10 minutes | On every run |

### Without a webhook

A webhook needs GitHub to reach your SerOps over the internet. When it cannot
(SerOps behind a firewall, or on a laptop), SerOps still works: it polls the
GitHub Actions runs of each pipeline, records each successful deploy with its
commit, and the **Sync** button in the service details fetches the recent
commits. An investigation then shows the commit behind an outage on the
analysis page, in the **Code changes** tab. Pull requests need the webhook.

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
| "Bad credentials" | Token expired, or not allowed on this repository |
| Repository missing from the list | Add it to the token's *Repository access* |
| "Not found" | Check repository name format (`owner/repo`) |
| "Rate limit exceeded" | Wait 1 hour or use organisation token |
| "SSL certificate verify failed" | Add enterprise CA cert to trust store |
| "Webhook not receiving" | Check firewall allows inbound from GitHub IPs |
