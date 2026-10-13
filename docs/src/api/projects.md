# Projects & Services API

Endpoints for managing projects, services, and integration bindings (SCM and CI/CD).

## Projects

### List Projects

```
GET /api/projects/
```

Returns all projects accessible to the authenticated user's organisation.

### Create Project

```
POST /api/projects/
```

**Request body:**

```json
{
  "name": "my-project",
  "description": "Optional description"
}
```

### Get Project

```
GET /api/projects/{id}/
```

Returns details for a single project, including its services.

### Update Project

```
PUT /api/projects/{id}/
```

**Request body:**

```json
{
  "name": "new-name"
}
```

### Delete Project

```
DELETE /api/projects/{id}/
```

---

## Services

Services belong to a project and represent individual deployable components.

### List Services

```
GET /api/projects/{project_id}/services/
```

Returns all services within the specified project.

### Add Service

```
POST /api/projects/{project_id}/services/
```

**Request body:**

```json
{
  "service_type": "application",
  "name": "my-service"
}
```

### Delete Service

```
DELETE /api/projects/services/{service_id}/
```

### Custom (Infra) Services

```
GET /api/projects/{project_id}/custom-services/
POST /api/projects/{project_id}/custom-services/
```

Lists and creates project-local infrastructure services that aren't tied to an SCM/CI-CD binding — e.g. a database, a message broker, or a managed cache. Useful for tracking dependencies you want the AI to correlate against but don't have code for.

---

## Integration Bindings

Bindings link a service to an external SCM or CI/CD provider. Each service can have one SCM binding and multiple CI/CD bindings.

### List SCM Bindings

```
GET /api/projects/scm-bindings/
```

Returns all SCM bindings for the organisation.

### Create SCM Binding

```
POST /api/projects/scm-bindings/
```

**Request body:**

```json
{
  "service": 1,
  "provider_type": "github",
  "repository": "owner/repo",
  "access_token": "glpat-..."
}
```

### Auto-Link Suggestions

```
GET /api/projects/scm-bindings/{id}/auto-link-suggestions/
```

Returns detected CI/CD pipelines in the repository. Use this to discover available pipelines before creating a CI/CD binding.

### Auto-Link a Pipeline

```
POST /api/projects/scm-bindings/{id}/auto-link/
```

**Request body:**

```json
{
  "pipeline_id": "job/build-main"
}
```

Creates the CI/CD binding for the suggested pipeline in one call. Skips having to call `POST /api/projects/cicd-bindings/` separately.

### Set Up SCM Webhook

```
POST /api/projects/scm-bindings/{id}/setup-webhook/
```

Registers a repository webhook on the linked SCM provider that points back at `/api/webhooks/scm/{binding_id}/`. Uses the credentials stored on the parent ProviderIntegration.

### Sync SCM Binding

```
POST /api/projects/scm-bindings/{id}/sync/
```

Pulls the latest branch list and repository metadata for this binding. Also refreshes `last_sync_at`.

### Create CI/CD Binding

```
POST /api/projects/cicd-bindings/
```

**Request body:**

```json
{
  "service": 1,
  "provider_type": "jenkins",
  "pipeline_id": "job/build-main",
  "base_url": "https://jenkins.example.com"
}
```

### Trigger Build

```
POST /api/projects/cicd-bindings/{id}/trigger/
```

**Request body:**

```json
{
  "branch": "main"
}
```

Triggers a new build on the linked CI/CD pipeline.

### Set Up CI/CD Webhook

```
POST /api/projects/cicd-bindings/{id}/setup-webhook/
```

Registers a pipeline webhook that points back at the provider-specific SerOps handler under `/api/webhooks/{provider}/{binding_id}/`. Idempotent — running it again updates the existing webhook.

### Sync CI/CD Binding

```
POST /api/projects/cicd-bindings/{id}/sync/
```

Refreshes recent pipeline runs, job status, and deployment events for this binding.

### Health Check (All Bindings)

```
GET /api/providers/integrations/health-check-all/
```

Runs a connectivity check against all configured integration bindings and returns their status.

---

## Deployments

A **ProjectDeployment** is one instance of "where a project runs" — the composed shape (environment × cluster × region × namespace). The batch pipeline runs once per active deployment, so multi-region and multi-cluster projects get analysed independently per copy.

A default deployment is auto-created for each active environment (via a Django post-save signal). Add more here when you have parallel deployments in different regions, clusters, or K8s namespaces.

### List Deployments

```
GET /api/projects/deployments/?project={project_id}
```

Returns all deployments the caller can see (filtered to their organisation). Pass `?project=` to filter to one project.

**Response element:**

```json
{
  "id": 42,
  "project": 7,
  "environment": 3,
  "environment_name": "production",
  "environment_display_name": "Production",
  "cluster": 12,
  "cluster_name": "prod-eks",
  "cluster_provider": "AWS EKS",
  "region": "us-east-1",
  "namespace": "payments",
  "name": "checkout · prod-eks · us-east-1 · ns=payments",
  "is_active": true,
  "created_at": "…",
  "updated_at": "…"
}
```

### Create Deployment

```
POST /api/projects/deployments/
```

**Request body:**

```json
{
  "project": 7,
  "environment": 3,
  "cluster": 12,
  "region": "us-east-1",
  "namespace": "payments",
  "is_active": true
}
```

**Invariants:**
- `namespace` may only be set when `cluster` is set (DB `CheckConstraint`).
- `(project, environment, cluster, region, namespace)` must be unique.
- `(project, name)` must be unique. If `name` is omitted the model composes one from the four dimensions on save.

### Update / Delete Deployment

```
PATCH  /api/projects/deployments/{id}/
DELETE /api/projects/deployments/{id}/
```

Deleting a deployment stops the batch pipeline for that shape. Existing batches keep their history but no new ones are created.

### Suggest Deployments for a New Cluster

```
GET /api/projects/deployments/suggest/?cluster={cluster_id}
```

Returns proposed deployments for a newly-registered cluster — one per (project × active environment) that could plausibly live on it. The frontend presents these as a modal so the user accepts individual rows rather than auto-creating dozens.

---

## Related

- [Integrations](integrations.md) -- Global SCM/CI-CD provider management
- [Observability](observability.md) -- Log and metric provider connections
- [API Overview](overview.md) -- Base URL, response format, and error codes
