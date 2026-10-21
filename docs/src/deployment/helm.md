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
  --version 1.2.5 \
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
  --version 1.2.5 \
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

    The chart's one AI-related value, `ai.embeddings.openaiApiKey`, is
    optional and unrelated: it enables semantic issue similarity via
    the OpenAI embeddings API. Without it SerOps falls back to
    deterministic hash embeddings.

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

database:
  existingSecret: serops-db-secret   # key: database-url
broker:
  existingSecret: serops-broker-secret   # key: broker-url

# AI PROVIDER KEYS ARE NOT SET HERE. Anthropic / Gemini / OpenAI / DeepSeek
# keys are entered in the UI under Settings → AI Providers → API Keys, stored per
# organisation and encrypted at rest. Nothing reads them from the environment,
# so a Helm value or secret for them has no effect.
#
# The only AI key the chart takes is the optional OpenAI *embeddings* key, used
# for "issues like this one" similarity — not for root-cause analysis. Without
# it, similarity falls back to deterministic hash embeddings.
ai:
  embeddings:
    existingSecret: serops-openai-embeddings   # secret key: openai-api-key

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

## What gets deployed

| Component | Replicas | Notes |
|---|---|---|
| `serops-backend` | ≥ 2 | Django + gunicorn (4 workers/pod). HPA-friendly. |
| `serops-frontend` | ≥ 2 | Vite build served by nginx. |
| `serops-celery-worker` | ≥ 2 | Two queues: `high_priority` + `celery`. Alert-triggered batches jump ahead. |
| `serops-celery-beat` | **exactly 1** | Scheduler — multiple copies double-fire tasks. |

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

* **Migration init container** — currently a one-off `kubectl exec`.
* **HPA definitions** — bring your own targeting CPU 70% on backend + worker.
* **NetworkPolicy** — bring your own; egress to AI providers + DB/Redis + ingress from cluster nginx.
* **Multi-process Prometheus exposition** — today each gunicorn worker exposes its own registry; Prometheus aggregates naturally.
