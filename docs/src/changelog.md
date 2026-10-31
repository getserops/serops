---
seo_title: "Changelog and release notes"
description: "Every SerOps release: new features, fixes, security notes and upgrade steps."
---
# Changelog

All notable changes to the SerOps project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
SerOps uses [Semantic Versioning](deployment/versioning.md) starting at
v1.0.0. Entries under **[Unreleased]** ship in the next tagged release.

---

## [Unreleased]

---

## [1.2.10] - 2026-10-31

Data collection release. Two migrations (Data 0055, Projects 0016) run on
their own. Set `SEROPS_VERSION=1.2.10` or `--version 1.2.10`.

**After upgrading,** SerOps finds logs it used to miss. Expect more analyses
and issues for a few batches, until Sentinel's baseline catches up.

### Logs as your shippers write them

Many standard setups silently got no data. Now:

- Elasticsearch and OpenSearch also search `logs-*`, `filebeat-*` and
  `logstash-*`, and a new **Index pattern** setting names your own indices.
  CloudWatch finds log groups named after the project, and a **Log groups**
  setting names them explicitly.
- Every level spelling is read: `WARN`, lowercase, Pino and Bunyan numeric
  levels, OpenTelemetry severity numbers, and lines with no level field.
- Elastic Common Schema (Filebeat, Elastic Agent), OpenTelemetry (including
  the Collector's Elasticsearch exporter), Fluent Bit, Pino and plain-text
  logs parse correctly. Datadog tags are matched as well as attributes.
- Environment spellings match: logs tagged `prod` belong to `production`.
- On Kubernetes, a log's host is the node, not the log shipper.

### Check my data

**Projects → [project] → Data** shows what the last scheduled run of each
environment did and, when it made no analysis, why. **Check my data** runs
the scheduled query against your log store one filter at a time and stops at
the first step that leaves nothing, with what to change. It lists the
project, environment and service values your logs carry (never log
messages) and fixes common cases in one click: list a service seen in your
errors, or accept an environment value your logs use (`live` for
Production). The onboarding wizard links to it when the first analysis has
not arrived.

### Project log rules

A project's logs no longer need a `project_name` field. Map the project onto
how your services are already grouped (`service.namespace`, a Kubernetes
namespace, an `app.kubernetes.io/part-of` or `team` label). Logs carrying the
project name or matching a rule belong to the project, in every log store.
Check my data lists how untagged logs are grouped and sets a rule in one
click. See [Projects tagged another way](how-to/configure-data-collection.md#projects-tagged-another-way).

### Analysis

- Warnings reach the AI (they were dropped from every prompt).
- An issue links only the commits the analysis says caused it, never a
  commit it named to rule out.
- During an incident, findings from reviewing the code are shown apart as
  code review notes: no notification, no commit blamed.
- Log lines in the prompt carry their host, so "fails on one node only" is
  visible; errors that differ only by a duration are grouped.

### Other fixes

- Log files rotate (`SEROPS_LOG_FILE_MAX_MB`, default 50).
- Redaction no longer blanks ordinary error text after words like `token`.
- The analysis log table shows the service of logs without `service_name`.
- The first batch of a project queries its own time window.

---

## [1.2.9] - 2026-10-27

Security and integrations release. One migration (Data 0054, runs on its
own). Set `SEROPS_VERSION=1.2.9` or `--version 1.2.9`.

**Upgrading with Docker Compose:** the containers now run as non-root
users. A logs volume created by an earlier release belongs to root, so the
backend logs to standard output until you give it the volume once; see
[Upgrading](deployment/upgrading.md#129-containers-run-as-non-root).

### Security

- **Containers run as non-root**: the backend as uid 10001, unable to
  change its own code; the frontend's nginx as uid 101. The Helm chart
  runs every pod under the Kubernetes *restricted* Pod Security Standard
  (no privilege escalation, capabilities dropped, seccomp, read-only root
  filesystem). See [Helm → Security context](deployment/helm.md#security-context).
- The legacy GitLab project registration had the same flaw as the project
  check fixed in 1.2.8, and on installs with several organisations could
  send another organisation's webhook secret to the caller's server. Fixed;
  a project registered by another organisation is now refused.
- Integration URLs refuse cloud-metadata addresses (private addresses still
  work for self-hosted backends). GitLab pipeline logs no longer echo
  GitLab's raw errors. Slack and Teams deliveries no longer follow
  redirects.

### Added

- **Sentry alerts**: a Sentry internal integration can start an analysis,
  verified by its signature. See [Real-time Alerts → Sentry](integrations/alerts.md#sentry).
- The alert that triggered an analysis, from any source, is now part of
  the evidence: for Sentry that includes the exception, release and stack
  frames. An alert alone is enough for an analysis.

### Fixed

- An organisation with no log integration (only traces, metrics or alerts)
  got no batch: batch creation crashed.
- Helm: alert secrets set in values (`alertSecrets.*`) never reached the
  backend; only `existingSecret` worked.

## [1.2.8] - 2026-10-26

Security release. No migrations: set `SEROPS_VERSION=1.2.8` or
`--version 1.2.8`. Upgrade if members you don't fully trust can create
services, or if your images are scanned.

### Security

- The GitLab project check used when adding a service could be pointed at
  any address by a member allowed to edit projects, and returned what it
  fetched. It now refuses cloud-metadata addresses, stays on GitLab's
  project API, doesn't follow redirects and returns only known fields.
  Self-hosted GitLab on a private network still works.
- Dependencies with published vulnerabilities updated: Django REST
  Framework 3.18.3, Pillow 13.0.0, certifi 2026.10.23. The images now
  apply operating-system security updates when they are built, and the
  backend image no longer contains pip.

### Fixed

- A request that failed once and then succeeded on retry could be reported
  as a warning, because the success line never reached the AI. Recovery
  lines are now part of the analysis.

### Added

- [RCA benchmark](development/rca-benchmark.md): incidents with a known
  root cause, run through the real analysis with your own AI key and scored
  by fixed rules, with failures reported.

## [1.2.7] - 2026-10-25

Security fix. No migrations: set `SEROPS_VERSION=1.2.7` or
`--version 1.2.7`.

### Security

- On installs with several organisations, cached dashboard panels (analysis
  feed, MTTR, root causes, service health, correlations) could show one
  organisation's figures to another for up to 5 minutes. Each user now has
  their own cached copy. Single-organisation installs were not exposed.

## [1.2.6] - 2026-10-25

Fixes from the end-to-end journey suite (Helm install to root-cause
analysis, every integration that runs locally), plus Argo CD / Flux
integrations and SSO sign-in domains.

**Upgrade:** migrations run automatically (`providers` 0015-0017, `Users`
0013). Pending invitation links stop working: they had no expiry. Re-send
them. The Celery worker now has a liveness probe
(`celeryWorker.livenessProbe.enabled`).

### Security

- Invitation links expire after 7 days (`INVITATION_TTL_DAYS`) and work
  once.
- CI/CD builds are kept per organisation: two organisations with the same
  Jenkins job name and build number no longer share a record.

### Added

- **Argo CD and Flux integrations** (no credentials). Bind a service to
  one and SerOps shows the webhook URL and secret to configure.
- **SSO sign-in domains**: people at your email domains can sign in with
  SSO before they are invited (Viewer role).
- Settings → Integrations: a **Trace Providers** tab (Jaeger, Zipkin,
  Tempo, Datadog APM); Splunk, Google Cloud and Azure Monitor as log
  providers; **Topology mode** in the provider form.
- An application service can be added without a repository.
- Recent Deployments and "Since the last deploy" include Argo CD, Flux and
  Jenkins deploys of services without a source-control binding.

### Changed

- One **primary** provider per capability and scope. Make the second one a
  fallback.
- The `critical_issue` notification fires when an issue becomes critical
  (new, escalated, or back after an hour), not on every analysis of an
  ongoing incident.

### Fixed

- A fresh Helm install could leave the Celery worker idle without error
  (liveness probe).
- Ollama: the Base URL is saved from the wizard and Settings, with no key.
- Sign-up says when the activation email could not be sent, and points to
  the inbox when it was.
- Saving a provider's Edit dialog no longer clears its environment and
  cluster.
- Argo CD deploys are recorded when the app already reads OutOfSync right
  after the sync.
- Analyses get traces for services that never start a trace, and for the
  investigation's own time window.
- Alertmanager alerts labelled `service_name` keep their service; trace
  IDs are no longer redacted as phone numbers.
- The Traces service filter lists and matches every service in a trace.
- Docs: Argo CD notification template (`oncePer`, body) and the Jenkinsfile
  environment.

---

## [1.2.5] - 2026-10-21

Personal notifications work again. No migrations: set
`SEROPS_VERSION=1.2.5` or `--version 1.2.5`.

### Fixed

- Personal notifications for subscribed projects (email, in-app and
  digests) were not being sent since the September 2026 notifications
  rework. They work again, now also respect your own severity choices, and
  daily or weekly digests arrive at 09:00 in your time zone. Deactivated
  users and users who left the organisation no longer receive them. The
  notifications guide now describes the real behaviour (opt-in
  subscriptions; quiet hours suppress rather than postpone).

### Changed

- The frontend `.env.example` recommends the relative `VITE_BASE_URL=/api`
  in production when the app and the API share a host (no CORS setup, one
  build for any domain).

---

## [1.2.4] - 2026-10-21

Integrations screens: dark mode, keyboard access and consistency. No
migrations, frontend only: set `SEROPS_VERSION=1.2.4` or `--version 1.2.4`.

### Fixed

- Log and metric provider rows, badges, health status and the provider
  dialogs ignored dark mode (white rows with light text).
- Provider pickers were not reachable by keyboard; they are now radio
  cards.
- Source Control showed **Add integration** twice and offered Jenkins, a
  CI/CD-only provider.
- Every Integrations tab has the same header, with the add action in the
  same place; tabs are in the URL (`?tab=cicd|logs|metrics`).
- Integration, provider and cluster dialogs: every field is linked to its
  label, for screen readers. All 69 provider screens pass an automated
  accessibility check in light, dark and phone layouts.
- A few panels (postmortem preview, metric tooltips, error panel, project
  environments) no longer force light colours.

---

## [1.2.3] - 2026-10-20

Fixes a 1.2.2 regression. No migrations: set `SEROPS_VERSION=1.2.3` or
`--version 1.2.3`.

### Fixed

- After saving their profile, a user's browser stored the organisation as
  a number, and the new organisation badge in 1.2.2 then broke the
  sidebar on every page until site data was cleared. Login, profile and
  demo sign-in now all return the organisation's name (plus
  `organisation_id`), and the sidebar ignores anything else.
- Demo sign-in returns the user's permissions, so the demo shows the right
  controls straight away.

---

## [1.2.2] - 2026-10-20

A security release from an internal review and penetration test of
roles, permissions and multi-tenancy, plus confirming an issue's root
cause when resolving it, one issue per shared cause, and logos and photos
stored in the database. Read the [upgrade notes](deployment/upgrading.md#122-security-release):
re-run **Setup Webhook** on each repository binding. Migrations Data
0051–0053, Projects 0015, Organisations 0013, Users 0012.

### Added

- Resolving an issue from its panel asks you to confirm or correct the
  root cause and the fix (prefilled with the AI's). Later analyses use the
  team's version first and see what the AI had said when it was
  corrected; similar-incident search uses it too. The panel shows who
  confirmed it. Migration `Data 0052`.
- Evidence on the analysis page links to where it lives: a commit to the
  batch's code changes (highlighted), a metric anomaly to its metrics, a
  pipeline to the timeline, and the failing trace to the trace.
- The organisation logo is shown next to the organisation name in the
  sidebar. Settings → General and Profile have **Remove logo** and
  **Remove photo**.

### Security

- Dependencies with known vulnerabilities upgraded: Django 5.1 → **5.2
  LTS** (5.2.17; 5.1 is past end of support), Django REST framework
  3.17.2, PyJWT 2.15, Pillow 12.3 (uploaded logos and photos go through
  it), requests 2.33, urllib3 2.8, and others. React Router 7.18 in the
  frontend. Two unused packages removed (`djangorestframework-simplejwt`,
  `react-stepper-horizontal`, which pulled in React 15). `pip-audit` and
  `npm audit` report no known vulnerabilities.
- The Django admin (`/api/admin/`) is off by default (set
  `DJANGO_ADMIN_ENABLED=True` to use it). It had no limit on failed
  logins, while every install has a superuser from the quick start. When
  enabled, its login now allows 10 failures per 10 minutes per client.
  Login rate limits also stop trusting client-written `X-Forwarded-For`
  entries (`TRUSTED_PROXY_COUNT`, default `1`).
- The app's pages were served without security headers (an nginx
  inheritance pitfall dropped them), so on Helm installs another site
  could embed SerOps in a frame (clickjacking). Every response now
  carries `X-Frame-Options: DENY`, `frame-ancestors 'none'`,
  `nosniff`, a Referrer-Policy and a Permissions-Policy. Docker Compose
  installs were covered by Caddy.
- An admin could change another member's email (then reset their
  password and sign in as them). The team API no longer changes emails;
  members change their own in their profile. The last admin of an
  organisation can no longer be demoted or removed, and an invalid role
  returns an error instead of a server error.
- A user of one organisation could create or delete webhooks on another
  organisation's GitLab project, using that organisation's stored token.
  Webhook actions now only act on the caller's own projects.
- Only admins add, edit, delete or test SCM/CI integrations (they hold
  credentials), as already for log/metric sources; only admins delete
  projects and services; viewers no longer read the security and SSO
  settings. The Integrations and Projects pages hide those controls
  from users who can't use them.
- Viewers are read-only again everywhere: they could trigger AI analyses
  and post-mortem drafts, change legacy GitLab projects, run provider
  checks, acknowledge issues and change the setup flow.
- The AI provider list is shared by every organisation; on installs with
  several organisations, only platform staff can change it now (an
  organisation admin could change or delete a provider for everyone).
- The SCM webhook receiver (`/api/webhooks/scm/<id>/`) accepted any
  payload when a binding had no secret, so a guessed binding id let an
  unauthenticated caller inject code-change data into a project. Every
  SCM binding now gets a secret on creation and the receiver rejects a
  binding without one. Existing bindings are backfilled (migration
  `Projects 0015`); re-point the provider-side webhook via **Setup
  Webhook** to send the new secret.
- The legacy GitLab project list (`GET /api/providers/`) returned the
  stored access token (encrypted, but still) to any member of the org,
  including viewers. The token is write-only now and never returned.
- Permissions are checked one way everywhere, modelled on Airflow and
  Grafana: a catalogue of named permissions (`project.write`,
  `integration.manage`, …) granted to the three roles, plus two platform
  permissions no organisation role holds. Every API endpoint declares the
  permission each method needs, and anything undeclared is refused. A test
  fails the build when an endpoint declares nothing, so a new endpoint
  can't ship open to every signed-in user. Nine overlapping role checks
  were replaced. See [Team Management](admin/team.md#roles) and
  [Permissions](development/permissions.md).
- Viewers no longer read retention, data usage or the AI budget (now
  `settings.read`, like the security settings).
- Superusers could read and change any organisation's data through the
  API (batches, post-mortems, issues, projects, including deleting them),
  and this wasn't audited. The quick start creates a superuser, so on an
  install with several organisations its operator could reach every
  tenant. Superusers and staff are now held to their own organisation like
  everyone else; install-wide operations use platform permissions.
- A test now calls every API route as another organisation's admin and
  superuser, and fails on any leak, so a new endpoint can't ship without
  the organisation filter.
- Ids sent in request bodies were not always checked against your
  organisation. A member could create a service in another
  organisation's project (`POST /api/services/…` with its id), subscribe
  to another organisation's project and receive its incident
  notifications, see another organisation's project names through an
  escalation rule, and attach another organisation's environment or
  cluster to a deployment. Every writable relation is now limited to your
  organisation, and a test fails the build when a new one isn't.
- A CI/CD binding could take over another organisation's GitLab project
  (the legacy record is shared per GitLab project id): binding the same
  pipeline id moved it, with a new token, to the binding's organisation,
  whose legacy webhook paths then received the other organisation's CI
  events. The record now stays with its organisation.
- Refused requests are recorded in the audit log (**Access Denied**,
  with the missing permission), once per user and path every 10 minutes.
  Audit entries now record the client address seen by your proxy, not an
  address the client wrote into `X-Forwarded-For`. Migration `Data 0053`.
- The Helm chart no longer publishes `/metrics/` on the ingress. It has
  no authentication by default, so on Helm installs anyone could read the
  install's request, analysis and AI-token counters (no organisation
  data). Prometheus scrapes it inside the cluster; see
  [Self-metrics](admin/self-metrics.md) to publish it with basic auth.
- The backend no longer has a `/images/` route. Nothing used it, and with
  `DEBUG=True` it served the backend directory, `.env` included.
  Production settings (`DEBUG` off) never served it.

### Fixed

- Uploaded organisation logos and profile photos never displayed on a
  production install (they were served only with `DEBUG` on, and on Helm
  only one backend pod had the file). Both are now stored in the
  database, resized to a small PNG. Migrations `Organisations 0013` and
  `Users 0012`: existing profile photos are imported from the media
  volume; existing organisation logos were never kept there and must be
  uploaded again.
- Uploading a profile photo now updates the page and the top bar
  straight away.
- On the analysis page, each issue shows its status, and its button reads
  **View issue** (it said "Open", which read like a status).
- Memory and CPU metrics answered with a server error when no metrics
  source was configured; they return an empty result now.
  `GET /api/settings/api-keys/<provider_id>/` returned a server error; it
  returns that provider's key (masked).

### Changed

- One shared cause is one issue. When DNS, a cache, a database, a
  certificate or one deploy breaks several services, SerOps raises one
  issue on the component where the cause lives and lists the others as
  "also affects", instead of one CRITICAL issue per service. Filtering
  issues by a service includes causes elsewhere that affect it.
  Migration `Data 0051` (new `affected_services` field).
- The SerOps mark in the sidebar is smaller.
- The login and profile responses list the user's `permissions`. The app
  shows buttons and settings pages from that list instead of its own copy
  of the role table: the Settings menu now only lists the pages a role can
  open, and role changes apply when the app next loads.
- Users (not only admins) can run a health check on an existing log or
  metric source, like verifying any other integration.

---

## [1.2.1] - 2026-10-19

Fixes found by testing SerOps' root cause analysis on twelve simulated
incidents: the AI now sees every data source a batch carries, and diff
line numbers survive redaction. Also the SerOps "SO" logo and corrected
Helm install docs. No migrations: set `SEROPS_VERSION=1.2.1` or
`--version 1.2.1`.

### Fixed

- The AI now sees all the incident data in a batch. Logs, metrics, code
  changes, CI results and traces were left out of the prompt whenever the
  organisation had no integration configured for that source, even though
  the batch carried them (OpenTelemetry traces, webhook commits and CI
  results, and alerts arrive without one). A source now counts as available
  when it is configured or the batch has data from it.
- Code diffs sent to the AI kept their hunk headers: the phone-number
  redaction turned `@@ -88,9 +88,9 @@` into `@@ -88,9 [PHONE],9 @@`,
  dropping the line numbers that tie a change to a stack frame.
- A rejected Gemini key ("API key not valid") is reported as an
  authentication error instead of an unknown one.
- Helm docs: the from-source install command failed (setting one field of
  `ingress.hosts` dropped its paths), and neither install explained how to
  use your own hostname; both now use a small values file.

### Changed

- The app uses the SerOps "SO" logo again (sidebar, sign-in pages, browser
  icons).

---

## [1.2.0] - 2026-10-18

A redesigned app, root cause analysis that reads the part of a diff the
incident points at, code diffs for every SCM provider, and redaction of
code before it reaches the AI. No database migrations and no new
environment variables: upgrade by setting `SEROPS_VERSION=1.2.0`
(Docker Compose) or `--version 1.2.0` (Helm).

### Added

- **The AI reads the part of a diff the incident points at.** Diff excerpts
  are chosen from the stack traces and error text in the batch's logs
  (Python, JavaScript/TypeScript, Java/Kotlin, Go, Ruby, PHP, C#): whole
  hunks around the named lines and functions, within a fixed budget of about
  3,000 tokens. Previously each file got its first 500 characters.
- **Diff text for GitHub, Bitbucket and Azure DevOps.** Only GitLab stored
  diff content before; the others stored file names and line counts only.
- **Azure DevOps repositories.** The repository picker lists Git
  repositories across the organisation, and bindings accept
  `organisation/project/repository`, so repositories named differently from
  their project work. The organisation saved on the integration now
  reaches every request.
- Redesigned app: grouped navigation (Integrations and Alerts & routing
  now have their own entries; Dashboard is **Overview**, Data is
  **Analyses**), an environment picker on every page, full-width pages,
  a single page header, compact settings controls, the SerOps logo, and
  dark mode across every page. The list of received traces is reachable
  from Settings → Distributed Traces and the ⌘K palette.

### Security

- Code diffs and commit messages are redacted (credentials, tokens, emails)
  before they reach the AI, like logs. If redaction fails, the diff text is
  left out. See [What SerOps reads from your repositories](security/data-protection.md#what-serops-reads-from-your-repositories).

### Fixed

- Correlations were dropped for a whole batch when an error log named a
  file and the batch had code changes.
- Settings → AI showed $0.00 spent this month when no budget cap was set.
- An open tab no longer shows an error after an upgrade; it reloads into
  the new version.
- Turning off deduplication, recent resolutions or auto-cleanup could not
  be saved.

---

## [1.1.1] - 2026-10-17

Fixes found by end-to-end testing of v1.1.0 on Kubernetes: Sentinel now
skips recurring errors, trace error spans are recognised, chat uses the
selected model, and deploy and notification webhooks are hardened.
Upgrade by setting `SEROPS_VERSION=1.1.1` (Docker Compose) or
`--version 1.1.1` (Helm).

### Fixed

- **Sentinel skipped almost nothing.** It compared log patterns with issue
  fingerprints (a different hash), so every window containing a warning or
  error counted as a "new error pattern" and went to the AI. Sentinel now
  remembers the warning/error patterns it has seen per project and
  environment (numbers, IDs and timestamps ignored) and forgets one after 6
  hours unseen, so recurring errors no longer trigger analysis while new
  or returning ones still do. The "issue regression" rule, which could
  never fire for the same reason, is removed.
- **Spans from OpenTelemetry JSON exporters lost their status and kind.**
  OTLP/HTTP JSON sends these as integers, which were ignored, so failing
  spans never counted as errors in the analysis.
- **AI chat always used Gemini,** whatever model was selected, and failed
  on installs without a Gemini key.
- **Argo CD and Flux deploy events could not authenticate.** Argo CD cannot
  compute the documented HMAC and Flux sends its signature in another
  header. Argo CD now sends the binding secret as a bearer token, and
  Flux's `generic-hmac` signature (`X-Signature`) is accepted. See
  [GitOps deploy events](integrations/gitops.md).

### Security

- **Slack and Teams channel URLs must be public https URLs,** checked when
  saved and again when sending, so an organisation admin cannot make the
  server call internal services or the cloud metadata endpoint.
- **Deploy webhooks refuse unsigned events.** A binding without a secret
  no longer accepts anything, and unknown bindings and bad signatures get
  the same answer, so binding IDs cannot be probed.

**Upgrade notes:** migrations `Data.0049` and `Data.0050` run
automatically. If you send deploy events from Argo CD or Flux, update their
configuration as described in [GitOps deploy events](integrations/gitops.md).

---

## [1.1.0] - 2026-10-17

A UI release: SerOps opens on what is broken and why, with an incident
page, ⌘K search, dark mode, phone layouts and WCAG 2 AA accessibility.
Upgrade by setting `SEROPS_VERSION=1.1.0` (Docker Compose) or
`--version 1.1.0` (Helm).

**Upgrade notes**

- No database migrations and no configuration changes.
- The issue list API gains optional filters (`project`, `environment`,
  `component`, `since_hours`); existing calls are unchanged.

### Added

- **The Overview opens on what's broken now:** the most severe open issue
  with why it is happening and what to do, plus the next ones, before the
  numbers. "All clear" when nothing is open.
- **Incident page:** a batch is titled by the AI's hypothesis, with
  Acknowledge (stops escalation for its open issues), Copy link, Draft
  post-mortem and Re-run analysis.
- **⌘K / Ctrl+K search:** jump to any page, open issue or project, start an
  investigation or switch theme from the keyboard (also in the top bar).
- **Dark mode that works everywhere,** and a **compact density** option in
  the profile menu.
- **Issues:** filter by time ("seen in the last 24 h / 7 / 30 days", API
  `since_hours`), a Last seen column, and when the list last refreshed.
- **UI quality checks in CI:** every main page is checked for accessibility
  (WCAG 2 AA, light and dark), phone layout and table alignment against the
  quick-start stack built from the commit, with screenshots in the report.
- **Issues side panel:** click any issue (or press Enter) to read its root
  cause, recommendation and correlations without leaving the list, then
  resolve, mute, acknowledge, open the analysis, investigate that time window,
  ask the AI or copy a link (`/dash/issues?id=…`).
- **Issues filters:** filter by project, environment and service; the severity
  and status tiles are now clickable filters; a result count shows what
  matches. The API's issue list accepts `project`, `environment` and
  `component` (the service).

### Fixed

- **Read-only demo:** every refused change now shows one friendly notice
  instead of a different error per page ("Error", "Rotation failed", a raw
  `demo_read_only` code), and Settings says up front that it is read-only.
- `/notifications` crashed; it is now a full page at `/dash/notifications`
  (the digest email links there).
- 89 English and 101 French interface texts were missing, so some labels
  showed raw keys (`common.active`) and French users saw English. A test now
  fails if a key is missing from either language.
- The timeline's lane toggles were unreadable (coloured text on grey).
- Browser tabs are titled per page ("Issues · SerOps") instead of all reading
  "SerOps".
- Profile and registration labels fell back to a serif font; the demo user's
  role reads "Read-only demo".
- Settings → General showed the same heading twice; Investigate now defaults
  to the production environment.
- Issues: rows show readable status labels, the root cause under the title
  and full service names; bulk actions only offer what applies to the
  selection; phones get one card per issue instead of a cut-off table.
- Tables on the batch page and in Settings → Audit log were narrower than
  the search bar above them (a Data-page style leaked onto every table).
- **Phones:** tables turn into one card per row (Data, Projects, Delivery,
  Traces, Investigate, Team, Audit log and more); the batch page, Dashboard
  charts, timeline and metrics no longer overflow or overlap.
- The Create Project dialog kept Save below the screen; the 7-day trend drew
  smoothed hills between whole counts (now bars); Recent AI analyses hid most
  items in a small scroll box; the investigation / alert badge sat in the
  Environment column (now a Trigger column); an empty batch showed an empty
  table.
- Typing `(` or `[` in the Data or batch log search crashed the page.
- In the live demo, Settings disables every change with an explanation
  instead of letting Save, Test or Rotate fail.
- The last rows' action menus on Issues were cut off.

### Accessibility

- The main pages pass an automated WCAG 2 AA check (axe) with no violations,
  down from 214: secondary text, badges, links and health tiles meet 4.5:1
  contrast; icon buttons, links and form fields have accessible names; the
  user menu's list structure and decorative charts are fixed.

---

## [1.0.3] - 2026-10-15

A security and feature release: SSO tenant isolation, **Investigate**
(on-demand analysis), and fixes that make scheduled and alert-triggered
analysis work on Kubernetes. Upgrade by setting `SEROPS_VERSION=1.0.3`
(Docker Compose) or `--version 1.0.3` (Helm).

**Upgrade notes**

- Migrations run automatically: `Users.0011` (drops the unused SAML and
  realm fields), `Data.0048` (investigations, batch `trigger`; existing
  alert batches are tagged), `notifications.0007`.
- **Helm installs:** scheduling and AI analysis never ran before this
  release (see Fixed). After upgrading, drop the stale scheduler backlog
  once: `kubectl exec deploy/<release>-celery-worker -- celery -A api purge -Q normal -f`.
- A Helm install with `django.publicUrl` unset now derives `API_URL` from
  the first ingress host (https when TLS is configured).

### Security

- **SSO could sign in as a member of another organisation.** The SSO
  callback matched the email the identity provider returned against every
  user, so an admin who pointed their organisation's SSO at a provider they
  control could sign in as anyone. It now signs in only members of the
  organisation that started the flow, refuses inactive users and emails the
  provider marks unverified, and checks SSO is still switched on.
- **The login and SSO endpoints revealed which emails have an account.**
  Login answers an unknown email and a wrong password the same way, and SSO
  sign-in gives one answer whenever SSO is not available.
- **SSO sign-in showed internal errors.** An organisation without security
  settings got `500 "SecuritySettings matching query does not exist."`.

### Added

- **Investigate.** Analyse a time window now, from the sidebar, a
  deployment on the dashboard ("Investigate") or a batch ("Re-run
  analysis"). Same pipeline as scheduled analysis; Sentinel never skips
  it, it reads the whole window, and it notifies only the requester unless
  routing is opted in. Limited to two running and ten an hour per
  organisation. See [Investigate](user-guide/investigate.md) and the
  `/api/data/investigations/` API. Migration `Data.0048`.
- Batches carry `trigger` (`scheduled`, `alert`, `manual`), shown as a
  badge on alert and investigation batches.
- `DEMO_ONLY_LOGIN=true`, for a public demo host: the login page shows only
  "Try the live demo", and password login, SSO and password reset are
  refused server-side.
- Settings → Security shows the redirect URI to register at the identity
  provider.

### Changed

- "Try the live demo" appears only where a demo user is seeded.
- A failed SSO sign-in returns to the login page with a message instead of
  a JSON error.
- SAML settings are removed (migration `Users.0011`). SAML sign-in never
  worked; use OpenID Connect, which Okta, Entra ID, Google and Keycloak all
  support. Organisations set to SAML have SSO switched off.
- The unused SSO "Realm" field is removed; the discovery URL already names
  the realm.
- **Helm:** the chart now sets `API_URL` and `REACT_URL` from the ingress
  host (or `django.publicUrl`). They were unset, so the SSO redirect URI
  read `None/auth/sso/callback` and account activation emails failed.

### Fixed

- **Helm: no batch was ever scheduled or analysed.** The worker consumed
  only the `high_priority` and `celery` queues, while the scheduler runs on
  `normal` and AI analysis on `background`, so those tasks waited forever.
  The worker now always consumes all four queues, including on releases
  upgraded with `--reuse-values`. Periodic tasks now expire after one
  interval, so a backlog is not replayed. After upgrading an existing Helm
  install, drop the stale scheduler backlog once:
  `kubectl exec deploy/<release>-celery-worker -- celery -A api purge -Q normal -f`.
- **Batches could be linked to another organisation's project.** The
  pipeline looked the project up again by name, and names are only unique
  within an organisation. It now uses the project it was given.
- **Alert-triggered analysis never ran.** The alert's environment reached
  the pipeline as text and crashed it. Alert batches are now created,
  tagged `alert` and linked to their alert exactly.
- **The scheduler skipped data after an alert batch.** The next scheduled
  window started at the alert batch's creation time; minutes before the
  alert window were never analysed. Scheduled windows now continue from
  the previous scheduled batch's end, per deployment.
- Settings → Security showed saved SSO settings as empty after a reload.
- SSO sign-in could not complete on a plain-http install: the handoff
  cookie was always `Secure`, so the browser dropped it. It is `Secure`
  whenever the install is served over https.

---

## [1.0.2] - 2026-10-14

A bug-fix release. Upgrade by setting `SEROPS_VERSION=1.0.2` (Docker
Compose) or `--version 1.0.2` (Helm). No migrations.

### Fixed

- **Helm: the backend never became ready.** The chart set `ALLOWED_HOSTS`
  to the ingress host only, but the kubelet's health checks connect by pod
  IP, so Django answered 400 and the backend restarted in a loop on every
  install. The checks now send `Host: localhost`, which the chart always
  allows.
- **Helm: settings-only upgrades kept the old settings.** Backend and Celery
  pods now restart when the chart's ConfigMap or Secret changes.
- The 7-day trend on the dashboard now includes today.
- The root cause legend shows category names instead of 0, 1, 2.
- AI feed summaries no longer stop at a dot inside a word ("v2.3.4").
- The correlation rate counts an issue linked to both a deploy and a metric
  once.
- Recent deployments names the CI a service is bound to when it has no runs
  yet.
- The cluster list loads after login; it was requested on the login page
  and never retried.
- Settings → Security no longer reports an error on a new organisation's
  first visit.
- The Critical card reads "All clear" when there are no critical issues.

### Changed

- The Helm chart prints next steps after `helm install`.
- Users without an avatar get their initials instead of a stock photo; the
  unused template images are removed.

### Upgrade notes

- Helm users on 1.0.1 must not upgrade with `--reuse-values` alone: it
  keeps 1.0.1's health-check settings. Pass your values again, or use
  `--reset-then-reuse-values` (Helm 3.14+).

---

## [1.0.1] - 2026-10-13

A security and bug-fix release. Upgrade by setting `SEROPS_VERSION=1.0.1`
(Docker Compose) or `--version 1.0.1` (Helm); the database migration runs on
start.

### Security

- **Integration secrets are encrypted and write-only.** Credentials kept in an
  observability integration's `extra_config` (Datadog `api_key` and
  `app_key`, bearer tokens for Prometheus, VictoriaMetrics and Mimir, and
  similar) were stored in plain text and returned by the integrations API to
  every member of the organisation, viewers included. They are now encrypted
  at rest and never returned; responses list which ones are set in
  `secret_fields_set`. Migration `integrations.0010` encrypts existing rows.
- **AWS CloudWatch never uses the server's own AWS credentials.** An
  integration without an access key used to fall back to the host's
  environment, instance profile or pod role. Both halves of the key are now
  required, as Google Cloud and Azure already required their own credentials.
- **The backend refuses to start while a secret still holds the `change-me`
  placeholder** from `.env.example`.

### Fixed

- **AWS CloudWatch works.** The AWS SDK (`boto3`) was missing from the image,
  so the integration could not load in 1.0.0, and the keys entered in
  Settings were saved under names the adapter did not read. The access key ID
  is now the integration's username and the secret its (encrypted) password;
  Settings and the onboarding wizard ask for region, key ID and secret.
- The Distributed Traces settings entry is always visible, so OTLP ingest keys
  can be created before any trace exists.
- The SAML option is gone from Security settings: SAML has no login flow yet.
  Use OpenID Connect.
- Chat labels replies with the provider's display name ("Google Gemini"
  instead of "gemini").
- Documentation URLs without a trailing slash no longer redirect out of
  `/docs`.

### Changed

- **Open registration closes automatically** once the first organisation
  exists. `REGISTRATION_ENABLED` unset means automatic; set it to `True` to
  keep sign-up open for everyone, or `False` to close it from the start.
- Quick start: images are pinned with `SEROPS_VERSION`, migrations run on
  start, and localhost is served over HTTPS by Caddy.

### Upgrade notes

- **CloudWatch integrations created on 1.0.0 must be edited once**: open
  Settings → Global Integrations and enter the access key ID and secret
  access key again. The fields saved by 1.0.0 were never read.
- **If you rely on open sign-up**, set `REGISTRATION_ENABLED=True` before
  upgrading; otherwise new accounts are by invitation once an organisation
  exists.

---

## [1.0.0] - 2026-10-11

First public release: images `ghcr.io/getserops/backend:1.0.0` and
`ghcr.io/getserops/frontend:1.0.0`, Helm chart
`oci://ghcr.io/getserops/charts/serops` 1.0.0. The entries below are what
changed between 0.9.0 and 1.0.0.

### Added — Notification delivery model

SerOps notifications now follow the Grafana / Alertmanager / Sentry
pattern: **one uniform table of delivery targets** plus **one routing
table** that decides which targets fire for which incident.

- **Settings → Delivery Channels** replaces Settings → Notifications.
  Email, Slack, Microsoft Teams, PagerDuty, and OpsGenie are all
  channel *kinds* in a single table. Email is no longer a special
  case with its own page. Recipients for an email channel live in the
  channel's `extra_config.to` (single address, list, or
  comma-separated string).
- **Settings → Routing Rules** is new. Each rule declares a matcher —
  minimum severity, environments, services, event types, all AND-ed,
  with an empty value meaning "no filter on this axis" — and a set of
  target channels. The dispatcher walks every active rule, takes the
  union of matching targets, and de-duplicates so a channel matched by
  several rules is still contacted once.
- **Per-organisation alert-ingest secret** (rotate from Settings →
  Delivery Channels). Inbound Alertmanager / Grafana / Datadog
  webhooks authenticate with `Authorization: Bearer <secret>`. The
  plaintext is shown exactly once on rotation; SerOps stores only its
  SHA-256 hash. Deployments that used the global
  `ALERT_WEBHOOK_SECRETS` setting keep working — the per-org secret
  takes precedence only when set.

### Added — Distributed-trace evidence in root-cause analysis

- Trace spans now reach the AI prompt as first-class evidence.
  A batch whose window contains a slow or failing span gets that span
  cited by ID in the resulting hypothesis, letting the analysis name a
  database lock or an upstream timeout instead of stopping at the
  surface symptom.

### Added — Quality and accessibility test infrastructure

- **Real-prod gauntlet** (`backend/tests_gauntlet/`): 68 synthetic but
  realistic batches covering PII leakage, prompt injection,
  cross-tenant isolation, Sentinel edge cases, provider failure,
  100k-event volume noise, multi-hop cascades, misleading CI/CD
  signals, and log-format chaos. See
  [Testing](development/testing.md).
- **UI invariants** (`frontend/tests/e2e-invariants/`): a Playwright
  suite asserting no console errors, no object-coercion artefacts in
  rendered text, dark-mode legibility, mobile layout integrity, i18n
  completeness, and zero critical `axe-core` accessibility violations.

### Changed

- **Batch re-analysis is now explicit about intent.** The batch list
  offers *Re-run primary analysis* (rewrites the batch's primary
  hypothesis and refreshes its issues) separately from *Compare
  against another model* (records a second opinion without touching
  the primary). Previously "Re-Analyze" only ever did the latter, so
  it appeared to do nothing.
- **Analysis comparison and promotion.** A batch with more than one
  analysis shows them side by side; any alternative can be promoted to
  primary, which re-runs issue de-duplication so existing triage state
  survives.
- **Escalation is controlled by rules alone.** The organisation-wide
  `escalation_enabled` toggle is gone; escalation now happens when an
  `EscalationRule` matches, and does not when none does.
- **Correlation confidence is calibrated.** HIGH / MEDIUM / LOW now
  have documented meanings tied to explicit time-window and
  sample-count thresholds rather than ad-hoc scoring.
- **Batch Detail is a root-cause page, not a log dump.** The AI
  hypothesis, detected issues, and evidence tabs lead; raw logs sit
  below in a real table with timestamp, level, and service columns.

### Fixed

- **Correlations no longer disappear on batches without a deployment
  chain.** Staged code changes are used as evidence when no
  `Deployment` record links them, restoring commit correlation for
  self-hosters who push code events directly.
- **A failed AI call no longer leaves the UI spinning.** Batches whose
  analysis fails now record a terminal state, so the detail page shows
  the error instead of an indefinite loading indicator.
- **Alert-to-project resolution prefers wired projects.** When several
  projects share a service name, the one with SCM and CI/CD
  integrations connected wins over an empty placeholder.
- **Transient AI provider errors are retried** with exponential
  backoff instead of failing the batch on the first 5xx.
- **The AI hypothesis renders as prose.** A serialisation bug could
  store the raw analysis object in the narrative field, producing a
  wall of braces on the batch detail page.
- **Mobile layout** no longer scrolls horizontally on the dashboard,
  batch list, issues list, or batch detail.
- **Accessibility**: labelled every previously unlabelled search
  input, checkbox, filter select, and icon-only button across the
  batch and issue lists.

### Removed

- **`org_settings.NotificationSettings`** and its
  `/api/settings/notifications/` endpoints. Delivery configuration
  moved to `notifications.IncidentNotificationChannel` (see
  *Added — Notification delivery model* above). Existing email, Slack,
  and Teams settings are migrated automatically into channel rows on
  upgrade, and a catch-all routing rule is created per organisation so
  delivery behaviour is unchanged. The legacy
  `/dash/settings/notifications` and `/dash/settings/incident-channels`
  URLs redirect to `/dash/settings/delivery`.

### Documentation

- Corrected container names throughout: services are
  `serops-postgres`, `serops-redis`, `serops-backend`,
  `serops-frontend`, and `serops-caddy` (hyphens, not underscores)
  since the RFC-compliance rename.
- Clarified that **AI provider keys are configured in the UI only**
  (Settings → AI → API Keys) and are never read from environment
  variables — a shared env-var key would pool quota and billing across
  organisations on a multi-tenant self-host.

---

## [0.9.0] - 2026-09-07

### Added — Universal Deployment Topology (Batches 47-55)

- **`ProjectDeployment` model**: One row per (environment × cluster × region × namespace) instance of a project. Multi-region, multi-cluster, and namespace-partitioned projects now analyse each copy independently. See [Deployments](user-guide/deployments.md).
- **`IntegrationScope` model + `priority_tier`**: Observability integrations now carry four scope dimensions (cluster, environment, region, namespace) plus a three-level priority tier (`primary` / `fallback` / `tertiary`). Match-scoring routes each deployment to its most specific integration, with tier-based failover on adapter errors.
- **Batch pipeline switch**: `create_batches_for_all_projects` now iterates `project.deployments.filter(is_active=True)` instead of environments; batches carry a `deployment` FK so pipeline output is scoped correctly.
- **Multi-row Observability panel**: Settings → Observability now lists all integrations per capability with tier badges + scope pills + health status. Add / edit / delete inline.
- **`DeploymentContext` (frontend)**: Composed filter across cluster / environment / region / namespace / deployment, persisted as a single JSON blob in `localStorage`. Dashboard, batches, and analytics all forward the composed filter to the backend. Legacy `ClusterContext` import path preserved via re-export shim.
- **Deployments API**: `GET/POST/PATCH/DELETE /api/projects/deployments/` + `GET /api/projects/deployments/suggest/?cluster={id}` for post-cluster-registration flows.
- **Pre-creation Sentinel gate**: Sentinel decisions can now short-circuit batch persistence (`should_skip_batch_pre_creation`), preventing multi-region × multi-env × N-project fanouts from writing hundreds of noise batch rows per hour. Opt-out via `SentinelConfig.pre_creation_gate_enabled` for audit-trail-first users.
- **Progressive disclosure**: Project detail page auto-hides the Deployments tab when a project has ≤ 1 deployment (SMB projects never see the concept). Multi-deployment projects get a full tabbed view.
- **58 new backend tests** across `ProjectDeployment`, `IntegrationScope`, scope matching, tier-sliced uniqueness, failover chain, and pre-creation gate. 8 new Vitest specs for `DeploymentContext`.

### Migration notes

- Zero user action required. Data migrations seed one `ProjectDeployment` per (project × active env × project.cluster) and one `IntegrationScope` per existing integration (mirroring today's cluster field). Post-save signals keep new rows in sync.
- Backwards compatibility: `useCluster()` hook is a thin alias for `useDeployment()`, legacy `serops.cluster.selected` localStorage key is migrated on first read, and `_best_integration()` still accepts the old `cluster=` kwarg alongside the new `deployment=` kwarg.

---

## [Unreleased] - 2026-02-22

### Added
- **Per-Organisation Batch Interval**: Batch generation interval is now configurable per-organisation from **Settings > Data** (5 min to 12 hours). Default changed from 10 to 15 minutes. The old `BATCH_GENERATION_INTERVAL` env var remains as a system-wide fallback.
- **Interval-Aware Scheduler**: Celery Beat now ticks every 1 minute (`BATCH_SCHEDULER_TICK_RATE`) and checks each organisation's configured interval before dispatching batch creation tasks.
- **Comprehensive API View Tests (181 tests)**: Full test coverage for all major view endpoints across the backend:
    - **Middlewares** (29): RBAC permission classes, subscription middleware, query timeout, permission backend.
    - **Organisations** (20): Onboarding status/skip/reset views, model methods, admin-only enforcement.
    - **Data** (55): Batch CRUD, analytics (issue stats, trends, system health), dashboard (MTTR, sentinel, correlations), settings (security, audit log, retention), metrics.
    - **Projects** (45): Project CRUD, service management, SCM/CICD binding lifecycle, webhook receivers (GitLab/GitHub HMAC validation).
    - **Services** (20): Polymorphic ServiceViewSet, SCM/Infra/Custom sub-ViewSets, write-only credential fields.
    - **Integrations** (15): ObservabilityIntegration CRUD, health check, available providers, org isolation, duplicate provider constraint.
- **Local Test Database**: New `api/test_settings.py` with local PostgreSQL container for stable, fast test runs (2.3s for full suite).

### Fixed
- **Test Suite Auth**: Fixed 40+ test failures caused by tests using DRF `Token` model while the project uses Knox authentication. All tests now use `force_authenticate()`.
- **Test Fingerprint Constraints**: Fixed 9 test errors from Issue creation without fingerprints violating the `unique_open_issue_per_fingerprint_org` constraint.
- **Race Condition Test Resilience**: Added UUID-based unique names and retry-on-deadlock teardown to `TransactionTestCase` tests for stable runs on remote databases.

---

## [Unreleased] - 2026-02-20

### Fixed
- **Webhook Secret Lifecycle**: `CICDBinding.webhook_secret` is now auto-generated on creation — every binding has a secret from the start.
- **Webhook URL Mismatch**: GitLab webhook registrations now use per-binding URLs (`/webhooks/gitlab/{binding_id}/`) with the secret token, instead of the old generic `/gitlab/webhook/` path that couldn't resolve bindings.

### Added
- **`setup-webhook` Action**: New `POST /api/projects/cicd-bindings/{id}/setup-webhook/` endpoint to register webhooks with CI/CD providers automatically. Supports GitLab, GitHub, and Bitbucket API registration; returns manual config URL for Jenkins and Azure DevOps.
- **Payload-Based Binding Resolution**: Legacy webhook URLs (without `binding_id`) now fall back to resolving the binding from the payload's `project.id` field, ensuring backwards compatibility.
- **Legacy GitLab Webhook Route**: Added `/webhooks/gitlab/` route for existing webhooks registered with the old URL pattern.

---

## [Unreleased] - 2026-02-19

### Sentinel Tiered Intelligence (Phase 2 & 3)
- **Active Gating**: Sentinel now gates AI analysis — quiet batches skip AI when active mode is enabled, saving ~80-90% of AI API calls.
- **Per-Org Configuration**: New `SentinelConfig` model with `active_mode` toggle and threshold overrides (error spike multiplier, z-score threshold, max quiet batches).
- **Settings UI**: New **Settings → Sentinel** page with active mode toggle and threshold controls.
- **Sentinel Stats API**: New `GET /api/data/analytics/sentinel/` endpoint returning decision distribution, skip rate, and estimated token savings.
- **Dashboard Card**: New "Sentinel Intelligence" card on the dashboard showing AI skip rate, decision breakdown, and savings summary.
- **Batch List Badges**: Colored sentinel decision badges (alert/quiet/first/shadow) in the batch list table.
- **Forced Periodic Safety Net**: Even in active mode, AI is forced after N consecutive quiet batches (configurable, default 12).
- **AI Analysis Tracking**: `record_ai_analysis()` resets quiet counters after successful AI completion.
- **35 Tests**: Comprehensive test coverage for sentinel config, active gating, stats API, and model tests.

---

## [Unreleased] - 2026-02-16

### Deduplication Hardening
- **Database-Level Uniqueness**: Partial unique constraint on `(fingerprint, project)` for OPEN/MUTED issues — prevents duplicate issues at the DB level, not just application logic.
- **Race Condition Fix (TOCTOU)**: `select_for_update()` + `F()` expressions with IntegrityError retry loop — concurrent Celery workers can no longer create duplicate issues.
- **Organisation Isolation**: All log deduplication calls now pass the `organisation` filter, preventing cross-tenant dedup leakage.
- **Distributed Task Locking**: Celery batch tasks use Django cache-based locks (`cache.add` atomic set-if-not-exists) to prevent overlapping runs.
- **Time-Windowed Log Dedup**: `deduplicate_logs()` now respects `time_tolerance_seconds` — identical errors are only grouped when they occur within the tolerance window.
- **Scalability**: Log uniqueness filter uses `fetchmany()` chunked iteration + 30-day lookback cap to prevent unbounded memory growth.
- **SQL Injection Prevention**: `_escape_like()` escapes `%`, `_`, `\` in project names used in ILIKE queries.
- **Legacy Cleanup**: Removed dead code in `Data/utils/` (old `deduplicate_logs` and `remove_duplicate_logs`).

### Performance (Phase 2)
- **Database Indexes**: Added composite indexes on Issue model for common query patterns (100x query speedup).
- **ServiceHealthView N+1 Fix**: Replaced per-service `.count()` queries with `.aggregate()` — 75% query reduction, dashboard 90% faster (3-5s to <500ms).
- **Redis Caching**: Dashboard and stats views cached with 5-15 min TTL. Cache invalidation on Issue save/delete. 80%+ cache hit rate.
- **Aggregation Optimization**: RecommendationStatsView uses database `COUNT()` instead of Python loops — memory usage from 1GB to <10MB.
- **Celery Worker Concurrency**: Configurable concurrency, 6x faster batch processing (25 min to 3-4 min).
- **Task Routing & Priorities**: Separate Celery queues for analysis, ingestion, and notifications. Priority-based scheduling.

### Fixed (Phase 1)
- **Undefined Variable Bug**: Fixed `cpu_metrics` undefined in `Data/tasks.py` causing crashes during batch processing.
- **Missing Retry Logic**: Added exponential backoff retry (3 attempts) to all batch creation Celery tasks.
- **N+1 Query in Deduplication**: Optimized issue deduplication — 10x query speedup, 90% memory reduction.
- **Race Condition in Issue Dedup**: Added atomic operations with row-level locking to prevent duplicate issues.
- **Sequential Batch Processing**: Batch creation now runs in parallel via Celery (5x speedup).
- **AI Cost Tracking**: New `AITokenUsage` and `OrganisationAIQuota` models for token usage tracking and monthly quota enforcement.

### Added
- **Provider Encryption Improvements**: Updated credential encryption in provider integrations.

---

## [Unreleased] - 2026-01-24

### Added
- **AI Provider Extensibility**: Plugin-based architecture to support any AI provider via adapters.
- **Provider Management UI**: New **Settings > AI > Manage Providers** section to:
  - Add custom providers (e.g., Local Ollama).
  - Configure adapters (Gemini, Claude, OpenAI Compatible).
  - Set custom API keys and Base URLs.
- **Multi-Provider Support**: Native integration for **Anthropic Claude**, **DeepSeek**, and **Google Gemini**.
- **Dynamic Model Selection**: Chat and Batch Analysis dropdowns now dynamically list all active providers.

### Fixed
- **Provider Save Error (405)**: Fixed `PUT` method support in provider settings API.
- **Missing Models**: Fixed `AvailableModelsView` to include system-wide active providers even without custom config.
- **Batch Analysis Auth**: Fixed `batch.project` attribute error in async tasks.
- **Log Noise**: Clarified that 403 errors in logs are due to harmless demo data.

---

## [Unreleased] - 2026-01-20

### Added
- **Add Service Wizard**: New 3-step guided flow for connecting services.
  - **Step 1: Choose Type** - Visual cards for Application, Infrastructure, or Custom services.
  - **Step 2: Connect Code** - Seamless Integration -> Repository selection with smart defaults.
  - **Step 3: CI/CD** - Optional pipeline configuration step.
  - **Auto-Fill**: Service Name is automatically extracted from repository name (e.g., `docs` from `group/docs`).
- **Integrations UI Overhaul**: Modernized `Settings > Integrations` page.
  - **Grid Layout** - Clean, visual cards for all supported providers.
  - **Badge Status** - Clear Active/Inactive indicators.
  - **Coming Soon** - Placeholders for future integrations (JIRA, Slack, etc.).

### Fixed
- **Service Creation**: Standardized `service_type` validation (unified `application` type for all SCM providers).
- **Repository Loading**: Fixed `getRepos` API call and improved response parsing (handles array, paginated, and direct object formats).
- **Legacy Cleanup**: Removed deprecated Add Service modal and cleaned up unused code.

---

## [Unreleased] - 2026-01-17

### Added
- **Smart Issue Deduplication (v3)**: AI now classifies errors with `error_class` and `error_target` for more precise issue grouping.
  - 20 error categories: COMMAND_NOT_FOUND, MODULE_NOT_FOUND, CONNECTION_REFUSED, AUTH_FAILED, TEST_ASSERTION, etc.
  - Different errors of the same type now create separate issues (e.g., `chmod9` vs `chmod10` not found)
  - Backward compatible: existing issues unchanged, new issues get enhanced classification

### Fixed
- **CI/CD Trace Storage**: Traces now update existing ES documents instead of creating duplicates.
- **Date Value Out of Range**: Fixed anomaly detection crash when metric timestamps are invalid.

---

## [Unreleased] - 2026-01-13/14

### Added
- **Robust Deployment Sync**: Direct GitLab API sync fallback for webhook failures, periodic sync every 10 minutes via Celery beat.
- **CI/CD Trace Capture & Display**:
  - Full job traces stored in Elasticsearch with preprocessing
  - Traces displayed in batch detail UI with "--- Job Output ---" section
  - Preprocessed `trace_errors` field (max 20 error lines) for AI token efficiency
- **Code Changes Enhancement**:
  - `service_name` field shows which service each commit belongs to
  - Gray badge in Code Changes UI displaying service name
  - Full diffs included in batch data (truncated to 500 chars per file for AI)
- **Dynamic Service Filtering**: CI/CD logs now show actual service name (backend/frontend) in dropdown filter instead of hardcoded "CI/CD".
- **AI Analysis Improvements**:
  - `repair_json()` helper for robust JSON parsing
  - CI/CD Pipeline Outputs section added to AI prompt for failed job correlation

### Fixed
- **405 Method Not Allowed**: Fixed `/api/data/batches/reanalyze/` endpoint (URL pattern ordering).
- **Tuple Unpacking Error**: Fixed `reanalyze_batch_with_model` task.
- **Trace Storage Bug**: Fixed `job_instance.log` → `job_instance.logs` field name.
- **Environment Import**: Fixed `detect_environment_generic` import for trace indexing.

---

## [Unreleased] - 2026-01-12

### Added
- **Issue Deduplication v2**: Intelligent fingerprint-based deduplication to prevent duplicate issues across batches.
  - 25+ issue types (MEMORY_HIGH, CPU_HIGH, DATABASE_ERROR, API_ERROR, etc.)
  - Scope-based classification (SERVICE, INFRASTRUCTURE, PIPELINE)
  - Component normalization for consistent fingerprinting
  - Tiered matching with infrastructure promotion
  - Intra-batch deduplication
- **Issue Management Actions**: Manual issue lifecycle control.
  - **Resolve** - Mark issues as fixed (auto-reopens if same fingerprint detected)
  - **Mute** - Suppress notifications for 1/7/30/90 days or forever
  - **Reopen** - Bring back resolved or muted issues
- **Enhanced Issues Table**: New columns and UI improvements.
  - Type column (MEMORY_HIGH, API_ERROR, etc.)
  - Component column (affected service)
  - Occurrence count badge (2×, 5×)
  - Status column (OPEN, MUTED, RESOLVED)
  - Action buttons (resolve, mute, reopen)
- **New Filters**: Status filter (Open, Muted, Resolved) added to Issues page.
- **New API Endpoint**: `POST /api/data/issues/{id}/{action}/` for resolve, mute, reopen actions.

### Fixed
- **Legacy Batch Compatibility**: Batches analyzed before v2 now fall back to parsing `analysis_text` JSON.
- **Issues link regression**: Fixed batch-specific issues page showing 0 issues for legacy batches.
- **Component Identification**: AI now uses `service_name` from log/code change metadata instead of guessing from log content.

---

## [Unreleased] - 2026-01-07

### Added
- **Environment-Based Data Isolation**: Batch creation now runs per-environment (development, staging, production) with user-defined branch patterns.
- **Project Environments UI**: New section in "Create Project" modal with:
  - Editable branch patterns per environment
  - Add custom environments (e.g., qa, uat)
  - Remove custom environments (default 3 cannot be removed)
- **Environment Badge in Data Page**: Color-coded badges (🟢 Production, 🟡 Staging, 🔵 Development) in batch list.
- **Batch Creation Safeguards (3-Level Protection)**:
  - L1: Skip projects with 0 services
  - L2: Skip batches with 0 data points (logs + cicd + changes + metrics)
  - L3: Skip AI API call if batch has no meaningful data
- **API Enhancement**: Environment filter parameter added to batch list endpoint (`GET /api/data/batches/?environment=development`).

### Fixed
- **Project Isolation Bug**: Fixed issue where projects without services were creating batches and consuming AI API quota.
- **Empty Batch Prevention**: Batches are no longer created for environments with no data.

### Removed
- **Metrics Page Environment Filter**: Removed redundant filter (metrics are host-level, not environment-specific).

---

## [Unreleased] - 2026-01-04

### Added
- **Enhanced Batch Re-Analysis**: Multi-select batches and re-analyze with different AI models (Gemini, DeepSeek).
- **Model Comparison**: Store analysis history per batch, enabling side-by-side comparison of results from different AI models.
- **Action Dropdown Menu**: New dropdown in Data page with options: "Re-Analyze with Gemini", "Re-Analyze with DeepSeek", "Chat about Batch", "Compare Model Results".
- **New API Endpoints**:
  - `POST /api/data/batches/reanalyze/` - Queue re-analysis for selected batches with specific model.
  - `GET /api/data/batches/<batch_id>/history/` - Get analysis history for model comparison.
- **Backend**: Added `analysis_history` JSONField to AIAnalyzedBatch model for storing multiple analysis results.
- **Celery Task**: New `reanalyze_batch_with_model` task for background re-analysis.

---

## [Unreleased] - 2026-01-03

### Added
- **Multi-Tenancy Metrics Isolation**: Metrics now filtered by `org_id + environment + project_id` for complete tenant isolation.
- **Organisation-Level Deployment Filtering**: Added `organisation_id` parameter to `DeploymentService.get_deployments_for_batch()` for query-level org isolation.

### Fixed
- **Deployment Webhook**: Now captures ALL pipeline statuses (pending, running, failed, success) instead of only successful ones.
- **CI/CD Logs Security**: Removed dangerous wildcard fallback (`ci_cd-logs-*`) that could leak cross-project data.
- **Environment Detection**: Moved environment detection before metrics fetch to ensure correct filtering.

### Security
- **P1 Fix**: Code Changes now query-filtered by organisation at database level (prevents cross-org data in memory).
- **P2 Fix**: CI/CD logs query skipped entirely if no project name (prevents wildcard data leakage).

---

## [Unreleased] - 2026-01-01

### Added
- **GitLab-Style Settings UI**: Refactored major settings pages (`General`, `Team`, `Notifications`, `AI`, `Data`, `Security`, `Integrations`) to use a consistent, collapsible section layout.
- **Localization (i18n)**:
    - Complete French translations for "System Health" Dashboard, Metrics, and Charts.
    - Added missing translation keys for Notification Panel and Settings.
- **Error Handling**: Improved error reporting for Organization Logo upload (now shows specific backend error messages).

### Fixed
- **Dashboard UI**:
    - Fixed "100%" text overlap on System Health gauge chart by adjusting font size and position.
    - Resolved mixed English/French text on Dashboard cards (MTTR, Status, Trends).
- **Data Page**:
    - Fixed pagination logic error where filtering by "All Projects" failed due to string mismatch.
- **Issues Page**:
    - Corrected "Errors" column alignment to be left-aligned (`text-start`).
- **Notification System**:
    - Fixed "Unread" count pluralization issue (e.g., "19 Unread").
    - Fixed Notification Settings toggle switches visibility (was hidden due to missing `display: block`).
    - Fixed `NotificationPanel` interactivity and navigation.

### Changed
- **Styling**: Centralized `NotificationPanel` styles into `NotificationPanel.css`.
- **Refactoring**: Updated multiple components to use `react-router-dom` for smoother navigation.

