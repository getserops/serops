# Changelog

All notable changes to the SerOps frontend are documented in this
file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
starting from `v1.0.0`.

Frontend and backend versions are coordinated — a `v1.0.0` release
means backend + frontend + Helm chart appVersion all match.

## [Unreleased]

## [1.3.0] - 2026-11-11

Roles, teams and per-project access screens, Settings → Enterprise license, the sample incident and the email-change confirmation. Same version as the backend and the chart.

### Security

- Changing your email asks for your current password and is finished from a link sent to the new address (`/email/confirm/:token`).
- SSO sign-in sends the cookie that binds it to this browser.

### Added

- A sample incident, offered from the setup wizard and from the empty analyses card: the real incident page on made-up data, labelled as such, so a new install shows what SerOps produces before anything is connected. It stores nothing in the organisation and calls no AI provider
- Added `src/ee/` (SerOps Enterprise License) with Settings → Enterprise license; `utils/edition.js` (`useEdition`, `hasFeature`, Enterprise settings pages found with `import.meta.glob`, empty without `src/ee/`). `index.html` carries the serops.ai description and link-preview metadata.
- Settings → Security → SSO: rules from identity-provider groups to roles (ordered, add / move / remove), default role or refuse, sync at every sign-in, email domains. Login explains a refused SSO sign-in (`?sso=denied`); Team says when roles come from the identity provider.
- Settings → Roles (Enterprise, `src/ee/access`): custom roles built from grouped permissions (always-included and prerequisite permissions locked), member counts, edit/delete. Team invites and edits offer custom roles; SSO rules can target them; Profile and Team show the role name.
- Settings → Teams (members, SSO-sourced badge, project grants) and the project Access tab (Enterprise, `src/ee/access`, registered through `enterpriseProjectTabs`; without the license it can only open, lower or remove). `withEnterprisePages` places Enterprise menu items (`after`). Project buttons use the project's own `permissions` (`canOnProject`); New project needs the organisation role. SSO team rules. The Team page is labelled Members; page titles and the command palette know Roles and Teams.

### Fixed

- Profile: a refused save, or a refused new password, says why.
- The onboarding reminder chip (z-index 1300) covered Bootstrap dialogs' buttons; now 1040.

## [1.2.14] - 2026-11-07

### Security

- Content-Security-Policy: script only from SerOps itself. The login token is in the browser's storage, so a script injected through any future rendering bug could have taken over the account; it is now blocked. The unused inline script in `index.html` is gone and collapsible sections no longer use an inline `onclick`. The UI quality gate fails on any page the policy blocks something on.
- Fonts (Inter, IBM Plex Mono) ship with the app instead of loading from Google Fonts: every visitor's browser contacted Google, air-gapped installs fell back to system fonts, and the Content-Security-Policy blocks it.
- nginx no longer sends its version (`server_tokens off`).
- The image build honours `--build-arg VITE_BASE_URL` (the committed `.env.production` silently won), and a developer's local `.env*.local` or `node_modules` no longer reach the image (`.dockerignore`).

### Added

- Analysis page, Metrics: Kubernetes changes (rollouts with their image change, scale changes), containers that cannot start and Deployments short of replicas, next to the container terminations.
- Analysis page, Metrics: services throttled by their CPU limit.
- Analysis page, Metrics: rollouts that are not completing while the previous version still serves.
- Analyses list: labels for the Sentinel triggers `trace_latency_spike` and `trace_error_spike`.

### Changed

- Settings → Sentinel shows active mode as the default while it loads.

### Fixed

- Onboarding, Google Cloud: the wizard asks for the project ID, the service-account key and whether the services run on GKE, and no longer shows the host, username and API key fields Google does not use. It saved Google integrations without a project, so they never worked.
- Loading spinners have an accessible name ("Loading", or "Setup progress" for the onboarding ring): screen readers announced an unnamed progress bar (axe `aria-progressbar-name`).
- A failed analysis's tooltip names the new provider errors: no credit left, overloaded, server error, redaction failed.

