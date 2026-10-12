# SerOps

**AGPL-3.0 AI Root Cause Analysis platform** — logs · metrics · distributed traces · deploys · code changes.

Runs on Kubernetes (Helm) or Docker Compose and analyses workloads wherever they run — Kubernetes-aware (pods, restarts, OOMKills) but not Kubernetes-only. Complements your existing observability stack rather than replacing it:

- **Logs** — Elasticsearch, OpenSearch, Loki, Splunk, Datadog, AWS CloudWatch, Google Cloud Logging, Azure Log Analytics
- **Metrics** — Prometheus, VictoriaMetrics, Grafana Mimir, Datadog, AWS CloudWatch, Google Cloud Monitoring, Azure Monitor
- **Traces** — built-in OTLP receiver, Jaeger, Zipkin, Grafana Tempo, Datadog APM
- **Code & CI/CD** — GitHub, GitLab, Bitbucket, Azure DevOps, Jenkins; deployments from Argo CD and Flux

SerOps watches the signals you already produce, correlates them, and asks a large language model to explain *why* an incident happened. It is alert-agnostic: it surfaces issues even when nobody set up an alert for them.

## Repository layout

```
serops/
├── backend/     # Django 5 + Celery + PostgreSQL + Redis — REST API and workers
├── frontend/    # React 19 + Vite + Bootstrap — the dashboard
├── docs/        # MkDocs Material — https://serops.ai/docs
└── deploy/
    ├── quick-start/    # docker-compose self-host (5-minute install)
    └── helm/serops/    # Kubernetes Helm chart
```

## Install

**Docker Compose (single node):**
```bash
git clone https://github.com/getserops/serops.git
cd serops/deploy/quick-start
cp .env.example .env  # edit domain + secrets
docker compose up -d
```

**Kubernetes (Helm)** — lab install with bundled Postgres + Redis; for
production pass `database.url` / `broker.url` instead (see the
[Helm guide](https://serops.ai/docs/deployment/helm/)):
```bash
helm install serops oci://ghcr.io/getserops/charts/serops \
  --namespace serops --create-namespace \
  --set django.secretKey="$(openssl rand -hex 64)" \
  --set devServices.postgresql.enabled=true \
  --set devServices.redis.enabled=true
```

**AI provider keys are not set in `.env` or in Helm values.** Add them in the UI after first login under **Settings → AI Providers**. They are stored per organisation and encrypted at rest, so nothing reads `ANTHROPIC_API_KEY` or its siblings from the environment. SerOps needs at least one key — Anthropic, Google Gemini, OpenAI, DeepSeek, or Ollama (keyless, on-prem) — before it can analyse anything.

Full guides in [docs/](docs/) or at https://serops.ai/docs.

## What is in the box

| Component | Description |
|---|---|
| **Django REST API** | Multi-tenant API for projects, services, integrations, batches, issues, chat, audit, settings |
| **Celery workers** | Scheduled batch creation, AI analysis, deployment sync, notifications, retention |
| **AI adapter system** | Pluggable providers (Anthropic Claude, Google Gemini, OpenAI-compatible) with circuit breaker, rate limiter, prompt caching |
| **Integration adapters** | Pluggable log, metric and trace backends, an OTLP trace receiver, SCM, CI/CD and GitOps providers (current list above) |
| **Sentinel** | Cost-controlled AI gating — skips analysis on "quiet" batches based on rolling baselines |
| **Recent Resolutions Context** | Resolved issues from the same project become diagnostic hints in future AI prompts |
| **Dashboard** | Role-aware React UI mirroring the backend RBAC matrix, English and French |

## What works today

- Multi-tenant (several organisations per instance) with RBAC (admin / user / viewer) and audit logging
- Log, metric, trace, SCM, CI/CD and GitOps integrations (list above) plus OTLP trace ingestion
- AI batch analysis with cost tracking and Sentinel gating
- Email, Slack, Microsoft Teams, PagerDuty and OpsGenie notifications with routing rules, escalation and digest
- OIDC single sign-on with HttpOnly cookie token handoff
- Knox token auth, password change/reset with full token revocation
- GDPR right-to-erasure (`DELETE /api/auth/account`)
- PII redaction before any data reaches third-party AI providers

## What does not work yet

- SAML 2.0 SSO (OIDC only)
- Two-factor authentication
- Inbound Slack / Teams interactions (acknowledge from chat)
- Discord channel
- Encryption-key rotation tooling

See the [docs](https://serops.ai/docs/) roadmap for the full picture.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) — it covers all three components, including
per-component dev setup and test commands. Security issues go through
[SECURITY.md](SECURITY.md), never a public issue.

## License

AGPL-3.0. See [LICENSE](LICENSE).

Commercial licenses available for AGPL-policy-conflict organisations — see [LICENSE-COMMERCIAL.md](LICENSE-COMMERCIAL.md) and [docs/src/license.md](docs/src/license.md).
