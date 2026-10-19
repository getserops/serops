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
| Same as the app (1.1.0 and later) | 1.1.0 and later | 1.28, 1.29, 1.30, 1.31 |
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

## Automated Upgrade

The simplest way to upgrade is using the included upgrade script:

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
