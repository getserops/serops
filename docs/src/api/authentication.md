# Authentication API

Endpoints for user authentication, registration, profile management, SSO, one-click demo login, and account deletion.

All endpoints in this section use the `/api/auth/` prefix. `login`, `register`, `registration-status`, `activate`, `password/forget`, `password/set`, `accept/invitation`, `accept/password`, and the `sso/*` endpoints do not require an authentication token; all others do.

Several endpoints are rate-limited per client IP — see the [API Overview](overview.md#rate-limiting) for the current limits.

## Login

```
POST /api/auth/login
```

**Request body:**

```json
{
  "email": "user@example.com",
  "password": "password"
}
```

**Response:**

```json
{
  "token": "abc123...",
  "user": {"id": 1, "email": "user@example.com"}
}
```

## Registration Status

```
GET /api/auth/registration-status
```

Public flag the login page reads at mount time to decide whether to render the "Create account" prompt. Safe to call anonymously.

**Response:**

```json
{
  "registration_enabled": true
}
```

Controlled by the `REGISTRATION_ENABLED` env var — see [Configuration Reference](../deployment/configuration.md#public-access-control).

## Register

```
POST /api/auth/register
```

**Request body:**

```json
{
  "user": {
    "email": "user@example.com",
    "password": "password",
    "password_confirmation": "password",
    "first_name": "John",
    "last_name": "Doe",
    "phone": "+1000000000"
  },
  "organisation": {
    "name": "My Org",
    "website": "https://example.com"
  }
}
```

Creates a new organisation with the caller as its first admin. Sends an activation email.

**When registration is disabled:**

If the deployment sets `REGISTRATION_ENABLED=False`, this endpoint returns `403 Forbidden`:

```json
{
  "status": "error",
  "error": "registration_disabled",
  "message": "This SerOps instance does not accept new registrations. Ask an admin for an invite, or self-host your own instance: https://serops.ai/docs/getting-started/quick-start-self-hosted/"
}
```

## Get Profile

```
GET /api/auth/profile
```

Returns the authenticated user's profile information.

## Upload Avatar

```
PUT /api/auth/profile/upload-avatar/
Content-Type: multipart/form-data

avatar: <file>
```

Uploads a profile avatar image for the authenticated user.

## Update Password

```
POST /api/auth/password
```

**Request body:**

```json
{
  "old_password": "current",
  "new_password": "new-secure-password",
  "new_password_copy": "new-secure-password"
}
```

## Forgot Password

```
POST /api/auth/password/forget
```

**Request body:**

```json
{
  "email": "user@example.com"
}
```

Sends a password reset email to the specified address.

## Set Password (Reset)

```
POST /api/auth/password/set/{uidb64}/{token}
```

**Request body:**

```json
{
  "password": "new-password"
}
```

Completes the password reset flow using the link from the reset email.

## Resend Verification Email

```
GET /api/auth/resend
```

Resends the account activation email for the authenticated user.

## Activate Account

```
GET /api/auth/activate/{token}
```

Activates the user account using the token from the verification email. This is a `GET` because the activation link is opened directly from an email.

## Accept Invitation

```
GET /api/auth/accept/invitation/{token}
```

Accepts a team invitation using the token from the invitation email. Associates the user with the inviting organisation. This is a `GET` because the invitation link is opened directly from an email.

## Set Password (Invitation)

```
POST /api/auth/accept/password
```

**Request body:**

```json
{
  "password": "new-password"
}
```

Sets the password for a user who joined via team invitation.

## Logout

```
POST /api/auth/logout
```

Invalidates the current authentication token.

## Delete Account (GDPR Right to Erasure)

```
DELETE /api/auth/account
```

Permanently deletes the authenticated user's account and their personal profile data (name, avatar, phone). Team memberships are removed and any chat sessions owned by the user are deleted. Batches, issues, and other organisation-scoped data are retained under the organisation's control.

If the user is the sole admin of an organisation, the request is rejected — transfer admin to another member first, or delete the organisation via `/api/organisation/delete/{id}/`.

**Response:** `204 No Content`.

## SSO Configuration

```
GET /api/auth/sso/config
```

Returns the available SSO providers and their configuration for the organisation.

## SSO Login Init

```
POST /api/auth/sso/init
```

**Request body:**

```json
{
  "provider": "keycloak"
}
```

Initiates the SSO login flow and returns the redirect URL for the specified provider.

## SSO Callback

```
POST /api/auth/sso/callback
```

Handles the callback from the SSO identity provider after successful authentication. Sets a short-lived HttpOnly handoff cookie and redirects the browser back to the frontend. The frontend then calls `sso/exchange` to swap the cookie for a Knox token.

## SSO Token Exchange

```
POST /api/auth/sso/exchange
```

Exchanges the short-lived HttpOnly handoff cookie set by `sso/callback` for a usable Knox token + user payload. The browser sends the handoff cookie automatically; the caller must use `withCredentials: true`.

**Response:**

```json
{
  "token": "abc123...",
  "user": {"id": 1, "email": "user@example.com"}
}
```

This two-step flow keeps the SSO token out of the URL and out of local storage until after exchange, closing the risk of tokens leaking via referer headers or browser history.

---

## Related

- [API Overview](overview.md) -- Base URL, response format, rate limits, and error codes
- [Settings & Admin](settings.md) -- Organisation-level security settings
- [Configuration Reference](../deployment/configuration.md#public-access-control) -- `REGISTRATION_ENABLED` and other access flags
