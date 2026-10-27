---
seo_title: "Configuration reference (environment variables)"
description: "Every environment variable SerOps reads: Django, database, Redis, AI providers, email, SSO, metrics and image versions, with defaults."
---
# Configuration Reference

Complete reference for all environment variables consumed by SerOps.

---

!!! danger "Never commit `.env` files to version control."
    Environment files contain secrets such as database passwords, API keys, and the Django secret key. Add `.env*` to your `.gitignore` and use a secrets manager for production deployments.

---

## Core Settings

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DEBUG` | No | `False` | Django debug mode. **Must be `False` in production.** |
| `PROJECT_NAME` | No | `serops-backend` | Instance name used in emails |
| `DJANGO_SECRET_KEY` | Yes | -- | Django secret key for cryptographic signing. Must be unique per deployment. |
| `ALLOWED_HOSTS` | Yes | -- | Comma-separated list of allowed hostnames (e.g., `serops.yourdomain.com,backend`) |
| `CORS_ALLOWED_ORIGINS` | Yes | -- | Comma-separated CORS origins (e.g., `https://serops.yourdomain.com`) |

---

## Public Access Control

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `REGISTRATION_ENABLED` | No | unset (automatic) | Whether anonymous visitors can create a **new organisation** via `POST /api/auth/register`. **Unset:** open until the first real organisation exists (first sign-up or `createsuperuser`), then closed — a single-company install closes itself once set up. **`True`:** always open, for an instance hosting several teams. **`False`:** always closed. When closed, registrations return `403 registration_disabled`; existing users can still log in, and invitations to join an existing organisation always work. |
| `DJANGO_ADMIN_ENABLED` | No | `False` | Exposes the Django admin at `/api/admin/` (staff accounts only; failed logins are limited to 10 per 10 minutes per client). Off by default: SerOps itself never needs it, and superusers sign in to the app normally. |
| `TRUSTED_PROXY_COUNT` | No | `1` | How many reverse proxies sit in front of the backend. Login rate limits identify a client by the address the trusted proxy adds to `X-Forwarded-For`, so a client can't dodge them with a fake header. `1` fits the bundled Caddy (Compose) and ingress-nginx (Helm); raise it if, for example, a cloud load balancer sits in front of those. |
| `DEMO_ONLY_LOGIN` | No | `false` | For a public demo host only. `true` hides the password and SSO form and refuses password login, SSO and password reset server-side; the only way in is the "Try the live demo" button for the user seeded by `seed_demo_org`. Registration is closed too. |
| `BETA_INVITE_CODE` | No | -- | If set, register requests must include a matching invite code to succeed. Leave unset in normal deployments. |

---

## Image Registry

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SEROPS_VERSION` | No | `1.2.9` | Version tag for SerOps Docker images (backend + frontend) |

---

## URL Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SEROPS_DOMAIN` | Yes | `localhost` | Bare hostname SerOps is served on (e.g. `serops.yourdomain.com`) — **no scheme**. Caddy uses it as its site address and requests a Let's Encrypt certificate for it. |
| `API_URL` | Yes | -- | Public API URL, e.g. `https://serops.yourdomain.com/api`. Used to build account-activation links in emails. |
| `SERVER_URL` | Yes | -- | Public API URL, normally the same as `API_URL`. Used for the webhook URLs SerOps registers in GitLab, GitHub and other providers — it must be reachable from them. |
| `REACT_URL` | Yes | -- | Public UI URL, e.g. `https://serops.yourdomain.com`. Added to the CORS allow-list automatically. |
| `BASE_URL` | Yes | -- | Public UI URL used in links inside emails and notifications. |

The quick-start `.env.example` derives all four from `SEROPS_DOMAIN`, so a
compose install only sets the domain.

---

## Database (PostgreSQL)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_NAME` | No | `serops` | PostgreSQL database name |
| `DB_USER` | No | `serops` | PostgreSQL username |
| `DB_PASSWORD` | Yes | -- | PostgreSQL password |
| `DB_HOST` | No | `postgres` | PostgreSQL host. Use `postgres` for the bundled container or your server hostname for external. |
| `DB_PORT` | No | `5432` | PostgreSQL port |
| `DATABASE_URL` | No | -- | Full connection string, e.g. `postgres://user:pass@host:5432/serops`. When set and parseable it **overrides** all `DB_*` variables above. |

!!! tip "`DATABASE_URL` or `DB_*` — pick one per install"
    Both are supported and neither is deprecated. They suit different
    deployments:

    * **docker-compose** sets the five `DB_*` variables; `.env.example` ships
      that way and nothing here changes it.
    * **Kubernetes** hands out one connection string, because that is what a
      Secret naturally holds and what the Helm chart emits. The chart sets
      `DATABASE_URL` for you — from `database.url`, or derived automatically
      when `devServices.postgresql.enabled=true`.

    `DATABASE_URL` wins when both are present. Credentials are
    percent-decoded, so a password containing `@`, `:`, `/` or `#` is fine as
    long as it is encoded in the URL (`p%40ss` for `p@ss`). An unparseable
    `DATABASE_URL` logs a warning and falls back to `DB_*` rather than
    silently connecting somewhere unintended.

Example for external PostgreSQL:

```env
DB_HOST=your-pg-server.internal
DB_PORT=5432
DB_NAME=serops
DB_USER=serops
DB_PASSWORD=s3cur3-pa$$word
```

---

