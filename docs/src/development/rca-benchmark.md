---
seo_title: "RCA benchmark: how SerOps measures root-cause accuracy"
description: "24 incidents with a known root cause, run through SerOps' real analysis with your own AI key and scored by fixed rules. Method, scoring, how to reproduce."
---
# RCA benchmark

How well does SerOps name the cause of an incident? The benchmark answers it with incidents whose cause is known, run through the real analysis (same prompt, diff selection, PII redaction, parsing and issue creation as production) and scored by fixed rules. No model grades another model.

## The incidents

| Set | Count | What it is for |
|---|---|---|
| **Held-out** | 9 (8 incidents, 1 healthy window) | The measure. Written and committed before any model saw them; no prompt rule was changed for them. If one ever is, it moves to the tuned set and the commit says so. |
| **Tuned** | 15 (13 incidents, 2 healthy windows) | Regression guard. The product was changed while some of these failed, so passing them is expected and is not evidence. Three came from the held-out set: `h09`, a clean deploy with one retried request, raised a warning on its first run, and the log filter now keeps recovery lines because of it; `h04`, clock skew on one node, showed that warnings never reached the AI (the filter wanted `WARNING`, the pipeline writes `WARN`), and that filter was fixed because of it; `h07`, a feature-flag rollout, had Claude name a commit only to clear it while the issue still linked it, and commit links now come from the analysis' explicit list. |

They cover bad deploys (a connection leak on an error path, a retry storm, a dropped index), configuration (an autoscaler cap, a Kafka poll size, a feature-flag rollout with no deploy), infrastructure (clock skew on one node, a full disk, an Elasticsearch watermark, expired certificates, DNS), third parties (an outage, a rate limit), dependencies, healthy windows that must stay quiet, and a red herring next to old unrelated noise. Most incidents include a distractor commit that must not be blamed.

Logs read the way real services write them: an error may name itself (an x509 line does), but never the change that caused it. The sources are in `backend/rca_benchmark/` (`held_out.py`, `tuned.py`).

## Scoring

Every check is a rule over the issues SerOps created:

| Check | Passes when |
|---|---|
| **Root cause** (headline) | The **top** issue (worst severity, then highest confidence) names one of the right services in its component or affected services, its root cause contains the cause words, and it names the commit at fault when there is one. |
| No distractor blamed | No issue links a commit that is there only as a distraction. |
| Focused | At most two warning-or-worse issues for one root cause. |
| Healthy window quiet | Nothing worse than the allowed severity. |
| No critical on a decoy | Old unrelated noise doesn't get a critical issue. |
| Lenient | The rule used until October 2026: some issue mentions the service and the cause words anywhere. Reported so older results compare. |

A failed AI call is an error, never a quiet healthy window. The report quotes what SerOps said for every failed check, so a reader can judge the rule as well as the result.

**Limits.** These are written incidents fed to the analysis, not a live cluster: they test diagnosis, not collection (the [chaos suite](https://github.com/getserops/serops/tree/main/backend/tests_chaos) covers a real cluster). Keyword rules can pass a wrong answer that uses the right words and fail a right answer worded differently; the quoted answers make both visible. One run of a model is a sample: use `--repeat` to see how stable it is.

## Run it yourself

Every scenario is one real AI call, billed to your key. A full run is 24 calls.

```bash
# In a backend container connected to a SerOps database (never production).
export RCA_API_KEY=...              # the provider's API key
python manage.py rca_benchmark --provider gemini \
    --budget-usd 0.50 --json bench.json --markdown bench.md
```

| Option | Meaning |
|---|---|
| `--provider` | Provider name as in Settings → AI (`gemini`, `claude`, `openai`…). Its default model is used. |
| `--set held_out` | One set only (repeat the option for several). |
| `--only h01 s10` | Scenarios by id prefix. |
| `--repeat 3` | Rounds, to measure consistency. |
| `--budget-usd` | Stops once SerOps' usage records reach it (default 1.00). |
| `--pause 13` | Seconds between calls, for rate-limited free tiers. |
| `--keep` | Keep the throwaway organisation to inspect it in the UI. |
| `--list` | List the scenarios and exit. |

The run uses a throwaway organisation, one project per scenario so incidents can't inform each other, your key with no fallback provider, and SerOps' own monthly budget cap set to `--budget-usd`. The organisation is deleted at the end.

## Results

Results are published per release with the full Markdown report, failures included. See the [changelog](../changelog.md) for the latest.
