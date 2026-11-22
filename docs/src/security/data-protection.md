---
seo_title: "Data protection and PII redaction before the AI"
description: "How SerOps masks secrets and personal data in logs before anything reaches an AI model, and what you can configure."
---
# Data Protection & PII Redaction

SerOps masks credentials and personal data in everything it sends to an AI
provider: batch analysis, AI chat, re-analysis and model comparison, CI/CD job
errors, post-mortem drafts and the embeddings used for similar past incidents.
Every AI call goes through one redaction step, and if that step fails nothing
is sent. Masking is regex-based, so it reduces what reaches the AI provider but
cannot guarantee that nothing sensitive gets through; see
[Current limits](#current-limits).
If nothing may leave your network, use a local model through
[Ollama](../how-to/on-prem-ai-ollama.md).

## Overview

```mermaid
graph LR
    A[Raw Logs] --> B[Redaction Scanner]
    B --> C{Sensitive Data?}
    C -->|Yes| D[Mask & Report]
    C -->|No| E[Safe Data]
    D --> E
    E --> F[AI Analysis]
```

Every prompt passes through the **DataRedactionService** before it is sent to the configured AI model.

## Current limits

Every AI call (batch analysis, chat, re-analysis and model comparison, CI/CD
job errors, post-mortem drafts) is masked at the one place they all go
through, the prompt and the system prompt alike. If masking raises an error,
the call stops with `REDACTION_FAILED` and nothing is sent. Embeddings for
similar past incidents fall back to a local hash instead of sending unmasked
text.

| Limit | What it means |
|---|---|
| **Pattern coverage** | Only the formats in the tables below are recognised. Other token formats (for example some cloud-provider or SaaS keys) pass through unless they match the generic secret patterns. |
| **Very long lines** | A single line longer than 20,000 characters is cut there, with a note of how many characters were cut, before masking, so one pathological line cannot stall an analysis. |
| **Unformatted numbers** | A phone number needs phone formatting (`+33 6 12 34 56 78`, `(555) 123-4567`) or a `phone=` / `tel:` label, and an SSN its dashes or an `ssn` label. Bare digit runs are left alone so byte counts, timestamps and ids stay readable for the analysis. |
| **AI chat** | Your message is masked like everything else. The browser also warns before you send text that looks sensitive (see [AI Chat Protection](#ai-chat-protection)). |


---

## What SerOps stores

SerOps reads your logs, metrics and traces from the stores you already run.
It is not a second telemetry store, but it does keep what each analysis read,
in its own PostgreSQL on your infrastructure.

**With each analysis**

| Kept | Detail |
|---|---|
| Log lines | The warning and error lines of the analysis window, up to 5,000 per analysis |
| Metric points | The CPU and memory points of the window, and a summary of them |
| Code changes | Commit message, author name and e-mail address, and previews of the diffs |
| CI/CD job logs | The job logs read for the window |
| Trace summaries | The slowest and the failing operations of the window |
| The result | The analysis and the issues it raised |

**Stored log lines are kept as read.** Masking applies to the copy that is
sent to the AI model, not to the lines stored in your database. Trace
summaries and alert payloads are the exception: they are masked before they
are stored. Chat messages and answers are stored as typed; they too are masked
on the way to the model.

**Spans.** Spans you send to SerOps's own OTLP endpoint are stored in full,
with their attributes and events, and are not masked in storage.

**How long**

| Data | Default |
|---|---|
| Analyses, with their log lines, issues and the rest of the table above | Kept until you delete them. Automatic cleanup is **off** by default; switched on, it deletes analyses older than the period you choose, from 7 days to 1 year (30 days if you do not change it) |
| Raw metric points on an analysis | Dropped after 30 days; the summary stays with the analysis |
| Spans, chat conversations, code changes, pipelines and deployments | No retention period: kept until the organisation is deleted |

Automatic cleanup and its period are set in
[Data Retention](../admin/data-retention.md).


---

## What SerOps reads from your repositories

SerOps never clones, indexes or stores your repository. It reads **what changed**, nothing else:

| Step | What happens |
|------|--------------|
| **Read** | The commits deployed in the analysis window, and their diffs. GitHub, GitLab and Bitbucket return the diff directly. Azure DevOps has no diff API, so SerOps fetches each changed file before and after the commit, computes the diff, and discards the file contents (first 10 files per commit; binary files and files over 200 KB are skipped). |
| **Store** | The commit metadata (SHA, author, message, branch, file list) and up to 16,000 characters of diff per file, on the commit record in your own Postgres. |
| **Send to the AI** | Only the parts of those diffs that the incident points at: hunks named by a stack frame in the logs, or mentioning the failing function or error text, within a fixed budget of about 3,000 tokens per analysis. Files nothing points at get a short excerpt. |
| **Redact** | Diff excerpts and commit messages go through the same redaction as logs (credentials, tokens, emails, see below). If redaction fails, the diff text is left out and only file names are sent. |

SerOps only ever reads code. The scopes each integration page asks for are a little wider (GitHub `repo`, GitLab `api`) because SerOps can also create the push webhook for you; if you create the webhook yourself, a token that can read repositories is enough.

---
 
## Environment Isolation

SerOps enforces strict **functional** isolation between environments (Development, Staging, Production) so AI analysis for a production incident is never polluted by development noise.

### Mechanism

1. **Application Logs**: Logs are strictly filtered. A 'Production' batch will **only** contain logs explicitly tagged with `environment: production` (or aliases like `prod`), even if they share an Elasticsearch index with development logs.
2. **Metrics**: Metric provider queries are scoped by `organisation_id`, `project_id`, and `environment` labels.
3. **Deployments**: Only code changes deployed to the specific target environment are included.
4. **CI/CD Logs**: Pipeline logs are filtered by the environment they ran against.

### Environment is a **filter**, not a **security boundary**

Environment separates the *data content* of a batch (production batches contain only production logs) but does **not** control *who can see* that data. Any authenticated user in an organisation can query batches across all environments the organisation has data for — `production`, `staging`, `development` are all visible with the same permission grant. There is no built-in "staging only" role.

If your operational model requires "developers see staging only" or "SREs see production only", implement it at the identity-provider / SSO layer (separate organisations for separate visibility groups) rather than expecting SerOps's RBAC to enforce it.

**Security boundary hierarchy** in SerOps (in order of enforcement strength):

| Boundary | Enforcement | Configurable? |
|---|---|---|
| Organisation | Hard — every queryset filters on `organisation` FK | No — always enforced |
| Role (viewer / user / admin) | Hard — RBAC decorators on views | Yes — set per user |
| Project | Open to the whole organisation by default; with Enterprise, a project can be kept to the teams given access (its **Access** tab) | Yes — per project (Enterprise) |
| Environment | Filter, not boundary — see above | No |
| Service / component | Filter, not boundary | No |

For most teams the organisation boundary is the right unit — a whole SerOps organisation per customer / per business unit. That aligns with how the multi-tenancy is designed.

---

## What Gets Scanned

### Credentials (Critical)
| Pattern | Example | Masked As |
|---------|---------|-----------|
| AI provider keys | `sk-ant-...`, `sk-proj-...`, `AIza...` | `sk-[REDACTED]`, `AIza[REDACTED]` |
| API keys, generic secrets | `api_key=...`, `token=...` | `[API_KEY]`, `[SECRET]` |
| AWS keys | `AKIA...` | `AKIA***`, `[AWS_SECRET]` |
| GitLab, GitHub, Slack tokens | `glpat-...`, `ghp_...`, `xoxb-...` | `glpat-[REDACTED]`, `gh*_[REDACTED]`, `xox*-[REDACTED]` |
| Passwords | `password=...`, `secret: ...`, `mot de passe: ...`, `docker login -p ...` | `*****` (for `docker login`, only the password) |
| Authorization headers | `Bearer <token of 20+ characters>`, `Authorization: Basic ...` (and `Token`, `Digest`, ...) | `Bearer [REDACTED]`, `Authorization: Basic [REDACTED]` |
| Private and SSH keys | `-----BEGIN RSA PRIVATE KEY-----` (the whole key body) | `[PRIVATE_KEY]`, `[SSH_KEY]` |
| JWT tokens | `eyJhbGciOi...` | `[JWT_TOKEN]` |
| SaaS and cloud tokens | Stripe `sk_live_` / `rk_live_`, GitHub `github_pat_`, Slack `xapp-` and `hooks.slack.com/...` webhooks, SendGrid `SG.`, Twilio `SK`/`AC` SIDs, npm `npm_`, PyPI `pypi-`, Hugging Face `hf_`, DigitalOcean `dop_v1_`, Google OAuth `ya29.` | the prefix with `[REDACTED]` (`[STRIPE_KEY]`, `[TWILIO_KEY]`) |
| Azure storage | `AccountKey=...`, SAS `sig=...` | the key or signature only: `[REDACTED]` |
| Credentials in a URL query | `?access_token=...`, `&token=...`, `&key=...`, `api_key`, `client_secret` | the value only: `[REDACTED]` |
| Cookies | `Cookie:` and `Set-Cookie:` values (every cookie) | `[REDACTED]` |
| Command-line passwords | `curl -u user:pass`, `mysql -p<password>` | the password only: `*****` |
| Unlabelled secrets | a long hex or base64 value just after `key`, `secret`, `signing`, `signature` or `hmac` | `[SECRET]` |

### Personal Information (High)
| Pattern | Example | Masked As |
|---------|---------|-----------|
| Emails | `user@company.com` | `[EMAIL]` |
| Phone numbers | `+1-555-123-4567`, `phone=0612345678` | `[PHONE]` |
| Credit cards | `4111-1111-1111-1111` | `****-****-****-XXXX` |
| SSN | `123-45-6789`, `ssn=123456789` | `[SSN]` |

### Infrastructure (Medium)
| Pattern | Example | Masked As |
|---------|---------|-----------|
| IP addresses | `192.168.1.100`, `203.0.113.7` | `[PRIVATE_IP]`, `[PUBLIC_IP]` (loopback, link-local and netmasks are kept) |
| Connection strings | `postgresql://user:pass@host/db`, `DATABASE_URL=...` | `*****`, `[CONNECTION_STRING]`, `[DATABASE_URL]` |
| Credentials in URLs | `https://user:pass@api.com` | `https://user:*****` (the host goes with the password) |
| S3 buckets | `s3://my-bucket` | `s3://[BUCKET]` |

## Batch Log Redaction

When batch analysis runs (every 15 minutes by default), logs are automatically scanned:

```python
# Automatic redaction before AI analysis
from Utils.data_redaction import redact_batch_logs

redacted_logs, summary = redact_batch_logs(raw_logs)
# summary contains counts by severity: critical, high, medium
```

### Internal Logging
 
Redaction activity is logged internally for compliance, tracking:
 
- **Total items redacted**
- **Count by severity** (critical, high, medium)
- **Original vs redacted size**

---

## Trace and Alert Redaction

Logs are not the only path to the AI. Distributed traces and inbound
alerts also carry free-text fields that a provider wrote without
knowing SerOps would forward them, so they pass through the same
scanner before persistence or egress (`Utils/redaction_helpers.py`).

| Function | Applies to | Covers |
|---|---|---|
| `redact_text` | Any single string | The shared primitive the others build on |
| `redact_span_summary` | Trace snapshots | `operation_name`, `status_message`, `service_name`, `services_touched` across `top_slow` and `top_errors` |
| `redact_alert_parsed` | Parsed alert events | `summary`, and the normalised alert fields |
| `redact_raw_payload` | Raw webhook bodies | Recursive walk, depth-capped at 8 |

Redaction happens at **write** time, not read time. A trace summary is
scrubbed before it is stored on the batch, so the raw text never lands
in the database, never reaches an AI prompt, and never appears in a
support export. The same applies to alert payloads: what you see in
the UI is already the redacted form.

!!! note "Depth cap on raw payloads"
    `redact_raw_payload` stops recursing at depth 8. Alert bodies are
    provider-shaped and occasionally self-referential; the cap keeps a
    pathological payload from stalling ingest. Anything deeper than 8
    levels is dropped rather than passed through unscanned.

---

## Outbound requests

Cloud metadata and every link-local address are always refused, before and after redirects; localhost and private addresses are allowed by default because a self-hosted install reaches Ollama at `http://localhost:11434` and Loki, Prometheus or Elasticsearch inside its own network (an install shared by several organisations must set `SEROPS_OUTBOUND_ALLOW_PRIVATE=false` to refuse them).

The host name of a configured URL is resolved once; every address it resolves to must pass, and the connection goes to one of those addresses, with the Host header, TLS SNI and certificate check still using the name. This covers the HTTP integrations, SCM and CI calls, notification webhooks and the SSO token exchange. The Elasticsearch and OpenSearch clients check the URL before every request but resolve the name themselves when they connect; the AI SDKs (OpenAI-compatible endpoints) check a custom base URL when the client is created.

## Secrets at Rest

Some values must be stored to function, so the question is what an
attacker gets from a database dump.

| Secret | Storage | Recoverable? |
|---|---|---|
| AI provider API keys | Fernet-encrypted in `OrganisationAPIKey` with `SEROPS_ENCRYPTION_KEY` | Only with `SEROPS_ENCRYPTION_KEY` |
| Alert-ingest secret | SHA-256 hash plus a short display prefix | **No** — plaintext is shown once at rotation and never stored |
| Channel webhook URLs / API keys | Fernet-encrypted, write-only via the API | Only with `SEROPS_ENCRYPTION_KEY` |
| Observability integration credentials (`password`, and `extra_config` secrets such as Datadog `api_key`/`app_key` and `bearer_token`) | Fernet-encrypted, write-only via the API | Only with `SEROPS_ENCRYPTION_KEY` |

Write-only means what it says: once set, `webhook_url` and `api_key`
are never returned by any endpoint. Responses expose the booleans
`has_webhook_url` and `has_api_key` so the UI can show configured
state without ever re-transmitting the value. Observability integrations
work the same way: `password` and the secret `extra_config` keys are never
returned, and responses carry `has_password` and `secret_fields_set` (the
names of the secret keys that hold a value). Sending a secret back blank
on an update keeps the stored one. Rotation is a write, not
a read-modify-write.

Because AI keys are held per organisation rather than in an
environment variable, a multi-tenant self-host cannot accidentally
pool one tenant's quota — or one tenant's billing — across the
instance. That property is why there is no env-var fallback for them.

---

## AI Chat Protection

When users type messages in the AI Chat, real-time scanning warns about sensitive data:

### How It Works

1. User types a message
2. Frontend calls `scanMessageForSensitiveData(message)`
3. If sensitive data found → **Warning Modal** appears
4. User can:
   - **Edit** the message to remove sensitive data
   - **Send Anyway** (consent tracked for audit)
   - **Cancel** the message

If you send anyway, the server still masks what it recognises before the
message reaches the AI provider; the warning lets you remove what it would not.

### Warning Modal

The modal shows:
- Number of sensitive items detected
- Severity breakdown (critical/high/medium)
- Clear options to proceed or edit

---

## Configuration

### Enable/Disable Patterns

The redaction service is configured in `Utils/data_redaction.py`:

```python
service = DataRedactionService(config={
    'patterns': ['api_key', 'password', 'email'],  # Enable specific patterns
    'custom_patterns': {
        'internal_id': r'INTERNAL-\d{6}'  # Add custom patterns
    }
})
```

---

## Best Practices

!!! tip "Recommendations"
    1. **Review Redaction Reports** - Check weekly for patterns in detected sensitive data
    2. **Train Teams** - Educate developers to not log sensitive data
    3. **Custom Patterns** - Add company-specific patterns (internal IDs, etc.)
    4. **Audit Regularly** - Export reports for compliance audits

!!! warning "Limitations"
    - Redaction uses regex patterns; novel formats may not be detected
    - Encrypted/encoded data is not scanned
    - Very large logs may be sampled for performance

---

## API Reference

### Scan Message
```
POST /api/utils/scan-message/
Content-Type: application/json

{
  "message": "My API key is sk-live-abc123"
}
```

Response:
```json
{
  "has_sensitive_data": true,
  "findings": [
    {
      "pattern_type": "api_key",
      "sensitivity": "critical",
      "context": "...API key is sk-l..."
    }
  ],
  "critical_count": 1,
  "high_count": 0
}
```


