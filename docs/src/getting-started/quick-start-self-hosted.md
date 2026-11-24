---
seo_title: "Quick start: self-host SerOps with Docker Compose"
description: "Install SerOps on your own Docker host in about 10 minutes: clone, set four secrets, docker compose up, create the first user."
---
# Quick Start (Self-Hosted)

Deploy SerOps on your own Docker host in about 10 minutes (Steps 1 to 5).
The first analysis also needs an observability stack that already holds
your logs (Steps 6 to 8).

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

- Linux host with Docker 24+ and Docker Compose v2 or newer (`docker compose`, not
  the legacy `docker-compose`)
- **2 GB RAM, 1 vCPU, 10 GB disk** for a single-project evaluation.
  Production sizing starts higher — see
  [System Requirements](../deployment/requirements.md)
- An API key for one of: Anthropic, Google Gemini, OpenAI, or DeepSeek —
  or [Ollama](../how-to/on-prem-ai-ollama.md) for fully on-prem inference
  with no key. You add it in the SerOps UI after signing in, **not** in a
  config file
- (Optional) A DNS name pointing at your host if you want automatic
  HTTPS

## Step 1: Get the compose files

The quick-start compose file and its supporting configuration live in
`deploy/quick-start/` of the repository:

```bash
git clone https://github.com/getserops/serops.git
cd serops/deploy/quick-start
```

## Step 2: Configure

```bash
cp .env.example .env
```

Open `.env` and set the four required values. They are empty in
`.env.example`:

| Variable | How to generate |
|---|---|
| `DJANGO_SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `SEROPS_ENCRYPTION_KEY` | `openssl rand -base64 32 \| tr '+/' '-_'` |
| `POSTGRES_PASSWORD` | `openssl rand -hex 24` |
| `REDIS_PASSWORD` | `openssl rand -hex 24` |

`SEROPS_ENCRYPTION_KEY` encrypts the credentials SerOps stores (AI keys,
integration tokens). Keep a copy with your backups: without it, those
credentials cannot be read after a restore.

!!! info "AI provider keys do not go in `.env`"
    SerOps reads AI keys from the database, per organisation — never
    from the environment. You will add yours in **Settings → AI Providers**
    at [Step 5](#step-5-add-an-ai-provider-key), after the
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

For a purely local install, leave `SEROPS_DOMAIN=localhost`. Caddy then
serves `https://localhost` with a certificate from its own local
authority, so your browser shows a certificate warning the first time —
accept it to continue. `http://localhost` redirects there.

!!! warning "Set all four values before the first start"
    Compose refuses to start while `POSTGRES_PASSWORD` or
    `REDIS_PASSWORD` is empty. The backend refuses to start while
    `DJANGO_SECRET_KEY` or `SEROPS_ENCRYPTION_KEY` is empty or still a
    placeholder such as `change-me`: the other containers come up, the
    backend restarts in a loop, and its log names the value to fix
    (`docker compose logs backend`).

    Use the hex commands above: the Redis password is embedded in a
    `redis://` URL, and a `/` (common in base64 output) breaks it.

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

## Step 4: Create the first admin

The backend applies database migrations itself on every start, so the
schema is ready once `serops-backend` reports `healthy`
(`docker compose ps`; about 30 seconds after the images are pulled).
Create the first admin account:

```bash
docker compose exec backend python manage.py createsuperuser
```

It asks for an email address, a username and a password. The account
gets its own organisation, named after the part of the email address
before the `@` (`admin@example.com` gives "Admin's Organisation").

Once this organisation exists, the public sign-up page closes
automatically: invite teammates from **Settings → Users** instead (a
sign-up would create a separate organisation). To let other teams create
their own organisations on this instance, set `REGISTRATION_ENABLED=True`
in `.env`.

## Step 5: Add an AI provider key

Open `https://<SEROPS_DOMAIN>` and sign in with the email address and
password you just entered. The
[Onboarding Wizard](onboarding.md) starts automatically on first login
and walks you through the remaining steps; you can also do them
manually.

Go to **Settings → AI Providers**. Under **Manage Providers**, paste
the key in your provider's row and confirm it with the check button.
Then choose that provider as the primary one and click **Save
Settings**. Keys are stored per organisation and encrypted at rest.

