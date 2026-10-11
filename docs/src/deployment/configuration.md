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
| `PROJECT_NAME` | No | `serops` | Instance name displayed in the UI and emails |
| `DJANGO_SECRET_KEY` | Yes | -- | Django secret key for cryptographic signing. Must be unique per deployment. |
| `ALLOWED_HOSTS` | Yes | -- | Comma-separated list of allowed hostnames (e.g., `serops.yourdomain.com,backend`) |
| `CORS_ALLOWED_ORIGINS` | Yes | -- | Comma-separated CORS origins (e.g., `https://serops.yourdomain.com`) |

---

## Public Access Control

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `REGISTRATION_ENABLED` | No | `True` | Whether anonymous visitors can create a new organisation via `POST /api/auth/register`. Leave as `True` for the normal sign-up flow. Set to `False` on a closed deployment — registrations return `403 registration_disabled`, existing users can still log in, and admins can still invite team members. |
| `BETA_INVITE_CODE` | No | -- | If set, register requests must include a matching invite code to succeed. Leave unset in normal deployments. |

---

## Image Registry

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SEROPS_VERSION` | No | `1.0.0` | Version tag for SerOps Docker images (backend + frontend) |

---

## URL Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SEROPS_DOMAIN` | Yes | `http://localhost` | Your domain or IP where SerOps will be accessible (e.g., `https://serops.yourdomain.com`) |
| `API_URL` | No | `http://backend:8000/api` | Internal Docker network URL for the backend. Usually no need to change. |
| `REACT_URL` | No | `http://frontend:3000` | Internal Docker network URL for the frontend. Usually no need to change. |
| `BASE_URL` | Yes | `http://localhost` | Public-facing base URL for link generation in emails and notifications |
| `SERVER_URL` | Yes | `http://localhost:8000/api` | Public-facing API URL used by the frontend to reach the backend |

---

## Database (PostgreSQL)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_NAME` | No | `serops` | PostgreSQL database name |
| `DB_USER` | No | `serops` | PostgreSQL username |
| `DB_PASSWORD` | Yes | -- | PostgreSQL password |
| `DB_HOST` | No | `postgres` | PostgreSQL host. Use `postgres` for the bundled container or your server hostname for external. |
| `DB_PORT` | No | `5432` | PostgreSQL port |
| `POSTGRES_PORT` | No | `5432` | Host port to expose the bundled PostgreSQL container on. Leave empty to disable host access. |
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
| `REDIS_PORT` | No | `6379` | Host port to expose the bundled Redis container on |

---

## Batch Processing

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BATCH_SCHEDULER_TICK_RATE` | No | `1` | How often (in minutes) Celery Beat checks whether any organisation is due for a new batch. Keep at `1` unless you need to reduce scheduler overhead. |

!!! info "Batch Generation Interval"
    The batch generation interval is configured **per-organisation** via **Settings > Data > Batch Generation Interval** in the UI. There is no system-wide environment variable for this setting.

---

## Email / SMTP

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `EMAIL_BACKEND` | No | `console` | Django email backend class. Use `django.core.mail.backends.smtp.EmailBackend` for production. |
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
    When `EMAIL_BACKEND` is set to `console` (the default), emails are printed to stdout instead of being sent. This is useful for development but must be changed for production.

!!! tip "Verify SMTP after config"
    Run `python manage.py check_smtp <your-address@example.com>` (or `docker compose exec backend python manage.py check_smtp …` in Docker deployments) to send a test email. The command also prints which env vars are currently in effect.

!!! info "No UI editor for SMTP"
    SMTP configuration is env-only (Grafana model). Change requires restarting the backend. The `SystemMailSettings` UI + `/api/settings/mail/` endpoints were removed 2026-09-01 to eliminate the lifecycle-email hijack risk on multi-tenant hosts.

---

## Network / Ports

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FRONTEND_PORT` | No | `80` | Host port for the frontend container |
| `BACKEND_PORT` | No | `8000` | Host port for the backend API container |

---

## Performance Tuning

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BACKEND_MEM_LIMIT` | No | `1g` | Memory limit for the backend container (e.g., `1g`, `2g`) |
| `BACKEND_CPUS` | No | `1` | CPU limit for the backend container |

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
    wants `METRICS_ENABLED=true`. This table previously said the default was
    `true`; it is not — `Data/tasks.py` reads
    `os.getenv('METRICS_ENABLED', 'false')`.

    * **docker-compose**: `.env.example` sets it to `true`, so compose
      installs are unaffected.
    * **Helm**: the chart sets it from `django.metricsEnabled`, which
      defaults to `true`.
    * **Anything else**: set it yourself, or SerOps runs log-only and the
      metric panels stay empty with no error explaining why.

---

## Example `.env`

A complete production configuration:

```env
# General
DEBUG=False
PROJECT_NAME=serops
SEROPS_VERSION=latest

# Security
DJANGO_SECRET_KEY=your-unique-secret-key-at-least-50-chars

# Database (bundled PostgreSQL)
DB_NAME=serops
DB_USER=serops
DB_PASSWORD=your-secure-db-password
DB_HOST=postgres
DB_PORT=5432

# Redis / Celery (bundled Redis)
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# Networking
SEROPS_DOMAIN=https://serops.yourdomain.com
API_URL=http://backend:8000/api
REACT_URL=http://frontend:3000
BASE_URL=https://serops.yourdomain.com
SERVER_URL=https://serops.yourdomain.com:8000/api
ALLOWED_HOSTS=serops.yourdomain.com,backend
CORS_ALLOWED_ORIGINS=https://serops.yourdomain.com
FRONTEND_PORT=80
BACKEND_PORT=8000

# Batch Processing
BATCH_SCHEDULER_TICK_RATE=1

# Email
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.yourdomain.com
EMAIL_HOST_USER=noreply@yourdomain.com
EMAIL_HOST_PASSWORD=smtp-password
EMAIL_USE_TLS=True
EMAIL_PORT=587
DEFAULT_FROM_EMAIL=SerOps <noreply@yourdomain.com>

# Performance
BACKEND_MEM_LIMIT=1g
BACKEND_CPUS=1
METRICS_ENABLED=true
```

---

## Validating Configuration

After setting environment variables, verify they are loaded correctly:

```bash
# Check that Django can start
docker exec serops-backend python manage.py check --deploy

# Verify database connectivity
docker exec serops-backend python manage.py dbshell -c "SELECT 1;"

# Verify Celery broker connectivity
docker exec serops-backend celery -A api inspect ping
```

!!! warning
    The `check --deploy` command runs Django's deployment checklist and will flag security issues such as `DEBUG=True`, missing `ALLOWED_HOSTS`, or an insecure `SECRET_KEY`.

---

## Next Steps

- [Production Deployment](production.md) -- deploy with these settings
- [Upgrading](upgrading.md) -- update to new versions
