---
seo_title: "CI/CD webhook setup"
description: "Set up CI/CD and deployment webhooks for SerOps: one URL per binding, signature checks and per-provider instructions."
---
# Webhook Setup Guide

SerOps receives CI/CD pipeline events and deployment events via webhooks. Every webhook URL is tied to a specific **CI/CD Binding** you create in SerOps under **Projects → Services → CI/CD Bindings**. The binding provides multi-tenancy isolation (only your org's data flows to your batches) and lets you configure per-binding secrets for signature verification.

This page covers:

- Finding your webhook URL in SerOps
- Configuring the webhook in each supported provider
- The generic deployment webhook (ArgoCD, Flux, Helm, Terraform, kubectl)
- HMAC signature verification (recommended for public-facing webhooks)

---

## Where to find your webhook URL

1. Log in to SerOps as an admin
2. Navigate to **Projects → \<your project\> → Services → \<service\> → CI/CD Bindings**
3. Create a binding (Provider = the tool you're wiring up, Binding Type = `build` / `deploy` / etc.)
4. Copy the **Webhook URL** shown on the binding detail page. It looks like:

```
https://your-serops.com/api/providers/webhook/<provider>/<binding_id>/
```

or, for the generic deployment webhook:

```
https://your-serops.com/api/providers/webhook/deployment/<binding_id>/
```

Optionally set a **Webhook Secret** on the binding — SerOps will then require every request to include an HMAC-SHA256 signature (see [Signature verification](#signature-verification) below).

---

## Per-provider setup

### GitHub Actions

Two options: send a native GitHub webhook (recommended), or POST from within a workflow step.

**Native webhook** (repo → Settings → Webhooks → Add webhook):

- **Payload URL**: paste your SerOps webhook URL
- **Content type**: `application/json`
- **Secret**: paste your binding's Webhook Secret (if set)
- **Which events**: at minimum, `Workflow runs`. Add `Pushes` and `Pull requests` for richer correlation.

**Workflow step** (add near the end of your workflow):

```yaml
- name: Notify SerOps
  if: always()
  run: |
    curl -X POST \
      -H "Content-Type: application/json" \
      -H "X-SerOps-Signature: sha256=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "${{ secrets.SEROPS_WEBHOOK_SECRET }}" | cut -d' ' -f2)" \
      -d "$PAYLOAD" \
      "${{ secrets.SEROPS_WEBHOOK_URL }}"
  env:
    PAYLOAD: |
      {"pipeline_id":"${{ github.run_id }}",
       "status":"${{ job.status }}",
       "branch":"${{ github.ref_name }}",
       "commit_shas":["${{ github.sha }}"]}
```

### GitLab CI

Two options: project-level webhooks (recommended) or a `.gitlab-ci.yml` post-build job.

**Project webhook** (project → Settings → Webhooks → Add webhook):

- **URL**: your SerOps webhook URL
- **Secret Token**: paste your binding's Webhook Secret
- **Trigger**: `Job events` and `Pipeline events`
- **SSL verification**: leave enabled

**`.gitlab-ci.yml` post-build job**:

```yaml
notify-serops:
  stage: .post
  script:
    - |
      PAYLOAD='{"pipeline_id":"'$CI_PIPELINE_ID'","status":"'$CI_JOB_STATUS'","branch":"'$CI_COMMIT_REF_NAME'","commit_shas":["'$CI_COMMIT_SHA'"]}'
      SIG=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$SEROPS_WEBHOOK_SECRET" | cut -d' ' -f2)
      curl -X POST -H "Content-Type: application/json" \
        -H "X-SerOps-Signature: sha256=$SIG" \
        -d "$PAYLOAD" \
        "$SEROPS_WEBHOOK_URL"
  when: always
```

### Bitbucket Pipelines

**Repository webhook** (Repository settings → Webhooks → Add webhook):

- **URL**: your SerOps webhook URL
- **Status**: Active
- **Triggers**: `Repository:push`, `Pipeline:*`
- **Secret**: paste your binding's Webhook Secret in the `Secret` field (Bitbucket Cloud only — self-hosted Server uses `Webhook signature`)

### Azure DevOps Pipelines

**Service hook** (Project settings → Service hooks → Create subscription):

- **Service**: Web Hooks
- **Trigger**: `Build completed` and `Release deployment completed`
- **URL**: your SerOps webhook URL
- **Basic authentication username/password**: leave blank
- **HTTP headers**: add `X-SerOps-Signature: sha256=<computed-per-request>` if using signature verification

### Jenkins

Jenkins doesn't have first-class outbound webhooks. Use a post-build step in your `Jenkinsfile`:

```groovy
pipeline {
  agent any
  stages {
    stage('Build') {
      steps { echo 'building...' }
    }
  }
  post {
    always {
      script {
        def payload = """{
          "pipeline_id":"${env.BUILD_ID}",
          "status":"${currentBuild.result?.toLowerCase() ?: 'success'}",
          "branch":"${env.BRANCH_NAME}",
          "commit_shas":["${env.GIT_COMMIT}"]
        }"""
        def sig = sh(
          script: "echo -n '${payload}' | openssl dgst -sha256 -hmac '\${SEROPS_WEBHOOK_SECRET}' | cut -d' ' -f2",
          returnStdout: true,
        ).trim()
        sh """
          curl -X POST -H "Content-Type: application/json" \
            -H "X-SerOps-Signature: sha256=${sig}" \
            -d '${payload}' \
            "\${SEROPS_WEBHOOK_URL}"
        """
      }
    }
  }
}
```

Store `SEROPS_WEBHOOK_URL` + `SEROPS_WEBHOOK_SECRET` as Jenkins credentials.

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

- **Required**: `commit_sha` (7-64 hex chars), `environment` (`production` / `staging` / `development` / `preview` / `demo`; aliases like `prod`/`dev`/`stage` accepted).
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
  -d '{"commit_sha":"${var.git_sha}","environment":"${var.environment}","actor":"terraform","version":"${var.release_tag}"}' \
  "${var.serops_webhook_url}"
EOT
  }
  triggers = { always_run = timestamp() }
}
```

---

## Signature verification

SerOps supports HMAC-SHA256 signatures on all webhook endpoints. Highly recommended for any webhook exposed on a public URL.

1. **Generate a secret**: any 32+ char random string. `openssl rand -hex 32` works.
2. **Set it on the binding**: **Projects → Services → CI/CD Bindings → \<binding\> → Webhook Secret**.
3. **Compute + attach the signature** on every request:

```
signature = HMAC-SHA256(secret, raw-request-body).hex()
header    = X-SerOps-Signature: sha256=<signature>
```

- If a binding has NO secret set, SerOps accepts requests without a signature (useful for private-network installs).
- If a binding HAS a secret, missing / malformed / wrong signatures return **403 Forbidden**.
- Comparison uses `hmac.compare_digest` (constant-time) — no timing side-channels.

## Rate limits

All webhook endpoints are rate-limited to protect against runaway loops:

| Endpoint | Limit |
|---|---|
| Per-provider CI/CD webhooks | 300/min per binding |
| Generic deployment webhook | 600/hour per binding |

If you legitimately need higher — e.g. a monorepo with 100+ pipelines/hour — contact `security@serops.ai`.
