---
seo_title: "Users, roles and teams"
description: "Invite users, give them built-in or custom roles, group them in teams and keep projects to the teams that work on them."
---
# Users, Roles and Teams

Three pages under **Settings** control who can do what, the same split as Grafana:

| Page | What it is for |
|------|----------------|
| **Users** | Invite people, change their role, remove them |
| **Roles** | The built-in roles, and custom roles built from individual permissions |
| **Teams** | Groups of users that restricted projects are opened to |

Only users with the `team.manage` permission (admins, by default) see these pages.

---

## Users

### Invite a user

1. Go to **Settings → Users** and click **Invite User**.
2. Enter the email address.
3. Choose a role: Viewer, User, Admin, or one of your [custom roles](#custom-roles).
4. Click **Send Invitation**.

Only the email and role are required; people complete their profile on first sign-in.

The invitation email has a link to set a password. When [single sign-on](../security/authentication.md#single-sign-on-sso) is on, the invited user can instead click **Log in with SSO** on the sign-in page. People of [email domains you list](../security/authentication.md#who-can-sign-in) don't need an invitation at all: their account is created at their first SSO sign-in.

### Change a role

Click the edit button on the user's row, pick the new role and save. The user's permissions change straight away; the app picks up the new list the next time it loads.

When SSO roles are set to update at every sign-in, the Users page says so: a role changed here is replaced at the user's next SSO sign-in, so change their groups in the identity provider instead.

### Remove a user

Click the delete button on the user's row and confirm. Removed users lose access immediately; their audit history is kept.

!!! note "Guardrails"
    - An admin can change a user's name, phone and role, but not their email: email is the sign-in identity, and users change it in their own profile.
    - The last admin of an organisation can't be demoted or removed: make someone else admin first.
    - You can only give a role, or change or remove a user, whose permissions you hold yourself (see [No escalation](#no-escalation)).

---

## Roles

Roles add up: a user can do everything a viewer can, an admin everything a user can. Each row is one named permission; the API checks that name on every request.

| Permission | What it allows | Viewer | User | Admin |
|------------|----------------|:------:|:----:|:-----:|
| `self.manage` | Your own profile, password, photo, notifications, preferences, chat sessions; delete your account | ✓ | ✓ | ✓ |
| `org.read` | Organisation name, logo, capabilities, setup status | ✓ | ✓ | ✓ |
| `project.read` | Projects, services, bindings, deployments | ✓ | ✓ | ✓ |
| `batch.read` | Analyses, logs, metrics, traces, timelines, code changes, dashboards | ✓ | ✓ | ✓ |
| `issue.read` | Issues and their details | ✓ | ✓ | ✓ |
| `integration.read` | The list of integrations, log/metric sources and clusters (never their secrets) | ✓ | ✓ | ✓ |
| `alerting.read` | The list of delivery channels (never their secrets) | ✓ | ✓ | ✓ |
| `chat.use` | Ask AI Chat about existing analyses | ✓ | ✓ | ✓ |
| `issue.update` | Resolve, mute, reopen, acknowledge issues | | ✓ | ✓ |
| `batch.analyze` | Run analyses, re-analyses, investigations and post-mortems (spends the AI budget) | | ✓ | ✓ |
| `project.write` | Create and edit projects, services, bindings, deployments; set up webhooks; the setup flow | | ✓ | ✓ |
| `integration.use` | Verify, sync and health-check existing integrations | | ✓ | ✓ |
| `settings.read` | Read security, SSO, retention, data usage and AI budget settings | | ✓ | ✓ |
| `project.delete` | Delete projects and services | | | ✓ |
| `integration.manage` | Add, edit, delete or test integrations, log/metric sources, clusters and trace ingest keys (they hold credentials) | | | ✓ |
| `alerting.manage` | Delivery channels, routing and escalation rules, the alert ingest secret | | | ✓ |
| `settings.manage` | Organisation info and settings, AI providers and keys, Sentinel, retention, data deletion | | | ✓ |
| `team.manage` | Users, roles, teams and the audit log | | | ✓ |

With single sign-on, roles can come from your identity provider's groups: see [Roles from your identity provider's groups](../security/authentication.md#roles-from-your-identity-providers-groups).

### Custom roles

!!! info "SerOps Enterprise"
    Creating, editing and handing out custom roles needs an [Enterprise
    license](../license.md#enterprise-code-ee-directories) with *Custom roles*.
    Without it, custom roles that exist keep working for the users who have
    them; you can move those users to a built-in role and delete unused roles.

When the built-in roles don't fit, build your own in **Settings → Roles** from the permissions above, for example *On-call* (resolve issues, re-run analyses) or *Auditor* (Viewer plus the audit log). Assign it in **Settings → Users** like any role, or from an identity-provider group.

- Every custom role can manage its own account and see the organisation (`self.manage`, `org.read`), and a permission brings the one it needs: `batch.analyze` adds `batch.read`. The form shows both as locked.
- Editing a role changes what its users can do straight away.
- A role still given to a user, or named by an SSO rule, can't be deleted.
- Viewer, User and Admin can't be changed. Escalation targets and the last-admin rule concern the built-in **Admin** role.

### Platform permissions

Three permissions touch state shared by every organisation on the install, so no organisation role grants them:

| Permission | What it allows | Who holds it |
|------------|----------------|--------------|
| `ai_catalogue.manage` | Add, edit or delete providers in the AI provider catalogue | Platform staff (`is_staff`), or the admin of an install with a single organisation |
| `platform.manage` | Install-wide operations, such as tripping or resetting AI circuit breakers | Platform staff |
| `license.manage` | Install or remove the [Enterprise license key](../license.md#enterprise-code-ee-directories) | Platform staff (`is_staff`), or the admin of an install with a single organisation |

Organisation admins always set their own organisation's AI key and base URL.

---

## Teams and project access

Teams are part of SerOps Community, including filling them from SSO groups.
Restricting projects to teams and giving teams a role on a project is
SerOps Enterprise (*Per-project access*):

!!! info "SerOps Enterprise"
    Without the license, restrictions that exist keep applying, and you can
    still lower or remove a team's access and open a project to the whole
    organisation. On an install without the `ee/` directories,
    `python manage.py project_access_open --project ID` (or
    `--organisation ID --all`) opens restricted projects again; organisation
    admins see every project in the meantime.

By default every user sees every project, with their role. To keep a project to the people who work on it:

1. Create teams in **Settings → Teams** and add users (or let SSO groups fill them: see [Teams from your identity provider's groups](../security/authentication.md#teams-from-your-identity-providers-groups)).
2. Open the project, **Access** tab: choose **Only teams given access**, add teams and give each a role on this project (Viewer, User or Admin), then save.

How it works:

- On a restricted project, only its teams (and organisation admins) see it: its services, analyses, issues, investigations, dashboards, notifications and AI Chat context. Everyone else gets "not found", and it disappears from their lists.
- A team's role applies to that project only and adds to its users' organisation role: a Viewer whose team is User on *payments* can resolve *payments* issues and run its analyses, and stays a Viewer everywhere else. Grants also work on open projects, to give a team more there.
- Project buttons follow what you may do on each project (the API sends your permissions per project).
- Creating projects needs the organisation role: a grant on one project doesn't let you create others.
- Project-level permissions: `project.read`, `project.write`, `project.delete`, `batch.read`, `batch.analyze`, `issue.read`, `issue.update`. Everything else (settings, integrations, alerting, users) stays organisation-wide.
- Organisation admins see every project and manage access. A project's admins (through a team) who hold `team.manage` can change its access too.
- Users subscribed to a project they can no longer see stop receiving its notifications.
- Distributed traces are organisation-wide telemetry with no project link, so restrictions don't apply to them.

---

## No escalation

Nobody can hand out more than they hold. Whoever manages users, roles or teams through a custom role:

- can only give a role, or create and edit a role, whose permissions they hold;
- can't change or remove a user who holds permissions they lack;
- can only change a team, or grant a project role, if they hold that access on those projects;
- can only map SSO groups to roles and teams within their own permissions.

Organisation admins hold every organisation permission, so these checks never stop them.

---

## How it is enforced

- Every API endpoint declares the permission each method needs. Anything it doesn't declare is refused (`403`), so a new endpoint can't ship open by mistake: a test fails the build when an endpoint declares nothing.
- Project-scoped data is filtered by project access on every route; another test walks every route as a user outside a restricted project.
- Users only ever see their own organisation's data, whatever their role, superusers included (see [Multi-Tenancy](../architecture/multi-tenancy.md)).
- The app hides the buttons and settings pages you can't use, from the permission list the server sends at sign-in (`permissions` in the [profile](../api/authentication.md#get-profile)).

---

## Audit trail

Everything on these pages is in **Settings → Audit Log**:

| Action | Log entry |
|--------|-----------|
| Invite a user | `TEAM_INVITE` |
| Change a role (in SerOps, or from SSO with `source: sso`) | `TEAM_ROLE_CHANGE` |
| Remove a user | `TEAM_REMOVE` |
| Account created by SSO / SSO sign-in refused | `SSO_PROVISION` / `SSO_DENIED` |
| Custom role created, changed, deleted | `ROLE_CREATE`, `ROLE_UPDATE`, `ROLE_DELETE` |
| Team created, changed (also SSO membership changes), deleted | `TEAM_CREATE`, `TEAM_UPDATE`, `TEAM_DELETE` |
| Project access changed | `PROJECT_ACCESS_CHANGE` |
| Request refused for a missing permission | `ACCESS_DENIED` |
