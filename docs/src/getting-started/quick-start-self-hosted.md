# Quick Start (Self-Hosted)

Deploy SerOps on your own Docker host in about 5 minutes.

## What this ships

Only what SerOps *is* — the SerOps application:

- **frontend** — React SPA
- **backend** — Django API + Celery worker + beat
- **postgres** — application database (Postgres 16)
- **redis** — cache + Celery broker
- **caddy** — single reverse proxy on ports 80 / 443, automatic HTTPS
  via Let's Encrypt

SerOps is the AI layer that sits **on top of** the observability stack
you already run. It does not bundle Elasticsearch, Loki, Prometheus, or
any log/metric shipper. Supported providers you connect from the UI
after signing in:

- **Logs**: Elasticsearch, OpenSearch, Grafana Loki, Splunk, Datadog,
  AWS CloudWatch, Google Cloud Logging, Azure Log Analytics
- **Metrics**: Prometheus, VictoriaMetrics, Grafana Mimir, Datadog,
  AWS CloudWatch, Google Cloud Monitoring, Azure Monitor
- **SCM + CI/CD**: GitLab, GitHub, Bitbucket, Azure DevOps, Jenkins

## Prerequisites

- Linux host with Docker 24+ and Docker Compose v2
- **2 GB RAM, 1 vCPU, 10 GB disk** for a single-project evaluation.
  Production sizing starts higher — see
  [System Requirements](../deployment/requirements.md)
- An API key for one of: Anthropic, Google Gemini, OpenAI, or DeepSeek.
  You will paste it into the SerOps UI after signup, **not** into a
  config file
- (Optional) A DNS name pointing at your host if you want automatic
  HTTPS

## Step 1: Get the compose files

The quick-start compose file and its supporting configuration live
inside the backend repo:

```bash
git clone https://github.com/getserops/serops.git
cd serops/deploy/quick-start
```

## Step 2: Configure

```bash
cp .env.example .env
```

Open `.env` and set the required values:

| Variable | How to generate |
|---|---|
| `DJANGO_SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `POSTGRES_PASSWORD` | `openssl rand -base64 24` |
| `REDIS_PASSWORD` | `openssl rand -base64 24` |

!!! info "AI provider keys do not go in `.env`"
    SerOps reads AI keys from the database, per organisation — never
    from the environment. You will add yours in **Settings → AI →
    API Keys** at [Step 5](#step-5-add-an-ai-provider-key), after the
    stack is running.

    This is deliberate: on a multi-tenant self-host a shared env-var
    key would pool quota and billing across every organisation, and
    the onboarding wizard could no longer tell "no key yet" apart from
    "key rejected by the provider". Setting `ANTHROPIC_API_KEY` in
    `.env` has no effect.

For a real hostname with automatic HTTPS:

```env
SEROPS_DOMAIN=serops.your-domain.com
```

Point that DNS name at your host's public IP *before* starting Caddy —
otherwise the Let's Encrypt HTTP-01 challenge fails and Caddy retries
on its own timer.

For a purely local install, leave `SEROPS_DOMAIN=localhost` — Caddy
will serve plain HTTP on port 80.

!!! warning "Never use default values in production"
    The `.env.example` file ships with placeholder text
    (`change-me-…`). The compose file fails fast if any required
    password is left as a placeholder or omitted.

See [Configuration Reference](../deployment/configuration.md) for the
full list of environment variables.

## Step 3: Start the stack

```bash
docker compose up -d
```

Five containers come up: `serops-postgres`, `serops-redis`,
`serops-backend`, `serops-frontend`, `serops-caddy`. Only Caddy
exposes ports (80 and 443) to the host — everything else is reachable
only inside the internal `serops` Docker network.

## Step 4: Initialise the database

```bash
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser
```

## Step 5: Add an AI provider key

Sign in with the superuser you just created. The
[Onboarding Wizard](onboarding.md) starts automatically on first login
and walks you through the remaining steps; you can also do them
manually.

Go to **Settings → AI → API Keys**, pick your provider, and paste the
key. Keys are stored per organisation and encrypted at rest.

Supported: Anthropic (Claude), Google (Gemini), OpenAI, DeepSeek, and
[Ollama](../how-to/on-prem-ai-ollama.md) for fully on-prem inference
with no key at all.

## Step 6: Connect your observability stack

Go to **Settings → Integrations** and connect at least one of the 14
supported observability providers so SerOps has real logs and metrics
to analyse. See [Integrations Overview](../integrations/overview.md)
for the full list and per-provider setup guides.

## Step 7: Tag your telemetry

!!! warning "Skip this and your batches will be empty"
    This is the single most common reason a new install analyses
    nothing. SerOps finds your data by querying the provider for
    specific field values — if your logs don't carry them, the query
    matches zero documents and every batch comes back empty.

Your log shipper (Fluent Bit, Vector, Promtail, the OTel Collector,
a Datadog Agent…) must stamp these fields on every record:

| Field | Example | What it maps to |
|---|---|---|
| `organisation_name` | `acme-cloud` | Your SerOps organisation |
| `project_name` | `checkout-api` | A SerOps project |
| `service_name` | `checkout` | A service inside that project |
| `environment` | `production` | The environment being analysed |
| `log_level` | `ERROR` | Severity, used by Sentinel triage |

Common aliases are accepted automatically — OpenTelemetry's
`service.name`, Datadog's `service` / `env`, Kubernetes' `app` label,
and `level` / `severity` / `status` for the level field.

[**Configure Data Collection**](../how-to/configure-data-collection.md)
has copy-pasteable configuration for each shipper, plus the equivalent
label and tag setup for metrics.

## Step 8: Create your first project

With a key, a provider, and tagged telemetry in place, create a project
and link a service. [First Project](first-project.md) walks through it.

---

## Common operations

**Update to a new release**

Images are pinned by version, not floating on `latest`. Pulling
without changing the version re-pulls the tag you already have, so
set the new version first:

```bash
# 1. Back up the database — always, before any upgrade
docker compose exec postgres pg_dump -U serops serops > backup-$(date +%F).sql

