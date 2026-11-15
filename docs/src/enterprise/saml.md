---
seo_title: "SAML 2.0 single sign-on"
description: "Sign in to SerOps with SAML 2.0 from Microsoft Entra ID, Okta or Keycloak: what to register, what SerOps checks on every assertion, group-to-role and group-to-team mapping, and enforcing SSO."
---
# SAML 2.0 single sign-on

!!! info "SerOps Enterprise"
    SAML sign-in needs an Enterprise license that lists `saml` (**Settings →
    Enterprise license**). Without one, SAML is inert: no sign-in starts, the
    endpoints below answer as if SAML did not exist, and the settings stay
    saved. **OpenID Connect**, with the same group rules, teams and
    enforcement, is part of every edition: see
    [Authentication & SSO](../security/authentication.md#single-sign-on-sso).

SerOps is the service provider (SP). Each organisation has its own SAML
service provider, with its own entity ID and ACS URL, so several
organisations on one install can each use their own identity provider.

## Set it up

1. In SerOps, **Settings → Security → Single Sign-On**: turn SSO on and
   choose **SAML 2.0**. The panel shows what to register at your identity
   provider:

    | SerOps shows | Entra ID calls it | Okta calls it |
    |---|---|---|
    | Identifier (Entity ID) `https://HOST/api/ee/saml/<id>/metadata/` | Identifier (Entity ID) | Audience URI (SP Entity ID) |
    | Reply URL `https://HOST/api/ee/saml/<id>/acs/` | Reply URL (Assertion Consumer Service URL) | Single sign-on URL |
    | Metadata (download) | *Upload metadata file* | — |

2. Create the application at your identity provider (walkthroughs below).
3. Back in SerOps, paste the identity provider's **metadata URL** (or its
   metadata XML) and save. SerOps reads the entity ID, the sign-in URL and
   the signing certificates from it, and shows each certificate's expiry and
   SHA-256 fingerprint.
