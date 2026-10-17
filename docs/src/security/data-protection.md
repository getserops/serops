---
seo_title: "Data protection and PII redaction before the AI"
description: "How SerOps masks secrets and personal data in logs before anything reaches an AI model, and what you can configure."
---
# Data Protection & PII Redaction

SerOps implements comprehensive data protection to ensure no sensitive information is sent to AI models.

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

All data passes through the **DataRedactionService** before being sent to the configured AI model.

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
| Project | Soft — no separate ACL; anyone in the org can see any project | No |
| Environment | Filter, not boundary — see above | No |
| Service / component | Filter, not boundary | No |

For most teams the organisation boundary is the right unit — a whole SerOps organisation per customer / per business unit. That aligns with how the multi-tenancy is designed.

---

## What Gets Scanned

### Credentials (Critical)
| Pattern | Example | Masked As |
|---------|---------|-----------|
| API Keys | `sk-live-abc123...` | `[REDACTED: API_KEY]` |
| AWS Keys | `AKIA...` | `[REDACTED: AWS_KEY]` |
| Passwords | `password=secret123` | `[REDACTED: PASSWORD]` |
| Private Keys | `-----BEGIN RSA...` | `[REDACTED: PRIVATE_KEY]` |
| JWT Tokens | `eyJhbGciOi...` | `[REDACTED: JWT_TOKEN]` |

### Personal Information (High)
| Pattern | Example | Masked As |
|---------|---------|-----------|
| Emails | `user@company.com` | `[REDACTED: EMAIL]` |
| Phone Numbers | `+1-555-123-4567` | `[REDACTED: PHONE]` |
| Credit Cards | `4111-1111-1111-1111` | `[REDACTED: CREDIT_CARD]` |
| SSN | `123-45-6789` | `[REDACTED: SSN]` |

### Infrastructure (Medium)
| Pattern | Example | Masked As |
|---------|---------|-----------|
| IP Addresses | `192.168.1.100` | `[REDACTED: IP_ADDRESS]` |
| Connection Strings | `postgresql://user:pass@host` | `[REDACTED: CONNECTION_STRING]` |
| URLs with Auth | `https://user:pass@api.com` | `[REDACTED: AUTH_URL]` |

---

## Batch Log Redaction

When batch analysis runs (every 10 minutes by default), logs are automatically scanned:

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

## Secrets at Rest

Some values must be stored to function, so the question is what an
attacker gets from a database dump.

| Secret | Storage | Recoverable? |
|---|---|---|
| AI provider API keys | Fernet-encrypted in `OrganisationAPIKey`, key derived from `SECRET_KEY` | Only with the app's `SECRET_KEY` |
| Alert-ingest secret | SHA-256 hash plus a short display prefix | **No** — plaintext is shown once at rotation and never stored |
| Channel webhook URLs / API keys | Fernet-encrypted, write-only via the API | Only with `SECRET_KEY` |
| Observability integration credentials (`password`, and `extra_config` secrets such as Datadog `api_key`/`app_key` and `bearer_token`) | Fernet-encrypted, write-only via the API | Only with `SECRET_KEY` |

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

### Organization-Level Settings

Admins can configure redaction behavior in **Settings → Security**:

- Enable/disable specific pattern types

- Export compliance reports

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


