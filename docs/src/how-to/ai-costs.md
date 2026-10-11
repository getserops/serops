# Track AI Costs

SerOps records every AI API call (batch analysis, chat message, re-analysis) along with input/output token counts and an estimated USD cost. This page explains where the data lives, how to query it, and how to keep costs predictable.

There is no quota enforcement in SerOps — this is **observability**, not a hard cap. If you need to gate AI spending, pair this data with [Sentinel Tiered Intelligence](sentinel.md), which skips AI analysis on batches that don't warrant it.

---

## Provider free tiers are not enough for production

SerOps has to be honest about a real trap self-hosters hit day one: **most AI providers' free tiers cap daily requests below the volume SerOps generates on a single project.**

Anecdote from our own audit runs — Gemini's free tier for `gemini-3.6-flash` allows **20 requests per project per day**. With the default 5-minute batch cadence and even one active service, SerOps can generate 288 potential batches per day; the free tier is exhausted before lunch. When you hit the wall you'll see this in Celery logs and on failed batches:

```
Gemini Adapter Error: 429 RESOURCE_EXHAUSTED.
Quota exceeded for metric: generate_content_free_tier_requests, limit: 20
```

Realistic minimums by workload:

| Workload | Recommended provider tier |
|----------|--------------------------|
| Evaluation / demo (single project, high Sentinel threshold, ≤20 batches/day) | Provider free tiers OK |
| Small production install (1 project, default batch cadence) | **Anthropic Build tier** (pay-as-you-go, ~$3-8/month with prompt caching) or **local Ollama** |
| Multi-project / multi-cluster | **Paid Claude Sonnet / Gemini Pro** on a workspace-scoped key with a monthly budget cap set at Settings → AI |
| Air-gapped / privacy-sensitive | **Ollama on the same VM** — unlimited, ~8-16 GB RAM, [setup guide](on-prem-ai-ollama.md) |

**How to blunt the impact if you must stay free:** raise `BATCH_GENERATION_INTERVAL` to 30 minutes (from the 5-minute default), enable Sentinel active mode with a strict `quiet_min_error_count` threshold, and pin analysis to one project. That combination realistically fits under 20 AI calls per day.

**How to catch it early:** the [Track AI Costs](#what-gets-recorded) section below covers the SerOps side. On the provider side, monitor your account's quota dashboard directly — SerOps surfaces the 429 as `FAILED (QUOTA_EXCEEDED)` on the batch, but the daily-limit warning has to come from the provider.

---

## What gets recorded

Every successful AI call writes one `AITokenUsage` row with:

| Field | Description |
|-------|-------------|
| `organisation` | Multi-tenancy scope |
| `batch` | Linked batch (null for chat) |
| `model_name` | e.g. `claude-sonnet-4-20250514`, `gemini-2.5-flash` |
| `tokens_input` | Prompt tokens |
| `tokens_output` | Completion tokens |
| `tokens_total` | Sum |
| `cost_usd` | Estimated cost using public per-1M token list prices |
| `usage_type` | `batch_analysis` / `chat_message` / `manual_analysis` / `batch_reanalysis` |
| `timestamp` | When the call happened |

Costs are estimates derived from **per-provider prices stored on the `AIModelProvider` DB rows** (`price_input_per_million` + `price_output_per_million`, seeded in migration `0012_ai_provider_pricing`). Update via the `AIModelProvider` admin or a data migration when provider list prices change — no code deploy required. Unknown models fall back to a mid-tier estimate so usage is never reported as free.

---

## Viewing usage

### In the dashboard

The dashboard surfaces AI usage in two places:

- **Sentinel Intelligence card** — shows estimated tokens *saved* by skipping quiet batches
- **AI Analysis Feed** — recent AI calls with their model + token counts

### Via the Django shell

```python
from ai_model.usage_tracking import AITokenUsageService
from Organisations.models import Organisations

org = Organisations.objects.get(name='Acme')
summary = AITokenUsageService.get_usage_summary(org)
print(summary)
# {
#   'total_tokens': 1_234_567,
#   'total_cost_usd': 4.21,
#   'total_calls': 312,
# }
```

`get_usage_summary` accepts optional `start_date` and `end_date` for windowed queries.

### Direct SQL

```sql
SELECT
  model_name,
  COUNT(*) AS calls,
  SUM(tokens_total) AS tokens,
  SUM(cost_usd) AS cost_usd
FROM ai_model_token_usage
WHERE organisation_id = <ORG_ID>
  AND timestamp >= NOW() - INTERVAL '30 days'
GROUP BY model_name
ORDER BY cost_usd DESC;
```

---

## Keeping costs under control

SerOps has five levers, roughly in order of impact:

1. **Sentinel active mode** — skips AI entirely on quiet batches. Typical savings: 60-80% of scheduled batches never reach the model. See [Sentinel Tiered Intelligence](sentinel.md).
2. **Smart Aggregation** — before a batch is sent to the model, log entries are grouped by a normalised signature (component + level + first-60-chars of message, with timestamps / UUIDs / IPs / numeric literals stripped). 1,000 identical stack traces collapse to a single representative line + a count. Applied automatically in `ai_model/tasks._normalize_for_signature`; capped at 100 signatures per batch.
3. **Prompt caching** — the ~2,500-token JSON schema + analysis rules are cached provider-side so you only pay for them once:
      * **Claude** (Sonnet, Opus): `cache_control:ephemeral` marker, ~90% off cached tokens after the first call (min 1,024 tokens — SerOps' prefix is well over that).
      * **OpenAI / DeepSeek**: system-role message with a ≥1,024-token prefix qualifies for automatic caching (OpenAI ~50% off, DeepSeek ~90% off).
      * **Gemini**: implicit caching kicks in at 4,096 tokens — SerOps' prefix falls under that on 3.5-flash, so no cache win here today. Wiring is in place for later prefix growth.
      The whole batch-analysis prompt was refactored into `(system_static, user_dynamic)` tuples in `ai_model/prompts.get_batch_analysis_prompt_parts` — the static half is byte-stable across batches (verified by tests) so cache hits are guaranteed.
4. **Recent Resolutions Context cap** — `memory_max_items` in Settings → Data bounds how many past resolutions get injected per prompt. Lower = fewer input tokens.
5. **Cheaper default model** — most analyses don't need the largest model. Switch the org default to a cheaper provider (e.g. `gemini-2.5-flash` or `claude-haiku-4.5`) under Settings → AI.

---

## Related

- [Sentinel Tiered Intelligence](sentinel.md) — skip-rate gate, the primary cost lever
- [Compare AI Models](compare-ai-models.md) — pick the right model for your workload
- [AI Resilience](../architecture/ai-resilience.md) — circuit breaker, rate limiter, adapter system
