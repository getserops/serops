# Chaos-RCA — scored fault injection against a real cluster

Measures whether SerOps' root-cause analysis **names the cause we actually
caused**, using real signals from a real Kubernetes cluster.

## Why this exists alongside `tests_gauntlet/`

`tests_gauntlet/` writes documents straight into Elasticsearch with the
canonical fields already set. That tests scenario breadth cheaply and it
found real bugs — but it bypasses every layer between a workload and the
analysis, and it hand-writes the log text.

Two consequences, both measured:

**It cannot see pipeline bugs.** A day of validating the documented
Kubernetes setup turned up faults the 68-batch gauntlet had passed over
cleanly: Loki batches arriving empty because severity was filtered on a
label Loki does not have; Kubernetes CPU never collected because the metric
path ignored `topology_mode`; the OTLP receiver rejecting the OpenTelemetry
Collector's default gzip; container metrics double-counted on nested
runtimes. Each needed a real collector to surface.

**It measures extraction, not diagnosis.** The old demo workload logged
`ERROR checkout PaymentGatewayTimeout upstream=stripe after=30000ms` — a
line that names its own root cause. Repeating it back is string matching.

Here the workload emits *symptoms only*: a timeout, a 503, an RSS number, a
slow span. The cause has to be inferred from which service degraded, what
its metrics did, and where the trace spent its time.

## Layout

```
app/           three-tier instrumented workload (one image, four roles)
manifests/     Deployments + Services for the workload
scenarios.py   declarative scenarios with scoring expectations
run_chaos.py   host-side harness: inject -> soak -> analyse -> score
_analyze_once.py  runs inside the backend pod, emits one JSON line
results.json   last run's output (gitignored — regenerated per run)
```

## The workload

`loadgen -> checkout -> api -> cache`, all from `chaos-svc`, role picked by
`SVC_ROLE`. Each service exposes `/work` (the business path), `/fault` (set
faults at runtime) and `/fault/clear`.

Faults are toggled over HTTP rather than by redeploying, so a failure starts
mid-flight and the metric and trace signals show a **change** against a
baseline. Without a baseline there is no anomaly to detect.

All three signals are real:

| Signal | Path |
|---|---|
| Logs | stdout → Fluent Bit → Elasticsearch, and Promtail → Loki |
| Traces | OTel SDK → Collector → OTLP ingest, W3C context propagated across hops |
| Metrics | cAdvisor, by genuinely consuming CPU and memory |

Distributed tracing needs the context propagation to work, and it is easy to
get silently wrong: `dict(request.headers)` yields `Traceparent`, while the
W3C propagator looks up `traceparent` with a case-sensitive dict get. It
finds nothing, starts a new root trace, and a three-service cascade appears
as three unrelated incidents. The keys are lowercased for that reason.

## Running

```bash
./run_chaos.py                  # all 18 scenarios (~1 hour of soak)
./run_chaos.py --tier A         # one tier
./run_chaos.py --only a03 b03   # by name prefix
./run_chaos.py --dry-run        # inject and soak, skip the AI call
```

Each scenario makes a **real provider call**, so a full run costs real
tokens. Iterate on a cheap model and score finalists on an expensive one.

## Scoring

Every dimension is reported separately, so a partially-correct answer is
visible rather than collapsed into one bit:

| Check | Meaning |
|---|---|
| `root_cause_any` | at least one phrase appears in narrative + issue text |
| `component_any` | at least one issue blames one of these components |
| `must_not_say` | none of these appear — catches confident misblame |
| `sentinel_analysed` | Sentinel let the AI run rather than gating it away |
| `min_issues` / `max_issues` | issue count bounds |

`root_cause_any` is deliberately generous — it accepts any of several
phrasings, because the same correct diagnosis can be worded many ways. That
generosity is also its weakness: a wrong-but-plausible answer containing the
right noun can pass. Treat a green run as necessary, not sufficient, and
spot-check the narratives in `results.json`.

## What the first full run found

Five product bugs, each one a case of SerOps holding the evidence and either
staying silent or naming the wrong thing:

| Finding | Effect |
|---|---|
| Claude adapter read `content[0].text` | Extended thinking puts a ThinkingBlock first, which has no `.text` — Claude was unusable through the batch path with a valid key and quota, silently falling back |
| `generate_for_organisation` returned `fallback_error or error` | A quota failure on the primary was reported as an auth failure on the fallback, pointing the operator at a provider they had not chosen |
| Data-presence check ignored traces, counted dict keys as metrics | A batch carrying only spans was skipped without an AI call |
| Prompt treated quiet logs as a quiet system | Batches with 0 logs but 305 CPU points and 2500 spans spent the call and reported nothing |
| No kubelet lifecycle signal | An OOMKill leaves no application log line, so memory exhaustion was undiagnosable — the AI described the resulting cascade and never named the cause |

