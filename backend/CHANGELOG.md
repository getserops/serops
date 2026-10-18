# Changelog

All notable changes to the SerOps backend are documented in this
file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
starting from `v1.0.0` (see [versioning guide](https://serops.ai/docs/deployment/versioning/)).

## [Unreleased]

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
