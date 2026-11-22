---
seo_title: "RCA benchmark: how SerOps measures root-cause accuracy"
description: "98 incidents and healthy windows with a known answer, run through SerOps' real analysis with your own AI key and scored by fixed rules. Method, scoring, how to reproduce."
---
# RCA benchmark

How well does SerOps name the cause of an incident? The benchmark answers it with incidents whose cause is known, run through the real analysis (same prompt, diff selection, PII redaction, parsing and issue creation as production) and scored by fixed rules. No model grades another model.

## The incidents

| Set | Count | What it is for |
|---|---|---|
| **Held-out v3** | 34 held out (28 incidents, 6 healthy windows); 6 more moved to the tuned set on 2026-11-16 (w19 staging-only and the five incidents over 3–6 windows, after MR !121 was shaped on their first results) | Production-shaped incidents from November 2026 (table below), including incidents that evolve over several analysis windows of one project. Committed in its own pre-registration commit before any model run, under the same rule. Opt-in: `--set held_out_v3`. |
| **Held-out v2** | 33 (30 incidents, 3 healthy windows) | The measure from November 2026, written to cover what the first sets do not (table below). Committed in its own commit (`5ecbd317`) before any model run, under the same rule. Opt-in: `--set held_out_v2`. |
| **Held-out** | 9 (8 incidents, 1 healthy window) | The October 2026 measure. Written and committed before any model saw them; no prompt rule was changed for them. If one ever is, it moves to the tuned set and the commit says so. |
| **Tuned** | 16 (14 incidents, 2 healthy windows) | Regression guard. The product was changed while some of these failed, so passing them is expected and is not evidence. Three came from the held-out set: `h09`, a clean deploy with one retried request, raised a warning on its first run, and the log filter now keeps recovery lines because of it; `h04`, clock skew on one node, showed that warnings never reached the AI (the filter wanted `WARNING`, the pipeline writes `WARN`), and that filter was fixed because of it; `h07`, a feature-flag rollout, had Claude name a commit only to clear it while the issue still linked it, and commit links now come from the analysis' explicit list. `t01`, a traffic surge that slowed every service, comes from production scenario R9 on Online Boutique, where the analysis blamed one service's client code; it was written together with the traffic counts that fix it. |

They cover bad deploys (a connection leak on an error path, a retry storm, a dropped index), configuration (an autoscaler cap, a Kafka poll size, a feature-flag rollout with no deploy), infrastructure (clock skew on one node, a full disk, an Elasticsearch watermark, expired certificates, DNS), third parties (an outage, a rate limit), dependencies, healthy windows that must stay quiet, and a red herring next to old unrelated noise. Most incidents include a distractor commit that must not be blamed.

### What each set covers

| Incident class | Held-out / tuned (2026-10) | Held-out v2 (2026-11) |
|---|---|---|
| Bad deploy: code | h01 connection leak, h02 retry storm, s11 NPE, s02 cache leak | v03 thread pool, v14 event contract break |
| Bad deploy: config | h03 Kafka poll size, h05 autoscaler cap, s03 env typo, s10 Redis maxclients, h08 cron schedule | v04 file-descriptor limit, v05 liveness probe, v12 consumer scaled to 0, v21 database host |
| Dependency bump | s08 (CI fails) | v17 (CI green, breaks at runtime) |
| Feature flag | h07 | – |
| Database | s01 pool, h06 migration lock, s07 dropped index, s06 disk full | v01 deadlock, v02 replica lag, v33 failover |
| Cache, queue | s10 | v12 queue with no consumer, v13 cache flush stampede |
| DNS, TLS, network | s12 DNS, s05 expired certificate | v08 zone partition, v11 CA chain change, v24 expired certificate |
| Third party, credentials | s04 outage, h08 rate limit, h11 rotated SMTP password | v09 vendor latency, v10 expired OAuth secret |
| Kubernetes | h05 autoscaler, h10 healthy autoscaling | v05 probe, v06 node disk pressure, v07 image pull credentials, v26 crash loop |
| Capacity, memory | t01 traffic surge, s02 OOM | v15 batch job, v16 noisy neighbour, v18 slow leak, v19 CPU throttling, v22 heap |
| Infrastructure | h04 clock skew, h12 Elasticsearch watermark | v20 full volume |
| Several causes, cascades | s10 (one cause, many symptoms) | v31 two causes at once, v32 cascade, v33 coincidence |
| Partial data | – | v09 traces only, v18 and v19 metrics only, v20 logs only and no repository |
| Not English | – | v21 French, v22 German |
| Adversarial and privacy | – | v23 injection in a log line, v24 injection in an alert, v25 personal data in logs |
| Volume | – | v26 eight errors under 2300 lines of noise |
| Misleading input | h11 old unrelated noise | v27 an engineer's report blaming the wrong deploy |
| Healthy windows | h09, h10, s09 | v28 noisy hour, v29 deploy warm-up, v30 nightly backup |

