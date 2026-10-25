# Changelog

All notable changes to the SerOps backend are documented in this
file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
starting from `v1.0.0` (see [versioning guide](https://serops.ai/docs/deployment/versioning/)).

## [Unreleased]

## [1.2.7] - 2026-10-25

Security: cached dashboard views vary on Authorization and Cookie (`cache_per_user`), so one organisation's cached response is never served to another. No migrations.

## [1.2.6] - 2026-10-25

See the full notes in docs/src/changelog.md (journey-suite fixes, Argo CD / Flux integrations, SSO sign-in domains).
Migrations: providers 0015-0017, Users 0013.

## [1.2.5] - 2026-10-21

No migrations.

### Fixed

- Personal project-subscription notifications (email, in-app, digests) were never sent since the 2026-09 notifications cleanup: `notifications.dispatcher` still imported the retired `NotificationSettings` model and every dispatch raised. The dispatcher now uses only the user's preferences and subscription; team-wide Slack/Teams delivery stays with Delivery Channels and Routing Rules. The user's own severity choices now apply (they were ignored), deactivated users and users who left the organisation are skipped, and daily/weekly digests arrive at 09:00 in the user's time zone. Dead per-org sender-name lookup removed from `notifications.services`.

## [1.2.4] - 2026-10-21

No backend changes (frontend-only release); image rebuilt at 1.2.4 so versions match.

## [1.2.3] - 2026-10-20

`UserSerializer.organisation` is the organisation's name (read-only) plus `organisation_id` for login, profile and demo-login; demo-login returns the full serializer (permissions). No migrations.

## [1.2.2] - 2026-10-20

Security release (roles, tenancy, webhooks, dependencies), issue resolution
with the team's root cause, one issue per shared cause, logos and avatars in
the database. Migrations Data 0051–0053, Projects 0015, Organisations 0013,
Users 0012. Full notes in the [project changelog](https://serops.ai/docs/changelog/).

### Security

- SCM webhook receiver fails closed: bindings get a webhook secret on creation (`SCMBinding.save`), the receiver rejects a secretless binding, and existing rows are backfilled (migration `Projects 0015`). Previously a secretless binding accepted unauthenticated payloads.
- Role gaps closed and cross-tenant GitLab webhook actions blocked (see commits); AI provider catalogue writes need platform staff on multi-org installs.
- `/images/` media route removed (unused; under `DEBUG=True` it served `MEDIA_ROOT` = the backend directory). Helm: `/metrics` removed from the default ingress paths (unauthenticated by default; scrape in-cluster via `serviceMonitor`).
- `CICDBinding._sync_legacy_gitlab_project` no longer moves another organisation's `GitlabProject` row (global `project_id` uniqueness let a binding take it over, token included).
- Body ids limited to the requester's organisation (`Utils/scoped_relations.limit_relations`): service `project` (create and update), project-subscription and escalation-rule `project`, project-service `project`/`gitlab_project`/`provider_integration`, deployment `environment` (must be the project's) and `cluster`. Notification and Issue relations and `UserSerializer.organisation` are read-only. `Middlewares/tests/test_body_relations.py` fails on any writable relation left open.
- Superuser tenancy bypass removed (30 `is_superuser` branches in Data, Projects, notifications, ai_model, Organisations views): superusers could read, change and delete other organisations' objects via the API. `BatchIssuesView` also refused a user without an organisation only when the batch had one.
- `Middlewares/tests/test_tenant_coverage.py`: walks every API route as another org's admin and superuser (marker scan on lists, `TARGETS` map for routes with ids, no 5xx).
- `ACCESS_DENIED` audit entries from `Requires` (cache-deduplicated per user/method/path, 10 min); migration `Data 0053`. `get_client_ip` takes the `X-Forwarded-For` entry added by the trusted proxy (`NUM_PROXIES`).
- One RBAC model (`Middlewares/rbac.py`): `PERMISSIONS` catalogue, cumulative `ROLE_PERMISSIONS`, platform permissions (`ai_catalogue.manage`, `platform.manage`), one `has_permission()`. Every API view declares `Requires(...)` per method or viewset action; undeclared requests are denied. `Middlewares/tests/test_permission_coverage.py` fails on any route without full coverage (public endpoints are allowlisted with how they authenticate). Removed: `Users/permissions.py` (`IsAdminRole`, `ReadOnlyForViewer`, `IsUserOrAdmin`, `CanManageSharedSettings`), `require_role`, `Middlewares/OrganisationMiddleware.py`, in-view role checks, and the unrouted `JobList` and `Gitlab_save_logs` views.

### Added

- Issue resolution: `resolved_by`, `resolution_root_cause`, `resolution_fix` (migration `Data 0052`). `POST /api/data/issues/<id>/resolve/` accepts optional `root_cause` and `fix`; bulk resolve records `resolved_by`. Past-incident memory and issue embeddings prefer the team's root cause and fix, rank confirmed resolutions first and label corrections.

### Changed

- `UserSerializer` (login, profile) returns `permissions`, the user's sorted permission list.
- Viewers lose read access to retention, data usage and AI budget (`settings.read`); users gain the observability source health check (`integration.use`).
- One issue per root cause: the analysis prompt asks for one issue on the component where a shared cause lives, with the other services in the new `Issue.affected_services` (merged on recurrence; the issue `component` filter matches it). Migration `Data 0051`.

### Fixed

- `NodeMemoryRawView` / `NodeCPURawView` returned 500 without a metric integration; `APIKeysView` GET on the detail URL returned 500 (now returns that key; POST there is 405).
- Organisation logos and profile photos are stored in the database as
  small PNGs (they were never served with `DEBUG` off). Profile photos are
  served at `GET /api/auth/avatar/<key>`; `DELETE
  /api/auth/profile/upload-avatar/` and an empty `logo` remove them.
  Migrations `Organisations 0013`, `Users 0012`.

## [1.2.1] - 2026-10-19

Fixes: the AI sees every data source a batch carries (sections were hidden
when no integration was configured), diff hunk headers survive redaction,
a rejected Gemini key reads as an auth error; SerOps "SO" logo; Helm docs.
Full notes in the [project changelog](https://serops.ai/docs/changelog/).

## [1.2.0] - 2026-10-18

A redesigned app (full-width pages, grouped navigation, environment
picker, dark mode everywhere), AI analysis that reads the diff hunks the
stack traces point at, diff text for GitHub/Bitbucket/Azure DevOps, code
redaction before the AI, and Azure DevOps repositories. No migrations.
Full notes in the [project changelog](https://serops.ai/docs/changelog/).

## [1.1.1] - 2026-10-17

Fixes: Sentinel skips recurring errors, OTLP JSON span status, chat model
selection, Argo CD/Flux deploy webhook authentication; Slack/Teams URL
validation and required deploy webhook signatures.
Full notes in the [project changelog](https://serops.ai/docs/changelog/).

## [1.1.0] - 2026-10-17

UI release: incident-first Overview and incident page, Issues side panel
and filters, ⌘K search, dark mode, phone layouts, WCAG 2 AA.
Full notes in the [project changelog](https://serops.ai/docs/changelog/).

## [1.0.3] - 2026-10-15

Security and feature release: SSO tenant isolation, Investigate
(on-demand analysis), and scheduled/alert analysis fixed on Kubernetes.
Full notes in the [project changelog](https://serops.ai/docs/changelog/).

## [1.0.2] - 2026-10-14

Bug-fix release: the Helm chart's backend now starts, plus dashboard
fixes. Full notes in the
[project changelog](https://serops.ai/docs/changelog/).

## [1.0.1] - 2026-10-13

Security and bug-fix release. Full notes in the
[project changelog](https://serops.ai/docs/changelog/).

## [1.0.0] - 2026-10-11

First public release.

### Added
- Auto-detect enabled data sources per project (capability registry).
- OTLP HTTP receiver + Trace/Span models + IngestKey auth.
- Trace adapters for Jaeger, Zipkin, Datadog APM, Grafana Tempo.
- Unified event timeline API (`/api/data/batches/<id>/timeline/`)
  with engine-backed causal pairs.
- Real-time alert webhooks (Alertmanager, Grafana, Datadog Monitors).
- Native ArgoCD + Flux GitOps deploy webhooks.
- Multi-cluster K8s model + cluster-scoped observability integrations.
- Post-RCA notification channels: Slack, Teams, PagerDuty, OpsGenie.
- Prometheus self-metrics `/metrics/` endpoint.
- Kubernetes Helm chart (OCI + classic repo publish on `v*.*.*`).
- Similar-incidents suggestion + post-mortem draft generator.
- Per-org monthly AI cost budget + `/api/settings/ai/budget/`.
- First-class on-prem Ollama support + admin-only probe endpoint.
- `DataSourceContext` dataclass — replaces 13-kwarg fan-out on the
  prompt builder.
- AI adapter error classification for timeout / overloaded /
  server_error / network_error / (Gemini) content_blocked.
- `/api/version/` endpoint exposing version + git sha + build time.

### Changed
- AI adapter clients now explicit 120s request timeout (was
  provider-default 600s / Gemini none).
- ES helper now defaults to `verify_certs: True`.
- Password policy validators now fire through DRF serializers.

### Fixed
- IDOR: `providers.views.JobList` scoped pipeline query to project.
- Password-reset user enumeration (constant-response).
- Invitation / verification / reset tokens no longer logged verbatim.
- AI chat prompt no longer logged at INFO.

### Security
- Explicit cookie hardening (`SESSION_COOKIE_HTTPONLY`,
  `SESSION_COOKIE_SAMESITE=Lax`, same for CSRF).
- Ollama probe endpoint rejects cloud-metadata IPs (SSRF guard).
- File upload capped at 10MB.
- Base-text XSS closed in `renderFormattedText` (frontend).

### Removed
- 19 unused pip packages (previous 10 + Batch 36's 9-package
  aiohttp/threadpoolctl/watchdog transitive chain).

[Unreleased]: https://github.com/getserops/serops/compare/v1.0.2...HEAD
[1.0.2]: https://github.com/getserops/serops/releases/tag/v1.0.2
[1.0.1]: https://github.com/getserops/serops/releases/tag/v1.0.1
[1.0.0]: https://github.com/getserops/serops/releases/tag/v1.0.0
