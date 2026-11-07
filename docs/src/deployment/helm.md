---
seo_title: "Install SerOps on Kubernetes with Helm"
description: "Install SerOps on Kubernetes with the official Helm chart: lab install with bundled PostgreSQL and Redis, or production with your own database and broker."
---
# Kubernetes / Helm

Ship SerOps to Kubernetes via the Helm chart at
[`deploy/helm/serops/`](https://github.com/getserops/serops/tree/main/deploy/helm/serops)
in the SerOps monorepo. Chart lives alongside `deploy/quick-start/`
(docker-compose) so all deployment artefacts share one directory —
the PostHog-style flat monorepo pattern.

## Prerequisites

* Kubernetes ≥ 1.25
* Helm 3
* One of:
  * **Lab / demo:** just this cluster (chart bundles Postgres + Redis).
  * **Production:** external Postgres 14+ and Redis 6+.

## Install paths

Pick whichever fits your workflow — the chart is identical in both.
**You do not need to clone the repo for production.**

### 1. OCI (recommended, no repo-add needed)

The chart needs a database and a Redis broker. For production, point it
at your own:

```bash
helm install serops oci://ghcr.io/getserops/charts/serops \
  --version 1.2.14 \
  --namespace serops --create-namespace \
  --set django.secretKey="$(openssl rand -hex 64)" \
  --set database.url="postgres://serops:PASSWORD@your-pg-host:5432/serops" \
  --set broker.url="redis://:PASSWORD@your-redis-host:6379/0"
```

Prefer `database.existingSecret` / `broker.existingSecret` (keys
`database-url` / `broker-url`) over passing credentials on the command
line.

For a lab or demo cluster, let the chart run Postgres and Redis itself:

```bash
helm install serops oci://ghcr.io/getserops/charts/serops \
  --version 1.2.14 \
  --namespace serops --create-namespace \
  --set django.secretKey="$(openssl rand -hex 64)" \
  --set devServices.postgresql.enabled=true \
  --set devServices.redis.enabled=true
```

Both commands serve SerOps at the chart's default host,
`serops.example.com`. To use your own name, put it in a small values file
and add `-f my-values.yaml` to the command: the host has to be set in three
places, or the API rejects the browser's requests (HTTP 400) and the login
page reads as though the password were wrong.

```yaml
# my-values.yaml
ingress:
  hosts:
    - host: serops.company.io
      paths:
        - { path: /api, pathType: Prefix, service: backend }
        - { path: /metrics, pathType: Prefix, service: backend }
        - { path: /, pathType: Prefix, service: frontend }
django:
  allowedHosts: "serops.company.io"
  corsAllowedOrigins: "https://serops.company.io"
```

Set the whole `hosts` entry as above: `--set ingress.hosts[0].host=…`
replaces the entry and drops its paths, and the install fails.

!!! warning "Set one of the two"
    With neither `database.url` nor `devServices.postgresql.enabled`
    (and likewise for the broker), the chart renders no connection
    strings and the pods fail to start.

!!! warning "AI provider keys are not a Helm value"
    SerOps reads root-cause-analysis keys per organisation from the
    database, never from the environment — a cluster-wide key would
    pool quota and billing across every organisation on the instance.

    Add yours after install at **Settings → AI Providers**.

    Similar-incident search uses the same per-organisation provider
    for embeddings (OpenAI, Gemini or Ollama), and local lexical
    similarity otherwise. There is no AI value in the chart.

### 2. From source (dev / lab / customisation)

Bundled PG + Redis, single-command install:

```bash
git clone https://github.com/getserops/serops.git
cd serops

helm upgrade --install serops deploy/helm/serops \
  --namespace serops --create-namespace \
  --set devServices.postgresql.enabled=true \
  --set devServices.redis.enabled=true \
  --set django.secretKey="$(openssl rand -hex 64)" \
  -f my-values.yaml   # your hostname: see my-values.yaml above
```

Both **OCI** and **Helm HTTP repo** paths are published by the
`helm-release` GitHub Actions workflow on every `v*.*.*` tag —
users never touch the source tree to run SerOps in production.

Wait for pods:

```bash
kubectl get pods -n serops -w
```

Migrations run automatically. The chart ships a `post-install,post-upgrade`
hook Job (`migrations.enabled`, default true) with an init container that
waits for the database to accept connections first. Create your first admin
user:

```bash
kubectl exec -n serops -it deploy/serops-backend -- python manage.py createsuperuser
```

Check the migration Job if the backend does not come up:

```bash
kubectl get jobs -n serops
kubectl logs -n serops job/serops-migrate
```

Set `migrations.enabled=false` only if you run migrations from your own
pipeline — for example a stage that gates on a review of the generated SQL.

## Production

Bring your own Postgres + Redis (managed / HA), reference existing
Secrets for keys:

```yaml
# my-values.yaml
backend:
  replicaCount: 3
celeryWorker:
  replicaCount: 5
  # Restarts a worker that stops answering `celery inspect ping` (on by default).
  livenessProbe:
    enabled: true

database:
  existingSecret: serops-db-secret   # key: database-url
broker:
  existingSecret: serops-broker-secret   # key: broker-url

# AI PROVIDER KEYS ARE NOT SET HERE. Anthropic / Gemini / OpenAI / DeepSeek
# keys are entered in the UI under Settings → AI Providers → API Keys, stored per
# organisation and encrypted at rest. Nothing reads them from the environment,
# so a Helm value or secret for them has no effect — similar-incident
# embeddings use the same per-organisation provider.

django:
  existingSecret: serops-django   # key: django-secret-key
  # Both default to serops.example.com, so they MUST be set to your host or
  # the install looks broken in two confusing ways: Django answers
  # DisallowedHost, and the browser silently blocks the frontend's own API
  # calls — which the login page reports as invalid credentials.
  allowedHosts: "serops.company.io"
  corsAllowedOrigins: "https://serops.company.io"
  # Optional. The URL users open SerOps at, used for the SSO redirect URI and
  # links in emails. Left empty, it is the first ingress host below, https
  # when ingress TLS is set.
  # publicUrl: "https://serops.company.io"

ingress:
  hosts:
    - host: serops.company.io
      paths:
        - {path: /api, pathType: Prefix, service: backend}
        - {path: /metrics, pathType: Prefix, service: backend}
        - {path: /, pathType: Prefix, service: frontend}
  tls:
    - hosts: [serops.company.io]
      secretName: serops-tls
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod

# Alert webhook secrets — env-only.
alertSecrets:
  existingSecret: serops-alert-secrets
    # keys: alertmanager, grafana, datadog

# Outgoing email: account activation, password reset, invitations and
# notifications. Without a host, SerOps sends no email.
smtp:
  existingSecret: serops-smtp   # keys: smtp-password (smtp-user etc. optional)
  host: smtp.company.io
  port: 587
  security: starttls   # starttls (587), ssl (465) or none (plain relay)
  user: serops@company.io
  fromEmail: serops@company.io

# Auto-scrape /metrics with Prometheus Operator.
serviceMonitor:
  enabled: true

# Optional basic-auth on /metrics.
selfMetrics:
  basicAuth: "scraper:REPLACE_WITH_RANDOM"
```

```bash
helm upgrade --install serops deploy/helm/serops \
  --namespace serops --create-namespace \
  --values my-values.yaml
```

## Multi-node clusters

Tested in November 2026 on AKS with two nodes (2 vCPU and 16 GB each): the
chart from GHCR, Postgres as a StatefulSet on an Azure disk, two replicas of
the backend, frontend and worker, then one node drained while an incident was
under way. Postgres came back on the other node with its data, SerOps kept
serving from the remaining node, and the investigation still named the cause.

- **Replicas are spread one per node by default** (a soft
  `topologySpreadConstraints`; a single-node cluster still runs them all).
  Set `<component>.spreadAcrossNodes: false` to turn it off, or give your own
  `<component>.topologySpreadConstraints`. `nodeSelector`, `tolerations` and
  `affinity` apply to every component.
- **Keep room for losing a node.** The default CPU requests (backend 250m and
  worker 500m per replica, plus your cluster's own system pods, about 1 vCPU
  on AKS) do not fit on one 2-vCPU node: after a drain the pods wait for CPU.
  Size the cluster so one node can carry the whole load, or lower the requests
  to what SerOps actually uses (the test above used about 0.2 cores at rest).
- **Use a real database.** `devServices` keeps data in an `emptyDir` and loses
  it when the pod moves; run Postgres with a persistent volume or a managed
  service and set `database.url`.
- **AKS and ingress-nginx:** give the controller's Service the annotation
  `service.beta.kubernetes.io/azure-load-balancer-health-probe-request-path:
  /healthz`, or Azure's load balancer marks every node unhealthy and the
  ingress never answers.

## What gets deployed

| Component | Replicas | Notes |
|---|---|---|
| `serops-backend` | ≥ 2 | Django + gunicorn (4 workers/pod). HPA-friendly. |
| `serops-frontend` | ≥ 2 | Vite build served by nginx. |
| `serops-celery-worker` | ≥ 2 | Two queues: `high_priority` + `celery`. Alert-triggered batches jump ahead. |
| `serops-celery-beat` | **exactly 1** | Scheduler — multiple copies double-fire tasks. |

## Security context

Every pod meets the Kubernetes **restricted** Pod Security Standard: a non-root user (the backend image runs as uid 10001, the frontend's nginx as uid 101), no privilege escalation, all Linux capabilities dropped, the runtime's default seccomp profile, and a read-only root filesystem. The backend pods write only to two `emptyDir` volumes, `/tmp` and `/app/logs`; the frontend writes only to `/tmp`.

The settings are `podSecurityContext` and `containerSecurityContext` (backend, Celery and migrations) and `frontend.podSecurityContext` / `frontend.containerSecurityContext`. On a platform that assigns user ids itself, such as OpenShift, remove `runAsUser`, `runAsGroup` and `fsGroup`.

## Verifying the install

```bash
# Health probe
curl -sS https://serops.company.io/api/health/

# Self-metrics (basic-auth if configured)
curl -sS https://serops.company.io/metrics/ | head

# Prometheus Operator picks up the ServiceMonitor:
kubectl get servicemonitor -n serops
```

## Upgrading

```bash
git pull                       # get latest chart + app
helm upgrade serops deploy/helm/serops --namespace serops --values my-values.yaml
# Migrations run as a post-upgrade hook — no manual step. Watch it:
kubectl logs -n serops job/serops-migrate
```

Rolling update on backend/frontend/worker is safe; beat is `Recreate`
strategy (single replica).

## Uninstall

```bash
helm uninstall serops --namespace serops
# Persistent DBs (if bundled) survive — delete PVCs manually if intended:
kubectl delete pvc --all -n serops
kubectl delete namespace serops
```

## Not yet in the chart

Planned for a later release:

* **HPA definitions** — bring your own targeting CPU 70% on backend + worker.
* **NetworkPolicy** — bring your own; egress to AI providers + DB/Redis + ingress from cluster nginx.
* **Multi-process Prometheus exposition** — today each gunicorn worker exposes its own registry; Prometheus aggregates naturally.
