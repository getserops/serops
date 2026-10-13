# Authentication & Single Sign-On (SSO)

SerOps provides robust authentication options ranging from standard email/password login to Enterprise-grade Single Sign-On (SSO).

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

### User Provisioning
SerOps supports **Just-In-Time (JIT) Provisioning**. 
- When a user logs in via SSO for the first time, their account is automatically created in SerOps.
- They are assigned the default `Viewer` role.
- Admins can upgrade their role in **Settings > Team**.

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

Tokens expire after 30 days. However, active usage keeps the token alive: each authenticated request automatically extends the token's expiry, throttled to at most once per hour to avoid excessive writes.

## Session Management

Admins can control the session duration for all users in the organization:
- **Range**: From 30 minutes up to "Never Expires" (not recommended).
- **Default**: 8 Hours.
- **Inactivity**: Users are automatically logged out after the specified period of inactivity.
