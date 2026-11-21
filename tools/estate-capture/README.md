# Estate capture

Saves everything about each incident of a benchmark estate run, so the
question "was the evidence readable, and did SerOps read it" can be answered
from saved data after the estate is deleted.

```bash
python3 tools/estate-capture/capture.py <estate-dir>             # every incident run not yet captured
python3 tools/estate-capture/capture.py <estate-dir> --only J2-r1
python3 tools/estate-capture/capture.py <estate-dir> --force     # capture again
```

Run it after each round is scored. It only reads: the SerOps API with the
estate's token, the stores, and the query trail on the SerOps workers. It
never changes a scored result.

## What one incident directory holds

`<output>/<estate>/<incident>-<round>/`

| File | Content |
|---|---|
| `analysis.json` | The investigation, the batch (what SerOps gave the AI), its issues with root cause and evidence, the timeline, the analysis history, model and token count |
| `query-trail.jsonl.gz` | Every request SerOps sent to a store during the investigation and its analysis, and the answer (see "Query trail") |
| `<store>.json.gz` | What each store held, read directly: every metric series in the window with all its labels; logs at every level and traces of the incident's services |
| `injection.json` | The inject and revert records (what was changed, when), the fault's start and end, the services, the pre-registered key row |
| `versions.json` | SerOps version and commit, the estate setup commit, the model, the capture tool's commit |
| `manifest.json` | Written last: files with sizes and sha256, windows, per-store counts, truncation, redaction counts, secret scan result |

The window is SerOps' own investigation window widened to cover the fault
from inject to revert, plus `margin_minutes` (default 5) on each side, and
at most 90 minutes.

## Rules it keeps

- **Redaction.** Every string goes through SerOps' own redaction
  (`backend/Utils/data_redaction.py`, the code that runs before every AI
  call) before anything is written.
- **Secret check.** Each file is then scanned for credential shapes (private
  keys, kubeconfig material, bearer and basic credentials, JWTs, cloud, AI,
  GitHub, GitLab and Slack tokens) and for the exact values of the estate's
  own secrets (`token`, the `secret_files`, the kubeconfig's keys and
  tokens). A hit stops the whole run at once with exit code 3, keeps
  nothing on disk for that incident, and names the file and the kind of
  secret, so it can be fixed and captured again while the estate is up.
- **Fails loudly.** A store that cannot be read, or answers nothing at all
  for the window, stops that incident with an error. A missing query trail
  is an error when `trail` is configured. Nothing is saved half-empty.
- **Safe to run twice.** A complete capture (`manifest.json` present) is
  skipped unless `--force`. Each incident is written to a temporary
  directory and moved into place only when complete.
- **Location.** `output` must be outside the repository and outside
  `common/`. The estate and incident directories are created mode 0700.

## Query trail

Off by default, for debugging and benchmarks. The trail holds raw store
answers, not redacted ones; this tool redacts them before saving.

SerOps records its store traffic only when `SEROPS_QUERY_TRAIL_DIR` is set
(Helm: `django.queryTrailDir: /tmp/serops-query-trail`). Each investigation
writes `investigation-<id>.jsonl` and each analysis `<batch_id>.jsonl` on
the worker that ran it: method, URL (credentials removed), request body,
status, answer. Request headers are never recorded. It covers every store
reached through `Utils.outbound`, Elasticsearch, OpenSearch and Google Cloud
Monitoring. Not covered: CloudWatch, Azure Monitor and Google Cloud Logging
(their SDKs), and SerOps' own trace store (a database read; captured
through the API instead). The answers are stored unredacted on the pod, so
the setting is for test estates only.

## capture.json

In the estate directory. Paths are relative to it.

```json
{
  "estate": "ledger",
  "output": "~/Documents/workspace/serops/benchmark-captures",
  "serops": {"base_url_file": "base_url", "token_file": "token"},
  "kubeconfig": "kubeconfig",
  "results_dir": "results",
  "keys_file": "/path/to/2026-11-16-c2-incidents-PREREG.md",
  "setup_dir": ".",
  "secret_files": ["admin.env", "gitea.env"],
  "trail": {"namespace": "serops", "selector": "app.kubernetes.io/component=celery-worker",
            "dir": "/tmp/serops-query-trail"},
  "stores": [
    {"name": "mimir", "kind": "prometheus", "service": "obs/svc/mimir", "port": 9009, "path": "/prometheus"},
    {"name": "loki", "kind": "loki", "service": "obs/svc/loki", "port": 3100,
     "selector": "{namespace=\"ledger\", app=\"SERVICE\"}"},
    {"name": "tempo", "kind": "tempo", "service": "obs/svc/tempo", "port": 3200}
  ]
}
```

- `results_dir` holds `<incident>-<round>-{inject,investigation,revert}.json`
  as the estate runners write them.
- `setup_dir` must be a git checkout with a commit: its commit is the
  estate setup version. Uncommitted changes are counted in `versions.json`.
- `trail.source` is `kubectl` (default) or `docker` with `containers`.
- A store is reached by `url`, or by `service` (`namespace/svc/name`) and
  `port` through `kubectl port-forward`. `auth` reads credentials from a
  file: `{"file": "es.env", "type": "basic", "user": "ES_USER", "password": "ES_PASSWORD"}`.

| `kind` | Saves | Store options |
|---|---|---|
| `prometheus` (`mimir`, `victoriametrics`) | Every series of every metric name in the window, all labels, at `step` (15 s) | `path` (`/prometheus` for Mimir), `step`, `parallel` |
| `loki` | All lines of each service, every level | `selector` with `SERVICE`, `max_lines_per_service` (200 000) |
| `elasticsearch`, `opensearch` | All documents of each service | `index`, `time_field`, `service_filter` (JSON clause with `SERVICE`), `insecure`, `max_lines_per_service` |
| `tempo` | Traces of each service, full spans | `service_attribute`, `max_traces_per_service` (300) |
| `jaeger` | Traces of each service | `max_traces_per_service` |
| `serops-traces` | Traces SerOps received over OTLP, through its API | `max_traces_per_service` |
| `gcp-monitoring` | Every series of every metric type under `prefixes` | `project`, `key_file`, `prefixes`, `filter` |

Choose log selectors that do not depend on the SerOps labels (for example
the Kubernetes `namespace` and `app` labels), so lines the SerOps labelling
missed are captured too. A cap reached is recorded as `truncated`.

## Tests

```bash
python3 -m unittest discover -s tools/estate-capture -p 'test_*.py'
```
