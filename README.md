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
    ├── quick-start/    # docker-compose self-host (about 10 minutes)
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
  --set django.encryptionKey="$(openssl rand -base64 32 | tr '+/' '-_')" \
  --set devServices.postgresql.enabled=true \
  --set devServices.redis.enabled=true \
  --set ingress.allowInsecure=true   # lab only: no certificate, plain HTTP
```

**AI provider keys are not set in `.env` or in Helm values.** Add them in the UI after first login under **Settings → AI Providers**. They are stored per organisation and encrypted at rest, so nothing reads `ANTHROPIC_API_KEY` or its siblings from the environment. Similar-incident search uses the same organisation keys: embeddings from your AI provider when it offers them (OpenAI, Gemini, or Ollama `nomic-embed-text`), otherwise a local word-overlap match (see [Incident intelligence](https://serops.ai/docs/how-to/intelligence/)). SerOps needs at least one key — Anthropic, Google Gemini, OpenAI, DeepSeek, or Ollama (keyless, on-prem) — before it can analyse anything.

Full guides in [docs/](docs/) or at https://serops.ai/docs.

## What is in the box

| Component | Description |
|---|---|
| **Django REST API** | Multi-tenant API for projects, services, integrations, batches, issues, chat, audit, settings |
| **Celery workers** | Scheduled batch creation, AI analysis, deployment sync, notifications, retention |
| **AI adapter system** | Pluggable providers (Anthropic Claude, Google Gemini, OpenAI-compatible) with circuit breaker, rate limiter, prompt caching |
| **Integration adapters** | Pluggable log, metric and trace backends, an OTLP trace receiver, SCM, CI/CD and GitOps providers (current list above) |
| **Sentinel** | Cost-controlled AI gating — skips analysis on "quiet" batches based on rolling baselines, and fires on error spikes, deployments, new patterns and trace latency or error spikes (active mode by default; shadow mode analyses every batch) |
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
- Regex-based masking of secrets and personal data in every AI call (analysis, chat, re-analysis, CI/CD errors, post-mortems); if masking fails, nothing is sent — see [Data protection](https://serops.ai/docs/security/data-protection/#current-limits)

## What does not work yet

- Two-factor authentication
- Inbound Slack / Teams interactions (acknowledge from chat)
- Discord channel

See the [docs](https://serops.ai/docs/) roadmap for the full picture. Everything above,
and every item in this list once it ships, is in SerOps Community.

## Community and Enterprise

Community is the complete product for a team, free under the AGPL. Enterprise adds
governance for running SerOps as an organisation, under a commercial license. It only
adds to Community: nothing is ever moved out of it
([open source promise](https://serops.ai/docs/open-source-promise/)).

Enterprise is priced per organisation by employees, never per seat, and nothing is
counted or limited in the product:

| Band | Employees | Price per year |
|---|---|---|
| Business | up to 500 | €7,500, introductory |
| Enterprise | up to 5,000 | from €30,000 |
| Strategic | above 5,000, or a regulated sector | from €60,000 |

Custom roles and per-project access are available since 1.3.0, with a commercial license
and a support contract. Planned next: SAML 2.0 and SCIM, then real-time audit streaming to a
SIEM, delegated administration across organisations, and compliance reports. Cloud is
planned for 2027.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) — it covers all three components, including
per-component dev setup and test commands. Security issues go through
[SECURITY.md](SECURITY.md), never a public issue.

## License

AGPL-3.0. See [LICENSE](LICENSE). The two Enterprise directories, `backend/ee/` and
`frontend/src/ee/`, are the exception: they are under the
[SerOps Enterprise License](backend/ee/LICENSE), need a license key to run,
and SerOps is complete without them. Delete them and you have the Community
edition under the AGPL only. Every Community feature stays in Community, forever:
see our [open source promise](https://serops.ai/docs/open-source-promise/).

Commercial licenses available for AGPL-policy-conflict organisations — see [LICENSE-COMMERCIAL.md](LICENSE-COMMERCIAL.md) and [docs/src/license.md](docs/src/license.md).
