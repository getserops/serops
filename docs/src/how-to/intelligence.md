---
seo_title: "Similar incidents and AI post-mortems"
description: "SerOps finds similar past incidents and drafts post-mortems, so each analysis learns from how earlier incidents were resolved."
---
# Historical Intelligence (Similar Incidents + Post-mortems)

Two AI-powered features that turn SerOps into a **learning system**
across incidents.

## Similar incidents

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
  task (`embed_resolved_issue`, priority 3, standard queue) that
  embeds the issue text and stores the vector on `Issue.embedding`,
  with the model that produced it on `Issue.embedding_model`. Open
  issues are embedded on demand the first time their similar
  incidents are requested.
* **Backend selection** — no environment variable involved:
  * Your organisation's AI provider (**Settings → AI Providers**),
    default first, then fallback, when it offers embeddings: OpenAI
    (`text-embedding-3-small`), Google Gemini (`gemini-embedding-001`)
    or Ollama (`nomic-embed-text`, run `ollama pull nomic-embed-text`).
    Set `embedding_model` in the provider key's extra config to use
    another model. Anthropic Claude and DeepSeek have no embeddings
    API.
  * Otherwise, or if the provider call fails → **local lexical
    similarity**: word, word-pair and character n-grams, hashed into
    a vector. Deterministic, no network, no model download; it
    matches incidents described with the same words (e.g. "connection
    pool exhausted" vs "ran out of DB connections in the pool"), not
    paraphrases with no word in common.
* **Similarity search** runs in Python, scoped to the caller's org.
  Vectors are only compared when they come from the same model and
  dimension; anything else (another provider, older rows) is compared
  lexically, so switching provider never mixes vector spaces. Fine at
  MVP scale (~thousands of resolved issues per org). Migration to
  `pgvector` is tracked in the quality backlog for orgs pushing past
  ~50K resolved.
* **Thresholds**: cosine 0.75 for provider embeddings, 0.25 for
  lexical vectors (paraphrased incidents score ~0.5-0.75, unrelated
  ones under 0.1).
* **AI prompt memory**: the resolved issues injected into an
  analysis are the ones most similar to the batch's errors (same
  project, `memory_window_days`, up to `memory_max_items`), ties going
  to the same environment, team-confirmed root causes, then the most
  recent. At most one recent non-matching issue fills a free slot.

### Privacy

Resolved-issue text goes to your organisation's own AI provider, the
same one that analyses your logs, after PII redaction via
`Utils.data_redaction`. With Ollama, Claude, DeepSeek or no provider,
nothing leaves the instance for embeddings.

## Post-mortem draft generator

**Turn an incident into a starting post-mortem in one click.**

### How to use

*Analyses page → select one batch → dropdown → "Generate post-mortem
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
* **Similar past resolved incidents** (see [Similar incidents](#similar-incidents)) — surfaces
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
text-embedding-3-small; free with Ollama or the lexical fallback). Cost per post-mortem draft depends on
model — expect ~$0.01 with GPT-4o, ~$0.001 with GPT-4o-mini.