## Celery / Redis

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CELERY_BROKER_URL` | No | `redis://redis:6379/0` | Redis URL for the Celery message broker |
| `CELERY_RESULT_BACKEND` | No | `redis://redis:6379/0` | Redis URL for Celery task results |
| `REDIS_URL` | No | value of `CELERY_BROKER_URL` | Redis URL for the distributed lock backend used by the batch scheduler. Falls back to `CELERY_BROKER_URL` when unset. |

---

## Batch Processing

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BATCH_SCHEDULER_TICK_RATE` | No | `1` | How often (in minutes) Celery Beat checks whether any organisation is due for a new batch. Keep at `1` unless you need to reduce scheduler overhead. |
| `BATCH_GENERATION_INTERVAL` | No | `15` | Default batch interval in minutes for organisations that have not set their own. |

!!! info "Batch Generation Interval"
    Each organisation can override the interval in **Settings > Data Management > Batch Generation Interval**; `BATCH_GENERATION_INTERVAL` only applies where it has not.

---

## Email / SMTP

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `INVITATION_TTL_DAYS` | No | `7` | Days an invitation link stays valid. Each link also works only once. |
| `EMAIL_BACKEND` | No | `django.core.mail.backends.smtp.EmailBackend` | Django email backend class. The quick-start `.env.example` sets `django.core.mail.backends.console.EmailBackend`, which prints emails to the backend log instead of sending them. |
| `EMAIL_HOST` | No | -- | SMTP server hostname (e.g., `smtp.gmail.com`) |
| `EMAIL_HOST_USER` | No | -- | SMTP username / email address |
| `EMAIL_HOST_PASSWORD` | No | -- | SMTP password or app-specific password |
| `EMAIL_USE_TLS` | No | `True` | Enable TLS encryption for SMTP connections |
| `EMAIL_PORT` | No | `587` | SMTP port (587 for TLS, 465 for SSL) |
| `DEFAULT_FROM_EMAIL` | No | -- | Sender email address for outgoing notifications |

Example:

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_HOST_USER=serops@yourdomain.com
EMAIL_HOST_PASSWORD=app-specific-password
EMAIL_USE_TLS=True
EMAIL_PORT=587
DEFAULT_FROM_EMAIL=SerOps <serops@yourdomain.com>
```

!!! note
    With the console backend (the quick-start default), emails are printed to the backend log instead of being sent — fine for a trial, but invitations and password resets never reach anyone. Switch to SMTP for real use.

!!! tip "Verify SMTP after config"
    Run `python manage.py check_smtp <your-address@example.com>` (or `docker compose exec backend python manage.py check_smtp …` in Docker deployments) to send a test email. The command also prints which env vars are currently in effect.

!!! info "No UI editor for SMTP"
    SMTP configuration is env-only (Grafana model). Change requires restarting the backend. The `SystemMailSettings` UI + `/api/settings/mail/` endpoints were removed 2026-09-01 to eliminate the lifecycle-email hijack risk on multi-tenant hosts.

---

## SSL / Security

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECURE_SSL_REDIRECT` | No | `False` | Redirect all HTTP requests to HTTPS. Enable when behind HTTPS. |

---

## Metrics

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `METRICS_ENABLED` | No | `false` | Enable metrics collection from configured providers. **Set this explicitly** — see the warning below. |

!!! warning "The default is `false`, and it is easy to get caught by"
    Metrics are half of what the AI reasons over, so almost every install
    wants `METRICS_ENABLED=true`.

    * **docker-compose**: `.env.example` sets it to `true`, so compose
      installs are unaffected.
    * **Helm**: the chart sets it from `django.metricsEnabled`, which
      defaults to `true`.
    * **Anything else**: set it yourself, or SerOps runs log-only and the
      metric panels stay empty with no error explaining why.

---

## Example `.env`

The authoritative template is
[`deploy/quick-start/.env.example`](https://github.com/getserops/serops/blob/main/deploy/quick-start/.env.example)
— copy it rather than writing one from scratch. A production install on
`serops.yourdomain.com` with SMTP changes these lines from the template:

```env
SEROPS_DOMAIN=serops.yourdomain.com
DJANGO_SECRET_KEY=<python3 -c "import secrets; print(secrets.token_urlsafe(64))">
POSTGRES_PASSWORD=<openssl rand -hex 24>
REDIS_PASSWORD=<openssl rand -hex 24>

EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.yourdomain.com
EMAIL_HOST_USER=noreply@yourdomain.com
EMAIL_HOST_PASSWORD=smtp-password
EMAIL_USE_TLS=True
EMAIL_PORT=587
DEFAULT_FROM_EMAIL=SerOps <noreply@yourdomain.com>
```

The URL variables, database settings and Redis/Celery URLs are derived
from these by `.env.example` and the compose file.

---

## Validating Configuration

After setting environment variables, verify they are loaded correctly:

```bash
# Check that Django can start
docker exec serops-backend python manage.py check --deploy

# Verify database connectivity
docker exec serops-backend python manage.py check --database default

# Verify Celery broker connectivity
docker exec serops-backend celery -A api inspect ping
```

!!! warning
    The `check --deploy` command runs Django's deployment checklist and will flag security issues such as `DEBUG=True`, missing `ALLOWED_HOSTS`, or an insecure `SECRET_KEY`.

---

## Next Steps

- [Production Deployment](production.md) -- deploy with these settings
- [Upgrading](upgrading.md) -- update to new versions
