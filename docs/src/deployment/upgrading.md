---
seo_title: "Upgrade SerOps"
description: "How to upgrade a SerOps installation safely with Docker Compose or Helm: back up, change the version, run migrations, verify."
---
# Upgrading SerOps

How to safely upgrade your SerOps installation to a new version.

---

## Pre-Upgrade Checklist

Before upgrading, complete the following steps:

- [ ] **Back up the database**: Follow the [Backup & Restore](backup-restore.md) procedure, or run the quick-start rotation script
  ```bash
  ./scripts/backup.sh
  ```
- [ ] **Note the current version**: Check your `.env` file for `SEROPS_VERSION`
- [ ] **Review the changelog**: Read the [Changelog](../changelog.md) for breaking changes, new required environment variables, or migration notes
- [ ] **Check the compatibility matrix** below — some upgrades require intermediate stops
- [ ] **Review new environment variables**: Compare `.env.example` with your `.env` for any new settings
- [ ] **Notify your team**: Inform users of a brief maintenance window

!!! danger "Always back up your database before upgrading."
    Database migrations are irreversible. If an upgrade introduces problems, you will need a backup to roll back. See [Backup & Restore](backup-restore.md) for the full procedure including secrets and PVCs.

---

## Version compatibility matrix

SerOps follows [Semantic Versioning](https://semver.org/). Same
**major** version means safe rolling upgrades; a major bump means
review the migration notes.

| From | To | Supported path | Notes |
|---|---|---|---|
| 1.0.x | 1.0.y (patch) | Direct rolling upgrade | Zero-downtime with Helm |
| 1.0.x | 1.x.0 (minor) | Direct upgrade | Read changelog for new envs |
| 1.x | 2.0 | **Via last 1.x release** | Never skip the last minor of a major |
| Older than N-2 minor | Latest | **Via intermediate release** | Migrations accumulate; step through |

### Kubernetes / Helm chart compatibility

Since 1.1.0 the Helm chart is versioned with the app: chart 1.2.0 deploys SerOps 1.2.0.

| Chart version | App version | Kubernetes tested |
|---|---|---|
| Same as the app (1.1.0 and later) | 1.1.0 and later | 1.28, 1.29, 1.30, 1.31; AKS 1.36 (upgrade 1.2.14 → 1.3.0, 2026-11-11) |
| 0.1.x | 1.0.x | 1.28, 1.29, 1.30, 1.31 |

We test the newest patch of each supported Kubernetes minor against
`helm template` + `helm install` on a KinD cluster. Older Kubernetes
minors may work but aren't gated by CI.

### PostgreSQL compatibility

| SerOps version | Postgres major | Notes |
|---|---|---|
| 1.x | 14, 15, 16, 17 | 16 recommended; bundled image = 16 |

Upgrading Postgres itself (e.g. 15 → 16) is out of scope for the
SerOps upgrade path — dump + reload into the new Postgres major,
then run the SerOps upgrade. See [Backup & Restore](backup-restore.md).

### Redis compatibility

| SerOps version | Redis version |
|---|---|
| 1.0.x | 6.x, 7.x |

Redis holds only ephemeral state (Celery queue, cache) so version
upgrades are safe with a brief restart.

---

## Upgrade notes

Releases that need something from you after upgrading. Migrations run on their own (`docker compose up` / the Helm migrate job).

### 1.3.0: users, roles and teams

- **`SEROPS_ENCRYPTION_KEY` is required.** Stored credentials now have their own key instead of being encrypted with `DJANGO_SECRET_KEY`, and SerOps refuses to start without it. Generate one with `openssl rand -base64 32 | tr '+/' '-_'`, add it to your environment, and back it up. Keep `DJANGO_SECRET_KEY` unchanged. Once upgraded, run `python manage.py rotate_secrets` once: until then, existing credentials still depend on `DJANGO_SECRET_KEY`.
  - Quick-start: add `SEROPS_ENCRYPTION_KEY=<key>` to `.env`, then `docker compose exec backend python manage.py rotate_secrets`.
  - Helm with `django.secretKey` in your values: add `django.encryptionKey: <key>`.
  - Helm with `django.existingSecret`: add the key to that Secret before `helm upgrade`, or every pod fails to start:
    `kubectl -n serops patch secret <your-secret> --type merge -p '{"stringData":{"encryption-key":"<key>"}}'`.
  - Helm: then `kubectl -n serops exec deploy/serops-backend -- python manage.py rotate_secrets` (see [Helm → Upgrading](helm.md#upgrading)).
- **What happens to an existing install**: without the key, the backend refuses to start and says how to generate one. With it, existing credentials stay readable (they are still decrypted with the key derived from `DJANGO_SECRET_KEY`) and new ones use the new key; `rotate_secrets` (`--dry-run` reports first) re-encrypts the old ones and names any it cannot read. After that, `DJANGO_SECRET_KEY` no longer protects them.
- **Helm (chart 1.3.0)**: `ingress.tls` is required when the ingress is enabled; an install that relied on plain HTTP fails to render until you set it, or `ingress.allowInsecure=true` when TLS ends in front of the ingress controller. NetworkPolicies, PodDisruptionBudgets and a ServiceAccount per release are on by default; if your ingress controller is not in a namespace labelled `kubernetes.io/metadata.name: ingress-nginx`, set `networkPolicy.ingressFrom` first, or the ingress gets 502s. Your CNI must enforce NetworkPolicy (`networkPolicy.enabled=false` skips them). The bundled lab Redis now needs a password, generated at install. Details: [Helm → Upgrading](helm.md#upgrading).
- **Images**: the backend still runs as uid 10001 and the frontend's nginx as uid 101 (since 1.2.9). The quick-start now drops every capability and sets `no-new-privileges` on them; a `backend_logs` volume created before 1.2.9 still needs the one-off `chown` below. `latest` now follows release tags only, and `main` builds are tagged `edge`: pin a version.
- **Quick-start**: `.env.example` leaves `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD` and `REDIS_PASSWORD` empty, so compose refuses to start until you fill them; existing `.env` files are unaffected.
- **New migrations**: Users 0014–0016, Data 0057–0059, Organisations 0014, Projects 0017, and ee 0001 when the `ee/` directories are present.
- **Nothing is restricted after the upgrade**: every project stays open to the whole organisation until you restrict it in its **Access** tab. Existing roles are unchanged.
- **Community and Enterprise**: SSO group mapping and teams are Community. Custom roles and per-project access are [Enterprise](../open-source-promise.md#what-enterprise-adds) (license key in **Settings → Enterprise license**).
- **SSO accounts are only created for listed email domains.** Before, a sign-in for an unknown email could create an account; now uninvited people need their domain under *Email domains that can join* (single organisation) or `manage.py sso_domains` (several organisations). Invited users are unaffected.
- **Settings → Team is now Settings → Users**, next to the new Teams page (and Roles, with Enterprise).
- **Integrations calling the API** see two new fields on users (`role_key`, `role_name`; `role` can be `custom`) and on projects (`access_mode`, `permissions`). Login, profile and SSO now return `organisation` as the organisation's name, plus `organisation_id`.
- **Forks adding API endpoints**: every endpoint must declare `Requires(...)` and project-scoped views must filter with `scope()`, or the test suite fails (see [Permissions](../development/permissions.md)).

### 1.2.14: security release

- **SSO accounts only for listed domains.** A first SSO sign-in creates an account only when the email's domain is in *Email domains that can join* (Settings → Security → Single Sign-On). With no domain listed, only invited and existing members sign in. On an install with several organisations, only the operator (a staff user) sets these domains.
- **Alert webhooks on an install with several organisations** need a per-organisation secret: `POST /api/organisation/alert-secret/rotate/`, then update the sender. The global `ALERT_WEBHOOK_SECRETS` and Sentry's client secret still work on a single-organisation install.
- **Changing an integration's host** asks for its credentials again.
- **Activation links** sent before the upgrade no longer work; resend them from the login page.
- Behind HTTPS (Helm with an HTTPS public URL, the quick-start), cookies become Secure and responses send HSTS. Nothing to do.

### 1.2.9: containers run as non-root

- The images no longer run as root: the backend as uid 10001, the frontend's nginx as uid 101 (listening on 3000 as before).
- **Docker Compose**: a `backend_logs` volume created by an earlier release belongs to root, so the backend can't write its log files there and logs to standard output instead (`docker compose logs backend`). To keep file logs, give the volume to the new user once: `docker compose run --rm --no-deps --user root --entrypoint chown backend -R 10001:10001 /app/logs`.
- **Helm**: pods now run with the restricted security context described in [Helm → Security context](helm.md#security-context). Nothing to migrate.

### 1.2.2: security release

- **New migrations**: Data 0051–0053, Projects 0015, Organisations 0013, Users 0012.
- **Re-run Setup Webhook** on each repository (SCM) binding: bindings now have a webhook secret, and the receiver refuses payloads without it. Until you do, pushes from that repository are ignored.
- **Django admin is off** by default: set `DJANGO_ADMIN_ENABLED=True` to use `/api/admin/`.
- **`TRUSTED_PROXY_COUNT`** (default `1`): the number of reverse proxies in front of SerOps, used for login rate limits and audit IPs. Raise it if several proxies append to `X-Forwarded-For`.
- **Superusers no longer reach other organisations' data through the API**: sign in as a member of an organisation to work in it.
- **Helm**: `/metrics` is no longer published on the ingress. Scrape it in the cluster (`serviceMonitor.enabled: true`), or add the path back with basic auth (see [Self-metrics](../admin/self-metrics.md)).
- **Organisation logos** must be uploaded again (they were never stored durably before); profile photos are imported automatically.

## Changing the encryption key

1. Set `SEROPS_ENCRYPTION_KEY_PREVIOUS` to the current key, and `SEROPS_ENCRYPTION_KEY` to a new one.
2. Restart the backend and the workers.
3. Run `python manage.py rotate_secrets` (`--dry-run` reports first). It exits with an error and names any secret it cannot read.
4. Remove `SEROPS_ENCRYPTION_KEY_PREVIOUS` and restart.

## Upgrading a Helm install

1. Back up the database (`pg_dump`, or your managed database's snapshot) and the release's values and Secrets.
2. Apply the release's [upgrade notes](#upgrade-notes) to your values and Secrets.
3. `helm upgrade` with the same chart source and values ([Helm → Upgrading](helm.md#upgrading)); leave the nodes room for the rolling update.
4. Run any command the notes ask for (`rotate_secrets` for 1.3.0) in a backend pod.
5. Check `kubectl -n serops get pods`, `kubectl logs -n serops job/serops-migrate -c migrate` and `/api/version/`, then sign in.

The rest of this page (`scripts/upgrade.sh`, `.env`, `docker compose`) is for the quick-start.

## Automated Upgrade

The simplest way to upgrade the quick-start is using the included upgrade script:

```bash
./scripts/upgrade.sh [version]
```

For example:

```bash
# Upgrade to a specific version
./scripts/upgrade.sh 1.5.0

# Upgrade to the latest version
./scripts/upgrade.sh
```

The script automatically:

1. Creates a pre-upgrade database backup
2. Pulls new images for the specified version
3. Restarts the backend and frontend (PostgreSQL and Redis keep running)
4. Reports which images were updated

---

## Manual Upgrade Procedure

If you prefer to upgrade manually:

### Step 1: Back Up the Database

```bash
./scripts/backup.sh
```

### Step 2: Update the Version (Optional)

If upgrading to a specific version, edit `.env`:

```env
SEROPS_VERSION=1.5.0
```

### Step 3: Pull New Images

```bash
docker compose pull
```

### Step 4: Restart Services

```bash
docker compose up -d
```

!!! note
    Database migrations run automatically when the backend container starts. There is no need to run them manually.

### Step 5: Verify the Upgrade

```bash
# Check container status
docker compose ps

# Check application logs for errors
docker compose logs --tail 50 backend

# Run the health check
./scripts/healthcheck.sh
```

Log in and verify core functionality:

- [x] Dashboard loads with data
- [x] Batch list and analysis results display correctly
- [x] AI chat responds to queries
- [x] Notifications are being delivered

---

## Rolling Back

If an upgrade causes issues, roll back to the previous version:

### Step 1: Stop the Application

```bash
docker compose down
```

### Step 2: Restore the Database

```bash
docker exec -i serops-postgres pg_restore \
  -U serops -d serops --clean --if-exists \
  < backups/serops_db_YYYYMMDD_HHMMSS.dump
```

### Step 3: Start the Previous Version

Set the previous version in `.env` and start:

```bash
# Edit .env to set SEROPS_VERSION to the previous version
SEROPS_VERSION=1.4.0 docker compose up -d
```

### Step 4: Verify the Rollback

Confirm the application is running on the previous version and all data is intact.

!!! warning
    Database rollback restores data to the point of the backup. Any data created between the backup and the rollback will be lost.

---

## Migration Troubleshooting

Migrations run automatically on container startup. If you encounter issues:

### Migration Fails on Startup

Check the backend container logs for the specific error:

```bash
docker compose logs backend
```

### Check Migration State

```bash
# See which migrations Django thinks are applied
docker exec serops-backend python manage.py showmigrations

# Check actual database columns
docker exec serops-backend python manage.py dbshell -c "\d tablename"
```

### State Desync

If Django reports a migration as applied but the database schema does not reflect it, you may need to fake the migration backward and re-run:

```bash
# Mark migration as unapplied (does NOT touch the database)
docker exec serops-backend python manage.py migrate app_name 0003 --fake

# Re-run the migration
docker exec serops-backend python manage.py migrate app_name
```

### `unique=True` Constraint Errors

If a migration adding a unique constraint fails because of duplicate values:

1. Identify duplicate rows in the database
2. Resolve duplicates manually (delete or update)
3. Restart the backend container: `docker compose restart backend`

### Duplicate Index Errors

If Django's deferred SQL creates duplicate indexes:

```
django.db.utils.ProgrammingError: relation "index_name" already exists
```

This typically happens when `AddField` and `AlterField` appear in the same migration. Check if the index already exists and fake the migration if so:

```bash
docker exec serops-backend python manage.py migrate app_name 000X --fake
```

Then restart the backend container.

---

## Zero-Downtime Upgrades

For deployments that require high availability, consider the following approach:

1. **Run migrations before deploying new code** -- most Django migrations are backward-compatible with the old code
2. **Use a blue-green deployment** -- bring up a new set of containers alongside the old ones, switch traffic after verification
3. **Use a load balancer health check** -- point your load balancer at `/api/health/` and let it drain connections from old containers

!!! tip
    Database migrations that add columns (without `NOT NULL` constraints) or add new tables are safe to run while the old code is still serving traffic. Migrations that rename or drop columns require a maintenance window.

---

## Next Steps

- [Configuration Reference](configuration.md) -- check for new environment variables
- [Changelog](../changelog.md) -- review version-by-version changes