The last of those is worth reading twice if you maintain the metric path.
kube-state-metrics is a **separate exporter from cAdvisor** and does not
inherit the kubelet job's relabeling: its series carry only
`namespace` / `pod` / `container` / `reason`, none of `organisation_name`,
`project_name` or `environment`. Filtering lifecycle queries on the canonical
labels matched nothing while an OOMKill sat in Prometheus untouched. The join
that exists is `namespace`, which is also what both documented shipper recipes
map to `environment`.

After that fix the same scenario produces:

> The kubelet reports cache was terminated with reason=OOMKilled and has
> restarted twice ... causing repeated restarts and downstream connection
> failures

which is the diagnosis an SRE would write, rather than a description of the
connection-refused errors that followed.

## What the second pass found

Richer answers surfaced five more, all of the same class:

| Finding | Effect |
|---|---|
| Batch CREATION gated on logs and metrics only | A latency-only incident produced no batch at all, so it never reached the AI — worse than an empty analysis, because there is no row left to reanalyse. Two separate gates in the same function had the same omission |
| Memory usage joined total↔available on timestamp alone | Kubernetes templates aggregate `by (service_name)`, so a four-service project reports at identical instants and a dict keyed on time kept only the last service. Three services were discarded silently, and nothing guaranteed the surviving total and available came from the same one |
| Anomaly detection ran over the mixed series | One service's climb, interleaved with its neighbours' flat samples, reads as a sawtooth with nothing sustained — which is why `anomalies` was always 0 |
| `total_gb` read `memory_total[0]` | Whichever service the provider listed first, reported as the project's whole capacity |
| A truncated response was discarded whole | Zero issues, empty narrative, tokens billed. The bracket-balancing repair that could have recovered it appended `}` before `]`, so the one shape that actually occurs — an object holding a cut-off array — was closed as `}]` and never parsed |

The per-service ones compound: the aggregate figures read "48% avg, peak 95%"
with no service attached, which is an observation rather than a diagnosis. Now
each anomaly names its service and the prompt carries a per-service breakdown.

The batch-creation one hid behind itself: fixing the first gate only moved the
failure 150 lines down the same function, to a second emptiness check with the
identical omission. A latency scenario that had reported "no logs or metrics
found" then reported "skipped: no_data" instead — still no batch.

## Two harness properties worth understanding

**An explicit window per scenario.** Left alone, batch creation resumes from
the previous batch's end. The first trial run therefore analysed a window
stretching back hours and confidently diagnosed pods that had already been
deleted — it "passed" by describing a workload that no longer existed. Each
scenario now pins `window_start`/`window_end` around its own soak.

**Sentinel state is reset per scenario.** `known_fingerprints` accumulates
across batches, so a pattern seen in scenario 3 is no longer "new" in
scenario 4 and `new_error_pattern` would quietly stop firing partway through
a run. Resetting makes `first` the correct Sentinel decision, which is why
the check asserts "not gated away" rather than the literal label `alert`.

**The cluster must be quiet before measuring.** Clearing a fault stops the
cause, not its aftermath: a container OOMKilled in scenario N keeps crashlooping
into scenario N+1, where its restarts are genuinely in-window, so no amount of
window-bounding can filter them out — nor should it. Measured: the latency
scenario, run straight after the memory one, returned a narrative led by "api
was OOMKilled" and "cache repeatedly OOMKilled (4 restarts)" with the 1.5s delay
under test demoted to third place. It still passed every check, which is the
clearest example of why a green run is necessary and not sufficient.
`wait_for_stable_workload` now holds until restart counts have been flat for 90
seconds, and says so when it gives up.

**Score the analysis, not the Issue table.** `Issue.batch` is a FK to the
issue's MOST RECENT sighting, not the batch that found it — recurrence calls
`existing.move_to_batch(batch)`. So `Issue.objects.filter(batch=batch)` means
"issues last seen here" and silently includes issues opened hours earlier by a
different scenario. That mismeasurement failed the healthy-window scenario: the
model correctly returned zero issues and the harness scored 1, from a row
created at 06:19 with occurrence 9 whose FK had moved onto the healthy batch.
Scoring now reads `batch.data['analysis_result']['correlated_issues']`, and
reports the FK count separately so a large gap is visible.

Note that the product uses the same FK count for `batch.issue_count`, so a
batch whose analysis found nothing can still display a stale issue. That is
defensible for "currently active, last seen here" and misleading for "what this
batch found" — worth a decision before launch.

**Services must be registered.** Batch creation drops logs from services
with no `ProjectService` row. `cache` and `loadgen` need registering or
their logs vanish and every cache-origin scenario becomes unscoreable.
