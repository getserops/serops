# Demo seed from benchmark captures

Turns real analyses, saved by `tools/estate-capture`, into the files the demo
organisation is seeded from: one `<estate>-<incident>-<round>.json.gz` per
analysis and an `index.json`, in `backend/Data/demo_seed/`.

The analyses are real: what SerOps collected, what the model answered, the
issues it raised. This tool does not write or improve any of it. It trims the
logs, renames what identifies the test estates, and records where every time
is, so a loader can place the analysis on any date.

```bash
# 1. Find the real names (scans every file of the selected captures)
python3 -I tools/demo-seed/build_seed.py --discover \
    --captures ~/…/benchmark-captures --runtime ~/…/estates \
    --rename-map ~/…/demo-seed-private/rename-map.json

# 2. Convert, verify, write
python3 -I tools/demo-seed/build_seed.py --build \
    --captures ~/…/benchmark-captures --runtime ~/…/estates \
    --rename-map ~/…/demo-seed-private/rename-map.json \
    --private-dir ~/…/demo-seed-private

# 3. Check the files in place again (CI, or after a manual edit)
python3 -I tools/demo-seed/build_seed.py --verify \
    --rename-map ~/…/demo-seed-private/rename-map.json \
    --private-dir ~/…/demo-seed-private
```

`selection.json` lists the analyses to convert. `--out` defaults to
`backend/Data/demo_seed`. Exit codes: 0 done, 2 bad input, 3 a check failed.

## Rules it keeps

- **Reads only.** The captures are opened for reading. In the estates folder
  (`--runtime`) one file per analysis is read,
  `<estate>/results/<incident>-<round>-investigation.json`, and nothing else.
- **The rename map is private.** It holds the real names, so it lives outside
  the repository; the tool refuses a map or a report directory inside it. The
  tool prints counts and paths, never a value from the map.
- **Verify before write.** `--build` writes to a scratch directory, runs the
  checks of `--verify` there, and puts the files in place only when they pass.
- **Same input, same bytes.** Keys are sorted, the gzip header holds no clock
  and no file name, the discovered map keeps its assignments when discovery is
  run again.

## What a seed file holds

| Key | Content | Loads into |
|---|---|---|
| `schema` | `serops-demo-seed/1` | |
| `anchor` | The batch timestamp, as captured. Every other time in the file is consistent with it | the loader's time shift |
| `source` | Estate, incident, round, `healthy_window`, capture time and window, SerOps version and commit | not loaded (provenance) |
| `organisation` | `Acme Cloud`, slug `acme-cloud` | `Organisations` |
| `project` | `name` (`Fleet`, `Shopfront`, `Studio`), `key` (the lower-case name the data itself uses in `project_name` labels), `environment`, `repository` | `Projects.Project`, `ProjectEnvironment` |
| `model` | `used`: the model id that answered (from the AI settings at capture time, e.g. `claude-sonnet-5-5`); `batch_records`: what the batch row itself stored (the provider name) | see "Model" below |
| `ai_usage` | Always `null`, with `ai_usage_reason` | nothing: see "Tokens and cost" |
| `batch` | The analysed batch, see below | `Data.AIAnalyzedBatch` |
| `trim` | Real and kept line counts, evidence counts | not a model field: the UI can state "300 of 3,441 lines" from `logs_kept` / `logs_total` |
| `investigation` | The investigation record | `Data.Investigation` |
| `issues` | The issues **as they were right after the investigation** (the run-time file) | `Data.Issue`, `Data.IssueOccurrence` |
| `issues_at_capture` | Present only when the capture, taken later, holds a different state of an issue (a later batch saw it again) | not loaded; kept for reference |
| `traces` | Trace and span rows from the estate's trace store file, when the capture has one; otherwise the reason there are none | `traces.Trace`, `traces.Span` |
| `injection` | What was changed, when, and how it was reverted; the pre-registered description of the fault | not a model: source for the resolution notes |
| `derived_reference` | Counts SerOps computed at capture time (timeline events by kind, issue summary) | never written; for comparing after a load |

### `batch` → `AIAnalyzedBatch`

