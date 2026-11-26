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
- [ ] **Note the current version**: Check your `.env` file for `SEROPS_VERSION`; when it is not set, the default in `docker-compose.yml` applies
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
The 0.2.x chart numbers in the upgrade notes below are the `Chart.yaml`
version in the source tree; the published chart carries the release number.

| Chart version | App version | Kubernetes tested |
|---|---|---|
| Same as the app (1.1.0 and later) | 1.1.0 and later | Rendered for 1.31 in CI; installed by hand on AKS 1.36 (upgrade 1.2.14 → 1.3.0, 2026-11-11), GKE 1.36 (1.3.0, 2026-11-12) and EKS 1.36 (1.3.0, 2026-11-13) |
| 0.1.x | 1.0.x | 1.28, 1.29, 1.30, 1.31 |

CI runs `helm lint` and `helm template --kube-version 1.31.0` on each
chart change. It does not install the chart on a cluster; the AKS, GKE and EKS
installs above were done by hand ([AKS](aks.md), [GKE](gke.md), [EKS](eks.md)).

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
| 1.x | 7.x (bundled image: 7.4) |

Redis holds only ephemeral state (Celery queue, cache) so version
upgrades are safe with a brief restart.

---

## Upgrade notes

Releases that need something from you after upgrading. Migrations run on their own (`docker compose up` / the Helm migrate job).

### 1.5.6: minimum severity filters, Helm links

- **No migration and no new setting**: set the version and restart. Chart 0.2.8 sets `SERVER_URL` and `BASE_URL` (see below).
- **Minimum severity now filters.** Until 1.5.5 the "Min severity" of a delivery channel or a routing rule never blocked anything, so a channel set to Critical received every analysis. From 1.5.6 the floor applies: Info lets Info, Warning and Critical through, Warning lets Warning and Critical through, Critical only Critical. With a floor set, an analysis with no issue does not notify. Floors saved before 1.5.6 as Low, Medium or High count as Info, Warning and Critical and need no re-saving. **Channels and rules with a floor will receive fewer notifications than before**: check the floors in **Alerts & routing** after the upgrade. A channel or rule with no floor (Any) is unchanged.
- **Helm**: the chart now sets `SERVER_URL` and `BASE_URL` from the public URL, so GitLab webhook URLs and links in notification emails no longer start with `None/`. A value under `backend.env` still wins. If you connected GitLab on a Helm install before 1.5.6, check the project's webhooks in GitLab: an address that starts with `None/` should start with your public URL followed by `/api/webhooks/gitlab/`.
- **If a script of yours reads the service-health API** (`GET /api/data/analytics/service-health/`): it now returns every service, up to 200, instead of the 12 worst, and each entry has two new fields, `project_name` and `affected_by` ([Analytics API](../api/analytics.md)). The fields that were there are unchanged.
- **Going back to 1.5.5**: set the version back. There is no database step; floors saved from the 1.5.6 screen (INFO, WARNING, CRITICAL) are ignored again by 1.5.5, as all floors were.

### 1.5.5: web app changes only

- **Nothing to do.** No migration, no new setting and no changed default: set the version and restart. Chart 0.2.7 changes `appVersion` only.
- **Behind your own proxy**: the frontend container now gzips its scripts and stylesheets also when a proxy sits in front. If your proxy compresses too, it passes the compressed answer through; nothing to change.
- **Going back to 1.5.4**: set the version back. There is no database step.

### 1.5.4: web app changes only

- **Nothing to do.** No migration, no new setting and no changed default: set the version and restart. Chart 0.2.6 changes `appVersion` only.
- **Going back to 1.5.3**: set the version back. There is no database step.

### 1.5.3: web app changes only

- **Nothing to do.** No migration, no new setting and no changed default: set the version and restart. Chart 0.2.5 changes `appVersion` only.
- **Going back to 1.5.2**: set the version back. There is no database step.

### 1.5.2: web app changes only

- **Nothing to do.** No migration, no new setting and no changed default: set the version and restart. Chart 0.2.4 changes metadata only.
- **Going back to 1.5.1**: set the version back. There is no database step.
- **If you built on the frontend**: `npm run lint` now fails on a new literal colour outside `src/styles/design.css`; `frontend/DESIGN.md` has the rules.

### 1.5.1: security fixes for sign-in, email addresses and outbound requests

