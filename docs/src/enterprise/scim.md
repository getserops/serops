---
seo_title: "SCIM 2.0 provisioning"
description: "Provision SerOps accounts with SCIM 2.0 from Microsoft Entra ID or Okta: create accounts, keep roles and teams in line with groups, and deactivate people the moment the identity provider removes them."
---
# SCIM 2.0 provisioning

!!! info "Paid license"
    SCIM provisioning needs a paid license (Business or Enterprise) that lists `scim`
    (**Settings → Paid license**). Without one every SCIM request gets
    `403` and nothing changes; existing tokens can still be revoked. With
    Community, accounts are created at the first SSO sign-in and follow the
    group rules at each sign-in: see
    [Authentication & SSO](../security/authentication.md#single-sign-on-sso).

With SCIM, your identity provider pushes changes to SerOps as they happen,
instead of SerOps learning about them at the next sign-in:

- **New people** get an account before they first sign in.
- **Roles and teams** follow the groups, with the same group rules as
  single sign-on (**Settings → Security → Single Sign-On**).
- **People who leave** are deactivated at once: the account is disabled,
  and every session and API token it holds stops working on the next
  request.

SCIM provisions accounts; people still sign in with
[SAML](saml.md) or OpenID Connect. SerOps implements the part of SCIM 2.0
(RFC 7643, RFC 7644) that Microsoft Entra ID and Okta use.

## Set it up

1. Set up single sign-on and its group rules first (**Settings → Security →
   Single Sign-On**). SCIM uses the same rules: **Roles from your identity
   provider** (with **When no rule matches**) and **Teams from your identity
   provider**. To have the identity provider
   decide roles, turn on **Update roles at every sign-in**.
2. In **Settings → Security → Provisioning (SCIM)**, copy the **Tenant URL**,
   for example `https://serops.example.com/api/ee/scim/v2`.
3. Under **Tokens**, give the token a name (for example *Entra ID*) and
   select **Create a token**. Copy the token: it is shown only once, and
   SerOps stores only a hash of it.
4. Enter the Tenant URL and the token at your identity provider (below), and
   test the connection.

Only admins with every admin permission create and revoke tokens. A token
belongs to one organisation and only ever sees that organisation's people
and groups.

## What a change does

| At the identity provider | In SerOps |
|---|---|
| A user is assigned | An account for its email, with no password (sign-in is by SSO). Its role is the one set in **When no rule matches**. With **Refuse sign-in** there, it is created inactive and becomes active when it joins a mapped group. |
| A member who already has an account is assigned | That account is linked, not duplicated. |
| A user joins or leaves a group | The role (when **Update roles at every sign-in** is on) and the teams follow the group rules at once. Only team memberships that SSO or SCIM added are removed; members added by hand stay. |
| A user is disabled (`active: false`) | The account is deactivated and its sessions and API tokens are deleted. |
| A user is removed from every mapped group, with **Refuse sign-in** in **When no rule matches** | The same as disabled. |
| A user is deleted | Deactivated as above, removed from its SCIM groups and SSO teams, and unlinked from SCIM. The account stays, deactivated, for the audit trail; an admin can delete it in **Settings → Team**. |
| A group is renamed or deleted | The rules are applied again to everyone in it. |

Groups match the rules on their display name or their external ID. Entra
ID sends the group's object ID as the external ID, so a rule can name
either.

The organisation's last active admin is never deactivated or demoted by
SCIM, so a group change cannot lock the organisation out; SerOps logs a
warning instead, and deleting that user answers `409`.

Every change is in the audit log (**Settings → Audit Log**): `SCIM_USER_*`,
`SCIM_GROUP_*` and `SCIM_TOKEN_*`, and role and team changes with
`source: scim`.

## Microsoft Entra ID

In the Microsoft Entra admin center, open the enterprise application you
use for SerOps sign-in (or create a non-gallery application), then:

1. **Provisioning → Get started**, **Provisioning Mode: Automatic**.
2. **Admin Credentials**: **Tenant URL** = the SerOps Tenant URL,
   **Secret Token** = the SerOps token. Select **Test Connection**.
3. **Mappings**: keep *Provision Microsoft Entra ID Users* and *Provision
   Microsoft Entra ID Groups*. SerOps uses `userName`, `active`,
   `emails[type eq "work"].value`, `name.givenName`, `name.familyName` and
   `externalId`, and accepts and ignores the other default attributes.
4. **Settings → Scope**: *Sync only assigned users and groups*, and assign
   the users and groups under **Users and groups**.
5. **Provisioning Status: On**, then **Save**.

Entra ID provisions on a cycle (about every 40 minutes); **Provision on
demand** pushes one user at once. Check your Entra ID plan for what
automatic provisioning to a non-gallery application needs.

## Okta

*Tested live: Okta Integrator Free Plan, 15 Nov 2026: Test Connector Configuration, user and group push, role and team mapped from the pushed group, unassigning deactivates the account and ends its sessions, assigning again reactivates it.*

Okta provisions through a **SAML 2.0** (or SWA) app integration, the same
one people use to sign in with [SAML](saml.md). Okta's documentation says
OpenID Connect integrations made with the classic wizard cannot have SCIM.
To try it without a paid Okta org, sign up for Okta's free *Integrator Free
Plan* (it replaced the Developer Edition in 2025; up to 10 active users).

**1. Create the app integration** (skip if you already sign in with SAML).
In the Okta Admin Console:

1. **Applications → Applications → Create App Integration**, choose
   **SAML 2.0**, **Next**.
2. **App name**: `SerOps`, **Next**.
3. **Single sign-on URL** = the SerOps **Reply URL**, **Audience URI (SP
   Entity ID)** = the SerOps **Identifier** (both in **Settings → Security →
   Single Sign-On** with SAML chosen). **Name ID format**: *EmailAddress*,
   **Application username**: *Email*. **Next**, then **Finish**.

**2. Turn on SCIM.**

1. **General → App Settings → Edit**: **Provisioning: SCIM**, **Save**.
2. **Provisioning → Integration → Edit**:
    - **SCIM connector base URL** = the SerOps Tenant URL, without a slash
      at the end
    - **Unique identifier field for users** = `userName`
    - **Supported provisioning actions**: *Push New Users*, *Push Profile
      Updates*, *Push Groups*
    - **Authentication Mode**: *HTTP Header*; **Authorization** = the SerOps
      token alone (Okta sends it as `Bearer …`)

    Select **Test Connector Configuration**: Okta reads the
    ServiceProviderConfig and lists the actions it found. Close it and
    **Save**.
3. **Provisioning → To App → Edit**: enable *Create Users*, *Update User
   Attributes* and *Deactivate Users*, **Save**.

**3. Assign people and push groups.**

1. **Assignments → Assign → Assign to People** (or *to Groups*). Each person
   assigned gets a SerOps account within seconds.
2. **Push Groups → Push Groups → Find groups by name**: pick the groups your
   SerOps rules name (for example *SerOps Users*), **Save**. Their members'
   roles and teams follow at once.

Unassigning someone, or deactivating them in Okta, deactivates their
SerOps account and ends their sessions. Okta's password sync is not used:
a password Okta sends is ignored.

## API

The endpoints are under `/api/ee/scim/v2/`, authenticated with the SCIM
token as a bearer token (`Authorization: Bearer serops_scim_…`), never a
user session:

| Endpoint | Methods |
|---|---|
| `/ServiceProviderConfig`, `/Schemas`, `/ResourceTypes` | `GET` |
| `/Users` | `GET` (filter, paging), `POST` |
| `/Users/{id}` | `GET`, `PUT`, `PATCH`, `DELETE` |
| `/Groups` | `GET` (filter, paging), `POST` |
| `/Groups/{id}` | `GET`, `PUT`, `PATCH` (`204`), `DELETE` |

- **Filters**: `eq` on `userName`, `externalId`, `id` and `emails.value` for users, and on
  `displayName`, `externalId` and `id` for groups.
- **Paging**: `startIndex` and `count`, at most 200 per page.
- **PATCH**: `add`, `replace` and `remove`, with a path or without one, in
  any letter case, with booleans as JSON or as strings (`"False"`).
  `excludedAttributes=members` is supported on groups.
- **Not supported**: bulk, sorting, ETags, password changes.
- **Errors** are SCIM error bodies (`application/scim+json`); `409` with
  `scimType: uniqueness` for a userName, email or group name already taken.
- **Rate limit**: 600 requests a minute per token (`429` beyond).

Tokens are managed by an admin at `/api/ee/scim/tokens/`: `GET` lists them
and the Tenant URL (never a token's value), `POST {"name": "…"}` creates one
and returns its value once, and `DELETE /api/ee/scim/tokens/{id}/` revokes
it at once.

## Troubleshooting

**Test Connection fails with 401.** The token is wrong or revoked. Create a
new one; the old value cannot be shown again.

**Every request gets 403.** The license does not list `scim`, or has
expired.

**Users are created but stay inactive.** **When no rule matches** is
**Refuse sign-in** and the user is in no mapped group. Assign a group the rules name
(by display name or Entra ID object ID), or change **When no rule matches**.

**409 on create.** The email belongs to an account in another organisation
on the same install, or a SCIM user with that userName exists.

**Roles do not change.** Turn on **Update roles at every sign-in** in the
SSO settings; without it, SCIM sets the role only when it creates the
account.
