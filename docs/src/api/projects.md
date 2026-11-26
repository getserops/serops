---
seo_title: "Projects and services API"
description: "API endpoints for SerOps projects, services and their source-control and CI/CD bindings."
---
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

Returns details for a single project, including its services, `access_mode` (`organisation` or `restricted`) and `permissions`: what the caller may do on this project (team grants can give more than the organisation role, a restricted project less). The project list carries the same fields. Projects the caller can't see are left out of lists and answer `404`.

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

### Project Access (Enterprise)

```
GET /api/ee/projects/{id}/access/
PUT /api/ee/projects/{id}/access/
```

Who sees the project. Available when the Enterprise directories are installed. Restricting a project, or adding or raising a grant, needs the *Per-project access* license feature (`403` with `"code": "enterprise_license_required"` otherwise); opening a project and lowering or removing grants never does. `GET` needs `project.read` on it; `PUT` needs `team.manage` and the admin permissions on this project (organisation admins have them on every project).

```json
{
  "access_mode": "restricted",
  "grants": [{ "team_id": 3, "role": "user" }]
}
```

`access_mode`: `organisation` (every member, their role applies) or `restricted` (only the teams in `grants`, and organisation admins). `role` is the team's role on this project: `viewer`, `user` or `admin`. Grants add to what members' organisation roles allow, on either mode. `grants` replaces the list. Changes are audited (`PROJECT_ACCESS_CHANGE`).

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
  "project_service": 1,
  "integration": 3,
  "repository_id": "123456",
  "repository_name": "owner/repo",
  "repository_url": "https://github.com/owner/repo",
  "default_branch": "main"
}
```

`project_service` is the service's id, `integration` the id of a source-control
integration from Settings → Integrations (it holds the token; a binding has
none of its own), and `repository_id` the provider's id for the repository
(GitHub and GitLab: the numeric id; Bitbucket and Azure DevOps: as the
integration's repository list returns it).

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
  "suggestion_ids": ["job/build-main"]
}
```

`suggestion_ids` lists the `pipeline_id` values of the suggestions to link. Without it, a binding is created for every suggestion. Creates the CI/CD bindings in one call. Skips having to call `POST /api/projects/cicd-bindings/` separately.

### Set Up SCM Webhook

```
POST /api/projects/scm-bindings/{id}/setup-webhook/
```

Registers a repository webhook on the linked SCM provider that points back at `/api/webhooks/scm/{binding_id}/`. Uses the credentials stored on the parent ProviderIntegration.

### Sync SCM Binding

```
POST /api/projects/scm-bindings/{id}/sync/
```

Syncs commits from the SCM provider: the last 7 days on the first sync, then everything since `last_sync_at`. Also refreshes `last_sync_at`.

### Create CI/CD Binding

```
POST /api/projects/cicd-bindings/
```

**Request body:**

```json
{
  "project_service": 1,
  "integration": 4,
  "binding_type": "build",
  "pipeline_id": "build-main",
  "pipeline_name": "Build main",
  "auto_trigger": true,
  "trigger_branches": ["main"]
}
```

`project_service` is the service ID and `integration` the ID of a CI/CD [provider integration](integrations.md) (GitLab, GitHub, Azure DevOps, Jenkins, Bitbucket, Argo CD or Flux). `binding_type` is `build` (default), `deploy`, `test` or `release`. `pipeline_name`, `pipeline_url`, `auto_trigger` and `trigger_branches` are optional.

### Trigger Build

```
POST /api/projects/cicd-bindings/{id}/trigger/
```

**Request body:**

```json
{
  "parameters": {"BRANCH": "main"}
}
```

Triggers a new build of the binding's `pipeline_id`. Jenkins only; other providers return `400`. `parameters` is optional and holds the Jenkins job's own build parameters.

### Set Up CI/CD Webhook

```
POST /api/projects/cicd-bindings/{id}/setup-webhook/
```

Registers a pipeline webhook that points back at the provider-specific SerOps handler under `/api/webhooks/{provider}/{binding_id}/`. Idempotent — running it again updates the existing webhook. For Argo CD and Flux it registers nothing: it returns `manual_setup: true`, the `webhook_url` (`/api/providers/webhook/argocd/{binding_id}/` or `/api/providers/webhook/flux/{binding_id}/`) and the `webhook_secret` to configure on the controller.

### Sync CI/CD Binding

```
POST /api/projects/cicd-bindings/{id}/sync/
```

Refreshes recent pipeline runs, job status, and deployment events for this binding.

### Health Check (All Bindings)

```
POST /api/providers/integrations/health-check-all/
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