4. Map groups to roles and teams under **Roles from your identity
   provider** (the same rules as for OIDC; see
   [roles](../security/authentication.md#roles-from-your-identity-providers-groups)
   and [teams](../security/authentication.md#teams-from-your-identity-providers-groups)).
   For SAML, **Groups attribute** is the name of the assertion attribute
   that lists the groups.
5. Sign in from the login page with **Sign in with SSO**, or from the
   identity provider's portal.
6. Optional: **Require single sign-on**, so members can no longer use a
   password ([details](../security/authentication.md#require-single-sign-on)).

`HOST` is the address of your SerOps install as the browser reaches it
(`API_URL`). The identity provider never calls SerOps directly: the browser
carries the assertion, so SerOps does not need to be reachable from the
internet.

## What SerOps checks

Every response is refused, and the browser sent back to the login page, unless:

- **The assertion is signed** by one of the identity provider's certificates
  from its metadata, with RSA-SHA256 or stronger. A signed response around an
  unsigned assertion is refused; SHA-1 signatures are refused.
- The **issuer** is the identity provider's entity ID, the **audience** is
  this organisation's entity ID, and the **destination** and **recipient**
  are this organisation's ACS URL.
- It is within its validity (`NotBefore`, `NotOnOrAfter`), with **180 seconds**
  of clock difference tolerated (`SAML_CLOCK_SKEW_SECONDS`), and was issued
  less than **10 minutes** ago (`SAML_MAX_ASSERTION_AGE_SECONDS`), whatever
  validity the identity provider gave it.
- **It has not been used before.** Each assertion ID is accepted once
  (replay protection, kept in the database until the assertion would have
  expired anyway).
- When the sign-in started on the SerOps login page, the response answers
  **that request, once** (`InResponseTo`). A response naming a request
  SerOps did not send, or sent for another organisation, is refused.
- Sign-in started at the identity provider (no `InResponseTo`) is accepted
  only while **Allow sign-in started from the identity provider** is on (the
  default, for the Entra ID My Apps portal and Okta tiles).

Then the same rules as OpenID Connect decide who gets in: an account of the
organisation, or a new account for an email domain listed under **Email
domains that can join**; the role from the first matching group rule, or
the default role, or a refusal; teams from the group rules. Accounts of
another organisation, disabled accounts and the demo account are refused.

**RelayState is ignored**: the browser always lands on SerOps, so the field
cannot be used to send people elsewhere.

**Encrypted assertions** are supported: SerOps publishes its encryption
certificate in its metadata and in the settings panel, and decrypts
assertions encrypted to it (AES-CBC or AES-GCM, RSA-OAEP). **Require
encrypted assertions** refuses the unencrypted ones.

**Where the email comes from:** the attribute named in **Email attribute**;
otherwise the usual ones (`http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress`,
`email`, `mail`, `urn:oid:0.9.2342.19200300.100.1.3`); otherwise the NameID
when it is an email address. First and last names likewise
(`givenname`/`surname` claims, `firstName`/`lastName`).

Every account creation, refused sign-in and role or team change is in
**Settings → Audit Log** with `source: saml`; a refused response records the
reason (never the assertion).

**Not supported: single logout (SLO).** Signing out of SerOps ends the
SerOps session only; it does not sign out of the identity provider, and a
logout started at the identity provider does not end SerOps sessions (they
end with the session timeout under **Settings → Security**).

## Microsoft Entra ID

*Tested live: Microsoft Entra ID, 15 Nov 2026: sign-in started at SerOps, account created at the first sign-in (listed email domain), role and team mapped from the group Object ID. Sign-in started at Entra ID and refused sign-ins are covered by the automated tests.*

1. **Entra admin center → Enterprise applications → New application →
   Create your own application.** Name it `SerOps`, choose *Integrate any
   other application you don't find in the gallery (Non-gallery)*.
2. **Single sign-on → SAML.** Under **Basic SAML Configuration**, set
   **Identifier (Entity ID)** and **Reply URL** to the values SerOps shows.
   Leave *Sign on URL*, *Relay State* and *Logout URL* empty.
3. **Attributes & Claims**: the defaults send the email address
   (`emailaddress` claim) and names. To map groups, **Add a group claim**:
   *Groups assigned to the application*, source attribute **Group ID**. In
   SerOps, set **Groups attribute** to
   `http://schemas.microsoft.com/ws/2008/06/identity/claims/groups` and write
   the rules with the groups' **object IDs**. With more than 150 groups Entra
   ID sends a link instead of the groups; "Groups assigned to the
   application" avoids it.
4. **Users and groups**: assign the people or groups who may sign in.
5. Copy **App Federation Metadata Url** (under *SAML Certificates*) into
   SerOps.
6. Test with **Test** on the Single sign-on page (sign-in started at the
   identity provider) and with **Sign in with SSO** on the SerOps login page.

Entra ID signs the assertion by default (*Signing Option: Sign SAML
assertion*); *Sign SAML response and assertion* works too. Token
encryption (*Token encryption* blade, needs Entra ID P1 or P2) works with the
certificate from the SerOps panel.

When Entra ID rolls its signing certificate, read the metadata again
(**Read the metadata again** in the panel): both certificates are accepted
during the rollover.

## Okta

*Tested live: Okta Integrator Free Plan, 15 Nov 2026: sign-in started at SerOps, role and team mapped from the groups attribute, same account as the one SCIM created. Sign-in started at Okta and refused sign-ins are covered by the automated tests.*

1. **Applications → Create App Integration → SAML 2.0.**
2. **Single sign-on URL**: the Reply URL from SerOps (*Use this for Recipient
   URL and Destination URL* ticked). **Audience URI (SP Entity ID)**: the
   Identifier from SerOps. **Name ID format**: EmailAddress, **Application
   username**: Email.
3. **Attribute statements**: `email` → `user.email`, `firstName` →
   `user.firstName`, `lastName` → `user.lastName`. **Group attribute
   statements**: name `groups`, filter *Matches regex* `.*` (or a narrower
   filter).
4. Okta signs the assertion and the response by default (*Assertion
   Signature: Signed*, RSA-SHA256): keep it.
5. **Sign On → Metadata URL**: paste it into SerOps. Assign people or groups
   to the application.

## Keycloak

*Tested: SerOps' integration test signs in against Keycloak 26 in Docker
(`backend/docker-compose.yml`, profile `sso`).*

1. **Clients → Create client**, type **SAML**. **Client ID**: the Identifier
   from SerOps.
2. **Valid redirect URIs** and **Assertion Consumer Service POST Binding
   URL** (Advanced): the Reply URL from SerOps. **IDP-Initiated SSO URL
   name**: a short name if you want a sign-in link from Keycloak.
3. **Keys**: turn **Client signature required** off (SerOps does not sign
   its requests). **Signature and Encryption**: **Sign assertions** on
   (required by SerOps; Keycloak's default signs only the document), RSA_SHA256.
4. **Name ID format**: email, *Force name ID format* on.
5. **Client scopes → dedicated scope → Add mapper**: *Group list* (attribute
   name `groups`, *Full group path* off) and *User Property* mappers for
   `email`, `firstName`, `lastName`.
6. Paste `https://KEYCLOAK/realms/<realm>/protocol/saml/descriptor` into
   SerOps as the metadata URL.

Keycloak sends one `groups` attribute per group; SerOps merges them.

## API

```
GET  /api/ee/saml/config/                    settings.read
PUT  /api/ee/saml/config/                    settings.manage + every admin permission; license required
GET  /api/ee/saml/<id>/metadata/             public: SP metadata (404 without the license)
POST /api/ee/saml/<id>/acs/                  public: the identity provider's response (HTTP-POST binding)
```

`PUT` accepts `idp_metadata_url` (fetched with the same outbound checks as
every URL an admin sets: no cloud metadata addresses, optional private-address
block), `idp_metadata_xml`, `refresh_metadata: true`, or the three values
typed in (`idp_entity_id`, `idp_sso_url`, `idp_certificate`), plus
`email_attribute`, `first_name_attribute`, `last_name_attribute`,
`want_assertions_encrypted` and `allow_idp_initiated`. Each change is
audited (`SETTINGS_CHANGE`, `setting: saml`). The response never contains the
SerOps private key, which is stored encrypted with `SEROPS_ENCRYPTION_KEY`
and re-encrypted by `python manage.py rotate_secrets`.

Sign-in starts with the same `POST /api/auth/sso/init` as OIDC, which
returns the identity provider URL with the `SAMLRequest`. The ACS is rate
limited (`auth_saml_acs`, 60 per minute per client).

## Troubleshooting

A refused sign-in sends the browser to `/login?sso=failed`; the reason is in
the backend log (`SAML response refused for org …: <reason>`) and in the
audit log (`SSO_DENIED`, `source: saml`).

| Reason in the log | Fix |
|---|---|
| `The Assertion of the Response is not signed and the SP require it` | Sign the assertion at the identity provider (Keycloak: *Sign assertions*). |
| `… is not a valid audience` | The identity provider's Identifier / Audience is not the Identifier SerOps shows. |
| `The response was received at … instead of …` | The Reply URL at the identity provider, or `API_URL`, does not match the address the browser uses. |
| `Signature validation failed` | The identity provider rolled its certificate: **Read the metadata again**. |
| `Could not validate timestamp` | Clocks differ by more than 180 seconds: check NTP on the SerOps host. |
| `assertion already used (replay)` | The browser posted the same response twice (back button); sign in again. |
| `sign-in started at the identity provider, which this organisation does not allow` | Turn on *Allow sign-in started from the identity provider*, or start from the SerOps login page. |
| `the assertion has no email address` | Send an email attribute, or set **Email attribute** to the attribute that has it. |
