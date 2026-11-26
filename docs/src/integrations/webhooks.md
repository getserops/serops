---
seo_title: "CI/CD webhook setup"
description: "Set up CI/CD and deployment webhooks for SerOps: one URL per binding, signature checks and per-provider instructions."
---
# Webhook Setup Guide

SerOps receives CI/CD pipeline events and deployment events via webhooks. Every webhook URL is tied to a specific **CI/CD Binding** you create in SerOps under **Projects → Services → CI/CD Bindings**. The binding provides multi-tenancy isolation (only your org's data flows to your batches) and carries the per-binding secret that every request must prove it knows.

This page covers:

- Finding your webhook URL in SerOps
- Configuring the webhook in each supported provider
- The generic deployment webhook (ArgoCD, Flux, Helm, Terraform, kubectl)
- Signature and token checks (required on every request)

---

## Where to find your webhook URL

1. Log in to SerOps as an admin
2. Navigate to **Projects → \<your project\> → Services → \<service\> → CI/CD Bindings**
3. Create a binding (Provider = the tool you're wiring up, Binding Type = `build` / `deploy` / etc.)
4. Copy the **Webhook URL** shown on the binding detail page. It looks like:

```
https://your-serops.com/api/webhooks/<provider>/<binding_id>/
```

where `<provider>` is `gitlab`, `github`, `bitbucket`, `azure-devops` or `jenkins`, or, for the generic deployment webhook:

```
https://your-serops.com/api/providers/webhook/deployment/<binding_id>/
```

SerOps generates a **Webhook Secret** when the binding is created; it cannot be left out. The create response returns it, and so does `POST /api/projects/cicd-bindings/{id}/setup-webhook/` for providers configured by hand (Jenkins, Azure DevOps, Bitbucket, Argo CD, Flux). Every request must prove it knows the secret, or SerOps answers **403 Forbidden** (see [Signature verification](#signature-verification) below).

---

## Per-provider setup

### GitHub Actions

**Native webhook** (repo → Settings → Webhooks → Add webhook):

- **Payload URL**: paste your SerOps webhook URL
- **Content type**: `application/json`
- **Secret**: paste your binding's Webhook Secret
- **Which events**: `Workflow runs`. SerOps reads completed workflow runs of the bound repository and ignores every other event on this URL.

### GitLab CI

**Project webhook** (project → Settings → Webhooks → Add webhook):

- **URL**: your SerOps webhook URL
- **Secret Token**: paste your binding's Webhook Secret
- **Trigger**: `Job events` and `Pipeline events`
- **SSL verification**: leave enabled

### Bitbucket Pipelines

**Repository webhook** (Repository settings → Webhooks → Add webhook):

- **URL**: your SerOps webhook URL
- **Status**: Active
- **Triggers**: `Build status created` and `Build status updated`. SerOps refuses any other event on this URL with 403.
- **Secret**: paste your binding's Webhook Secret in the `Secret` field

### Azure DevOps Pipelines

**Service hook** (Project settings → Service hooks → Create subscription):

- **Service**: Web Hooks
- **Trigger**: `Run state changed` and `Release deployment completed`. SerOps ignores other event types.
- **URL**: your SerOps webhook URL
- **Basic authentication password**: the binding's Webhook Secret (the username can be empty)

### Jenkins

Jenkins doesn't have first-class outbound webhooks. Use a post-build step in your `Jenkinsfile` with the **HTTP Request** plugin, and send the binding's secret in the `X-Jenkins-Token` header:

```groovy
pipeline {
    agent any
    stages {
        stage('Build') {
            steps {
                sh 'make build'
            }
        }
    }
    post {
        always {
            httpRequest(
                url: "https://your-serops.com/api/webhooks/jenkins/${SEROPS_BINDING_ID}/",
                httpMode: 'POST',
                contentType: 'APPLICATION_JSON',
                customHeaders: [[name: 'X-Jenkins-Token', value: "${SEROPS_WEBHOOK_TOKEN}"]],
                requestBody: """{
                    "job_name": "${env.JOB_NAME}",
                    "build_number": "${env.BUILD_NUMBER}",
                    "status": "${currentBuild.currentResult}",
                    "branch": "${env.GIT_BRANCH ?: ''}",
                    "commit": "${env.GIT_COMMIT ?: ''}",
                    "environment": "production"
                }"""
            )
        }
    }
}
```

Store `SEROPS_BINDING_ID` and `SEROPS_WEBHOOK_TOKEN` (the binding's Webhook Secret) as Jenkins credentials. The [Jenkins page](jenkins.md#webhook-configuration-optional) explains each field.

---

## Generic deployment webhook

For tools that emit deployment events but don't fit a "CI/CD pipeline" shape — **ArgoCD Notifications**, **Flux Notification Controller**, **Helm post-install / post-upgrade hooks**, **Terraform apply post-hooks**, custom `kubectl` rollout wrappers — use the generic deployment webhook:

```
POST /api/providers/webhook/deployment/<binding_id>/
Content-Type: application/json
X-SerOps-Signature: sha256=<hmac-hex>       # required (or Authorization: Bearer <binding secret>)

{
  "commit_sha":  "abc123def456",
  "environment": "production",
  "version":     "v2.3.1",
  "deployed_at": "2026-10-25T14:25:00Z",
  "actor":       "argocd",
  "notes":       "auto-sync from main"
}
```

- **Required**: `commit_sha` (7-64 hex chars), `environment`: the name of one of the project's environments, any name (`qa`, `uat`, `preview`, `eu-prod`; 1-50 letters, digits, `.`, `_`, `-`). `prod`/`prd`/`live`, `stage`/`stg`/`preprod` and `dev`/`develop` are recorded as `production`, `staging` and `development`, and a project environment named `prod` finds them.
- **Optional**: `version`, `deployed_at` (defaults to now), `actor` (defaults to `external`), `notes`.
- If the commit hasn't been ingested via an SCM webhook yet, SerOps creates a stub `CodeChange` so the deployment records anyway — the diff/message hydrate when the SCM webhook eventually arrives.

### ArgoCD Notifications

Add a template + trigger in `argocd-notifications-cm`:

```yaml
template.app-deployed: |
  webhook:
    serops:
      method: POST
      body: |
        {
          "commit_sha": "{{.app.status.sync.revision}}",
          "environment": "{{.app.spec.destination.namespace}}",
          "version":     "{{.app.status.sync.revision}}",
          "actor":       "argocd",
          "notes":       "app={{.app.metadata.name}}"
        }
trigger.on-deployed: |
  - description: Application is synced and healthy
    send: [app-deployed]
    when: app.status.operationState != nil and app.status.operationState.phase in ['Succeeded'] and app.status.health.status == 'Healthy'
service.webhook.serops: |
  url: https://your-serops.com/api/providers/webhook/deployment/<binding_id>/
  headers:
  - name: Content-Type
    value: application/json
  # ArgoCD Notifications cannot compute an HMAC, so send the binding's
  # webhook secret as a bearer token, read from argocd-notifications-secret.
  - name: Authorization
    value: Bearer $serops-webhook-secret
```

Then annotate each app to use the trigger:

```yaml
metadata:
  annotations:
    notifications.argoproj.io/subscribe.on-deployed.serops: ""
```

### Flux Notification Controller

Flux events have their own endpoint that understands Flux's payload and
its `generic-hmac` signature, with no adapter needed. See
[GitOps deploy events → Flux CD](gitops.md#flux-cd).

### Helm hooks

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ .Release.Name }}-serops-notify
  annotations:
    helm.sh/hook: post-install,post-upgrade
    helm.sh/hook-weight: "10"
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: notify
          image: curlimages/curl:8.4.0
          command: ["sh", "-c"]
          args:
            - |
              PAYLOAD='{"commit_sha":"{{ .Values.image.tag }}","environment":"{{ .Release.Namespace }}","actor":"helm","version":"{{ .Chart.AppVersion }}"}'
              curl -fsSL -X POST -H "Content-Type: application/json" \
                -H "Authorization: Bearer $SEROPS_WEBHOOK_SECRET" \
                -d "$PAYLOAD" \
                "https://your-serops.com/api/providers/webhook/deployment/<binding_id>/"
```

### Terraform post-apply

Add a `null_resource` at the tail of the deploy module:

```hcl
resource "null_resource" "notify_serops" {
  provisioner "local-exec" {
    command = <<EOT
curl -fsSL -X POST -H "Content-Type: application/json" \
  -H "Authorization: Bearer $SEROPS_WEBHOOK_SECRET" \
  -d '{"commit_sha":"${var.git_sha}","environment":"${var.environment}","actor":"terraform","version":"${var.release_tag}"}' \
  "${var.serops_webhook_url}"
EOT
  }
  triggers = { always_run = timestamp() }
}
```

Both examples read the binding's Webhook Secret from the `SEROPS_WEBHOOK_SECRET` environment variable; set it where the hook runs. Without the `Authorization` header the deployment webhook answers 403.

---

## Signature verification

Every webhook endpoint refuses a request that does not prove it knows the binding's Webhook Secret. Each provider proves it its own way:

| Endpoint | What SerOps checks |
|---|---|
| `/api/webhooks/gitlab/<binding_id>/` | `X-Gitlab-Token` equals the secret (GitLab's **Secret Token** field) |
| `/api/webhooks/github/<binding_id>/` | `X-Hub-Signature-256: sha256=<HMAC-SHA256 of the body>` (GitHub's **Secret** field) |
| `/api/webhooks/bitbucket/<binding_id>/` | `X-Hub-Signature: sha256=<HMAC-SHA256 of the body>` (Bitbucket's **Secret** field) |
| `/api/webhooks/azure-devops/<binding_id>/` | `Authorization: Basic` whose password is the secret |
| `/api/webhooks/jenkins/<binding_id>/` | `X-Jenkins-Token` header, or `?token=` in the URL, equals the secret |
| `/api/providers/webhook/{deployment,argocd,flux}/<binding_id>/` | `X-SerOps-Signature: sha256=<HMAC-SHA256 of the body>`, `X-Signature: sha256=<…>` (Flux `generic-hmac`), or `Authorization: Bearer <secret>` |

For the deployment endpoints, compute the signature over the raw request body:

```
signature = HMAC-SHA256(secret, raw-request-body).hex()
header    = X-SerOps-Signature: sha256=<signature>
```

- A missing, malformed or wrong signature or token returns **403 Forbidden**. So does a binding with no secret.
- Comparison uses `hmac.compare_digest` (constant-time) — no timing side-channels.

## Rate limits

The deployment endpoints (`/api/providers/webhook/{deployment,argocd,flux}/`) are limited to **600 requests per hour per client IP**, to protect against runaway loops. The per-provider CI/CD endpoints under `/api/webhooks/` have no rate limit of their own.

If you legitimately need higher — e.g. a monorepo with 100+ pipelines/hour — contact `security@serops.ai`.
