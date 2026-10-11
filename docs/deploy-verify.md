---
title: Post-deploy manual verification
---

# Post-deploy manual verification checklist

Three minutes, one operator, before you close the session on any deploy touching frontend or backend. Catches the class of bugs automation misses — layout regressions, "looks fine but the interaction is dead", and copy that reads wrong at a glance.

**When to run it:** every deploy to `serops.ai` / e2e / staging where the frontend bundle changed, the backend Batch Detail / Issues / Dashboard endpoints changed, or an AI-adapter code path touched Sentinel / correlations.

**Skip it only when:** you're deploying a backend-only change with zero user-visible surface (e.g. an internal task, a migration, a doc).

## Pre-flight

- [ ] Deploy landed cleanly (backend container `healthy`, frontend bundle loaded — check `/dash` renders without a blank white page)
- [ ] `curl -sk https://<host>/api/health/` returns `200 healthy`
- [ ] `docker exec serops-backend celery -A api inspect ping` returns a `pong`

## The five pages (2 min)

Log in as an org admin. For each page below, glance for:

1. Anything visibly broken (missing chart, empty card that should have data, spinner that never stops)
2. Text that reads like a placeholder (`undefined`, `[object Object]`, raw JSON, `NaN`, `null`)
3. Console errors (open DevTools; F12 → Console tab)

**Pages:**

| # | Page | What to eyeball |
|---|---|---|
| 1 | `/dash` (Dashboard) | Top-level KPIs render, no red spinner outlines |
| 2 | `/dash/data` (Batches list) | Table populated, latest batch is today's, model column has a name (not `null`) |
| 3 | `/dash/data/details/<batch_id>` (one recent batch) | Hero AI hypothesis is a real sentence (not a dict repr `{'summary':`), Sentinel chip visible, issues list has entries |
| 4 | `/dash/issues` (Issues list) | Severity chips have colours, filter dropdowns work, "Show more" pagination is clickable |
| 5 | `/dash/settings/team` (Team) | Users list renders with roles, "Invite" button opens a modal |

## The three interactions (1 min)

Actually click each of these — don't just look at the page:

- [ ] On `/dash/data`, click "Analyze with AI" dropdown → the split into **Re-run primary** / **Compare against** shows two groups
- [ ] On a batch's Detail page with `?compare=true`, the analysis-history panel renders side-by-side cards (only if the batch has >1 analysis)
- [ ] Language switcher: change to FR → nothing on the current page shows `translation missing` or unrendered `{{key}}` markers

## Sign-off

Screenshot each of the 5 pages, save under `docs/deploy-verify/<YYYY-MM-DD-HHMM>/`. Total time ~3 min. If everything checked, commit the folder to `serops-ops` (private) as evidence.

## When it fails

Any failure = do not tag the deploy as green. Fix, redeploy, re-verify. A red pre-flight is worse than "we didn't check" — it means we know something is broken and shipped anyway.

## Complements

- The **Playwright cross-cutting invariants** (`frontend/tests/e2e-invariants/`, PR-UI1) catch console errors, dict-repr in text, mobile overflow, i18n gaps, and a11y violations across 10 fixture batches. Run: `docker exec serops-backend python -m tests_gauntlet.seed_ui_fixtures` then `npm run test:e2e` from `frontend/`.
- The **real-prod gauntlet** (`backend/tests_gauntlet/`, PR-GT0 + PR-GT1) exercises the AI + correlation + Sentinel path against hostile input shapes.
- Frontend **vitest suite** covers component behaviour; run `npm test` from `frontend/`.

**None of these replace the manual eyeball.** Automation catches invariants; a human catches "yeah, but that's not what the user meant." Both matter.