### What v3 adds (2026-11-16)

| Incident class | Held-out v3 |
|---|---|
| Silent failure | w01 orders stop with no error anywhere (alert and trace traffic only) |
| Runtimes | w02 JVM garbage-collection pauses, w03 Node.js event loop blocked |
| Service mesh, ingress | w04 mesh root CA rotation, w05 another team's ingress snippet stops every reload |
| Kubernetes operations | w06 spot nodes preempted, w07 node upgrade stuck on a PDB, w08 autoscaler flapping |
| Network | w09 MTU (large responses only), w10 IPv6-only route on a dual-stack pool |
| Queues, serverless | w11 dead-letter queue from a short visibility timeout, w12 Lambda account concurrency, w21 Kafka consumer lag |
| Managed database | w13 failover then a reconnection storm |
| Scheduling, time | w14 cron overlap, w15 settlement run twice the night clocks go back, w28 tokens read as expired (time zone) |
| Security-shaped | w16 credential stuffing, w17 cryptocurrency miner in a compromised container |
| Collection shapes | w18 Java stack trace split one line per entry, w19 staging errors in a production window, w20 Lambda (CloudWatch) + Kubernetes (Datadog APM) |
| Classics, new shapes | w22 pool held by a remote call in a transaction, w23 letter O in a rate limit, w24 kill switch side effect, w25 internal CA intermediate vs a baked truststore, w26 S3 SlowDown from one key prefix, w27 per-IP rate limit behind a CDN |
| Adversarial and privacy | w16 email in logs, w35 an alert carrying an instruction and a customer's contact details |
| Healthy windows | w29 Black Friday load, w30 node-pool upgrade, w31 canary, w32 chaos game day, w33 certificate renewal, w34 month-end run |
| Over several windows | w36 memory leak to rollback (4), w37 broker disk filling (5), w38 query then index (3), w39 provider failing on and off (5), w40 cache loss cascade (6) |

**Incidents over several windows** run in order on one project, as a real incident is analysed window after window. Each window is scored like a scenario (a **severity** bound applies to the incident windows), the last one is the recovery and must not stay critical, and across the windows at most one warning-or-worse issue may name the incident's services: a continuing incident must reuse its issue, not open a new one every window. The report also counts the incidents that passed every window.

Two checks are used from v2 on: **also** (a second root cause in the same window must be named by some warning-or-worse issue: v31) and **forbidden text** (an issue must not contain the personal data from the logs: v25).

