---
seo_title: "Multi-tenancy and data isolation"
description: "How SerOps isolates organisations across API queries, logs, metrics and CI/CD events, and the guarantees behind it."
---
# Multi-Tenancy & Data Isolation

SerOps enforces strict data isolation between organisations. This page details the isolation layers across every data path -- from API queries and log storage to metrics and CI/CD events -- along with the infrastructure components and security guarantees that underpin the multi-tenant architecture.

---

## Isolation Layers

| Layer | Mechanism | Implementation |
|-------|-----------|----------------|
| **API Queries** | `OrgFilterMixin` | All batch/issue queries filter by `project__organisation` |
| **Logs** | Per-organisation integration | Each organisation queries its own log provider with its own credentials; records are filtered by `project_name` and `environment` |
| **Metrics** | Label filter | Queries select `organisation_name` (the organisation's name), `project_name` and `environment` |
| **Code Changes** | Direct FK | `CodeChange` has a direct `organisation` FK for multi-tenancy filtering |
| **CI/CD Logs** | Enriched Event | Flat `organisation_name` + `project_name` fields, and `serops_meta.org_id` + `serops_meta.project_id`, in the event document |

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

> **Note:** Label keys (e.g., `organisation_name`, `environment`) are provider-dependent. The example below uses Prometheus-style labels; other providers (Datadog, CloudWatch, etc.) may use different key conventions.

```python
provider = IntegrationRegistry.get_metric_provider_for_org(organisation)
ts = provider.query_range(
    'node_memory_MemTotal_bytes',
    labels={'organisation_name': 'Acme Corp', 'environment': 'production', 'project_name': 'demo'},
    start=start_time, end=end_time,
)
```

## Security Guarantees

| Guarantee | Enforcement |
|-----------|-------------|
| User A cannot see Org B's batches | `project__organisation=user_org` filter |
| User A cannot access Org B's integrations | `organisation` FK on ProviderIntegration |
| No bypass for operators | Superusers and staff are held to their own organisation in the API like everyone else. Install-wide operations go through platform permissions (see [Permissions](../development/permissions.md)) |
| Every endpoint is checked | `Middlewares/tests/test_tenant_coverage.py` calls every API route as another organisation's admin and as its superuser; a new route with an id fails until it is covered |

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
- [Permissions](../development/permissions.md) -- What each role may do, and how every endpoint declares it
- [Admin Settings](../admin/settings.md) -- Organisation-level configuration
- [Metrics](../user-guide/metrics.md) -- User-facing metrics with org-scoped data
