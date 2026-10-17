---
seo_title: "Testing SerOps"
description: "The three layers of SerOps backend tests, when to use each, and how to run them."
---
# Testing SerOps

Three layers of tests cover the backend, each with a different job.
Know which layer your change belongs to before you write a new file.

## Layers

| Layer | Location | Runs against | Answers |
|---|---|---|---|
| **Unit** | `<app>/tests/` (one folder per Django app) | in-memory objects, mocked I/O | "Does this function behave?" |
| **View / integration** | `<app>/tests/test_views.py`, `<app>/test/test_*.py` | Django test DB, real serialisers, mocked provider I/O | "Do the REST endpoints serialise the right data given a normal request?" |
| **End-to-end** | `backend/tests_e2e/` | Django test DB, real ORM writes at every hop, only the outbound AI network hop mocked | "Does the full chain from an inbound webhook (or scheduled task) to a persisted issue on the read API actually hold together?" |

## When to write an e2e test

Add one whenever a code change:

- **Wires a new inbound trigger** (webhook, ingest key, scheduled Celery
  task) to a pipeline the frontend eventually reads.
- **Reorders or renames a pipeline stage** — the seam is where signature
  drift silently breaks the chain.
- **Adds a new signal type** the AI RCA prompt or the correlation
  engine consumes.

Do NOT add an e2e test for:

- Isolated logic bugs — a unit or view test is faster and pinpoints
  the fault line.
- Provider adapter behaviour — that lives in `ai_model/tests/test_adapters.py`.
- AI response variance — the model provider has its own tests.

## Running

```bash
# From backend/
make test-e2e          # e2e only
make test-unit         # unit + view tests, skipping e2e
make test              # curated core suite (key view tests + e2e)
make test-fast         # smoke run: e2e + one representative view suite
```

The Make targets run a curated subset. The **whole** backend suite — what
CI runs — is plain `manage.py test`:

```bash
docker exec -e DJANGO_SETTINGS_MODULE=api.test_settings serops_backend_dev \
  python manage.py test --noinput --keepdb
```

`--keepdb` reuses the test database between runs and is safe to repeat:
transactional tests subclass `Utils.testing.SeedPreservingTransactionTestCase`,
which restores migration seed data after every flush. New transactional
tests must use that base class rather than `TransactionTestCase`.

### Frontend

```bash
cd frontend
npm run lint          # must pass — CI gates on it
npm test              # Vitest, one-shot
npm run test:watch    # interactive
```

## UI invariants (Playwright)

Six cross-cutting checks that run against every page rather than
testing one feature each. They catch the class of regression that unit
tests structurally cannot: a component renders, its props are valid,
and it still looks broken to a human.

| Invariant | Catches |
|---|---|
| No console or network errors | Broken imports, a backend contract that drifted, PropType warnings that become runtime failures |
| No `[object Object]` / `undefined` / `NaN` in visible text | An object leaking into a string coercion |
| Dark-mode legibility | A colour token defined only for the light theme |
| No horizontal scroll at 390×844 | A `min-width` wider than a phone |
| No missing translations in FR / AR | Copy shipped without translating |
| No critical `axe-core` violations | Unlabelled controls, keyboard traps |

They run against seeded fixture batches, so the backend must be up and
those fixtures must exist:

```bash
# 1. Seed ~10 stable-id fixture batches (costs a few AI calls)
docker exec serops-backend python -m tests_gauntlet.seed_ui_fixtures

# 2. Run the invariants
cd frontend
npm run test:e2e            # headless
npm run test:e2e:headed     # visible browser, for debugging
npm run test:e2e:ui         # Playwright UI mode
```

Full detail: `frontend/tests/e2e-invariants/README.md`.

## Real-prod gauntlet

Unit and e2e tests prove the code paths work. The gauntlet proves the
*analysis reaches the right conclusion* on hostile input — and that it
does so without leaking data across tenants.

It is 68 synthetic-but-realistic batches across five tiers, covering
PII in logs, prompt injection, cross-tenant isolation, Sentinel edge
cases, AI provider failure, high-volume noise, multi-hop cascades,
misleading CI/CD signals, and log-format chaos.

```bash
docker exec serops-backend python -m tests_gauntlet.run_gauntlet --list
docker exec serops-backend python -m tests_gauntlet.run_gauntlet --tier 0
docker exec serops-backend python -m tests_gauntlet.run_gauntlet --batch S1
```

Tiers, by what a failure means:

| Tier | Meaning | Count |
|---|---|---|
| 0 | Launch blocker — security, tenant isolation, Sentinel gating, provider fallback | 8 |
| 1 | Must survive — core cascade, volume, and red-herring correctness | 7 |
| 2 | Quality bar | 17 |
| 3 | Polish | 18 |
| 4 | Nice to have | 18 |

!!! warning "The gauntlet spends real money"
    Most batches make a real AI call. A full 68-batch run costs roughly
    **$2** against Claude. Use `--tier 0` during development and save
    the full run for release candidates. Set `GAUNTLET_MODEL` to pick
    the provider.

Full detail, including env vars and the generator contract:
`backend/tests_gauntlet/README.md`.

## Fake AI provider

E2e tests must not talk to a real Claude/OpenAI/Gemini endpoint —
that would burn credits, flake on network, and couple test outcome to
model prompt-response variance. Instead, patch the imported reference
inside `ai_model.tasks`:

```python
from unittest.mock import patch
import json
from tests_e2e.base import fake_ai_json

with patch('ai_model.tasks.generate_for_organisation') as gen:
    gen.return_value = (
        json.dumps(fake_ai_json(correlated_issues=[{'component': 'checkout'}])),
        'e2e-fake-model', None, 500, 700,
    )
    from ai_model.tasks import analyze_batch
    analyze_batch.run(batch.batch_id)
```

`fake_ai_json()` returns a dict matching the JSON schema the real
provider path parses. Customise only what your assertions need —
leave the schema alone so the downstream pipeline exercises its
production code paths.

## Cross-tenant assertions are mandatory

Every e2e that persists a row must also assert that a second-tenant
caller can't see it. `tests_e2e.base.E2ETestCase` provisions the two
orgs and users for you — flip via `self._auth(self.other_admin)` and
re-issue the read request; expect `403 / 404 / empty list`.

The single most damaging regression in a multi-tenant system is a
leaked queryset. E2e is the last checkpoint where that would surface
before beta.