The Online Boutique scenarios (B0-B5, R1-R12) and the [chaos suite](https://github.com/getserops/serops/tree/main/backend/tests_chaos) test the same classes on a running cluster, collection included.

Logs read the way real services write them: an error may name itself (an x509 line does), but never the change that caused it. The sources are in `backend/rca_benchmark/` (`held_out.py`, `held_out_v2.py`, `held_out_v3.py`, `tuned.py`).

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

Every scenario is one real AI call, billed to your key (an incident over several windows is one call per window). The default run (held-out and tuned) is 25 calls; `--set held_out_v2` is 33; `--set held_out_v3` is 34; the six v3 scenarios moved to the tuned set (w19 and the five multi-window incidents, 24 windows) are tuned scenarios, opt-in with `--set tuned_v3`.

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

## Alerts, chat and post-mortems (track 4)

The batch benchmark scores one thing: the issues an analysis writes. Three
other AI features have their own set in `backend/rca_benchmark/track4/`,
pre-registered on 2026-11-16 (expectations and the grading rubric committed
before any run):

| Set | Size | What is checked |
|---|---|---|
| Alerts | 20 | Real payloads from Alertmanager, Grafana, Datadog and Sentry posted to the real webhook: accepted, matched to the right project (or left unmatched when no label names a service), the analysis window starts 20 minutes before the alert started, and the analysis passes the scenario's own answer key. CloudWatch through SNS, PagerDuty and a generic JSON hook are included and expected to be refused: SerOps has no receiver for them. |
| Chat | 30 conversations, 110 turns | Ten analysed incidents, three conversations each: what happened, quote the evidence, which commit, a figure the data does not hold; a root cause, pushback with no evidence, a prompt injection, what to do first; another organisation's batch id, every customer's services, a cause the data does not show. |
| Post-mortems | 20 | The draft is written by the AI (not the template fallback), names the service, matches the cause, names the commit at fault and not a distractor, carries no personal data. |

Wording checks settle what they can. The rest (is every claim in the
evidence, does the answer admit missing data, does it hold its conclusion, is
the post-mortem timeline right) goes to a blind judge: `claude-opus-5-5`,
effort `medium`, a fixed rubric with JSON verdicts, never told which product
or model wrote the text, no refusal fallback so the instrument does not
change mid-run. A seeded 20 % of judged items is exported for a person to
check by hand.

```bash
python manage.py rca_track4 estimate
RCA_API_KEY=... python manage.py rca_track4 alerts --model claude-sonnet-5-5 --budget-usd 1.5 --rounds 2 --json alerts.json
RCA_API_KEY=... python manage.py rca_track4 chat --model claude-sonnet-5-5 --budget-usd 3.5 --json chat.json
RCA_API_KEY=... python manage.py rca_track4 postmortem --model claude-sonnet-5-5 --budget-usd 1.5 --json pm.json
JUDGE_API_KEY=... python manage.py rca_track4 judge --in chat.json pm.json --budget-usd 4 --json judge.json
python manage.py rca_track4 sample --in judge.json --json hand-check.json
```

Same rules as the batch benchmark: a throwaway database, a throwaway
organisation per run, your key with no fallback provider.

## Results

Results are published per release with the full Markdown report, failures included. See the [changelog](../changelog.md) for the latest.

## Other tools on the same scenarios

`python3 -m rca_benchmark.competitor` (from `backend/`) scores another RCA
tool on the same scenarios, keys and scoring rules, with no Django or
database. Method, fixed before any result was seen:

- **Evidence:** the tool gets each scenario's data, the data SerOps receives,
  as files: `logs.txt`, `changes.txt` (commits with diffs) and every other
  source as JSON. Nothing added, nothing removed; the answer key is never
  in it.
- **Question:** one fixed instruction asks for the incidents and their root
  cause as JSON with the fields the scoring reads. No model grades another.
- **Model:** the same as SerOps (`claude-sonnet-5-5`); cost at SerOps' prices.
- **HolmesGPT** 0.46.0 (pinned image): `holmes ask --no-interactive` with the
  files attached, in its documented defaults (`--mode default`, the mode of the
  published runs): its default toolsets stay on (bash, internet, connectivity
  check among them); the Kubernetes and cloud ones cannot load, as there is no
  cluster or credential in the container. `--mode evidence-only` turns the
  internet, connectivity and Prometheus toolsets off (`holmes-config.yaml`).
  HolmesGPT normally collects data itself with tools; here it gets the
  evidence, so this measures its reasoning over the same evidence, not its
  data collection. Settings of the published runs:
  `backend/rca_benchmark/competitor/SETTINGS.md`.
- **Reproduce the published round:** `python3 -m rca_benchmark.competitor
  --tool holmesgpt --env-file <file with ANTHROPIC_API_KEY=...> --set held_out_v2
  --budget-usd 2 --json holmes.json` (32 runs; the published round cost $1.39,
  the most expensive run $0.29). The results are on
  [/benchmark](https://serops.ai/benchmark).
- **k8sgpt** is not scored: its analyzers read live Kubernetes objects through
  the API server and it has no input for logs, metrics, traces or commits.
  A fair comparison needs a live cluster during an incident.
