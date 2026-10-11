# Onboarding Wizard

The Onboarding Wizard guides new users through initial setup after their first login. It auto-detects completion by polling integration + project + service counts — no self-attested "Mark Complete" buttons.

## Overview

When you first log in to SerOps, the wizard walks you through the essential steps to get your organisation up and running. Progress is tracked server-side, so you can leave and come back — a resume chip appears in the top bar on subsequent visits.

## Steps

Observability is the only **required** step (SerOps is useless without one). Everything else is skippable — you can add SCM + CI/CD bindings later from the project page.

| Step | Name | Required | Description |
|------|------|:--------:|-------------|
| 1 | **Observability provider** | ✅ | Connect Elasticsearch, OpenSearch, Loki, Datadog, CloudWatch, Prometheus, VictoriaMetrics, or Mimir. Sets up log ingestion — SerOps needs at least one to analyse anything. |
| 2 | **Project + first service** | — | Create a project and its first service (name + environment). Auto-created if you connect a provider that returns projects. |
| 3 | **SCM binding** | — (skippable) | Link the service to a GitLab / GitHub / Bitbucket / Azure DevOps repository (used to correlate deployments + commits with incidents). |
| 4 | **CI/CD binding** | — (skippable) | Link a CI/CD pipeline (GitLab CI, GitHub Actions, Jenkins, Bitbucket, Azure DevOps) so pipeline failures feed into the batch analysis. |
| 5 | **Run first analysis** | — | After the observability provider is connected, a **Run first analysis now** button appears. Click to trigger an on-demand batch. The wizard streams progress and lands you on the resulting issue page — no waiting for the scheduler. |

## Skipping steps

Every step except observability has a **Skip for now** button. Skipped steps show as "Not configured yet" on the project page later, with a one-click link back to the same form.

## Post-onboarding upsells

After you finish, the dashboard shows contextual upsells for anything you skipped (e.g., "Connect a SCM repo to see which commits caused this incident"). Dismissable per-user.

## Resetting

Admins can reset the onboarding state to re-run the wizard (useful when onboarding new team members):

- Use the API endpoint `POST /api/organisation/onboarding/reset/` (requires admin role). There is no UI button for this.

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/organisation/onboarding/status/` | `GET` | Get current onboarding step and completion data |
| `/api/organisation/onboarding/status/` | `PUT` | Update the current step with associated data |
| `/api/organisation/onboarding/skip/` | `POST` | Skip the onboarding wizard |
| `/api/organisation/onboarding/reset/` | `POST` | Reset onboarding to the beginning |

### Progress is computed, not reported

There is no endpoint to mark a step complete. `/onboarding/status/` is
read-only, and every read recomputes progress from actual database
state: the "connect an integration" step turns green when an
integration exists, not when a client says so.

That means you advance onboarding by doing the thing — and equally,
a step can turn *back* to incomplete if what it depended on is later
deleted.

## Related Pages

- [Quick Start](quick-start-self-hosted.md)
- [First Project Setup](first-project.md)
