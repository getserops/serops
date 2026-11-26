---
seo_title: "Bitbucket integration (code and Pipelines)"
description: "Connect Bitbucket Cloud to SerOps for commits and Bitbucket Pipelines runs linked to incidents."
---
# Bitbucket Integration

Connect Bitbucket repositories to SerOps for code change tracking and pipeline monitoring.

## Prerequisites

- Bitbucket Cloud (SerOps uses the Bitbucket Cloud 2.0 API; Bitbucket Server and Data Center are not supported)
- A Bitbucket **access token** (repository or workspace) with repository read access
- (Optional) Webhook configuration access

---

## Setup

Configuration is managed in **Integrations**.

### Bitbucket Cloud

!!! warning "Use an access token, not an app password"
    SerOps sends the Bitbucket credential as a Bearer token. Bitbucket
    accepts that from an access token, not from an app password, so an
    app password fails the connection test. The SerOps form still labels
    the field **App Password**: paste the access token there.

1. In Bitbucket, create an access token:
   - for one repository: **Repository settings → Access tokens**;
   - for several repositories: a workspace access token, in the
     workspace settings.

   Give it these scopes:
   - `Repositories: Read`
   - `Pipelines: Read` (for CI/CD)
   - `Webhooks: Read and write` (optional, for auto-setup)
2. In SerOps: **Integrations**
3. Click **Add Integration** and select **Bitbucket**
4. Enter:
   - **Name**: Identifier (e.g., "Team Bitbucket")
   - **Bitbucket URL**: Leave blank for bitbucket.org
   - **Username**: required by the form, not used to sign in; your
     Bitbucket username is fine
   - **App Password**: the access token created above
5. Click **Test Connection** to verify
6. Click **Create Integration**

---

## What Gets Synced

| Data | Description | Method |
|------|-------------|--------|
| **Commits** | Recent commits with diffs | Webhook + API |
| **Pipelines** | Bitbucket Pipelines status | Webhook |

> **Note**: Bitbucket **Deployments** tracking is not currently supported. Use pipelines for deployment visibility.

---

## Webhook Configuration

### Automatic Setup

SerOps auto-generates a webhook secret when you create a CI/CD binding and
sets it on the Bitbucket webhook it creates, so Bitbucket signs every
delivery. SerOps 1.4.0 and earlier created the webhook without a secret, so
every delivery was refused; run **Setup Webhook** again on an existing
binding to replace it. To register the webhook with Bitbucket automatically:

1. Navigate to the service's CI/CD binding
2. Click **Setup Webhook** (or call `POST /api/projects/cicd-bindings/{id}/setup-webhook/`)

### Manual Setup

1. In SerOps, find the CI/CD binding for your service and run **Setup Webhook**
   (`POST /api/projects/cicd-bindings/{id}/setup-webhook/`): it returns the
   **Webhook URL** and the binding's **webhook secret**
   - URL format: `https://your-serops.com/api/webhooks/bitbucket/{binding_id}/`
2. In Bitbucket: **Repository Settings → Webhooks**
3. Add webhook:
   - **Title**: SerOps Integration
   - **URL**: The binding-specific URL from step 1
   - **Secret**: the webhook secret from step 1. Bitbucket then signs each
     delivery (`X-Hub-Signature: sha256=…`, HMAC-SHA256 of the body), and
     SerOps refuses any delivery that is unsigned or signed with another
     secret
   - **Triggers**:
     - ✅ Build status: Created, Updated ("Updated" carries the final result).
       This URL refuses every other event with 403.

Commits pushed to the repository arrive on a separate repository webhook,
`https://your-serops.com/api/webhooks/scm/{scm_binding_id}/`, which
`POST /api/projects/scm-bindings/{id}/setup-webhook/` registers with the
repository connection's own secret.

---

Events are matched to the binding's repository (`workspace/repo` or its
UUID): a workspace-level webhook's events for other repositories are
acknowledged and ignored.

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
| "Invalid credentials" | Use an access token, not an app password (see the warning under Setup), and check its scopes |
| "Repository not found" | Check workspace/repo path format |
| "Rate limit exceeded" | Use team-level credentials or wait |
