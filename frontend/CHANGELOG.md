# Changelog

All notable changes to the SerOps frontend are documented in this
file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
starting from `v1.0.0`.

Frontend and backend versions are coordinated — a `v1.0.0` release
means backend + frontend + Helm chart appVersion all match.

## [Unreleased]

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
