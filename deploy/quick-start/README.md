# SerOps Quick Start (Self-Hosted)

Runs the full SerOps stack — frontend + backend + Postgres + Redis
behind a Caddy reverse proxy — on a single Docker host in about 5
minutes.

**What this ships**

Only what SerOps *is* — the SerOps application. SerOps is the AI layer
that sits **on top of** the observability stack you already run. It
does not bundle Elasticsearch, Loki, Prometheus, or any log/metric
shipper — you connect it to yours from the UI after signing in.

Supported observability providers:
Elasticsearch, OpenSearch, Grafana Loki, Datadog, AWS CloudWatch,
Prometheus, VictoriaMetrics, Grafana Mimir.

**System requirements**

- Linux host with Docker 24+ and Docker Compose v2 or newer
- ~2 GB RAM, 1 vCPU, 10 GB disk
- One of: Anthropic, Google Gemini, OpenAI, or DeepSeek API key — or Ollama
  (on-prem, no key needed)

---

## 1. Configure

```bash
cp .env.example .env
```

Open `.env` and set at minimum:

| Variable | How to generate |
|---|---|
| `DJANGO_SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `POSTGRES_PASSWORD` | `openssl rand -hex 24` |
| `REDIS_PASSWORD` | `openssl rand -hex 24` |

**AI provider keys do not go in `.env`.** They are entered in the UI after
first login, under **Settings → AI Providers**, and stored per organisation
(Fernet-encrypted at rest). Setting `ANTHROPIC_API_KEY` or any sibling in the
environment has no effect whatsoever — this table used to list one, which sent
self-hosters to configure a variable nothing reads and left them wondering why
analysis never ran.

SerOps needs at least one provider key before it can analyse anything:
Anthropic, Google Gemini, OpenAI, DeepSeek, or Ollama (keyless, on-prem — set
the base URL instead).

For a real hostname with automatic HTTPS, also set:

```
SEROPS_DOMAIN=serops.your-domain.com
```

Point that DNS name at the server's public IP before starting Caddy —
otherwise the Let's Encrypt challenge will fail and Caddy will retry
on its own timer.

## 2. Start the stack

```bash
docker compose up -d
```

## 3. Create the first admin

The backend applies migrations itself on every start. Once
`docker compose ps` shows `serops-backend` as `healthy`:

```bash
docker compose exec backend python manage.py createsuperuser
```

## 4. Log in

Open `https://<SEROPS_DOMAIN>/login` (`https://localhost/login` for a local
install — accept the certificate warning once) and sign in with the
superuser you just created.

---

## Common operations

**Update to a new release**

Set the new release in `.env` (`SEROPS_VERSION=…`), back up Postgres, then:

```bash
docker compose pull
docker compose up -d          # migrations run on start
```

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

---

## Networking + exposed ports

By design only Caddy exposes ports to the host:

| Port | Service |
|---|---|
| 80 | Caddy (HTTP + Let's Encrypt challenge) |
| 443 | Caddy (HTTPS) |

Postgres and Redis are reachable only from inside the `serops` Docker
network. For a psql session, run it inside the container:

```bash
docker compose exec postgres psql -U serops serops
```

## Security posture

- Every service that accepts a password is required to have one — the
  compose file refuses to start if `POSTGRES_PASSWORD` or `REDIS_PASSWORD`
  aren't set.
- No default credentials anywhere — the `.env.example` file is a
  template, not a working config.
- Postgres runs as the built-in `postgres` user, data-checksums on,
  `pg_stat_statements` enabled for query-level observability.
- Redis requires auth (`requirepass`) and caps memory at 256 MB with
  an LRU eviction policy.
- Caddy adds HSTS, `X-Frame-Options: DENY`, `X-Content-Type-Options:
  nosniff` on every response.

## Layout

```
deploy/quick-start/
├── README.md                    ← this file
├── docker-compose.yml           ← the whole stack
├── .env.example                 ← copy to .env and edit
└── config/
    ├── caddy/Caddyfile          ← reverse proxy + TLS routing
    └── postgres/init.sql        ← creates pg_stat_statements
```

## Troubleshooting

**Backend keeps restarting**

Almost always a database credential mismatch. Check the logs:
```bash
docker compose logs backend | tail -50
```
and verify `POSTGRES_PASSWORD` in `.env` matches what the postgres
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

Either no AI provider key is configured, or the org has no observability
integration wired. Check **Settings → AI** for the provider key, and
**Settings → Global Integrations** to connect at least one of the supported
log or metric providers (Elasticsearch, OpenSearch, Loki, Datadog,
CloudWatch, Prometheus, VictoriaMetrics, Mimir).

---

Full documentation lives at [serops.ai/docs](https://serops.ai/docs/).
