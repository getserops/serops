# SerOps Helm Chart

Deploys **SerOps** — AGPL-3.0 AI Root Cause Analysis platform — to a
Kubernetes cluster.

Chart location: `deploy/helm/serops/` at monorepo root (alongside
`deploy/quick-start/` docker-compose). Follows the flat-monorepo
pattern (PostHog / kubernetes ingress-nginx style) so all deployment
artefacts live under one `deploy/` tree.

## Install (no source needed for production)

Three paths — chart is identical. Published by `.github/workflows/
helm-release.yml` on every `v*.*.*` tag.

**OCI** (recommended). The chart needs a database and a Redis broker —
your own for production:

```bash
helm install serops oci://ghcr.io/getserops/charts/serops \
  --version 1.0.0 \
  --namespace serops --create-namespace \
  --set django.secretKey="$(openssl rand -hex 64)" \
  --set database.url="postgres://serops:PASSWORD@your-pg-host:5432/serops" \
  --set broker.url="redis://:PASSWORD@your-redis-host:6379/0"
```

or bundled ones for a lab: replace the last two lines with
`--set devServices.postgresql.enabled=true --set devServices.redis.enabled=true`.
With neither, the pods fail to start.

> **AI provider keys are not set here.** SerOps reads RCA keys
> per-organisation from the database, never from the environment — a
> cluster-wide key would pool quota and billing across every org on the
> instance. Add yours after install at **Settings → AI Providers**.

**From source** (lab / demo with bundled PG + Redis):

```bash
helm upgrade --install serops deploy/helm/serops \
  --namespace serops --create-namespace \
  --set devServices.postgresql.enabled=true \
  --set devServices.redis.enabled=true \
  --set django.secretKey="$(openssl rand -hex 64)" \
  --set ingress.hosts[0].host=serops.local
```

## Production

Bring your own Postgres + Redis (safer for backups + HA), inline
secrets via `--set` or `--values my-values.yaml`, and reference
externally-managed Secrets for API keys:

```yaml
# my-values.yaml
backend:
  replicaCount: 3
celeryWorker:
  replicaCount: 5

# External managed Postgres.
database:
  existingSecret: serops-db-secret   # key: database-url

# External Redis.
broker:
  existingSecret: serops-broker-secret   # key: broker-url

# Optional: OpenAI key for semantic issue similarity (embeddings only,
# NOT root-cause analysis). Omit it and SerOps falls back to
# deterministic hash embeddings.
ai:
  embeddings:
    existingSecret: serops-ai-keys   # key: openai-api-key

# Django secret from an existing Secret you rotate quarterly.
django:
  existingSecret: serops-django

# Ingress with cert-manager TLS.
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

# Scrape /metrics with the Prometheus Operator.
serviceMonitor:
  enabled: true

# Optional basic-auth for /metrics.
selfMetrics:
  basicAuth: "scraper:REPLACE"

# Alert webhook secrets — set only what you use.
alertSecrets:
  existingSecret: serops-alert-secrets
```

Then:

```bash
helm upgrade --install serops deploy/helm/serops \
  --namespace serops --create-namespace \
  --values my-values.yaml
```

## Components

| Component | Purpose | Replicas |
|---|---|---|
| **backend** | Django + gunicorn — API + auth + admin | 2+ (HPA-friendly) |
| **frontend** | React (Vite build) served by nginx | 2+ |
| **celery-worker** | Batch analysis, AI calls, webhooks. `high_priority` + `celery` queues | 2+ |
| **celery-beat** | Scheduled batches, retention cleanup | **exactly 1** (double-fire risk) |
| **postgres** (optional) | `devServices.postgresql` — plain pinned `postgres:16-alpine`. Lab only, `emptyDir` storage. | 1 |
| **redis** (optional) | `devServices.redis` — plain pinned `redis:7-alpine`. Lab only. | 1 |
| **migrate** (Job) | `manage.py migrate` as a post-install/post-upgrade hook, with an init container that waits for the DB | 1 per revision |

## Notes

* **HPA:** not shipped in v0.1.0 — add your own on backend + celery-worker
  targeting CPU 70% / requests. Coming in v0.2.
* **NetworkPolicy:** not shipped — add your own. Backend + workers need
  DB + Redis + egress to AI provider APIs; frontend needs no egress.
* **Trace storage:** Postgres JSONB. See docs for scale ceiling
  (~10M spans/day comfortably).
* **First run:** migrations run automatically via a Helm hook Job
  (`migrations.enabled`, default true). A hook rather than an init
  container, because an init container runs once per replica and N
  replicas would race on the same migration. Disable it only if you run
  migrations from your own pipeline.
* **Bundled DB/Redis:** the bitnami/postgresql and bitnami/redis
  subcharts were removed — the image tags they pinned no longer exist on
  Docker Hub since Bitnami moved versioned tags behind bitnamisecure, and
  following those charts forward would mean an unpinned `latest` Postgres.
  `devServices` replaces them with plain pinned Deployments. Enabling
  either also rewrites the matching connection URL, so the app is
  actually wired to it.
* **Metrics:** `django.metricsEnabled` defaults to true and sets
  `METRICS_ENABLED`. The application's own default is FALSE, so a chart
  that left this unset shipped a log-only install.

## Values reference

See [`values.yaml`](values.yaml) for the full reference with inline
comments.
