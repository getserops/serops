---
seo_title: "Argo CD and Flux deploy events"
description: "Send Argo CD and Flux notifications to SerOps so deployments appear in context and the AI links incidents to the deploy that caused them."
---
# GitOps Deploy Events (ArgoCD + Flux)

SerOps ingests native ArgoCD and Flux notifications so deploy events
land in the "Recent Deployments" panel — and, more importantly, feed
the AI RCA prompt as `code_changes` context. When a service degrades
right after a deploy, the AI links them automatically (`slow_span_
after_deploy` correlation).

You do **not** need to write custom notification templates — this
endpoint accepts the vendor's default payload and translates on our
side.

| Tool | Default payload accepted | Auth |
|---|---|---|
| ArgoCD (argocd-notifications-controller) | ✅ | Required: bearer token or HMAC-SHA256 (per-binding secret) |
| Flux (notification-controller) | ✅ | HMAC-SHA256, required (per-binding secret) |

## Prerequisites

1. Add an **Argo CD** or **Flux** integration in *Settings → Integrations*.
   It needs no URL or credentials: the controller sends events to SerOps,
   and SerOps never calls it.
2. On the project service you deploy, add a CI/CD pipeline with that
   integration, type **Deployment**. Setting up its webhook shows the URL
   (with the binding's numeric ID) and the secret to use below.

A binding on a GitLab, GitHub, Bitbucket, Azure DevOps or Jenkins
integration works too, if that is where the service is built.

## ArgoCD

**Endpoint**

```
POST https://your-serops-host/api/providers/webhook/argocd/<binding_id>/
Content-Type: application/json
Authorization: Bearer <binding webhook secret>   # or X-SerOps-Signature: sha256=<hex>
```

**Configure argocd-notifications-controller**

Put the binding's webhook secret in `argocd-notifications-secret`, then
create a notification service pointing at SerOps + a template + a
trigger. Argo CD notifications cannot sign a request body, so the secret
is sent as a bearer token (over https); `$serops-webhook-secret` is read
from the secret by Argo CD. Requests without it are refused.

```yaml
# argocd-notifications-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: argocd-notifications-secret
stringData:
  serops-webhook-secret: <the binding's webhook secret>
---
# argocd-notifications-cm.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-notifications-cm
data:
  service.webhook.serops: |
    url: https://your-serops-host/api/providers/webhook/argocd/42/
    headers:
      - name: Authorization
        value: Bearer $serops-webhook-secret
      - name: Content-Type
        value: application/json

  trigger.on-sync-succeeded: |
    - description: Application synced successfully
      send: [app-sync-status]
      when: app.status.operationState != nil and app.status.operationState.phase in ['Succeeded']
      oncePer: app.status.sync.revision

  template.app-sync-status: |
    webhook:
      serops:
        method: POST
        body: |
          {"app": {{ toJson .app }}, "context": {{ toJson .context }}}
```

Two lines matter here:

- **`oncePer: app.status.sync.revision`** sends one notification per synced
  revision. Without it Argo CD notifies once per Application and then logs
  "already sent" for every later sync, so SerOps hears only about the first
  deploy.
- **The body sends `app` and `context`**, which is what SerOps reads.
  `{{ toJson . }}` renders an empty body on Argo CD 2.13 (the root context
  also holds template functions and cannot be serialised), and SerOps
  answers `JSON parse error`.

Then in each `Application` resource:

```yaml
metadata:
  annotations:
    notifications.argoproj.io/subscribe.on-sync-succeeded.serops: ""
    serops.io/environment: production   # optional, wins over namespace
```

!!! tip "The `!= nil` guard is not optional noise"
    Until an Application has completed its first sync,
    `app.status.operationState` is absent. Without the guard the
    notifications controller logs an error on **every** evaluation:

    ```
    failed to execute when condition: cannot fetch phase from <nil> (1:27)
     | app.status.operationState.phase in ['Succeeded']
    ```

    Nothing is actually broken — the condition simply evaluates false, and
    the notification still fires once the sync finishes. But it is an
    error-level line in the log an operator reads only when hunting a
    problem, so it costs real debugging time. ArgoCD's own built-in
    `on-sync-succeeded` trigger carries the same guard.

    Verified on ArgoCD 2.13: unguarded produced the error on each pass;
    guarded produced none, with the deployment still recorded.

**What SerOps records**

- Only when `app.status.sync.status == "Synced"` AND
  `app.status.operationState.phase == "Succeeded"` (or phase absent).
  OutOfSync / Failed / Progressing events are ignored — keeps the
  Recent Deployments panel honest.
- `commit_sha` from `app.status.sync.revision`.
- `environment` — annotation `serops.io/environment` wins;
  falls back to namespace name if it maps to a known environment
  (`production`, `staging`, `development`, `preview`, `demo` — or
  aliases like `prod`, `stg`, `dev`); otherwise defaults to
  `production`.
- `actor` — `operationState.operation.initiatedBy.username`, or
  `"argocd"` if absent.
- `notes` — `argocd-app=<name>` + optional target revision.

## Flux CD

**Endpoint**

```
POST https://your-serops-host/api/providers/webhook/flux/<binding_id>/
Content-Type: application/json
X-Signature: sha256=<hex>    # Flux generic-hmac; X-SerOps-Signature also accepted
```

**Configure notification-controller**

Create a `Secret` holding the binding's webhook secret, then a
`generic-hmac` `Provider` + `Alert`. Flux signs each event with that
secret and sends it as `X-Signature: sha256=<hex>`, which SerOps accepts
in place of `X-SerOps-Signature`. Unsigned events are refused.

```yaml
---
apiVersion: v1
kind: Secret
metadata:
  name: serops-webhook
  namespace: flux-system
stringData:
  token: <the binding's webhook secret>
---
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Provider
metadata:
  name: serops
  namespace: flux-system
spec:
  type: generic-hmac
  address: https://your-serops-host/api/providers/webhook/flux/42/
  secretRef:
    name: serops-webhook
---
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Alert
metadata:
  name: serops-deploys
  namespace: flux-system
spec:
  providerRef:
    name: serops
  eventSeverity: info
  eventSources:
    - kind: Kustomization
      name: '*'
    - kind: HelmRelease
      name: '*'
```

**What SerOps records**

- Only when `severity == "info"` AND `reason` is one of
  `ReconciliationSucceeded`, `HealthCheckPassed`,
  `ProgressingWithReconciliation`. Errors + drift are ignored.
- `commit_sha` extracted from `metadata.revision`. Supports both
  legacy `<ref>@sha1:<sha>` and newer `<ref>@sha256:<sha>` formats.
- `environment` — `metadata["serops.io/environment"]` wins, then
  `involvedObject.namespace`, then `production`.
- `actor` — `reportingController` (e.g., `kustomize-controller`).
- `notes` — `flux-kustomization=<name>` or `flux-helmrelease=<name>`.

## Why not use the generic deploy webhook?

You still can — `POST /api/providers/webhook/deployment/<binding_id>/`
takes a minimal `{commit_sha, environment, ...}` shape and works
with Helm hooks, Terraform post-apply, kubectl-wrapping scripts,
etc. The ArgoCD / Flux endpoints exist so you don't have to write
custom notification templates for the two most-common GitOps tools.
