# Changelog

All notable changes to the SerOps backend are documented in this
file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
starting from `v1.0.0` (see [versioning guide](https://serops.ai/docs/deployment/versioning/)).

## [Unreleased]

## [1.2.10] - 2026-10-31

Data collection release: logs as real shippers write them reach the analysis,
**Check my data** says why a project gets none, and a project can be mapped
onto how its logs are already grouped. Two migrations (Data 0055, Projects
0016) run on their own. Set `SEROPS_VERSION=1.2.10` or `--version 1.2.10`.

After upgrading, SerOps finds logs it used to miss: expect more analyses and
issues for a few batches, until Sentinel's baseline catches up.

### Added

- **Project log rules**: a project's logs no longer need a `project_name` field. Map the project onto how your services are already grouped (`service.namespace = shop`, a Kubernetes namespace, an `app.kubernetes.io/part-of` or `team` label); logs carrying the project name or matching any rule belong to the project, in every log store. **Check my data** lists how untagged logs are grouped and sets a rule in one click.
- **Check my data** (**Projects → [project] → Data**): sends the query the scheduled analysis sends to your log store, one filter at a time (logs found → tagged with the project → in the environment → errors and warnings → from listed services), and says at the first empty step what to change. It lists the project, environment and service values your logs carry, and fixes two things in one click: list a service seen in your errors, or accept the environment value your logs carry (offered also when only some logs carry it, e.g. one team tags `live` and another `prod`; a value another environment of the project uses is never offered). It shows values such as service names, never log messages.
- The project page says what the last scheduled run of each environment did and why it made no analysis: no services, no log integration, nowhere to read logs from, no errors in the window, errors only from unlisted services, the log store refused the query.
- The onboarding wizard shows Check my data when the first analysis has not arrived after two minutes, or when the scheduler already found nothing to analyse, instead of a spinner that never ends.
- An environment's **log label value** (stored before, never used) is now queried: logs tagged with it count for that environment in every provider.

### Fixed

- Log files (`django.log`, `user_actions.log`) grew without limit: they now rotate at `SEROPS_LOG_FILE_MAX_MB` (default 50) and keep `SEROPS_LOG_FILE_BACKUPS` copies (default 5).
- Log warnings never reached the AI. Every provider's warnings are stored as `WARN`, but the prompt filter only kept levels starting with `WARNING`, so warnings were dropped unless their text contained an error keyword. They now reach the analysis and count in the batch's warning total. Found by the RCA benchmark: the decisive `chronyd` clock warning in its clock-skew scenario never reached the model.
- Log redaction blanked ordinary error text. The password and generic-secret patterns treated a plain space after words like `token`, `auth`, `password` or `credential` as the start of a secret, so `token rejected: issued in the future` reached the AI as `[SECRET]: issued in the future` and `password reset failed` as `***** failed`. A secret now needs `:` or `=`, or a value after the space that looks like one (it contains a digit).
- On Kubernetes, the host of a log was often the log shipper (Filebeat, Fluent Bit and the OpenTelemetry Collector write their own name to `host.name`), not where the container ran. The Kubernetes node is preferred now, so "fails on one node only" is visible to the analysis.
- The onboarding wizard showed the whole Check my data panel while waiting for the first analysis: the floating wizard grew taller than the screen, its Minimize button went off-screen and a new customer could not get it out of the way. It now says why nothing was analysed and links to Check my data on the project page.
- During an incident, a finding from reviewing the code (an unused import, a lowered timeout) came out as a second WARNING naming a commit: it read as a second suspect, notified on-call and pointed to an innocent commit. Such findings are now code review notes: INFO, no commit linked, left out of notifications and the incident summary, and shown apart on the analysis page. Outside an incident, code review works as before.
- The logs table of an analysis showed "—" as the service of every log whose shipper did not write `service_name` (Pino, Elastic Common Schema, OpenTelemetry), and the service filter left them out. It reads the service SerOps parsed.
- A batch stored an Elastic Common Schema record's whole `service` object (`{"name": "checkout-api", ...}`) as the service, in place of the name. The parsed name is kept, and the environment is kept wherever the record carried it.
- Errors that differ only by a duration ("failed after 1003ms", "1004ms") were not grouped, so one recurring error could fill the analysis with near-identical lines. Durations are now ignored when grouping, like ids and timestamps.
- Logs written by the OpenTelemetry Collector's Elasticsearch exporter in `otel` mode (the setup Elastic recommends) had no message, service or environment in SerOps: they sit in `body_text` and under `resource.attributes`. Both are read now.
- An issue linked every commit its root cause named, including a commit the analysis named only to clear it ("commit 8a9b0c1d only added a test fixture"), so an innocent commit was shown as the cause. The analysis now lists the commits at fault (`caused_by_commits`), and only those are linked.
- The AI never saw which host a log came from, so a failure confined to one node read like a service-wide one. Log lines now carry the host, and a repeated line says which hosts it came from.

Logs as real shippers write them now reach the analysis. Before, many standard setups silently got no data:

- Elasticsearch and OpenSearch only searched indices named `application-logs-<project>*`, so logs in `logs-*` (Elastic Agent, the OpenTelemetry Collector, our own Elasticsearch guide), `filebeat-*` or `logstash-*` were never read and the project was skipped. SerOps now falls back to those patterns, and a new **Index pattern** setting on the integration names them explicitly.
- Providers were asked for exactly `ERROR`/`WARNING`/`CRITICAL`, so `WARN`, lowercase levels, numeric levels (Pino, Bunyan) and logs with no level field were never fetched from Elasticsearch, OpenSearch, CloudWatch, Splunk or Datadog. Every spelling and case is now queried, numeric levels are read on their own scale, and lines without a level field are reached through their text. A numeric `level` field in one index no longer makes the whole search fail.
- Records in Elastic Common Schema (Filebeat, Elastic Agent) crashed the batch (`service` is an object) or lost their level (`log.level` was not read), and Pino's numeric levels crashed it too. One alias list now serves both querying and reading, flat or nested, with the Elastic Common Schema and OpenTelemetry names added.
- Datadog matched only log attributes (`@env`), not tags (`env:`), so logs tagged through the Agent or Unified Service Tagging were never found. Both are matched now.
- Logs tagged `prod` never matched an environment named `production` (and the reverse), although the guide said they would. Every spelling is queried.
- CloudWatch read every event as INFO with no service, discovered only `/aws/<project>` log groups and passed several groups as one name. Events are now read field by field (JSON) or from the line (text), groups containing the project name are found too, a new **Log groups** setting names them explicitly, and several groups are queried together.
- The first batch of a project queried no time range, so Elasticsearch returned an arbitrary 5000 records and the first analysis was usually empty. It now queries its own window, newest records first.
- `system-*` indices found on one organisation's cluster were added to every organisation's query.
- The metric examples in the data collection guide still used the old `org_id` / `project_id` labels.

## [1.2.9] - 2026-10-27

Security and Sentry release. Migration: Data 0054 (choice only). Containers now run as non-root: see the upgrade note.

### Added

- Sentry alerts: `POST /api/webhooks/alerts/sentry/<org_id>/` receives a Sentry internal integration's webhooks (issue alerts, metric alerts, new issues), verifies the `Sentry-Hook-Signature` HMAC against `SEROPS_SENTRY_CLIENT_SECRET`, and starts an analysis. Migration Data 0054 (choice only).
- The alert that triggered an analysis (any source) is now part of the prompt, fenced as reported evidence: title, state, severity, service and summary, which for Sentry holds the exception, culprit, release and top in-app frames. An alert alone is enough for an analysis.

### Fixed

- Batch creation crashed (`index_pattern` unset) for organisations with no log integration, so a window with only traces, metrics or an alert produced no batch.
- Helm: alert secrets set inline in values (`alertSecrets.*`) were stored under keys the backend didn't read, so they never took effect; only `existingSecret` worked.

### Security

- The legacy GitLab project registration (`POST /api/providers/`, members with `project.write`) had the same flaw as the project check fixed in 1.2.8 (any URL, raw replies echoed) and, on installs with several organisations, answered with another organisation's project and sent that organisation's webhook secret to the caller's GitLab URL. It now applies the same URL rules and refuses a project registered by another organisation (409) without revealing it.
- Integration URLs (`base_url`, observability `host`, connection test) refuse cloud-metadata addresses; private addresses stay allowed. GitLab pipeline logs no longer echo GitLab's raw error. Slack and Teams deliveries no longer follow redirects past the URL check.
- The backend image runs as an unprivileged user (uid 10001) and cannot modify its own code. If the logs directory isn't writable (a volume created by an earlier, root-run release), logging falls back to standard output instead of failing at startup. Celery beat keeps its schedule in `/tmp`. The Helm chart runs every pod under the restricted Pod Security Standard (non-root, no privilege escalation, capabilities dropped, seccomp, read-only root with `emptyDir` scratch space).

## [1.2.8] - 2026-10-26

Security release. No migrations.

### Fixed

- A failure that recovered ("request failed, retrying" then "succeeded on retry 1") reached the AI without its recovery line, which the severity filter dropped as INFO, so a transient blip on a healthy deploy was reported as a warning. The filter now keeps recovery lines for services that already have an error or warning line. Found by the RCA benchmark (h09).

### Added

- `manage.py rca_benchmark`: incidents with a known root cause, run through the real analysis with your own AI key and scored by fixed rules (`backend/rca_benchmark/`).

### Security

- Dependencies with known vulnerabilities, found by an image scan (Trivy) of the published 1.2.7 images: certifi 2026.10.23 (drops emSign roots with compromised intermediates), Django REST Framework 3.18.3 (denial-of-service and an authorization fix), Pillow 13.0.0 (image-decoder memory-safety fixes). The backend image now applies Debian security updates and upgrades setuptools and wheel at build time, and removes pip once requirements are installed (it vendors old urllib3 and msgpack). The frontend and docs images apply Alpine updates (brotli, expat, libX11).
- `POST /api/providers/verify-project/` (GitLab project check, open to members with `project.write`) could be pointed at any URL: it now refuses cloud-metadata addresses, keeps the project id inside `/api/v4/projects/<id>` (no `../`, `?` or `#` escape), doesn't follow redirects, sets a timeout, returns only known project and pipeline fields instead of the server's raw reply, and no longer reads or writes another organisation's GitLab project with the same id. Private addresses stay allowed for self-hosted GitLab.

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
