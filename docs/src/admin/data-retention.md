# Data Retention

Configure batch generation intervals, automatic cleanup policies, and audit log retention.

## Batch Generation Interval

**Location**: Settings → Data Management → Batch Generation Interval

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

1. Go to **Settings → Data Management**
2. Open the **Batch Generation Interval** section
3. Select the desired interval (5 minutes to 12 hours)
4. Click **Save**

The new interval takes effect within 1 minute. Existing in-progress batches are not affected.

---

## Retention Policy

**Location**: Settings → Data Management → Retention Policy

| Setting | Description |
|---------|-------------|
| **Auto-Cleanup** | Enable/disable automatic deletion |
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

| Frequency | When |
|-----------|------|
| Daily | Midnight UTC |
| Weekly | Sunday midnight |
| Monthly | 1st of month |

---

## Audit Log Retention

Separate setting for compliance logs:

| Period | Description |
|--------|-------------|
| 30 days | Short-term |
| 90 days | Quarterly |
| 365 days | Annual |
| Forever | Never delete |

---

## Manual Cleanup

For immediate cleanup:

1. Go to **Data** page
2. Select batches to delete
3. Click **Delete Selected**
4. Confirm

---

## What Gets Deleted

| Data | Deleted | Preserved |
|------|---------|-----------|
| Batch data | ✅ | - |
| Issues | ✅ | - |
| Logs | ✅ | - |
| Redaction reports | ✅ | - |
| Audit logs | Separate policy | - |
