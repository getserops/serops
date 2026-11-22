# HolmesGPT benchmark settings (published runs)

| Setting | Value |
|---|---|
| HolmesGPT | 0.46.0 (PyPI `holmesgpt==0.46.0`), LiteLLM 1.103.5, Python 3.12.14 |
| Image | `serops-bench/holmesgpt:0.46.0` built from `Dockerfile.holmesgpt` (python:3.12-slim + pip); local image id sha256:f72fd3e45efabefd5baaf6da169b4cc985d8d3b6fe90215460d425805421948f (2026-11-18) |
| Config file | none: HolmesGPT's documented defaults (`--mode default`). `holmes-config.yaml` is used only with `--mode evidence-only` |
| Toolsets enabled by default (`holmes toolset list` in the image) | kubernetes/kube-prometheus-stack, core_investigation, internet, connectivity_check, skills, bash. All others unavailable: no cluster, kubeconfig, CLI or token in the container |
| Command | `holmes ask --no-interactive --no-echo --model anthropic/claude-sonnet-5-5 --json-output-file /out/out.json -f /ev/<each evidence file> "<QUESTION>"` |
| Model | claude-sonnet-5-5 (same as SerOps), key via `--env-file` (ANTHROPIC_API_KEY) |
| Temperature | HolmesGPT default: env TEMPERATURE unset, so 1e-08 (`holmes/common/env_vars.py`) |
| Max steps | HolmesGPT default 100 (`holmes/config.py`) |
| Timeout | 600 s per scenario (harness) |
| Question | `QUESTION` in `__init__.py`, fixed before any result |
| Scoring | `rca_benchmark.scoring.score`, unchanged; same keys as SerOps |
| Cost | from HolmesGPT's token counts at SerOps' Sonnet 5.5 prices (2 / 2.5 / 0.2 / 10 USD per million: input / cache write / cache read / output) |
