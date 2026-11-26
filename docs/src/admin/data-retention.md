---
seo_title: "Data retention"
description: "Set batch intervals, automatic cleanup of old batches and audit-log retention in SerOps."
---
# Data Retention

Configure batch generation intervals, automatic cleanup policies, and audit log retention.

## Batch Generation Interval

**Location**: Settings → Data retention → Batch Generation Interval

Controls how frequently SerOps collects logs, metrics, traces, and other data sources to create analysis batches. Each organisation can set its own interval independently.

| Interval | Use Case |
|----------|----------|
| 5 min | High-traffic production — fastest anomaly detection |
| 10 min | Real-time monitoring for critical services |
| **15 min** | **Default (Recommended)** — good balance of speed and cost |
| 20 min | Standard monitoring |
| 30 min | Lower-traffic or cost-conscious environments |
| 45 min | Minimal monitoring |
| 1 hour | Low-priority or development-only orgs |
| 2 hours | Low-traffic staging or internal tools |
| 4 hours | Dev environments with periodic review |
| 6 hours | Cost-conscious orgs, batch-oriented review |
| 12 hours | Minimal monitoring — twice daily analysis |

!!! tip "Choosing an interval"
    Lower intervals mean faster anomaly detection but higher resource usage (more Celery tasks, more Elasticsearch queries, more AI analysis calls). Start with the default of **15 minutes** and adjust based on your needs.

!!! info "Extended intervals (2–12 hours)"
    Longer intervals reduce AI analysis costs and resource usage, making them ideal for staging environments, internal tools, or low-traffic services. Each batch will cover a larger time window, so individual batches may contain more data.

### How to configure

1. Go to **Settings → Data retention**
2. Open the **Batch Generation Interval** section
3. Select the desired interval (5 minutes to 12 hours)
4. Click **Save**

The new interval takes effect within 1 minute. Existing in-progress batches are not affected.

---

## Retention Policy

**Location**: Settings → Data retention → Retention Policy

| Setting | Description |
|---------|-------------|
| **Auto-Cleanup** | Enable/disable automatic deletion. **Off by default** |
| **Retention Period** | How long to keep batches |
| **Frequency** | When cleanup runs |

---

## Retention Options

| Period | Use Case |
|--------|----------|
| 7 days | High volume, limited storage |
| 14 days | Standard short-term |
| 30 days | **Default** - Good balance |
| 60 days | Extended analysis |
| 90 days | Quarterly review |
| 180 days | Semi-annual |
| 365 days | Annual compliance |

---

## Cleanup Frequency

A cleanup check runs every hour. It runs the cleanup when enough time has passed since the last one, so the frequency is counted from the last run, not from a time of day:

| Frequency | Runs when the last cleanup is older than |
|-----------|------|
| Daily | 23 hours |
| Weekly (**default**) | 6.5 days |
| Monthly | 29 days |

When no cleanup has run yet, the first check runs it at once.

---

## Audit Log Retention

Separate setting for compliance logs. No screen has a control for it: set it through the API, `PUT /api/data/settings/retention-policy/` with `audit_log_retention_days` (`30`, `90`, `365`, or `0` for forever).

| Period | Description |
|--------|-------------|
| 30 days | Short-term |
| 90 days | Quarterly (**default**) |
| 365 days | Annual |
| Forever | Never delete |

!!! warning "Audit-log retention runs only with Auto-Cleanup on"
    Old audit-log entries are deleted by the same cleanup run as old
    batches, on the same **Frequency**. While **Auto-Cleanup** is off,
    which is the default, nothing is deleted: neither batches nor audit
    logs, whatever retention period is set.

---

## Manual Cleanup

For immediate cleanup:

1. Go to **Settings → Data retention → Manual Cleanup**
2. In **Delete Batches Older Than**, choose 1, 3, 7, 14, 30 or 60 days
3. Click **Delete Now**
4. Confirm

---

## What Gets Deleted

| Data | Deleted | Preserved |
|------|---------|-----------|
| Batch data | ✅ | - |
| Issues | ✅ | - |
| Logs | ✅ | - |
| Redaction reports | ✅ | - |
| Audit logs | Separate period, same cleanup run (needs Auto-Cleanup on) | - |