# 2. Pick the release you want, then set it in .env
#    SEROPS_VERSION=1.1.0

# 3. Pull and restart
git pull
docker compose pull
docker compose up -d
docker compose exec backend python manage.py migrate
```

See [Upgrading](../deployment/upgrading.md) for the version
compatibility matrix and the full backup checklist.

**View logs**

```bash
docker compose logs -f backend        # or any service name
```

**Back up Postgres**

```bash
docker compose exec postgres pg_dump -U serops serops > backup-$(date +%F).sql
```

**Stop everything (keep data)**

```bash
docker compose down
```

**Wipe everything including data**

```bash
docker compose down -v
```

## Networking + exposed ports

By design only Caddy exposes ports to the host:

| Port | Service |
|------|---------|
| 80   | Caddy (HTTP + Let's Encrypt challenge) |
| 443  | Caddy (HTTPS) |

Postgres and Redis are reachable only from inside the `serops` Docker
network. To reach Postgres from a laptop for a psql session, tunnel
via SSH:

```bash
ssh -L 5432:localhost:5432 root@your-server
# then: psql -h localhost -U serops serops
```

## Security posture

- Every service that accepts a password is required to have one — the
  compose file fails fast if `POSTGRES_PASSWORD` or `REDIS_PASSWORD`
  aren't set.
- No default credentials anywhere — the `.env.example` file is a
  template, not a working config.
- Postgres runs with data-checksums on, `pg_stat_statements` enabled
  for query-level observability.
- Redis requires auth (`requirepass`) and caps memory at 256 MB with
  an LRU eviction policy.
- Caddy adds HSTS, `X-Frame-Options: DENY`, `X-Content-Type-Options:
  nosniff` on every response.

## Using your own reverse proxy

If you already run nginx / Traefik / a cloud load balancer, remove the
`caddy` service from `docker-compose.yml` and point your ingress at:

- `serops-frontend:3000` for everything by default
- `serops-backend:8000` for `/api/*` and `/images/*`

See [`config/caddy/Caddyfile`](https://github.com/getserops/serops/blob/main/deploy/quick-start/config/caddy/Caddyfile)
for the exact routing rules.

## Troubleshooting

**Backend keeps restarting**

Almost always a database credential mismatch. Check the logs:

```bash
docker compose logs backend | tail -50
```

Verify `POSTGRES_PASSWORD` in `.env` matches what the postgres
container was initialised with. If you started with a wrong password
and want to reset:

```bash
docker compose down -v            # wipes postgres data too
docker compose up -d
```

**Caddy stuck on cert issuance**

The Let's Encrypt HTTP-01 challenge requires port 80 to be reachable
from the internet at the exact `SEROPS_DOMAIN` you configured. Confirm
DNS points at your host and the host firewall allows port 80.

**AI analyses aren't producing issues**

Either no AI provider key is configured, or the org has no
observability integration wired. Check **Settings → AI** for the
provider key, and **Settings → Integrations** to connect at least one
of the supported log or metric providers.

---

## Next steps

- [First project setup](first-project.md)
- [Onboarding Wizard](onboarding.md) walk-through
- [Integrations Overview](../integrations/overview.md) — connect your
  observability stack
- [Production Deployment](../deployment/production.md) — SSL/TLS,
  backups, monitoring
- [Configuration Reference](../deployment/configuration.md) — every
  environment variable