- **Email addresses are one identity whatever their case.** Migration `Users 0018` adds a unique rule on the lowercase address. If two accounts have the same address in different case (`Ana@example.com` and `ana@example.com`), the migration stops before it changes anything and lists them, masked, with their user ids: the backend container (quick-start) or the migrate job (Helm) fails with `Users 0018 not applied`. Merge, rename or delete the extra account, then start the upgrade again. To check before upgrading, on PostgreSQL: `SELECT lower(email), count(*) FROM "Users" GROUP BY 1 HAVING count(*) > 1;` (no row means nothing to do).
- **Failed password sign-ins are counted.** Ten failures in 15 minutes for one account from one address stop that address for that account, and 100 from all addresses stop password sign-in for the account, until the window ends (answer 429). The three numbers are settings: `SEROPS_LOGIN_MAX_FAILURES_PER_SOURCE`, `SEROPS_LOGIN_MAX_FAILURES_PER_ACCOUNT`, `SEROPS_LOGIN_FAILURE_WINDOW_SECONDS`. A script that retries a wrong password in a loop will now be refused.
- **Outbound requests to the URLs you configure** (SCM and CI providers, notification senders, webhooks, the SSO token exchange) check every address the host name resolves to. With the default `SEROPS_OUTBOUND_ALLOW_PRIVATE=true` private addresses stay allowed, as before. An install shared by several organisations must set it to `false` (Helm: `django.outboundAllowPrivate: false`, chart 0.2.3).
- **`POST /api/organisation/create/` is removed.** It was unused by the web app.
- **Demo installs**: a "Try the live demo" sign-in lasts 8 hours (`SEROPS_DEMO_TOKEN_HOURS`) and is not extended by use.
- **New migration**: Users 0018. It adds the unique rule and changes no row.
- **Going back to 1.5.0**: the 1.5.0 images run on a database that has the unique rule. To remove it first, run `python manage.py migrate Users 0017` with the 1.5.1 backend image, then set the version back.

### 1.5.0: accuracy, integrations and security fixes

- **OpenSearch verifies TLS by default.** `verify_certs` is now `true` (it was `false`). For a self-signed certificate you trust, clear **Verify TLS certificate** on the integration.
- **Bitbucket webhooks**: run **Setup Webhook** again on an existing CI/CD binding; the webhook created by 1.4.0 and earlier has no secret, and its deliveries are refused.
- **Alerts that match no service are no longer analysed.** Check **Alerts & routing → Delivery Channels** for the alerts of the last week that matched nothing, with the labels tried.
- **Helm chart 0.2.2**: `backend.env` and `backend.envFrom` now reach the Celery workers, Celery beat and the migration job as well as the API pods. Check that nothing you set there was meant for the API pods only. The Celery worker and beat images now follow `backend.image` unless `celeryWorker.image` or `celeryBeat.image` is set; before, pinning `backend.image.tag` (a patch release, a registry mirror) left the workers on the chart's default version.
- **Checking all integrations at once** is `POST /api/providers/integrations/health-check-all/` and needs `integration.use`; a script that called it with `GET` gets 405.
- **The interactive API reference** (`/api/docs/`) is off unless `DEBUG` or `SEROPS_API_DOCS=true` is set.
- **Cache address**: `REDIS_URL` (or `CELERY_BROKER_URL` when it is unset) may be `redis://`, `rediss://` or `unix://`; any other scheme stops the backend at start with a clear error. The quick-start and the Helm chart need no change.
- **New optional settings**: `SEROPS_ISSUE_CONTINUITY_HOURS`, `SEROPS_MAX_LOG_WINDOW_MINUTES`, `SEROPS_USAGE_SCRIPT_PATH`, `SEROPS_USAGE_WEBSITE_ID`, `SEROPS_API_DOCS`.
- **New migrations**: Data 0062–0063, ai_model 0004, org_settings 0022, traces 0004. They only add columns and tables, except org_settings 0022, which moves the seeded Claude provider to `claude-sonnet-5-5` when no organisation uses it.

### 1.4.0: SAML, SCIM and audit streaming

- **New migrations**: Users 0017, ee 0002–0004, Data 0060–0061. Upgrading from 1.2.x: read the 1.3.0 notes first. 1.3.1 needs nothing.

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
- **Alert webhooks on an install with several organisations** need a per-organisation secret: `POST /api/organisation/alert-secret/rotate/`, then update the sender. The install-wide secrets (`SEROPS_ALERTMANAGER_SECRET`, `SEROPS_GRAFANA_ALERT_SECRET`, `SEROPS_DATADOG_MONITOR_SECRET` and Sentry's `SEROPS_SENTRY_CLIENT_SECRET`) still work on a single-organisation install.
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

The rest of this page (`scripts/backup.sh`, `.env`, `docker compose`) is for the quick-start.

## Upgrading the quick-start

### Step 1: Back Up the Database

```bash
./scripts/backup.sh
```

### Step 2: Set the New Version

Set the release you are upgrading to in `.env`. Without it, `docker compose pull` fetches the version written in `docker-compose.yml` again:

```env
SEROPS_VERSION=1.5.6
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

# Check the API answers (add -k for a local install with Caddy's own certificate)
curl -fsS https://<your-domain>/api/health/
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

Stop the web app and the API. PostgreSQL keeps running, because the restore needs it:

```bash
docker compose stop caddy frontend backend
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
# In .env: SEROPS_VERSION=1.4.0 (the previous version), then
docker compose up -d
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
docker exec serops-postgres psql -U serops -d serops -c '\d tablename'
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
