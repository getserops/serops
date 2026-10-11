# Team Management

Manage users, roles, and permissions within your organization.

## Roles

| Role | Permissions |
|------|-------------|
| **Admin** | Full access: settings, users, data, integrations |
| **User** | Read + write: projects, batches, chat |
| **Viewer** | Read only: view data, no modifications |

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
| Remove | `TEAM_REMOVE` |

View in **Settings → Audit Logs**.
