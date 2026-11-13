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
  --version 1.3.1 \
  --namespace serops --create-namespace \
  --set django.secretKey="$(openssl rand -hex 64)" \
  --set django.encryptionKey="$(openssl rand -base64 32 | tr '+/' '-_')" \
  --set database.url="postgres://serops:PASSWORD@your-pg-host:5432/serops" \
  --set broker.url="redis://:PASSWORD@your-redis-host:6379/0" \
  --set 'ingress.tls[0].hosts[0]=serops.example.com' \
  --set ingress.tls[0].secretName=serops-tls
```

or bundled ones for a lab: replace the two `url` lines with
`--set devServices.postgresql.enabled=true --set devServices.redis.enabled=true`.
With neither, the pods fail to start.

**TLS is required.** The chart refuses to render an ingress without
`ingress.tls`: a plain-HTTP install would send logins and API tokens in
clear, and the backend would run without Secure cookies or HSTS. Use the
cert-manager annotation in `values.yaml`, or a TLS Secret you manage. Only
when TLS terminates in front of the ingress controller (a cloud load
balancer) set `ingress.allowInsecure=true` together with an https
`django.publicUrl`.

> **AI provider keys are not set here.** SerOps reads RCA keys
> per-organisation from the database, never from the environment — a
> cluster-wide key would pool quota and billing across every org on the
> instance. Add yours after install at **Settings → AI Providers**.

**From source** (lab / demo with bundled PG + Redis, no certificate):

```bash
helm upgrade --install serops deploy/helm/serops \
  --namespace serops --create-namespace \
  --set devServices.postgresql.enabled=true \
  --set devServices.redis.enabled=true \
  --set django.secretKey="$(openssl rand -hex 64)" \
  --set django.encryptionKey="$(openssl rand -base64 32 | tr '+/' '-_')" \
  --set ingress.hosts[0].host=serops.local \
  --set ingress.allowInsecure=true   # lab only: plain HTTP on serops.local
```

## Production

Bring your own Postgres + Redis (safer for backups + HA) and put every
secret in a Kubernetes Secret you manage, referenced through the
`existingSecret` values (`django`, `database`, `broker`, `smtp`,
`alertSecrets`). That is the only production path: a value passed with
`--set` or in a values file is stored in the chart-managed Secret and in
every Helm release record in the namespace, and `--set` leaves it in your
shell history.

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

# Django secret from an existing Secret you rotate quarterly.
django:
  existingSecret: serops-django   # keys: django-secret-key, encryption-key

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
| **postgres** (optional) | `devServices.postgresql` — plain pinned `postgres:16.15-alpine`, password generated at install and kept across upgrades. Lab only, `emptyDir` storage. | 1 |
| **redis** (optional) | `devServices.redis` — plain pinned `redis:7.4.12-alpine`, `requirepass` with a generated password. Lab only. | 1 |
| **migrate** (Job) | `manage.py migrate` as a post-install/post-upgrade hook, with an init container that waits for the DB | 1 per revision |

Every release also gets its own **ServiceAccount** (no token mounted:
SerOps never calls the Kubernetes API), **PodDisruptionBudgets**
(`minAvailable: 1` for backend, frontend and worker when they have more
than one replica) and **NetworkPolicies**:

| Policy | Ingress allowed from | Egress |
|---|---|---|
| frontend | `networkPolicy.ingressFrom` (default: the `ingress-nginx` namespace), port 3000 | none |
| backend | `ingressFrom` + `networkPolicy.backendExtraIngressFrom` (add Prometheus here), port 8000 | `networkPolicy.egress`, or anywhere when empty |
| celery-worker, celery-beat, migrate | nobody | same as backend |
| dev postgres / redis | SerOps pods of the release only | none |

DNS (`networkPolicy.dnsNamespace`) and the bundled dev services are always
reachable. Egress is open by default because SerOps queries the observability
providers, SCM and AI endpoints you configure, on their own hosts and ports;
narrow `networkPolicy.egress` once you know them. The policies need a CNI
that enforces NetworkPolicy; set `networkPolicy.enabled=false` to skip them.

## Upgrading to chart 0.2.0

* `ingress.tls` is required when the ingress is enabled (or
  `ingress.allowInsecure=true`). Installs that relied on plain HTTP fail to
  render until one is set.
* The dev-service passwords moved into the chart's Secret and are generated
  when `devServices.*.password` is empty. The bundled Redis now requires a
  password; both are read back on upgrade, so existing lab installs keep
  theirs if you set the old value once or let the pods restart (the data is
  an `emptyDir` anyway).
* NetworkPolicies are on. If your ingress controller is not in a namespace
  labelled `kubernetes.io/metadata.name: ingress-nginx`, set
  `networkPolicy.ingressFrom` before upgrading, or the ingress gets 502s.

## Notes

* **HPA:** not shipped — add your own on backend + celery-worker
  targeting CPU 70% / requests.
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
