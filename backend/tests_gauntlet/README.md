# SerOps real-prod gauntlet

Synthetic-but-realistic batches that exercise the AI + correlation + Sentinel + persistence chain against real-world hostile shapes: PII in logs, prompt-injection payloads, cross-tenant isolation, sentinel edge cases, provider fallback, misleading CI/CD signals, cascade failures, and 100k-event volume noise.

Complement to unit + e2e tests: unit tests prove code paths work; the gauntlet proves the system reaches the *right* conclusion on real-world hostile input, and does so without leaking data across tenants.

## Layout

```
tests_gauntlet/
├── _core.py                 # pushers + context + expectations
├── run_gauntlet.py          # CLI runner (discovers generators)
├── generators/              # one file per batch
│   ├── real_s1_pii_leakage.py
│   ├── ...
└── README.md
```

## Run

Every gauntlet run needs to hit the DB the celery worker sees — locally that's `serops_backend_dev` against `serops_postgres`; on e2e, `serops-backend` on the box.

**Local dev** (transient container, tied to project stack):

```bash
docker run --rm --network code_serops \
  -v $(pwd)/backend:/app:rw -w /app \
  -e GAUNTLET_ORG_ID=1 \
  -e GAUNTLET_MODEL=claude \
  code_backend \
  python -m tests_gauntlet.run_gauntlet --list
```

**On e2e** (the way we validate before shipping):

```bash
ssh root@<e2e-host> 'docker exec \
  -e GAUNTLET_MODEL=claude \
  serops-backend \
  python -m tests_gauntlet.run_gauntlet --tier 0'
```

## Env vars (all optional)

| Var | Default | Purpose |
|---|---|---|
| `GAUNTLET_ORG_ID` | `1` | Target org (must exist). |
| `GAUNTLET_PROJECT_NAME` | `gauntlet-checkout` | Auto-created if absent. |
| `GAUNTLET_SERVICE` | `checkout` | Service on that project. |
| `GAUNTLET_ENV` | `production` | Environment label. |
| `GAUNTLET_MODEL` | `claude` | AI provider (claude/gemini/deepseek/etc). |
| `GAUNTLET_BASE_URL` | `https://localhost` | For HTTP surfaces (alerts/OTLP). |
| `GAUNTLET_USER` | `gauntlet@serops.internal` | For UI tests. |
| `GAUNTLET_PWD` | `Gauntlet-Str0ngP4ss-2026` | For UI tests. |
| `GAUNTLET_INGEST_KEY` | `` | Bearer token for OTLP `/api/traces/v1/traces`. |

## CLI

```
python -m tests_gauntlet.run_gauntlet --list
python -m tests_gauntlet.run_gauntlet --tier 0
python -m tests_gauntlet.run_gauntlet --batch S1
python -m tests_gauntlet.run_gauntlet --tier 1 --timeout 240
```

## Cleanup

Every gauntlet batch id is prefixed `gt-`. Wipe them all in one query:

```python
from Data.models import AIAnalyzedBatch, Issue
Issue.objects.filter(batch__batch_id__startswith='gt-').delete()
AIAnalyzedBatch.objects.filter(batch_id__startswith='gt-').delete()
```

## Generator contract

Every module in `generators/` that opts in must expose:

- `BATCH_ID: str` — short name (e.g. `'S1'`)
- `TIER: int` — 0-4
- `EXPECTATION: Expectation` — what the analysis should look like
- `run(ctx: GauntletContext) -> str` — synthesise the batch, return the real batch_id

`ctx.project_id` is populated by `run_gauntlet.ensure_project()` before generators execute.

## Tier map

- **Tier 0 (launch-blocker)** — security + isolation + sentinel + fallback. 8 batches. Must pass 8/8 before OSS launch tag `v1.0.0-rc1`.
- **Tier 1 (must-survive)** — core cascade / volume / red-herring correctness. 7 batches.
- **Tier 2 (quality-bar)** — 17 batches. ≥15/17 required for launch.
- **Tier 3 (polish)** — 18 batches. Best-effort.
- **Tier 4 (nice-to-have)** — 18 batches. v1.0.1 backlog.

Total: 68 batches (60 from plan + 8 buffer).
