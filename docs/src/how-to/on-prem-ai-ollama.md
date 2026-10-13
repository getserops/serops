# On-prem AI (Ollama)

Run SerOps' AI RCA **entirely inside your perimeter** — no data
leaves your network. SerOps ships with a first-class Ollama
integration: same batch pipeline, same prompt, same JSON schema,
just a local model instead of a hosted API.

## When to pick this

- **Compliance / data residency** — logs + traces + code diffs never
  cross the internet to a third-party AI vendor.
- **Cost control at scale** — no per-token metering; hardware cost
  only.
- **Air-gapped installs** — Ollama runs offline.

If you don't need any of the above, **hosted providers (Claude,
OpenAI, Gemini, DeepSeek) will be cheaper and higher-quality** at
low-to-medium volume. Ollama is a compliance / control tool, not
a default.

## Prerequisites

- One host (VM or K8s node) with:
  - **16 GB RAM minimum** for a 7-8B model, **32 GB+** recommended
    for 13B and up.
  - **1× GPU** highly recommended (NVIDIA T4 / L4 / A10 / A100 all
    fine). CPU inference works but is slow — expect 30–60s per
    batch analysis on CPU vs. 3–8s on GPU.
  - Network access from SerOps backend + celery-worker pods to
    the Ollama endpoint.
- Docker or a Kubernetes cluster.

## Step 1 — Deploy Ollama

**Docker (single-host quickstart):**

```bash
docker run -d --name ollama \
  --gpus all \
  -v ollama-models:/root/.ollama \
  -p 11434:11434 \
  ollama/ollama:latest
```

**Kubernetes:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ollama
spec:
  replicas: 1
  selector: {matchLabels: {app: ollama}}
  template:
    metadata: {labels: {app: ollama}}
    spec:
      containers:
        - name: ollama
          image: ollama/ollama:latest
          ports: [{containerPort: 11434}]
          resources:
            limits:
              nvidia.com/gpu: 1
              memory: 32Gi
          volumeMounts:
            - {name: models, mountPath: /root/.ollama}
      volumes:
        - name: models
          persistentVolumeClaim: {claimName: ollama-models}
---
apiVersion: v1
kind: Service
metadata: {name: ollama}
spec:
  selector: {app: ollama}
  ports: [{port: 11434, targetPort: 11434}]
```

## Step 2 — Pull a model

Recommended models for SerOps' RCA workload (JSON-structured
output, ~4K token prompts):

| Model | RAM | Quality | Speed |
|---|---|---|---|
| `qwen3:8b` | 8 GB | ★★★ (default) | Fast |
| `llama3.1:8b` | 8 GB | ★★★ | Fast |
| `qwen2.5-coder:14b` | 16 GB | ★★★★ | Medium |
| `llama3.3:70b` | 48 GB | ★★★★★ | Slow (needs A100) |

```bash
docker exec ollama ollama pull qwen3:8b
```

## Step 3 — Configure SerOps

*Settings → AI Providers*, select **Ollama (Local)**.

- **Base URL**: `http://<ollama-host>:11434/v1/` (note the trailing
  `/v1/` — that's Ollama's OpenAI-compat endpoint).
- **Model**: `qwen3:8b` (or whichever you pulled).
- **API key**: leave blank — Ollama is keyless.

Or via API:

```bash
# Update ollama provider record with your host URL
curl -X PATCH https://your-serops-host/api/settings/ai/providers/<ollama-provider-id>/ \
  -H "Authorization: Token $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"api_base_url": "http://10.0.5.42:11434/v1/", "default_model": "qwen3:8b"}'
```

Set Ollama as the default provider:

```bash
curl -X PUT https://your-serops-host/api/settings/ai/ \
  -H "Authorization: Token $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"default_provider": <ollama-provider-id>}'
```

## Step 4 — Verify

Reachability + model listing:

```bash
curl -X POST https://your-serops-host/api/settings/ai/ollama/probe/ \
  -H "Authorization: Token $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"base_url": "http://10.0.5.42:11434/v1/"}'
```

Response:

```json
{"reachable": true, "models": ["qwen3:8b", "llama3.1:8b"], "error": null}
```

Then trigger an analysis (any batch under *Data →
Analyze with AI*) and watch the celery-worker logs. First
analysis takes ~30–60s on CPU / ~3–8s on GPU.

## Rate limits + concurrency

Ollama serves one request at a time per model (with a small
in-memory queue). Under load you want either:

- **Multiple Ollama replicas** behind a load balancer + point
  SerOps' base URL at the LB.
- OR **larger celery worker concurrency reduced to 1-2** so
  simultaneous batches don't stack up on the single Ollama
  process.

For a small team (< 200 batches/day, single cluster), one Ollama
instance is fine.

## Cost budget still applies

Even at $0 per token, you can enforce a "max batches per month"
policy via **Settings → AI Providers → Monthly budget** (Q3.3) — set
`monthly_budget_usd` to a nominal value with tightened
`price_input_per_million` / `price_output_per_million` on the
Ollama row to represent your amortized hardware cost. The
budget-exceeded degradation still works: rule-based issue
creation (Sentinel, correlation engine) continues; AI RCA
resumes on the 1st of next month.
