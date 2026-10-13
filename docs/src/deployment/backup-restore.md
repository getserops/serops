---
title: Backup & Restore
description: Back up SerOps state and restore it after data loss or before an upgrade
tags:
  - deployment
  - operations
---

# Backup & Restore

SerOps stores customer state in two places:

| Store | What's in it | Loss impact |
|---|---|---|
| **PostgreSQL** | Users, orgs, projects, services, batches, issues, integrations, audit logs, API keys, notification channels | **Total** — this is the system of record |
| **Redis** | Celery task queue, cache | Low — tasks retry; cache is warmable |

Everything else (log payloads, metrics, traces) lives in your existing
observability stack (Elasticsearch, Datadog, Grafana Loki, etc.). Those
platforms have their own backup story — SerOps only stores pointers.

!!! danger "You must back up PostgreSQL before every upgrade."
    Django migrations are one-way. If an upgrade fails mid-migration,
    a database dump is the *only* way to recover cleanly.

---

## What to back up

### 1. PostgreSQL (required)

The `serops` database. Full schema + data. Nightly is the minimum
rhythm most teams should run; hourly is reasonable for busy stacks.

### 2. Secrets & config (once, then on every change)

Your `.env` file (Docker Compose) or Kubernetes `Secret`s (Helm)
carry credentials and encryption keys. **If you lose the
`SEROPS_ENCRYPTION_KEY` you cannot decrypt API keys, webhook secrets,
or notification credentials stored in the database** — a
PostgreSQL restore alone will not recover them.

Store this file in a password manager or secrets vault (1Password,
Vaultwarden, AWS Secrets Manager, HashiCorp Vault). Do **not** commit
it to git.

### 3. Redis (optional)

Only useful if you want in-flight Celery tasks to survive a restart.
Most teams skip Redis backups — task loss just means a batch analysis
retries on the next data collection cycle.

### 4. Static uploads (if you use them)

Avatar images and any customer uploads live in the `media/` volume
(Compose) or a PVC (Helm). Small and easily backed up with a
periodic `tar` or object-storage sync.

---

## Backing up (Docker Compose)

The quick-start ships a battle-tested rotation script at
`deploy/quick-start/scripts/backup.sh`:

```bash
cd /opt/serops/deploy/quick-start
./scripts/backup.sh                    # writes to ./backups/
./scripts/backup.sh /var/backups/pg    # or a custom directory
```

**What it does:**

* Runs `pg_dump --format=custom --compress=6` against the
  `serops-postgres` container
* Writes `serops_db_YYYYMMDD_HHMMSS.dump` to the target directory
* Rotates old dumps — keeps the last **7** by default
* Prints the exact `pg_restore` command to use

### Nightly cron

```bash
0 2 * * * cd /opt/serops/deploy/quick-start && ./scripts/backup.sh >> /var/log/serops-backup.log 2>&1
```

### Off-site copy (recommended)

The rotation script only protects against Postgres corruption — not
against losing the whole host. Sync dumps to object storage
after each run:

```bash
0 2 * * * cd /opt/serops/deploy/quick-start && \
  ./scripts/backup.sh && \
  aws s3 sync ./backups/ s3://my-bucket/serops-backups/ --delete
```

### Encrypt at rest

Backups contain encrypted secrets but also PII (user emails, service
names, incident content). Encrypt the dump file before uploading:

```bash
gpg --symmetric --cipher-algo AES256 \
    --output backups/serops_db_20260905.dump.gpg \
    backups/serops_db_20260905.dump
```

---

## Backing up (Kubernetes / Helm)

The Helm chart does not run a backup CronJob out of the box — the
recommended pattern is one of:

### Option A: Managed Postgres

If you deployed SerOps against a managed service (AWS RDS, Google
Cloud SQL, Azure Database for PostgreSQL, Aiven, Neon), enable the
provider's native automated backups. This is the simplest and most
reliable path for production.

### Option B: Bundled Postgres + CronJob

If you're running the Helm chart with `devServices.postgresql.enabled=true`,
stop: that database stores data in an `emptyDir` and loses everything when
the pod restarts, so there is nothing worth backing up. It exists for
evaluation only.

For a self-managed Postgres you run yourself (a StatefulSet with a real
PersistentVolume, pointed at by `database.url`), deploy a Kubernetes
`CronJob`:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: serops-postgres-backup
  namespace: serops
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: pg-dump
              image: postgres:16
              command:
                - /bin/bash
                - -c
                - |
                  pg_dump -h serops-postgresql -U serops \
                    --format=custom --compress=6 \
                    -d serops > /backup/serops_$(date +%Y%m%d_%H%M%S).dump
              env:
                - name: PGPASSWORD
                  valueFrom:
                    secretKeyRef:
                      name: serops-postgresql
                      key: postgres-password
              volumeMounts:
                - name: backup
                  mountPath: /backup
          volumes:
            - name: backup
              persistentVolumeClaim:
                claimName: serops-backup-pvc
