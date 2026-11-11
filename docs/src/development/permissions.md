---
seo_title: "Permissions for contributors"
description: "How SerOps declares and checks permissions: the catalogue, Requires on every API view, the deny-by-default coverage test, and the UI permission list."
---
# Permissions

SerOps' access model follows Airflow and Grafana: named permissions (`resource.action`), roles that add up (viewer < user < admin), and a platform level above organisation roles. Users see the result on [Users, roles and teams](../admin/team.md#roles). This page is for people adding endpoints or UI.

Everything lives in one file, `backend/Middlewares/rbac.py`:

| Name | What it is |
|------|------------|
| `PERMISSIONS` | Every permission, with what it covers. |
| `ROLE_PERMISSIONS` | Which role holds which permission. Roles add up. |
| `PLATFORM_PERMISSIONS` | Permissions no organisation role grants (`ai_catalogue.manage`, `platform.manage`, `license.manage`). |
| `role_permissions(user)` | What the organisation role grants: built-in, or the user's `CustomRole`. |
| `normalise_permissions(codes)` | A custom role's list: validated, plus `ALWAYS_GRANTED` and `IMPLIES` prerequisites. |
| `can_grant(actor, codes)` | No escalation: true when the actor holds every code. Every place that hands out a role checks it (team invite/update, role create/edit/delete, SSO rules). |
| `role_key(user)`, `resolve_role_key(org, key)` | One string per role: `viewer`, `user`, `admin`, `custom:<id>`. |
| `has_permission(user, code)` | The one check. Raises on an unknown name. |
| `get_user_permissions(user)` | The sorted list sent to the UI. |
| `Requires(...)` | The DRF permission class views declare. |

## Declaring what a view needs

Every API view lists `Requires` next to `IsAuthenticated`, keyed by HTTP method or viewset action:

```python
from Middlewares.rbac import Requires

class ProjectDetailView(APIView):
    permission_classes = [IsAuthenticated, Requires(GET='project.read', PUT='project.write', DELETE='project.delete')]

class ObservabilityIntegrationViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, Requires(
        list='integration.read', retrieve='integration.read',
        health_check='integration.use',          # a custom @action, by method name
        default='integration.manage')]           # create, update, destroy, ...
```

Rules:

- A viewset action wins over the HTTP method; `HEAD` and `OPTIONS` follow `GET`; `default` covers the rest.
- A method or action that matches nothing is **denied**, even for admins, and logged.
- A method the view doesn't implement still answers `405`.
- An unknown permission name fails at import time, so typos don't reach production.
- Don't check `request.user.role` in a view. If no permission fits, add one to `PERMISSIONS` and `ROLE_PERMISSIONS`, then to the table on [Users, roles and teams](../admin/team.md#roles).

Permissions decide *what* a user can do. *Which rows* they see is separate: every queryset filters by `request.user.organisation`, with no exception for superusers or staff (see [Multi-Tenancy](../architecture/multi-tenancy.md)). The tenant coverage test below checks it.

A refused request is written to the organisation's audit log as `ACCESS_DENIED` (once per user, method and path every 10 minutes).

## The coverage test

`backend/Middlewares/tests/test_permission_coverage.py` walks every route under `/api/` and fails when:

- a view has no `Requires(...)`,
- a method or viewset action it implements isn't covered, or
- a view uses `AllowAny` without being listed as public.

Public endpoints (login, registration, password reset, SSO, webhook receivers, OTLP ingest, health) authenticate another way: a token, a signature, a secret. They are listed in `PUBLIC` in that test with how they authenticate. Adding to that list is a security decision; say why in the review.

`Middlewares/tests/test_role_matrix.py` checks representative endpoints as each role through the API.

## The tenant coverage test

`backend/Middlewares/tests/test_tenant_coverage.py` seeds one organisation with an object of every kind, all named with a marker, then calls every API route as the admin of a second organisation, and again as its superuser:

- Routes without an id (lists, dashboards, settings) must not return the marker, with or without the first organisation's ids in the usual query parameters.
- Routes with an id are filled with the first organisation's object (`TARGETS`). Every method must fail; a 2xx on a write, or the marker in a read, is a leak.
- No route may answer 5xx.

A new route with an id fails until it is added to `TARGETS` with the object it takes, or marked shared with a reason (the AI provider catalogue, platform circuit breakers). Outbound HTTP and Celery are stubbed during the walk.

## Per-project access

`backend/Middlewares/project_access.py` adds teams and restricted projects on top of the role:

| Name | What it is |
|------|------------|
| `PROJECT_SCOPED` | The seven permissions that depend on the project. |
| `project_permissions(user, project)` | What the user holds on one project: organisation role (unless restricted) + team grants; organisation admins hold all. |
| `scope(queryset, user, code, field='project')` | Filter rows to projects where the user holds `code`. Unchanged for organisations with no restricted project and no grant. |
| `ProjectScoped` | View mixin: `self.scoped(qs, field)` scopes by the permission `Requires` declares for the request. |
| `scope_request(view, request, qs, read, writes)` | Same, for views not using the mixin. |
| `can_on_project`, `can_grant_project_role`, `can_manage_team` | Object checks and the no-escalation guards. |

`Requires` lets a project-scoped request through when *any* team grant holds the permission, so **every view that touches project data must scope its queryset by the request's permission**: reads by `*.read`, writes by `project.write`, `batch.analyze`, `issue.update`... Scoping writes by the read permission would let a grant on one project write another. Actions not tied to an existing project (creating a project) check the organisation role (`org_level`).

### The project-scope walker

`Middlewares/tests/test_project_scope_coverage.py` reuses the tenant walker inside one organisation: a member outside a restricted project calls every route (no marker in lists, every method on its ids fails), and a Viewer whose team is User on it checks reads succeed and writes are allowed there only. Both walkers authenticate with real tokens: dashboard responses are cached per `Authorization` header.

## Ids in request bodies

The walkers send empty bodies. `Middlewares/tests/test_body_relations.py` builds every serializer for a requester and fails on a writable relation (an id in the body) whose queryset isn't limited, unless it is listed with why. Limit one with `limit_relations(fields, request, project=lambda user, org: ...)` in `get_fields`.

## In the UI

The login and profile responses carry `user.permissions`. The frontend reads it through `frontend/src/utils/permissions.js` and keeps no copy of the role table:

```jsx
import { usePermissions } from '../utils/permissions';

const can = usePermissions();
{can('project.delete') && <Button variant="danger">Delete</Button>}
```

`can(code)` reads the stored list directly, for code outside React components. For project controls use `canOnProject(project, code)`: project responses carry the caller's `permissions` on that project. The sidebar calls `refreshPermissions()` when the app loads, so role changes take effect without signing out. Hiding a control is a convenience; the API enforces every permission either way.