- Analysis page, Metrics: a stuck rollout says how many new pods are not ready instead of "1 of 1 updated".
- Analysis page, Metrics: a workload back to full strength says it has recovered.
- An analysis where the AI ran and found nothing said "Sentinel skipped AI analysis" next to the model name and token count. The page now says which it was: skipped by Sentinel (no model or tokens shown), analysed with nothing wrong found, or not analysed yet.
- Phones: buttons in stacked table cards keep their size (Projects' Services and Batches were squeezed, their words broken letter by letter); the AI Chat no longer pushes the top bar off the screen or cuts its placeholder; the Traces list shows 20 traces a page (50 cards made a page about 13,000 px long); the issue menu and audit-log toggles are 32 px tap targets.
- AI settings: saving the primary model sent back the monthly budget loaded with the page and erased a budget saved a moment before (the spending cap silently gone). It now sends only the model fields.
- Analysis page on phones: the title (the whole first issue sentence) is at most four lines; log messages use the card's full width (a stack trace was squeezed into a narrow column, ~2000 px a line).
- Choosing the primary AI model saves it at once: it waited for the Save button at the bottom of the page, and leaving without it kept the old model with nothing said.
- Project services list: the count read "1 - 5 of 10" for six services (and "6 - 2 of 2" on page 2); it shows ten a page and opens the page of a service just created, which used to land on a later page with nothing visible changing.
- An address that matches no page shows "Page not found" instead of an empty area; `/dash/` with a trailing slash is the Overview.
- The AI Chat no longer labels its greeting "gemini" before the organisation's models load.
- AI Chat: the sensitive-data warning said a message is sent "without modifications"; secrets in it are now masked by the backend before it reaches the AI provider, and the warning says so.

## [1.2.13] - 2026-11-01

### Changed

- Azure Monitor integration form: the workspace and resource URI fields say what each is for (the workspace also gives per-service AKS metrics; the resource URI is optional for AKS).

## [1.2.12] - 2026-10-31

### Fixed

- Metrics page: the CPU "Peak reading across N services" caption sat under the Memory chart; it is under the CPU chart.
- The onboarding box and the floating wizard covered Settings dialogs' buttons; they stay below every dialog.
- The onboarding wizard asks for the Datadog application key.

## [1.2.11] - 2026-10-31

## [1.2.10] - 2026-10-31

## [1.2.9] - 2026-10-27

### Security

- The image is built on nginx's official unprivileged image and runs as uid 101 (port 3000 unchanged).

## [1.2.8] - 2026-10-26

### Security

- The image applies Alpine security updates at build time (brotli fix). No application changes.

## [1.2.7] - 2026-10-25

No frontend changes; image rebuilt at 1.2.7 so versions match.

## [1.2.6] - 2026-10-25

See the full notes in docs/src/changelog.md (journey-suite fixes, Argo CD / Flux integrations, SSO sign-in domains).

## [1.2.5] - 2026-10-21

No frontend code changes; `.env.example` recommends the relative `VITE_BASE_URL=/api` in production. Image rebuilt at 1.2.5 so versions match.

## [1.2.4] - 2026-10-21

Fixed: Integrations screens follow dark mode and the design system (ObservabilitySettings `.obs-*` tokens, ChoiceGroup provider pickers, shared `IntegrationsSectionHeader`, `?tab=` in the URL, labelled form controls; 0 axe violations on 69 provider screens). Removed unused `SettingsOrg` and the ObservabilitySettings default export.

## [1.2.3] - 2026-10-20

Fixed: the sidebar crashed when the stored organisation was an id (after a profile save); General settings guards the same value.

## [1.2.2] - 2026-10-20

Permissions from the server, hidden controls and settings pages per role,
resolve form with root cause, organisation logo in the sidebar, Access Denied
in the audit log. Full notes in the [project changelog](https://serops.ai/docs/changelog/).

### Added

- Organisation logo in the sidebar; remove logo / remove photo actions.
- Resolve form in the issue panel (confirm or correct the root cause and fix); resolved issues show the confirmed root cause and what the AI said.
- Clickable evidence on the analysis page (commit, metric, pipeline, failing trace) and commit links in the issue panel; Code changes highlights `?sha=`.

### Changed

- Issues show the other services a cause affects ("+N" in the list, "also affects" in the panel and on the analysis page).
- Smaller SerOps mark in the sidebar; profile photo updates without a reload.
- Analysis page issue rows show the status chip; the link reads "View issue" (translated) instead of a hard-coded "Open".
- Permissions come from the server (`user.permissions`, refreshed when the app loads): `utils/permissions.js` exposes `can()` / `usePermissions()` and no longer keeps a role table. The Settings menu lists only the pages a role can open; Dashboard setup, integration and source management, AI catalogue and delete controls use named permissions. The unused `RoleGuard` component was removed.
- Audit log shows **Access Denied** entries (red, with the missing permission).

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
- OTLP traces UI (ingest keys, traces dashboard, trace waterfall).
- Multi-cluster picker in navbar + cluster-scoped Dashboard / Data /
  Issues views.
- Per-batch trace view (`BatchTraces`) reading `batch.data.traces`.
- Unified batch timeline (`BatchTimeline`) — SVG chart with per-kind
  lanes, engine-backed causal arrows, lane/severity filters,
  brush-to-filter time-window selection.
- Similar-incidents card + post-mortem draft modal.
- Incident notification channels UI (Slack, Teams, PagerDuty,
  OpsGenie) with test-send action.
- AI cost budget snapshot on Settings → AI.
- Audit log user filter, clear filters, expandable JSON details.
- Error boundary around the routed app tree (per-region crash
  containment with Retry).
- On-prem Ollama documentation link + admin "Test connection" probe.

### Changed
- Traces removed from top-level sidebar (peer to logs / metrics /
  code / CI-CD as data source, not workflow).
- Timeline promoted out of Data-type dropdown into its own peer
  button on batch detail.
- Sidebar accessibility: real `<button>` elements, aria-expanded on
  Settings group, focus-visible outline on mobile backdrop.
- All API service files migrated to `apiClient` interceptor (401 →
  login redirect, consistent auth-header handling).

### Fixed
- Model dropdown fallback no longer hardcodes `[Gemini, DeepSeek]`
  when the org has no API keys configured; empty state links to
  Settings → AI instead.
- Chat renderer base-text now HTML-escaped (`<script>` in bot
  output no longer executes via `dangerouslySetInnerHTML`).
- Tab-nabbing hardening: every `target="_blank"` carries
  `rel="noopener noreferrer"`.

[Unreleased]: https://github.com/getserops/serops/compare/v1.0.2...HEAD
[1.0.2]: https://github.com/getserops/serops/releases/tag/v1.0.2
[1.0.1]: https://github.com/getserops/serops/releases/tag/v1.0.1
[1.0.0]: https://github.com/getserops/serops/releases/tag/v1.0.0