```

Pair the PVC with a sidecar that syncs to S3 / GCS, or use
[Velero](https://velero.io/) for cluster-wide backup including PVCs.

### Option C: Velero

For teams already using Velero, snapshot the whole `serops` namespace
including the Postgres PVC:

```bash
velero backup create serops-nightly \
    --include-namespaces serops \
    --ttl 720h0m0s \
    --schedule "0 2 * * *"
```

Velero handles PVC snapshots via your CSI driver — no `pg_dump`
CronJob needed.

---

## Restoring

### Postgres restore (Docker Compose)

Follow this order on a fresh host or an existing broken install:

```bash
# 1. Bring up the stack (creates the empty serops database)
cd /opt/serops/deploy/quick-start
cp /path/to/backed-up/.env .env    # restore secrets FIRST
docker compose up -d postgres redis

# 2. Wait for Postgres to be ready
docker exec serops-postgres pg_isready -U serops

# 3. Restore the dump
docker exec -i serops-postgres pg_restore \
    -U serops -d serops --clean --if-exists \
    < backups/serops_db_20260905_020000.dump

# 4. Start backend + frontend (migrations will be a no-op — schema
#    already at the dump's version)
docker compose up -d
```

!!! warning "Restore the `.env` file BEFORE restoring the database."
    The database contains encrypted API keys and webhook secrets. If the
    backend starts with a different `SEROPS_ENCRYPTION_KEY` than the one
    used when those secrets were written, they become unrecoverable
    ciphertext. Roll your integrations manually if this happens — you'll
    have to re-enter every API key.

### Postgres restore (Kubernetes)

```bash
# 1. Scale backend + workers to 0 (no writes during restore)
kubectl -n serops scale deployment serops-backend --replicas=0
kubectl -n serops scale deployment serops-celery-worker --replicas=0
kubectl -n serops scale deployment serops-celery-beat --replicas=0

# 2. Copy the dump into the Postgres pod
kubectl -n serops cp serops_db_20260905.dump serops-postgresql-0:/tmp/dump

# 3. Run pg_restore inside the pod
kubectl -n serops exec -it serops-postgresql-0 -- bash -c \
    "pg_restore -U serops -d serops --clean --if-exists /tmp/dump"

# 4. Scale back up
kubectl -n serops scale deployment serops-backend --replicas=2
kubectl -n serops scale deployment serops-celery-worker --replicas=2
kubectl -n serops scale deployment serops-celery-beat --replicas=1
```

For Velero restores:

```bash
velero restore create --from-backup serops-nightly-20260905020000
```

### Point-in-time recovery (managed Postgres)

If you're on RDS / Cloud SQL / equivalent, use the provider's
point-in-time restore UI. Restore into a new database instance,
verify the data, then either:

* Update `DATABASE_URL` in your Helm values / `.env` to point at
  the recovered instance, **or**
* Take a `pg_dump` from the recovered instance and restore it into
  your primary using the steps above.

---

## Disaster recovery drill

Test restores catch problems that backup scripts hide. Run a drill
**quarterly**:

1. Pick a recent backup.
2. Spin up an isolated stack on a spare host or namespace (do
   **not** point at your production database).
3. Restore the backup end-to-end using the procedure above.
4. Verify the SerOps UI shows expected data (batches, issues,
   integrations).
5. Log the outcome — restore time, any surprises, whether secrets
   decrypted correctly.

Common failure modes surfaced by drills:

* Backup file corrupt (silent I/O errors) — solved by verifying
  every dump with `pg_restore --list backup.dump` after write
* Wrong encryption key — solved by storing `.env` alongside the
  first dump of a fresh install
* Postgres version drift — a dump from Postgres 16 won't restore
  cleanly into Postgres 14. Pin your Postgres major version in
  Compose / Helm and only upgrade with a full backup + reload.

---

## Retention policy

Recommended defaults:

| Backup age | Retention | Rationale |
|---|---|---|
| Last 7 days | Daily | Fast recovery from recent mistakes |
| Last 4 weeks | 1 per week | Restore points across a month |
| Last 12 months | 1 per month | Compliance & long-tail incidents |
| Beyond 12 months | Delete | PII should not linger in cold storage |

The bundled `backup.sh` handles the daily rotation. Weekly and
monthly retention need a separate lifecycle rule on your object
store — S3 lifecycle policies, GCS object lifecycle management, or
equivalent.

---

## Backup verification

Every backup should be verifiable without a full restore:

```bash
# List the contents of a dump — non-zero exit if corrupt
pg_restore --list backups/serops_db_20260905.dump > /dev/null && echo OK

# Row count sanity check (attaches to the live DB, read-only)
docker exec serops-postgres psql -U serops -d serops -c \
    "SELECT schemaname, tablename, n_live_tup
     FROM pg_stat_user_tables
     ORDER BY n_live_tup DESC LIMIT 10;"
```

Wire the first check into your backup cron — a corrupt backup that
you don't discover until you need it is worse than no backup.

---

## Related

* [Upgrading](upgrading.md) — the upgrade checklist requires a fresh
  backup before every step
* [Production Deployment](production.md) — the production section on
  DB backups points here for the full procedure
* [Data Retention](../admin/data-retention.md) — application-level
  retention policies (auto-cleanup of old batches, audit logs)
