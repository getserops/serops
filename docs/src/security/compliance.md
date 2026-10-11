# Compliance & Audit

SerOps provides comprehensive audit logging and compliance features for enterprise environments.

## Audit Log

Every significant action is logged with:

| Field | Description |
|-------|-------------|
| `action` | Type of action performed |
| `user` | Who performed the action |
| `organisation` | Which org the action belongs to |
| `ip_address` | Request IP address |
| `user_agent` | Browser/client info |
| `details` | JSON with action-specific data |
| `created_at` | Timestamp |

### Tracked Actions

| Action | Trigger |
|--------|---------|
| `LOGIN` | Successful login |
| `LOGIN_FAILED` | Failed login attempt |
| `LOGOUT` | User logout |
| `PASSWORD_CHANGE` | Password updated |
| `SETTINGS_CHANGE` | Any settings modified |
| `SERVICE_CREATE` | Service added to project |
| `SERVICE_DELETE` | Service removed |
| `BATCH_DELETE` | Batch deleted |
| `BATCH_CLEANUP` | Auto-cleanup ran |
| `TEAM_INVITE` | User invited |
| `TEAM_REMOVE` | User removed |
| `TEAM_ROLE_CHANGE` | Role updated |
| `AI_MODEL_CHANGE` | AI provider changed |
| `EXPORT_DATA` | Data exported |

### Viewing Audit Logs

Navigate to **Settings → Audit Log**:

- Filter by date range
- Filter by action type
- Filter by user
- Export to CSV

---

## Redaction Reports

Every batch analysis generates a `RedactionReport` for compliance:

```json
{
  "batch_id": "batch_20260107_143000_a1b2",
  "source_type": "logs",
  "total_items_redacted": 47,
  "critical_count": 3,
  "high_count": 12,
  "medium_count": 32,
  "findings_summary": {
    "api_key": 3,
    "email": 28,
    "ip_address": 16
  },
  "original_size_bytes": 524288,
  "redacted_size_bytes": 521400
}
```

---

## Data Retention

Configure automatic data cleanup in **Settings → Data Management**:

| Setting | Options |
|---------|---------|
| **Auto-Cleanup** | Enabled/Disabled |
| **Retention Period** | 7, 14, 30, 60, 90, 180, 365 days |
| **Cleanup Frequency** | Daily, Weekly, Monthly |
| **Audit Log Retention** | 30, 90, 365 days, or Forever |

### Retention Policy Model

```python
class RetentionPolicy:
    auto_cleanup_enabled: bool
    retention_days: int  # 7-365
    cleanup_frequency: str  # daily, weekly, monthly
    audit_log_retention_days: int
    last_cleanup_at: datetime
    next_cleanup_at: datetime
```

---

## Export & Compliance

### Export Options

- **Batches**: Export batch data with analysis results
- **Audit Logs**: Export action history (CSV)
- **Redaction Reports**: Export compliance audit trail

### GDPR Considerations

SerOps helps with GDPR compliance:

1. **Data Minimization** — Only necessary log data is stored
2. **Right to Erasure** — Both per-account and per-batch deletion are supported (see below)
3. **Audit Trail** — All access and modifications are logged
4. **Data Protection** — PII is automatically redacted before AI processing

### Right to Erasure — Delete Your Account

Authenticated users can delete their own account and personal data with a single API call:

```
DELETE /api/auth/account
```

What is removed:

- The user record (email, name, avatar, phone)
- Team memberships across all organisations the user belongs to
- Chat sessions and messages owned by the user

What is retained (and why):

- Organisation-scoped batches, issues, and analysis history remain under the organisation's control — they may be relied on by other members and are not tied to the deleted user's identity
- Audit log entries about the user are kept for compliance (they store the acting user ID at the time of the action, not personal data)

If the user is the sole admin of an organisation, the request is rejected until admin is transferred or the organisation itself is deleted via `DELETE /api/organisation/delete/{id}/`. This prevents accidental orphaning of shared data.

See [Delete Account](../api/authentication.md#delete-account-gdpr-right-to-erasure) in the API reference.

!!! note "Data Location"
    SerOps stores data in your configured PostgreSQL instance and (optionally) the log/metric providers you connect. You control where your data resides.
