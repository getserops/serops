# End-to-end integration tests

Unit tests prove individual functions behave. Adapter tests prove the
provider layer talks the right protocol. **End-to-end tests prove the
full chain — from an inbound webhook / scheduled task to a persisted
issue visible on the read API — actually holds together.**

## Why this package exists

The launch plan flagged (Q1.1) that we had **zero** e2e tests across
the 11 feature batches shipped Aug-Sep 2026. Unit coverage is strong
(1,100+ tests), but nothing verified that the seams between apps do
not silently break when a signature drifts. Beta partners will notice
a broken chain long before they notice a slick unit.

## What lives here

Each file exercises **one product chain** end-to-end. A chain has:

1. **An inbound trigger** — a real HTTP request, a Celery task
   invocation, or an ORM signal.
2. **A pipeline** — task fan-out, AI call, DB writes.
3. **A read surface** — the REST API a user or the frontend hits.

The AI provider layer is the only thing stubbed: `generate_for_organisation`
is patched to return a realistic JSON matching `_JSON_TEMPLATE`. Every
other layer runs for real — DB, serialisers, dispatch, correlation
engine, capability gate, redaction. The point of e2e is to *not* mock
the seams; we mock only the network call to the AI provider.

## How the fake AI response works

`tests_e2e.base.fake_ai_json(...)` returns a dict shaped exactly like
what a real Claude / OpenAI / Gemini response parses to. The dict
contains one or more `correlated_issues`, each with the fields the
downstream pipeline actually reads (`issue_type`, `scope`, `component`,
`severity`, `error_class`, `error_target`, `root_cause`,
`description`, `recommended_action`, `reasoning`, `confidence`,
`evidence_sources`). No placeholders — real values that the deduplicator
and serialisers will accept without mutation.

## What each e2e test asserts

- **DB writes at every hop**. If a chain writes 4 rows, the test
  reads back 4 rows.
- **The read API returns them cleanly**. Not just 200; also the
  serialised shape the frontend depends on.
- **Cross-org isolation stays intact**. A second org's parallel batch
  is not visible to the first org's caller. E2e tests are the last
  line where a leaked queryset would show up.

## What e2e tests must NOT do

- **Load-test the pipeline.** Wall-clock timing lives in benchmarks
  (Q3.4), not here.
- **Test AI response variance.** The AI adapter has its own tests
  for schema handling. E2e uses one canonical response so a failure
  here means the pipeline broke, not that the model drifted.
- **Talk to external providers.** No live Slack, no live PagerDuty.
  Dispatch is patched at the sender boundary.

## Adding a new e2e test

1. Pick one chain (inbound → pipeline → read API).
2. Subclass `E2ETestCase` from `tests_e2e.base`.
3. Use `fake_ai_json(...)` for the AI response — customise only the
   `correlated_issues` list; leave the schema alone.
4. Assert both the DB rows and the API response. Both matter.

## Running

```
make test-e2e                       # from backend/
python manage.py test tests_e2e     # equivalent
```

Run against the local `serops_test_db` container (see `MEMORY.md`
project notes) — the remote Postgres OOMs on the full suite.
