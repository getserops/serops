---
seo_title: "Troubleshooting"
description: "Fixes for common SerOps problems: installation, providers, missing data, AI analysis, notifications and performance."
---
# Troubleshooting

Common issues and their solutions, organised by category.

If you don't find your issue here, jump to [Getting Help](#getting-help)
at the bottom.

## Authentication

| Issue | Check | Solution |
|-------|-------|----------|
| Cannot log in | Credentials | Verify email and password. Check if account is active. |
| Token expired | Session | Tokens expire after 30 days of inactivity. Log in again. |
| SSO login fails | Callback URL | Ensure the Redirect URI in your Identity Provider matches the one configured in **Settings > Security**. |
| "403 Forbidden" on API calls | Permissions | Your role lacks the permission. **Settings → Audit Log** shows an *Access Denied* entry naming the missing permission; see [Team Management](admin/team.md#roles). |
| Invitation link says "invalid or already used" | Link freshness | Invitations expire after 7 days. Ask the admin to re-invite. |

## Integrations

| Issue | Check | Solution |
|-------|-------|----------|
| "Connection refused" | Network | Verify the provider URL is reachable from the SerOps backend container. |
| "401 Unauthorized" | Credentials | Check that the access token or API key has not expired. Regenerate if needed. |
| Integration shows "Unverified" | Status | Click **Verify** on the integration to re-test credentials. |
| No repositories listed | Token scope | Ensure the access token has `api` scope (GitLab) or `repo` scope (GitHub). |
| Webhook not receiving events | URL/Secret | Each CI/CD binding has its own unique webhook URL (`/webhooks/{provider}/{binding_id}/`) and auto-generated secret. Verify both match in SerOps and your provider. |
| Webhook fires but no pipeline appears | Signature | Backend rejects any webhook where the HMAC signature doesn't match the binding secret. Regenerate the secret in the UI and re-copy it to your provider. |

## Data Pipeline

| Issue | Check | Solution |
|-------|-------|----------|
| No batches appearing | Services | Ensure at least one service is connected to the project. |
| Empty batches | Logs | Verify logs exist in your log provider for the time window. Check `service_name` matches a registered service. See [Configure Data Collection Agents](how-to/configure-data-collection.md). |
| "Unknown" batch status | Database | Run `docker exec serops-backend python manage.py migrate` to ensure migrations are current. |
| Missing logs after filtering | Service registration | Ensure the `service_name` field in your logs matches the registered `ProjectService` names exactly. See [Configure Data Collection Agents](how-to/configure-data-collection.md). |
| Wrong environment assignment | Branch patterns | Check that branch patterns in project environment settings match your actual branch names. |
| Batch appears but never analyzes | Sentinel filter | Check **Settings > Sentinel** — under `ACTIVE` or `QUIET` mode, low-signal batches are skipped by design. Switch to `EAGER` to force analysis on every batch. |

## Observability Providers

| Issue | Provider | Solution |
|-------|----------|----------|
| "Connection refused" | All | Verify the `host` URL is reachable from the SerOps backend container. |
| "401 Unauthorized" | ES, Prometheus | Check `username`/`password` or `bearer_token` configuration. |
| "403 Forbidden" | Datadog | Verify both `api_key` and `app_key` are valid and have required permissions. |
| "InvalidAccessKeyId" | CloudWatch | Check AWS credentials (`aws_access_key_id`, `aws_secret_access_key`) and region. |
| "No data returned" | All | Verify the time range has data. Check that `capabilities` match the provider type. |
| "Tenant not found" | Loki, Mimir | Verify `tenant_id` in `extra_config` matches your provider's tenant configuration. |
| "SSL certificate error" | ES, OpenSearch | Set `verify_certs: false` in `extra_config` (not recommended for production). |

## AI Analysis

Every AI-analysis failure surfaces a **structured error code** on the
batch. Codes below match `AIServiceError.code`.

| Code | Meaning | What to do |
|---|---|---|
| `AUTH_ERROR` | Provider rejected the API key | Re-enter the key in **Settings > AI Providers** and click **Test Connection**. |
| `QUOTA_EXCEEDED` | Provider rate-limit / paid quota exhausted | Wait for the rate-limit window to reset, upgrade your plan with the provider, or switch to a different provider for a while. |
| `OVERLOADED` | Provider capacity is transiently degraded (Claude Sonnet 529, etc.) | Retry shortly — this is a provider-side incident, not a config issue. Sentinel will automatically retry on the next batch. |
| `SERVER_ERROR` | Provider returned a 5xx | Check the provider's status page. If it's an outage, the fallback provider (if configured) will pick up. |
| `TIMEOUT` | Request exceeded the adapter timeout (default 120s) | Batch is too large — split it via a shorter batch interval — or increase `timeout_seconds` under **Settings > AI Providers > Provider Config** (only recommended for slow local Ollama). |
| `NETWORK_ERROR` | Connection failed at TCP / DNS level | Almost always self-hosted: Ollama container down, wrong `api_base_url`, network policy blocking egress. Test with `curl <api_base_url>/models`. |
| `CONTENT_BLOCKED` | Provider safety filter refused the content | Gemini's SAFETY filter can trip on log content that looks like an attack. Retry usually fails — either switch providers for this batch or increase the PII-redaction aggressiveness in **Settings > Security**. |
| `AI_BUDGET_EXCEEDED` | Monthly cost cap reached | Raise **Settings > AI Providers > Monthly budget** or wait for the calendar month to reset. Rule-based issue creation (Sentinel, correlation engine) still runs — AI polish is what's paused. |
| `TRUNCATED` | Model hit its output-token limit mid-response | The partial answer is salvaged rather than discarded: the issues the model had finished writing are kept, the batch is labelled `(truncated)` with a note on the analysis, and any half-written trailing issue is dropped rather than published with missing fields. Re-analyse for the complete picture, or raise `max_tokens` under **Settings > AI Providers > Provider Config**. You will only see this code with no analysis attached when the response was cut before any usable text arrived. |
| `PROVIDER_NOT_SUPPORTED` | Provider name doesn't map to a known adapter | Check that the provider is in the AIModelProvider catalog. |
| `UNKNOWN_ERROR` | Adapter couldn't categorise the failure | Check `raw_error` on the batch for the original provider message. If it's a new pattern, open an issue so we can add classification. |

Related settings:

* Cost & budgets — [Track AI Costs](how-to/ai-costs.md)
* On-prem AI (Ollama) — [On-prem AI (Ollama)](how-to/on-prem-ai-ollama.md)
* Sentinel batch filtering — [Sentinel Tiered Intelligence](how-to/sentinel.md)

### Fallback + circuit breaker

When primary provider fails with `QUOTA_EXCEEDED` / `OVERLOADED` /
`SERVER_ERROR`, SerOps automatically falls back to the configured
fallback provider (if any). After N consecutive failures, the circuit
breaker OPENS and skips the primary for a cooldown window.

`TRUNCATED` deliberately does **not** fall back. The primary answered — it just
ran out of room — so spending a second paid call to replace an answer that is
mostly complete would be waste, and a successful fallback would silently swap
providers on a batch that already had a usable diagnosis. The partial analysis
is salvaged from the primary instead.

| Symptom | Meaning |
|---|---|
| Batch used fallback provider name | Primary failed once; automatic fallback fired. Expected. |
| Every batch uses fallback | Primary circuit is OPEN — check **Settings > AI Providers** for the reason. |
| Both providers erroring | Provider outage or a bad prompt (rare). Look at `raw_error` on the batch. The reported error is the **primary's**, with the fallback's code appended to the message — so `QUOTA_EXCEEDED ... Fallback provider gemini also failed (AUTH_ERROR)` means your chosen provider is out of quota *and* the fallback's key is bad. Fix the first one; the second is a separate problem. |

## Notifications

| Issue | Check | Solution |
|-------|-------|----------|
| Not receiving emails | Email config | Verify SMTP settings in `.env`. Check spam/junk folder. |
| Not receiving Slack alerts | Webhook URL | Verify the Slack webhook URL in **Settings > Delivery Channels**. Test with the "Send test" button on the channel. |
| Slack channel accepted but no messages arrive | Channel filters | Check the channel's trigger filters + severity floor — you may be filtering the events out. |
| PagerDuty pages nobody | Integration key | Ensure the Events API v2 integration key is for the correct service, not the account. |
| OpsGenie alerts appear at P4 | Non-paging by design | SerOps posts as P4 to be additive to your existing pager schedule. Escalate manually via the alert if needed. |
| Too many notifications | Preferences | Configure severity filters, quiet hours, or digest frequency in **Notification Preferences**. |
| Escalation not triggering | Rules | Verify escalation rules exist: they are managed through the API (`/api/notification/escalation-rules/`), see [Escalation rules](how-to/escalation-rules.md). |
| Notifications delayed | Quiet hours | Check if quiet hours are active. Notifications are held and delivered as a summary afterward. |

## Distributed traces (OTLP)

| Issue | Check | Solution |
|-------|-------|----------|
| Collector returns 401 | Ingest key | Bearer token must match a key issued under **Settings > Distributed Traces**. |
| Collector returns 400 | Payload | SerOps only accepts OTLP/HTTP JSON — set your Collector exporter to `otlphttp` (not `otlp`). |
| Traces ingested but not appearing on batches | Time window | Batch trace correlation uses the batch's time window. Traces older than the batch or from a service not in the project don't appear. |
| Trace count on batch is 0 | Service names | The trace's `service.name` resource attribute must match a registered SerOps service name (case-insensitive). |

## Self-metrics (`/metrics/` endpoint)

| Issue | Check | Solution |
|-------|-------|----------|
| Prometheus scrape returns empty | Path | Endpoint is `/metrics/` (trailing slash). Some scrapers strip it — configure the full path. |
| Metrics endpoint returns 401 | Basic auth | If `SEROPS_METRICS_BASIC_AUTH` is set, configure Prometheus with matching creds. |
| High cardinality warnings | Middleware | The HTTP middleware caps cardinality by grouping URLs — if you see unbounded labels, file an issue. |

## Cost budget (Q3.3)

| Symptom | Meaning | Action |
|---|---|---|
| Yellow banner "AI budget at 80%" | Warn threshold reached | Non-blocking; either raise the cap or expect the hard cap soon. |
| Batches marked `AI_BUDGET_EXCEEDED` | Hard cap reached | Rule-based issues still fire; AI RCA polish is paused until the calendar month resets. Raise **Settings > AI Providers > Monthly budget** to resume. |
| Cost snapshot shows zero after AI calls ran | Token-usage recording failure | Check backend logs for `AITokenUsage` write errors. Rare — usually a DB write permission issue. |

## Deployment

| Issue | Check | Solution |
|-------|-------|----------|
| Container won't start | Logs | Run `docker logs serops-backend` to check for errors. |
| Migration errors | Database | Verify database connection settings. Run `python manage.py showmigrations` to check state. |
| Static files not loading | Build | Run `docker exec serops-frontend npm run build` to rebuild frontend assets. |
| Redis connection refused | Network | Verify Redis is running and accessible at the configured `CELERY_BROKER_URL`. |
| High memory usage | Configuration | Check batch generation interval. Consider increasing the interval for large deployments. |
| Post-restore: all API keys "invalid" | Encryption key | Your restored DB has secrets encrypted with a *different* `SEROPS_ENCRYPTION_KEY` than the running backend. Restore the original `.env` — see [Backup & Restore](deployment/backup-restore.md). |
| Post-upgrade: batches stop analyzing | Migration state | Some upgrades add new required env vars. Compare `.env.example` with your `.env` — see [Upgrading](deployment/upgrading.md). |

## Kubernetes (Helm)

| Issue | Check | Solution |
|-------|-------|----------|
| Pods CrashLoopBackOff on first install | Secrets | Check that `secrets.postgresPassword` and `secrets.encryptionKey` are set. Never leave the chart defaults for production. |
| Celery-beat pod has multiple replicas | Deployment strategy | Beat must be exactly 1 replica with `Recreate` strategy — the chart enforces this. If you overrode it in values, revert. |
| `/metrics/` scrape returns 401 in-cluster | ServiceMonitor | Enable `serviceMonitor.enabled=true` in values and configure a Prometheus scrape that carries the basic-auth secret. |
| Migrations don't run on upgrade | Job status | The chart's `helm upgrade` runs `migrate` as a Job. Check `kubectl -n serops get jobs`. |

## Getting Help

If your issue is not listed above:

1. **Check the container logs** — this catches 80% of issues:
   ```bash
   docker logs serops-backend --tail 200
   # Or in Kubernetes:
   kubectl -n serops logs -l app=serops-backend --tail 200
   ```
2. **Check `/metrics/`** for pipeline health — batch success rate,
   analysis duration, error counts (see [Self-metrics](admin/self-metrics.md)).
3. **Check the audit log** — **Settings > Audit Log** captures every
   admin action + failure with structured details.
4. **Read the architecture overview** — [Architecture Overview](architecture/overview.md)
   explains the pipeline so you can localise where things break.
5. **Search the docs** — the top-right search box covers every page in
   the site.
6. **File an issue** — [github.com/getserops/serops/issues](https://github.com/getserops/serops/issues)
   with backend logs, the batch ID (if AI-related), and reproduction
   steps.
