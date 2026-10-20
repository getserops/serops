---
seo_title: "Team management and roles"
description: "Invite users, assign admin, user and viewer roles, and manage access to your SerOps organisation."
---
# Team Management

Manage users, roles, and permissions within your organization.

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
| `team.manage` | Invite and remove members, change roles, audit log | | | ✓ |

An admin can't change a member's email (members change their own), and the last admin can't be demoted or removed.

### Platform permissions

Two permissions touch state shared by every organisation on the install, so no organisation role grants them:

| Permission | What it allows | Who holds it |
|------------|----------------|--------------|
| `ai_catalogue.manage` | Add, edit or delete providers in the AI provider catalogue | Platform staff (`is_staff`), or the admin of an install with a single organisation |
| `platform.manage` | Install-wide operations, such as tripping or resetting AI circuit breakers | Platform staff |

Organisation admins always set their own organisation's AI key and base URL.

### How it is enforced

- Every API endpoint declares the permission each method needs. Anything it doesn't declare is refused (`403`), so a new endpoint can't ship open by mistake: a test fails the build when an endpoint declares nothing.
- Refused requests appear in **Settings → Audit Log** as **Access Denied**, with the permission that was missing.
- Members only ever see their own organisation's data, whatever their role, superusers included (see [Multi-Tenancy](../architecture/multi-tenancy.md)).
- The app hides the buttons and settings pages you can't use, from the permission list the server sends at sign-in (`permissions` in the [profile](../api/authentication.md#get-profile)). A role change takes effect the next time the app loads.

---

## Inviting Users

1. Go to **Settings → Team**
2. Click **+ Invite User**
3. Enter email address
4. Select role (Viewer, User, or Admin)
5. Click **Send Invitation**

> **Simplified Flow**: Only email and role are required. Users complete their profile on first login.

### Invitation Flow

**Standard (No SSO):**

1. User receives email with invitation link
2. User clicks link → sets password → completes profile (name, phone)
3. User gains access with assigned role

**With SSO/LDAP Integration:**

1. User receives email with invitation link
2. User clicks link → redirects to SSO provider
3. Profile data (name, email) auto-populates from identity provider
4. User gains access with assigned role

---

## Managing Users

### Change Role

1. Find user in team list
2. Click role dropdown
3. Select new role
4. Confirm change

### Remove User

1. Find user in team list
2. Click **Remove**
3. Confirm removal

!!! warning "Removing Users"
    Removed users lose access immediately. Their audit history is preserved.

---

## Audit Trail

All team changes are logged:

| Action | Log Entry |
|--------|-----------|
| Invite | `TEAM_INVITE` |
| Role change | `TEAM_ROLE_CHANGE` |
| Refused request | `ACCESS_DENIED` |
| Remove | `TEAM_REMOVE` |

View in **Settings → Audit Log**.

!!! note "Admin guardrails"
    An admin can change a member's name, phone and role, but not their email: email is the sign-in identity, and members change it in their own profile. The last admin of an organisation can't be demoted or removed; make someone else admin first.
