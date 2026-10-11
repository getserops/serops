# Historical Intelligence (Similar Incidents + Post-mortems)

Two AI-powered features that turn SerOps into a **learning system**
across incidents.

## Similar incidents (Item #27)

When SerOps resolves an issue, it computes an **embedding** of the
resolved text (root cause + recommendation + component + type) and
stores it on the issue row. Future incidents can then ask "have
we seen anything like this before?" and get ranked past resolutions
by cosine similarity.

### Where you see it

* **ChatIssues detail page** — a *Similar past incidents* card
  appears below the correlations card, showing up to 5 matches with
  their prior-fix text.
* **API**: `GET /api/data/issues/<id>/similar/?limit=5`
* **AI prompt**: similar past incidents feed into the RCA prompt as
  precedent context (via the existing `past_memories` slot).

### How it works

* **On resolve**: an OPEN → RESOLVED transition enqueues a Celery
  task (`embed_resolved_issue`, priority 3, standard queue). The
  task calls the embedding backend and stores a 1536-dim vector on
  `Issue.embedding`.
* **Backend selection**:
  * If `OPENAI_API_KEY` is set → OpenAI `text-embedding-3-small`
    (real semantic similarity).
  * Otherwise → deterministic hash embedding (reproducible for
    tests + demos, not semantically meaningful).
* **Similarity search** runs in Python via numpy cosine similarity,
  scoped to the caller's org. Fine at MVP scale (~thousands of
  resolved issues per org). Migration to `pgvector` is tracked in
  the quality backlog for orgs pushing past ~50K resolved.
* **Threshold**: `min_similarity=0.75` by default — strong-match
  bar for text-embedding-3-small on RCA text.

### Privacy

Resolved-issue text is sent to the configured embedding provider
(OpenAI by default). PII redaction runs via `Utils.data_redaction`
before the API call — same policy as batch analysis. Set
`OPENAI_API_KEY=""` to fall back to the hash backend and keep all
data local.

## Post-mortem draft generator (Item #28)

**Turn an incident into a starting post-mortem in one click.**

### How to use

*Data page → select one batch → dropdown → "Generate post-mortem
draft"*. A modal opens with:

* AI-drafted markdown with 10 standard sections (Summary, Impact,
  Timeline, Root cause, Contributing factors, What went well,
  What to improve, Action items, Precedent).
* `[FILL IN: ...]` placeholders for what the SRE needs to complete
  (detection time, first responder, mitigation steps, owners,
  due dates).
* **Copy** button to paste straight into Confluence / Notion /
  GitHub / Google Docs.
* **Regenerate** button — the AI is non-deterministic; a fresh run
  often produces cleaner prose.

### Context the draft is seeded with

* The batch's top 3 issues (root cause + recommendation).
* Deploys in the incident window (code_changes).
* **Similar past resolved incidents** (via Item #27) — surfaces
  precedent + how the team fixed it before, under a `## Precedent`
  section.

### Fallback

If the AI provider is unavailable (no key, rate limit, network
error), a **template-based post-mortem** is returned instead. Same
sections, seeded with the same batch data, just less polished
prose. Never a 500 error for the user.

### API

```bash
curl -X POST -H "Authorization: Token $TOKEN" \
  https://your-serops-host/api/data/batches/<batch_id>/postmortem/
# Response: {"batch_id": "...", "markdown": "...", "generated_at": "..."}
```

## Cost note

Embeddings + post-mortem drafts both use the configured AI provider.
Cost per resolved issue is negligible (~$0.00001 for
text-embedding-3-small). Cost per post-mortem draft depends on
model — expect ~$0.01 with GPT-4o, ~$0.001 with GPT-4o-mini.
