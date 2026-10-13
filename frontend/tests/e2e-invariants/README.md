# UI-invariant gauntlet (PR-UI1)

Playwright cross-cutting invariants that run against seeded fixture batches on e2e. Six checks × 10 fixtures. Purpose: catch the class of UI regressions a solo founder would miss on the manual 3-min post-deploy checklist — console errors, dict-repr in text, mobile overflow, i18n gaps, a11y violations, dark-mode contrast.

## Run

**Step 1 — seed fixtures on e2e** (needs Claude tokens):

```bash
ssh root@<e2e-host> 'docker exec serops-backend python -m tests_gauntlet.seed_ui_fixtures'
```

Creates 10 stable-id `gt-ui-*` batches on org 1. Idempotent — safe to re-run. Takes ~5 min (one AI call per fixture, ~30s each).

**Step 2 — run invariants against those fixtures**:

```bash
docker run --rm --network host \
  -v $(pwd):/app:rw -w /app \
  mcr.microsoft.com/playwright:v1.63.0-jammy \
  npx playwright test
```

Alternatively (from the repo root):

```bash
cd frontend
npm run test:e2e            # headless
npm run test:e2e:headed     # visible browser (for local debug)
npm run test:e2e:ui         # Playwright UI mode
```

## What each invariant catches

| # | Invariant | What it catches |
|---|---|---|
| **I1** | no console/network errors on Detail | broken imports, mismatched backend contract, React PropType→runtime |
| **I2** | no `[object Object]` / `undefined` / `NaN` in visible text | PR-AUDIT6-style bugs where an object leaks into text coercion |
| **I3** | dark mode text has contrast | forgot to define a token under `[data-theme="dark"]` |
| **I4** | mobile viewport has no horizontal scroll | `min-width` wider than screen, unbounded table |
| **I5** | i18n: no missing translations in FR/AR | new copy shipped without translating |
| **I6** | axe-core critical/serious violations | missing aria labels, insufficient contrast, keyboard traps |

## Fixture cleanup

```bash
docker exec serops-backend python manage.py shell -c "
from Data.models import AIAnalyzedBatch, Issue
Issue.objects.filter(batch__batch_id__startswith='gt-ui-').delete()
AIAnalyzedBatch.objects.filter(batch_id__startswith='gt-ui-').delete()
"
```

## Env overrides

| Var | Default |
|---|---|
| `GAUNTLET_BASE_URL` | `https://localhost` |
| `GAUNTLET_USER` | `gauntlet@serops.internal` |
| `GAUNTLET_PWD` | `Gauntlet-Str0ngP4ss-2026` |
| `GAUNTLET_ORG_ID` | `1` |
| `GAUNTLET_MODEL` | `claude` (backend seed side) |

## Not in scope for PR-UI1

- Per-batch bespoke UI checks (60 files a solo founder wouldn't maintain — see `docs/deploy-verify.md`).
- CI wiring (backend CI is broken; the gauntlet stays manual until that's fixed).
- Screenshot golden files (flaky across chrome versions; not worth the maintenance).

PR-UI2 will add axe-core + console-error assertions to the existing vitest component suite for coverage that doesn't need a running backend.