Written as captured: `batch_id`, `timestamp`, `issue_count`, `data`,
`logs_analyzed`, `created_at`, `indices_covered`, `token_count`,
`analysis_text`, `analyzed_at`, `model_name`, `sentinel_decision`,
`sentinel_triggers`, `ai_skipped`, `logs_raw_count`,
`logs_after_severity_filter`, `logs_unique_patterns`, `logs_sent_to_ai`,
`trigger`, and `analysis_history` (the `analysis_history` list of the
capture's `history` answer).

`batch.data` has every key SerOps stored: `logs`, `cicd_logs`,
`code_changes`, `change_events`, `metrics`, `metrics_summary`, `traces`
(the snapshot the analysis saw, not the span rows), `statistics`,
`analysis_result`, `correlation_results`, `data_sources`,
`project_capabilities`. Only `logs` (and `cicd_logs` above the limit) are
shorter than captured.

`created_at` is `auto_now_add` on the model: set it with a queryset
`update()` after creating the row, as `seed_demo_org` does.

Every analysis here was started by hand: `trigger` is `manual` and
`sentinel_decision` is `manual`. The files hold no scheduled or alert row.

### `investigation` → `Investigation`

`status`, `services`, `window_start`, `window_end`, `hint`,
`notify_routing`, `counts`, `error_code`, `error`, `created_at`,
`started_at`, `finished_at` as captured. `project`, `environment`,
`deployment` and `requested_by` are names (the loader resolves them to its
own rows); `requested_by` is one of the invented people.

### `issues` → `Issue` and `IssueOccurrence`

All model fields the API returns: `severity`, `description`,
`recommendation`, `root_cause`, `reasoning`, `confidence`, `created_at`,
`issue_type`, `scope`, `component`, `affected_services`, `environment`,
`status`, `occurrence_count`, `muted_until`, `last_seen_at`,
`acknowledged_at`, `error_class`, `error_target`, `has_commit_correlation`,
`has_metric_correlation`, `linked_commits`, `metric_correlation_type`,
`correlation_confidence`, `metric_anomaly_type`, `correlation_details`,
`has_cicd_correlation`, `resolved_at`, `resolution_root_cause`,
`resolution_fix`.

Added: `capture_ref` (`<estate>-issue-<id>`). SerOps deduplicates issues, so
the same issue appears in several files of one estate with the same
`capture_ref`: load it once and attach an occurrence per batch.

Not in the capture, so not in the file: `fingerprint` (computed by
`Issue.save()`), `embedding*`, `escalation_level`, and the occurrence's
`seen_at`.

In most incident files `created_at` is earlier than the batch and
`occurrence_count` is above 1: the issue was first raised by an earlier batch
that is not in the seed set. The values are left as they were; `index.json`
records, per issue, `created_at`, `last_seen_at`, `occurrence_count` and
`created_at_precedes_batch`, so the loader can apply its own rule.

`created_at` (`auto_now_add`) and `last_seen_at` (`auto_now`) need a
queryset `update()` after the row is created.

### `traces` → `Trace` and `Span`

`items` are trace rows in the shape of the SerOps traces API (`trace_id`,
`root_service_name`, `root_operation`, `start_time`, `end_time`,
`duration_ms`, `span_count`, `error_span_count`, `status_code`, `spans[]`
with `span_id`, `parent_span_id`, `service_name`, `operation_name`, `kind`,
`start_time`, `end_time`, `duration_ms`, `status_code`, `status_message`,
`attributes`, `events`). At most 25 per file: the traces the analysis cites
first, then error traces, then the earliest.

No span is invented. `available`, `reason`, `cited_trace_ids`, `cited_found`
and `cited_missing` say what exists: a file with `cited_missing` ids has no
row for those traces, so their detail pages cannot be seeded from it.

### One issue in several files

SerOps rewrites a deduplicated issue each time an analysis sees it again, so
two files with the same `capture_ref` hold that issue as it stood after each
analysis: the text, and sometimes the severity or type, differ from file to
file. Each file's version is the one its own analysis wrote
(`description` equals that analysis' `correlated_issues[].description`).
Which version a single loaded row shows is the loader's decision.

### Fields left out on purpose

Serializer output that is derived from other rows, or a database key of an
estate that no longer exists. The loader must not write them:

- Batch: `id`, `issues` (the nested copy), `analysis` (a copy of
  `data.analysis_result`), `metrics_summary` and `timing` (built by the view
  from the row's own fields), `investigation`, `project`, `deployment`
  (primary keys).
- Issue: `id`, `batch`, `batch_id_str`, `batch_timestamp`, `project`,
  `project_name`, `confidence_display`, `issue_type_display`,
  `status_display`, `error_class_display`, `correlation_summary`,
  `informed_by`, `resolved_by_name`, `related_traces`.
- Investigation: `id`, `status_label`, `batch_id`, `issue_count`.
- The capture's `timeline` answer: SerOps computes it from `batch.data` on
  every request. Its counts are in `derived_reference`.
- The pre-registered key's file name.

## Model

`batch.model_name` is what the batch row held: the provider name (`claude`).
The model that actually answered is `model.used`. A loader that wants the
analysis page to show the real model writes `model.used` into
`AIAnalyzedBatch.model_name`.

## Tokens and cost

`ai_usage` is `null` in every file, with the reason "not recorded in the
capture; estate database deleted". Real usage rows cannot be recovered: the
databases of the three estates were deleted, and no capture, query trail
(store requests only, no AI-provider request) or run-time file holds input or
output token counts.

`batch.token_count` is not model usage. It is SerOps' own size estimate of
the batch (the length of the log text divided by 4, `AIAnalyzedBatch` in
`backend/Data/models.py`). It is kept as captured, like every other figure,
and **nothing may compute a cost from it**. Do not estimate tokens or cost.

## Log trim

`batch.data.logs` is cut to 300 lines per analysis (`--max-log-lines`);
`cicd_logs` likewise when longer. Kept, in this order:

1. every line the analysis cites: `analysis_result.correlated_issues[]`
   `.evidence_sources.logs` and `.occurrences.timestamps`, and any log id
   named in `correlation_results`;
2. the first and the last line of the window;
3. lines the product shows beside the analysis: correlation sample messages,
   the timeline's log events, change events, text quoted in the issue fields;
4. an even sample of the rest.

A cited line is matched by log id where there is one, else by its timestamp
(to the millisecond, then narrowed by service and text), else by its text.
Cited lines are never dropped, even past the limit (`trim.over_limit`). The
original order is kept and a kept line is not altered, except by the
renaming.

`trim` holds `logs_total`, `logs_kept`, `cicd_logs_total`, `cicd_logs_kept`,
how many references were located, and
`evidence_references_not_located`: the references for which no line was
found (the model sometimes quotes a line that the batch only held as a change
event, counted in `evidence_references_located_in_change_events`, or
paraphrases one).

Every figure of the analysis stays as captured (`logs_analyzed`,
`statistics.total_logs`, `logs_raw_count`, metrics, timings): they describe
the analysis, not the trimmed file.

## Time

No time is shifted. Each file has one `anchor`, its batch timestamp, and
every time in it is in its original form.

`index.json` → `time.paths` lists every place a time was found, with its
formats: ISO strings, times written inside log lines and other text
(`2026-11-19 00:04:38,914`, `18 Nov 2026 23:57:56.419`), epoch seconds,
milliseconds and nanoseconds as numbers or inside text and ids, and the time
inside `batch_id`. Paths are JSON pointers with `*` for a list index.

To place a file on another date, compute one delta and call
`build_seed.shift_times(doc, delta_seconds, paths, anchor)`: it moves every
value at those paths and keeps each format. Use a whole number of days:
the texts listed in `time.clock_time_only_paths` (analysis text, reasoning)
name times of day without a date, "at 23:59:34", which stay true only then.

A 10-digit number is taken for a time only under a time-named key, so a
metric value is never moved.

## Renaming

| Real | Becomes |
|---|---|
| Organisation name (where a field names the organisation) | `Acme Cloud` |
| Cloud project and account ids | `acme-prod-<n>` |
| Cluster names | `acme-<estate>-cluster` |
| Node and other host names | `acme-<estate>-node-<n>`, `host-<n>.acme.example` |
| The short node suffix the analysis uses for a host | `node-<n>` |
| Private and link-local addresses | `10.20.x.y` (RFC 1918) |
| Other addresses | `203.0.113.x`, `198.51.100.x`, `192.0.2.x` (RFC 5737) |
| Repository URLs, repository owners | `git.acme.example/acme-cloud/<estate>`, `acme-cloud` |
| Companies and domains that are not ours (`third_party` in the map): a card brand in a log line, the registry an image came from, a public documentation host | an invented name or a host under `acme.example`, for example `registry.acme.example/<estate>/…` |
| A folder of the test setup in front of file paths (`path_prefix` in the map), also where the AI's text quotes the path | the path without that folder, for example `fleet/jobs.yaml` |
| Commit authors, committers, requesters | one of a fixed set of invented people, one per real person |
| Any e-mail address | `…@acme.example` |

The same real value always becomes the same replacement, in keys, label
values, free text, log lines, URLs and ids. Kept as they are: service names,
namespaces, pod names, commit shas and messages, error text, image names
and tags (the registry host in front of them is renamed), regions, and the
estate names, which are the project names. Names of tools and open-source
projects (Redis, PostgreSQL, Jenkins, Kubernetes, Python and so on) stay:
only companies, people and domains that are not Acme are renamed.

The placeholders `[PRIVATE_IP]`, `[PUBLIC_IP]`, `[EMAIL]` and
`[CREDIT_CARD]` in the files were written by SerOps' own redaction when the
capture was taken; they are left as they are.

`--discover` builds the map by scanning every file of the selected captures,
store files and query trail included, for organisation, project and cluster
names, cloud project ids, host names, addresses, URLs, e-mail addresses and
repository owners. People are looked for only in commit author and
`requested_by` fields. Public hosts found in URLs are listed under
`url_host_keep`; review that list.

## Verification

`--verify`, also run by `--build` before anything is written:

1. the secret patterns of `tools/estate-capture/capture.py`
   (`SECRET_PATTERNS`, imported) over every output file;
2. no real value of the rename map in any output file or file name, case
   ignored, compressed files included;
3. no IP address outside the placeholder ranges (plus `0.0.0.0` and
   loopback), no e-mail address outside `acme.example`, no URL host outside
   the allow-list: `acme.example`, in-cluster
   service names of the estate (a host whose last label is one of the file's
   own namespaces, services or project, or ends in `.svc` /
   `.cluster.local`), and the hosts in `url_host_keep`;
4. `ai_usage` is `null`;
5. time window: every time in `batch`, `investigation`, `issues`, `traces`
   and `injection` lies inside [investigation window start − 15 min, capture
   time]. An issue `created_at` that precedes its batch is exempt.

Checks 1 to 4 fail the run. Check 5 is reported: its violations, as counts
and field paths without values, go to `verify-report.md` in `--private-dir`,
with anything doubtful from check 3 (kept public hosts).

## Private reports

Written by `--build` into `--private-dir`, never into the repository:

- `verify-report.md`
- `third-party-names.md`: product, company and trademark names in the
  user-visible text, with counts and an example; image names; every commit
  sha and URL the UI could render as a link (none resolves after renaming)
- `resolution-facts.md`: per incident, what was changed and when, what
  reverted it, how long it lasted, which issues were raised

## Loading

`python manage.py seed_demo_org` loads the files (`backend/Data/demo_seed_loader.py`,
`backend/Data/management/commands/seed_demo_org.py`). Beside the seed files,
`backend/Data/demo_seed/` holds what the loader adds:

- `resolutions.json`: the resolution note of each issue (`resolution_root_cause`,
  `resolution_fix`, `resolved_at`), written by hand from the injection records.
  `keep_open: true` leaves the issue open and its note unloaded.
- `replaced-values.json`: per issue, the run-time `created_at`, `last_seen_at`
  and `occurrence_count` of each file and the values the loader writes instead
  (counted and dated from the seeded analyses), and under `batch_ids` the
  stable batch id each file is loaded under (`acme-<file name, lower case>`,
  in place of the captured id, which holds a time). Generated, never edited:
  `python3 backend/Data/demo_seed_loader.py --write-replaced-values`.
- `chat/*.json`: one chat session per file. Three ship with the seed (`fleet-K7-r1`,
  `shopfront-I1-r1`, `studio-L4-r1`): three questions each, asked on 19 Nov 2026
  through SerOps's own chat endpoint on a local instance loaded with this seed,
  answered by `claude-sonnet-5-5`, stored verbatim. Each answer carries the tokens
  and cost SerOps recorded for it (`tokens_input`, `tokens_output`, `cost_usd`,
  `asked_at`); the loader reads `role`, `text` and `offset_seconds` only, so no
  spend is loaded. The file's `produced` block says how it was made.

  ```json
  {"schema": "serops-demo-chat/1", "title": "…", "batch": "studio-L7-r1",
   "model": "claude-sonnet-5-5",
   "messages": [{"role": "user", "text": "…", "offset_seconds": 60},
                {"role": "assistant", "text": "…", "offset_seconds": 72}]}
  ```

  `batch` is a seed file name without `.json.gz`; `offset_seconds` counts from
  the end of that analysis.

The backend image does not hold this tool, so the time code above
(`shift_times` and what it needs) is copied to
`backend/Data/demo_seed_time.py`; `test_shift_parity.py` fails when the two
differ. A trace whose span id was masked by SerOps' redaction at capture time
(one, in `studio-L4-r1`) is not loaded.

## Tests

```bash
python3 -m unittest discover -s tools/demo-seed -p 'test_*.py'
```

Standard library only. The fixtures are invented; no capture data is in the
tests.
