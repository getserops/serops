---
title: Versioning & Release Contract
description: How SerOps versions its releases, what version compatibility guarantees mean, and how to check what you're running.
tags:
  - deployment
  - operations
---

# Versioning & Release Contract

SerOps follows [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html)
starting from `v1.0.0` (the initial public release). This page is the
contract — what a version bump means, what upgrade paths are
supported, and how to verify the running version.

## The contract

Given a version `MAJOR.MINOR.PATCH`:

| Bump | Means | Upgrade path |
|---|---|---|
| **PATCH** (`1.0.0 → 1.0.1`) | Bug fixes only. No API changes. No new required env vars. | Direct, zero-downtime with Helm rolling update or `docker compose up -d`. |
| **MINOR** (`1.0.0 → 1.1.0`) | New features. New optional env vars. API additions. No removals. | Direct. Read the changelog for new env vars you may want to set. |
| **MAJOR** (`1.x → 2.0.0`) | Breaking changes: removed API endpoints, changed env-var names, incompatible DB schema. | **Via the last minor of the prior major** (e.g. `1.9.x → 2.0.0`, never `1.5.x → 2.0.0`). Read the migration guide. |

Breaking changes are always announced in a **preceding minor** with
deprecation warnings before the major bump removes them.

## Version components

A running SerOps deployment has three versioned pieces:

| Piece | What it is | Where the version lives |
|---|---|---|
| **App version** | The SerOps release itself (backend + frontend as a coordinated pair) | `SEROPS_VERSION` env var → image tag |
| **Helm chart version** | The packaging format for K8s installs | `Chart.yaml:version` (independent of app version — bump on chart change alone) |
| **Helm appVersion** | The default SerOps app version the chart pulls | `Chart.yaml:appVersion` (matches the app release we tested the chart against) |

Chart version bumps independently: a chart-only fix (e.g. a values
template bug) can ship as `chart-0.1.5 / app-1.0.0` without a new app
release.

## How to check what you're running

### From the API (no auth required)

```bash
curl https://your-serops-host/api/version/
# {"version":"1.0.0","git_sha":"a1b2c3d","built_at":"2027-01-22T14:00:00Z"}
```

Same information appears in the running container's environment as
`SEROPS_VERSION`.

### From Docker Compose

```bash
docker inspect serops-backend --format '{{.Config.Image}}'
# ghcr.io/getserops/backend:1.0.0
```

### From Kubernetes / Helm

```bash
helm list -n serops
# NAME    NAMESPACE  REVISION  APP VERSION
# serops  serops     3         1.0.0

kubectl -n serops get deploy serops-backend -o jsonpath='{.spec.template.spec.containers[0].image}'
# ghcr.io/getserops/backend:1.0.0
```

## Pinning a version

**Docker Compose** — set `SEROPS_VERSION` in `.env`:

```bash
# .env
SEROPS_VERSION=1.0.0
```

The bundled `docker-compose.yml` reads this and applies it to both
the backend and frontend images (they're always coordinated). To
upgrade or roll back, edit the line and `docker compose up -d`.

Advanced: override the whole image reference if you mirror the
images to a private registry.

```bash
SEROPS_BACKEND_IMAGE=my-registry.example.com/serops/backend:1.0.0
SEROPS_FRONTEND_IMAGE=my-registry.example.com/serops/frontend:1.0.0
```

**Kubernetes / Helm** — set `image.tag` in your values:

```yaml
image:
  backend:
    repository: ghcr.io/getserops/backend
    tag: "1.0.0"
  frontend:
    repository: ghcr.io/getserops/frontend
    tag: "1.0.0"
```

**Never rely on `:latest` in production.** Rolling latest defeats
version pinning and makes rollbacks impossible. The bundled compose
and Helm chart both use explicit tags by design.

## Docker tag matrix

Every published release ships four Docker tags for the same image:

| Tag | Example | Use case |
|---|---|---|
| `MAJOR.MINOR.PATCH` | `1.0.0` | Exact pin (recommended for production) |
| `MAJOR.MINOR` | `1.0` | Auto-pick latest patch — safe for patch-level auto-updates |
| `MAJOR` | `1` | Auto-pick latest minor — accepts new features silently |
| `latest` | `latest` | Convenience only. **Do not use in production.** |
| `sha-<7chars>` | `sha-a1b2c3d` | Reproducibility for CI/CD pipelines |

## Rollback

If a new release causes issues, downgrade is fast:

**Docker Compose:**

```bash
# In .env
SEROPS_VERSION=1.0.0   # from 1.0.1

docker compose up -d
```

**Helm:**

```bash
helm rollback serops -n serops
# Or to a specific revision:
helm rollback serops 3 -n serops
```

!!! danger "Rollback across a MINOR that includes a migration"
    Downgrading past a Django migration boundary requires restoring
    the pre-migration database backup. See
    [Backup & Restore](backup-restore.md). Rollback within the same
    MINOR (patch downgrade) is always safe because patches never
    change schemas.

## Release cadence

* **PATCH releases** — ship on-demand for bug fixes. Typically
  weekly at cruising altitude.
* **MINOR releases** — targeted at ~monthly to ~6-weekly cadence,
  aggregating features + non-breaking API additions.
* **MAJOR releases** — infrequent (~annually). Every major has a
  named migration guide.

The [changelog](../changelog.md) in the docs lists every published
release; each of the code repos also carries a `CHANGELOG.md` at
its root ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format).

## Pre-release identifiers

Development builds carry the SemVer pre-release suffix `-dev`:

* `1.0.0-dev` = "on the way to 1.0.0, not there yet"
* `1.0.0-rc1` = "release candidate for 1.0.0, feature-frozen"
* `1.0.0` = the actual release

Pre-release identifiers sort **below** the corresponding release per
SemVer rules, so `1.0.0-dev < 1.0.0-rc1 < 1.0.0`.

Don't run pre-releases in production.

## Related

* [Upgrading](upgrading.md) — the full upgrade checklist + compat matrix
* [Backup & Restore](backup-restore.md) — required reading before any upgrade
* [Helm chart](helm.md) — chart-specific version notes
