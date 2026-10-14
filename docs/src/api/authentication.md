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

An unknown email and a wrong password both return `401` with `{"error": "Invalid email or password"}`, so the endpoint does not reveal which emails have an account. On a host with `DEMO_ONLY_LOGIN=true` it returns `403` with `{"error": "demo_only"}`.

## Registration Status

```
GET /api/auth/registration-status
```

Public flags the login page reads at mount time. Safe to call anonymously.

**Response:**

```json
{
  "registration_enabled": true,
  "demo_available": false,
  "demo_only": false
}
```

| Field | Meaning |
|---|---|
| `registration_enabled` | The "Create account" prompt is shown. |
| `demo_available` | A seeded read-only demo user exists, so "Try the live demo" is shown. |
| `demo_only` | `DEMO_ONLY_LOGIN=true`: the login page shows only the demo button. |

Controlled by the `REGISTRATION_ENABLED` env var. Left unset, it is `true` until the first organisation exists and `false` afterwards — see [Configuration Reference](../deployment/configuration.md#public-access-control).

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

If registration is closed — `REGISTRATION_ENABLED=False`, or left unset on an instance that already has an organisation — this endpoint returns `403 Forbidden`:

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

Returns the organisation's OpenID Connect settings (`sso_enabled`, `sso_provider` — `oidc` or `none`, `sso_client_id`, `sso_discovery_url`, `sso_client_secret_configured`) and `sso_redirect_uri`, the URL to register at the identity provider. `PUT` (admin only) updates them; the client secret is write-only. SAML is not supported.

## SSO Login Init

```
POST /api/auth/sso/init
```

**Request body:**

```json
{
  "email": "user@example.com"
}
```

Looks up the organisation that owns the email and returns `{"auth_url": "..."}`, the identity provider's sign-in page. Every case without an auth URL — unknown email, SSO switched off, inactive or demo account — returns the same `400 {"error": "SSO is not available for this account."}`, so the endpoint does not reveal who has an account. `502` means the identity provider's discovery URL could not be reached.

## SSO Callback

```
GET /api/auth/sso/callback
```

The identity provider redirects the browser here. SerOps exchanges the code, reads the user's email from the userinfo endpoint and signs them in:

- An existing user signs in only if they belong to the organisation that started the flow and are active.
- An unknown email becomes a new `viewer` in that organisation, with no password.
- An email the provider marks `email_verified: false` is refused.

On success it sets a short-lived HttpOnly handoff cookie and redirects to the frontend's `/auth/callback`, which calls `sso/exchange` to swap the cookie for a Knox token. On any failure it redirects to `/login?sso=failed`.

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
