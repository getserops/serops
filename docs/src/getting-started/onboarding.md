# Onboarding Wizard

The Onboarding Wizard guides new users through initial setup after their first login. It auto-detects completion by polling integration + project + service counts — no self-attested "Mark Complete" buttons.

## Overview

When you first log in to SerOps, the wizard walks you through the essential steps to get your organisation up and running. Progress is tracked server-side, so you can leave and come back — a resume chip appears in the top bar on subsequent visits.

## Steps

Only **Source Control** and **CI/CD** can be skipped — you can add those
bindings later from the project page. Every other step completes when the
thing it asks for exists.

| Step | Name | Skippable | Description |
|------|------|:---------:|-------------|
| 1 | **AI Model** | — | Add an API key for Gemini, Claude, OpenAI or DeepSeek, or configure Ollama (local, no key). Keys are stored per organisation and encrypted at rest. |
| 2 | **Observability** | — | Connect a log or metric provider. SerOps needs at least one to analyse anything. |
| 3 | **Project** | — | Create your first project. |
| 4 | **Service** | — | Add a service to the project. |
| 5 | **Source Control** | ✅ | Link the service to a GitLab / GitHub / Bitbucket / Azure DevOps repository, so incidents can be correlated with commits and deployments. |
| 6 | **CI/CD** | ✅ | Link a CI/CD pipeline (GitLab CI, GitHub Actions, Jenkins, Bitbucket, Azure DevOps) so pipeline failures feed into the analysis. |
| 7 | **First Analysis** | — | Waits for the first batch analysis to complete. |

## Skipping steps

Source Control and CI/CD have a **Skip for now** button. Skipped steps show as "Not configured yet" on the project page later, with a one-click link back to the same form. Closing the wizard (`POST /api/organisation/onboarding/skip/`) only hides it; a resume chip in the top bar brings it back.

## Post-onboarding upsells

After you finish, the dashboard shows contextual upsells for anything you skipped (e.g., "Connect a SCM repo to see which commits caused this incident"). Dismissable per-user.

## Resetting

Admins can reset the onboarding state to re-run the wizard (useful when onboarding new team members):

- Use the API endpoint `POST /api/organisation/onboarding/reset/` (requires admin role). There is no UI button for this.

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/organisation/onboarding/status/` | `GET` | Get current onboarding step and completion data |
| `/api/organisation/onboarding/status/` | `PUT` | Skip an optional step (`action: skip_step`) or store wizard scratch data (`action: store_data`) |
| `/api/organisation/onboarding/skip/` | `POST` | Dismiss the wizard UI (progress is kept) |
| `/api/organisation/onboarding/resume/` | `POST` | Show the wizard again after a dismiss |
| `/api/organisation/onboarding/reset/` | `POST` | Reset onboarding to the beginning |

### Progress is computed, not reported

There is no endpoint to mark a step complete. `PUT /onboarding/status/`
can only skip the two optional steps, and every read recomputes progress
from actual database state: the "connect an integration" step turns green when an
integration exists, not when a client says so.

That means you advance onboarding by doing the thing — and equally,
a step can turn *back* to incomplete if what it depended on is later
deleted.

## Related Pages

- [Quick Start](quick-start-self-hosted.md)
- [First Project Setup](first-project.md)
