# Multi-Tenancy & Data Isolation

SerOps enforces strict data isolation between organisations. This page details the isolation layers across every data path -- from API queries and log storage to metrics and CI/CD events -- along with the infrastructure components and security guarantees that underpin the multi-tenant architecture.

---

## Isolation Layers

| Layer | Mechanism | Implementation |
|-------|-----------|----------------|
| **API Queries** | `OrgFilterMixin` | All batch/issue queries filter by `project__organisation` |
| **Logs** | LogStream | Routing via `org_slug` to provider-specific isolation (Index/Label/Tag) |
| **Metrics** | Series ID Filter | Prometheus labels include `org_id` |
| **Code Changes** | Direct FK | `CodeChange` has a direct `organisation` FK for multi-tenancy filtering |
| **CI/CD Logs** | Enriched Event | `serops_meta.org_id` + `serops_meta.project_id` in event document |

## OrgFilterMixin Pattern

All data views inherit from `OrgFilterMixin`:

```python
class LogBatchView(OrgFilterMixin, APIView):
    def get(self, request):
        # Automatically filtered to user's organisation
        batches = self.get_user_batches(request)
```

## Metrics Isolation

Metrics are fetched from the organisation's configured MetricProvider with label-based filtering:

> **Note:** Label keys (e.g., `org_id`, `environment`) are provider-dependent. The example below uses Prometheus-style labels; other providers (Datadog, CloudWatch, etc.) may use different key conventions.

```python
provider = IntegrationRegistry.get_metric_provider_for_org(organisation)
ts = provider.query_range(
    'node_memory_MemTotal_bytes',
    labels={'org_id': 'acme-corp', 'environment': 'production', 'project_id': 'demo'},
    start=start_time, end=end_time,
)
```

## Security Guarantees

| Guarantee | Enforcement |
|-----------|-------------|
| User A cannot see Org B's batches | `project__organisation=user_org` filter |
| User A cannot access Org B's integrations | `organisation` FK on ProviderIntegration |
| Superuser bypass | Explicit `is_superuser` check, audited |

---

## Infrastructure

### Additional Components (not shown in main diagram)

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Celery Beat** | Celery scheduler | Periodic batch creation, deployment sync |

---

## Related Pages

- [System Overview](overview.md) -- High-level architecture and environment isolation concepts
- [Data Model](data-model.md) -- Core schema and provider integration model
- [Authentication](../security/authentication.md) -- Auth flows and token policies
- [Data Protection](../security/data-protection.md) -- Redaction and PII handling
- [Compliance](../security/compliance.md) -- Compliance and auditing details
- [Admin Team Management](../admin/team.md) -- Managing organisation members
- [Admin Settings](../admin/settings.md) -- Organisation-level configuration
- [Metrics](../user-guide/metrics.md) -- User-facing metrics with org-scoped data
