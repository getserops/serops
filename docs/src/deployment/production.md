---
seo_title: "Production deployment with Docker Compose"
description: "Deploy SerOps in production with the quick-start distribution: TLS with Caddy, secrets, external PostgreSQL and Redis, backups and monitoring."
---
# Production Deployment

Step-by-step guide to deploying SerOps on your own infrastructure
using the [`deploy/quick-start/`](https://github.com/getserops/serops/tree/main/deploy/quick-start)
distribution at the repository root.

The quick-start Compose stack is the canonical self-host path. It
bundles everything SerOps itself needs (Postgres 16, Redis 7, backend,
frontend, Caddy for TLS + ingress) and connects out to whatever
observability tools you already run.

---

## Prerequisites

| Requirement | Minimum | Recommended |
|---|---|---|
| Docker | 20.10+ | 24+ |
| Docker Compose | v2 (built-in) | v2 |
| CPU | 2 cores | 4+ cores |
| RAM | 4 GB | 8+ GB |
| Disk | 20 GB | 50+ GB |
| OS | Linux (any), macOS | Ubuntu 22.04+, RHEL 9+ |
| Public hostname | Optional (Caddy falls back to `localhost`) | Recommended for HTTPS |

!!! info "Not bundled — connect these separately"
    SerOps is the AI/analysis layer on top of the observability
    stack you already run. Elasticsearch / Loki / Datadog /
    Prometheus / CloudWatch / VictoriaMetrics / Mimir / OpenSearch
    are **not** shipped in this Compose file — you configure them
    from *Integrations* after the app is up.

---

## Step 1: Clone the backend repo

```bash
git clone https://github.com/getserops/serops.git
cd serops/deploy/quick-start
```

Everything you need for a self-host deploy lives in this directory.

---

## Step 2: Configure

```bash
cp .env.example .env
```

Edit `.env` — at minimum:

```env
# Security — REQUIRED
DJANGO_SECRET_KEY=<generate one: python3 -c 'import secrets; print(secrets.token_urlsafe(50))'>

# Database (Postgres bundled — set your own password)
POSTGRES_PASSWORD=<pick something long>
REDIS_PASSWORD=<pick something long>

# Hostname Caddy serves under — leave 'localhost' for local eval
SEROPS_DOMAIN=serops.yourdomain.com

# Add at least one AI provider configuration via the wizard after
# first login. AI keys are stored per-organisation via the UI, not
# via env vars (since the 2026-08-30 rework).
```

See the [Configuration Reference](configuration.md) for every
supported variable.

---

## Step 3: Bring the stack up

```bash
docker compose up -d
```

Compose starts these containers, in dependency order:

| Container | Role | Internal port |
|---|---|---|
| `serops-postgres` | Postgres 16 (app DB) | 5432 |
| `serops-redis` | Redis 7 (Celery broker + cache) | 6379 |
| `serops-backend` | Django API + Celery worker + Beat | 8000 |
| `serops-frontend` | React SPA (Nginx-served bundle) | 3000 |
| `serops-caddy` | HTTPS reverse proxy | 80 / 443 |

Only ports 80 and 443 are exposed to the host. Postgres and Redis
are reachable only from inside the compose network.

Migrations run automatically on backend startup via `start.sh` — no
manual `manage.py migrate` needed.

---

## Step 4: Create the first admin

```bash
docker compose exec backend python manage.py createsuperuser
```

Alternatively, open the web UI at your `SEROPS_DOMAIN` and use the
registration page — the first user through gets admin.

---

## Step 5: Complete the onboarding wizard

Open your browser at your `SEROPS_DOMAIN` and log in. The onboarding
wizard walks through:

1. Pick an AI provider (Gemini / Claude / OpenAI / DeepSeek / Ollama)
   and add your API key. Key is encrypted at rest with Fernet.
2. Connect an observability source (log store).
3. Create your first project + service.
4. First AI analysis fires automatically once a service is linked.

The wizard uses computed state — no "Mark Complete" clicks needed;
it detects each step as you finish it.

---

## Step 6: Verify

```bash
curl https://serops.yourdomain.com/api/health/         # → 200 OK
docker compose ps                                       # all healthy
docker compose logs -f backend                          # tail app logs
```

---

## Post-deployment

### TLS

Caddy handles HTTPS automatically via Let's Encrypt when
`SEROPS_DOMAIN` is a publicly-reachable hostname. No cert files to
manage.

If you're behind a corporate load balancer or want to terminate TLS
elsewhere:

1. Remove the `caddy` service from `docker-compose.yml`.
2. Point your ingress at `frontend:3000` and `backend:8000` (routing
   `/api/*` and `/images/*` to backend, everything else to frontend
   — see `config/caddy/Caddyfile` for the exact rules).
3. Set `SECURE_SSL_REDIRECT=True` in `.env`.

### Database backups

The quick-start ships a rotation script — see the dedicated
[Backup & Restore](backup-restore.md) guide for the full procedure
(retention policy, off-site copies, encryption, disaster-recovery
drills, Kubernetes patterns, restoring the `.env` secrets alongside
the dump).

Quick reference:

```bash
# Back up (writes ./backups/serops_db_YYYYMMDD_HHMMSS.dump, keeps last 7)
./scripts/backup.sh

# Cron for nightly at 2am
0 2 * * * cd /path/to/quick-start && ./scripts/backup.sh

# Restore
docker exec -i serops-postgres pg_restore \
    -U serops -d serops --clean --if-exists \
    < backups/serops_db_YYYYMMDD_HHMMSS.dump
```

### Use an external Postgres

If you already run Postgres and want SerOps to use it instead of the
bundled container:

1. Comment out the `postgres` service block in `docker-compose.yml`.
2. In `.env`, set `DB_HOST` to your Postgres hostname and
   `DB_PORT` if it's non-standard.
3. `docker compose up -d`.

### Monitoring the deployment

Docker's built-in healthchecks + `docker compose ps` covers most of
what you need day-to-day:

- Container status: `docker compose ps`
- Application logs: `docker compose logs -f backend`
- Celery worker output: `docker compose logs -f backend | grep -i celery`
- DB connection count: `docker exec serops-postgres psql -U serops -d serops -c 'SELECT count(*) FROM pg_stat_activity;'`

For long-term observability, feed the SerOps container logs into the
same log store you connected to SerOps itself — you get
eating-your-own-dogfood for free.

### Connect your observability + SCM providers

Once the app is up:

1. **Integrations** → add your log provider (Elasticsearch,
   Loki, Datadog, CloudWatch, etc.).
2. Add your SCM provider (GitHub, GitLab, Bitbucket, Azure DevOps) so
   AI analysis can reference recent commits.
3. Add your CI/CD provider (Jenkins, GitHub Actions, GitLab CI, etc.)
   so AI can correlate incidents with deploys.

See the [Integrations Overview](../integrations/overview.md) for
provider-specific setup.

---

## Next

- [Configuration Reference](configuration.md) — every environment variable
- [Upgrading](upgrading.md) — how to move between versions
- [Team Management](../admin/team.md) — invite the rest of your team