The onboarding wizard's **Configure AI provider** button opens the same
form in a dialog. If you use **Settings → AI Providers** instead, the
wizard's **Getting Started** panel in the bottom-right corner can cover
the key fields: minimize it with the **←** button at its top right (the
**×** button dismisses the wizard).

Supported: Anthropic (Claude), Google (Gemini), OpenAI, DeepSeek, and
[Ollama](../how-to/on-prem-ai-ollama.md) for fully on-prem inference
with no key at all.

## Step 6: Connect your observability stack

Go to **Integrations** and connect at least one of the
supported observability providers so SerOps has real logs and metrics
to analyse. See [Integrations Overview](../integrations/overview.md)
for the full list and per-provider setup guides.

SerOps does not ship a log stack: this step needs one that already
holds your logs. To see what an analysis looks like before you connect
anything, open the wizard's **See a sample incident** link, or the
[live demo](https://app.serops.ai).

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

!!! note "Grafana Loki: the level must be in the line"
    On Loki, SerOps selects error and warning lines by their text, not by
    a label. A level that exists only as a `log_level` label is not
    read: the line itself must contain it, for example `ERROR ...` or a
    JSON line with `"level":"error"`. The other four fields are stream
    labels.

[**Configure Data Collection**](../how-to/configure-data-collection.md)
has copy-pasteable configuration for each shipper, plus the equivalent
label and tag setup for metrics.

## Step 8: Create your first project

With a key, a provider, and tagged telemetry in place, create a project
and link a service. [First Project](first-project.md) walks through it.

When you add the first service, SerOps starts a first analysis right
away. It reads the project's first environment, which is
**development** when you keep the form's defaults; the other
environments are analysed on the next scheduled run (every 15 minutes by
default).

---

## Common operations

**Update to a new release**

Images are pinned by version, not floating on `latest`. Pulling
without changing the version re-pulls the tag you already have, so
set the new version first:

```bash
# 1. Back up the database — always, before any upgrade
docker compose exec postgres pg_dump -U serops serops > backup-$(date +%F).sql

# 2. Set the release you want in .env (see the releases page), e.g.
#    SEROPS_VERSION=1.5.5

# 3. Pull and restart — the backend applies migrations on start
git pull
docker compose pull
docker compose up -d
```

`SEROPS_VERSION` is the only knob for upgrades. The
`SEROPS_BACKEND_IMAGE` / `SEROPS_FRONTEND_IMAGE` overrides in
`.env.example` exist only for pulling from your own registry mirror.

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
network. For a psql session, run it inside the container:

```bash
docker compose exec postgres psql -U serops serops
```

## Security posture

- Every service that accepts a password is required to have one — the
  compose file refuses to start if `POSTGRES_PASSWORD` or
  `REDIS_PASSWORD` isn't set.
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
- `serops-backend:8000` for `/api/*` (uploaded images such as avatars
  and logos are served under `/api` too)

See [`config/caddy/Caddyfile`](https://github.com/getserops/serops/blob/main/deploy/quick-start/config/caddy/Caddyfile)
for the exact routing rules.

## Troubleshooting

**Backend keeps restarting**

Check the logs first:

```bash
docker compose logs backend | tail -50
```

On a first install, the usual cause is an empty or invalid
`SEROPS_ENCRYPTION_KEY` (or `DJANGO_SECRET_KEY`): the log says
`SEROPS_ENCRYPTION_KEY must be set` and gives the command to generate
one. Set it in `.env` and run `docker compose up -d` again.

After that, the usual cause is a database credential mismatch. Verify `POSTGRES_PASSWORD` in `.env` matches what the postgres
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
observability integration wired. Check **Settings → AI Providers** for the
provider key, and **Integrations** to connect at least one
of the supported log or metric providers.

---

## Next steps

- [First project setup](first-project.md)
- [Replay your last incident](replay-past-incident.md): analyse an
  incident you already know, from the logs your store still holds
- [Onboarding Wizard](onboarding.md) walk-through
- [Integrations Overview](../integrations/overview.md) — connect your
  observability stack
- [Production Deployment](../deployment/production.md) — SSL/TLS,
  backups, monitoring
- [Configuration Reference](../deployment/configuration.md) — every
  environment variable
