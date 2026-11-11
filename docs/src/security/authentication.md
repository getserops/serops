---
seo_title: "Authentication and SSO (OIDC)"
description: "Sign in to SerOps with email and password or single sign-on (OIDC) with Keycloak, Okta, Azure AD or Google, per organisation."
---
# Authentication & Single Sign-On (SSO)

SerOps signs people in with email and password or with OpenID Connect single sign-on (SSO). Both are in Community; with Enterprise, custom roles can also be handed out from identity-provider groups.

## Registration

New organizations can sign up directly via the Registration page. The process is streamlined for efficiency:

1.  **Basic Details**: Enter your Full Name and Work Email.
2.  **Organization**: Provide your Company Name.
3.  **Security**: Set a strong password.

> [!NOTE]
> We have removed the requirement for a phone number to speed up the onboarding process.

## Single Sign-On (SSO)

SerOps supports Single Sign-On through **OpenID Connect (OIDC)**, so you can manage user access from your central Identity Provider (IdP). It is part of every edition.

!!! note "SAML 2.0 is not supported yet"
    Use OIDC — every major IdP (Okta, Azure AD / Entra ID, Google Workspace, Keycloak, Auth0) offers it.

### Configuring SSO

Navigate to **Settings > Security > Single Sign-On** to configure your provider.

#### OpenID Connect (OIDC)
Ideal for modern providers like **Okta**, **Azure AD**, **Google Workspace**, or **Keycloak**.

**Required Fields:**
*   **Client ID**: From your IdP application.
*   **Client Secret**: From your IdP application.
*   **Discovery URL**: The `.well-known/openid-configuration` endpoint (e.g., `https://accounts.google.com/.well-known/openid-configuration`).

### Roles from your identity provider's groups

Under **Roles from your identity provider**, map the groups people are in at your identity provider to SerOps roles:

| Setting | What it does |
|---------|--------------|
| **Groups claim** | Where the groups are in the user's claims. `groups` for Okta, Entra ID and Keycloak with a group mapper; a dotted path for nested claims, such as `realm_access.roles` for Keycloak realm roles. SerOps reads the userinfo response and the ID token (Entra ID only puts groups in the ID token). |
| **Extra scopes** | Requested on top of `openid email profile`. Okta needs `groups`. |
| **Rules** | `group → role`, checked from top to bottom: the first group the person is in sets their role. Put the most privileged rule first. Group names are not case-sensitive, and a group path such as `/Engineering/sre` also matches `sre`. |
| **When no rule matches** | The role of people in none of the groups, or **Refuse sign-in**, so only people in a mapped group can use SerOps. |
| **Update roles at every sign-in** | On: your identity provider decides, and a role changed in SerOps is replaced at the person's next sign-in. Off: the rules only set the role of new accounts. The last admin of an organisation is never demoted. |

Every SSO account creation, refused sign-in and role change is in **Settings → Audit Log** (`SSO_PROVISION`, `SSO_DENIED`, `TEAM_ROLE_CHANGE` with `source: sso`).

Example for Keycloak: add a **Group Membership** mapper to the client (claim name `groups`, *Full group path* off, *Add to userinfo* on), then add the rules `platform-admins → Admin` and `sre → User`.

### Teams from your identity provider's groups

Under **Teams from your identity provider**, map a group to a team (see [Teams and project access](../admin/team.md#teams-and-project-access)): members of the group join the team at each sign-in and leave it when they leave the group. Members added to a team in SerOps are never removed by SSO. You can only map groups to teams whose project access you hold.

### Who can sign in

- **Invited members** sign in with SSO as soon as their invitation is sent.
- **People without an invitation** can sign in when their email domain is listed under **Email domains that can join**: their account is created at their first SSO sign-in, with the role from the rules. On an install with one organisation, its admin sets the domains. With several organisations, a domain decides which organisation's identity provider a newcomer is sent to, so the platform operator sets them:

    ```bash
    python manage.py sso_domains "Acme" acme.com acme.io
    python manage.py sso_domains --list
    ```

    A domain belongs to one organisation only.
- An account of another organisation, a disabled account or an email the identity provider marks unverified is refused.

## Token Authentication

SerOps uses **Knox token-based authentication** for API access (not JWT).

| Property | Details |
|----------|---------|
| **Token Type** | Knox token |
| **Header Format** | `Authorization: Token <token>` |
| **Token TTL** | 30 days |
| **Auto-Refresh** | Token expiry is extended on each authenticated request (at most once per hour) |

When a user logs in, a Knox token is issued. Include it in subsequent API requests via the `Authorization` header:

```
Authorization: Token 8f2e1a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f
```

Tokens expire after 30 days. However, active usage keeps the token alive: each authenticated request automatically extends the token's expiry, at most once per minute to avoid excessive writes.

## Session Management

Admins can control the session duration for all users in the organization:
- **Range**: From 30 minutes up to "Never" (not recommended; the token's own 30 days then apply).
- **Default**: 8 Hours, also for organisations that never opened the setting.
- **Inactivity**: A session idle for longer than this ends, and the user signs in again. The check is accurate to the minute.

## Changing Your Email

Changing your sign-in email from your profile needs your current password and a confirmation link sent to the new address, valid for 24 hours. Nothing changes until the link is used. Then every session ends and the old address is told.

Accounts that sign in with SSO keep the email of their identity provider. An address in a domain that another organisation's SSO claims cannot be used.

## OpenID Connect Sign-In

Each sign-in is bound to the browser that started it with a short-lived HttpOnly cookie, and uses a `nonce` and PKCE (S256). Your identity provider must return `email_verified: true`. Providers that leave the claim out can be trusted by their host name with `SSO_TRUST_MISSING_EMAIL_VERIFIED` (default: `login.microsoftonline.com`, for Microsoft Entra ID).
