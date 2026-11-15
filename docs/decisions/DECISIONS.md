# Decisions: Enterprise SAML, SCIM and audit streaming (1.4.0)

Decisions taken while building the owner's brief of 2026-11-13 ("Enterprise
features: SAML 2.0, SCIM 2.0, audit streaming"), where it left a choice
open. Not published with the docs site (`docs/src` is). Newest at the end.

## SAML 2.0 (feature `saml`)

**D1. Library: python3-saml 1.16 (OneLogin toolkit), not pysaml2.**
Both are maintained and licence-compatible (MIT; pysaml2 is Apache-2.0).
python3-saml installs from wheels (xmlsec and lxml bundle their C libraries),
so the image needs no extra Debian package and no subprocess; pysaml2 shells
out to the `xmlsec1` binary, which adds a package to the image and to the
Trivy gate. python3-saml's last release is from 2023, but its xmlsec binding
is current (1.3.18) and its validation (signature, issuer, audience,
destination, recipient, time conditions, InResponseTo) is the part we rely
on; replay, request single use and maximum age are ours. Checked before
choosing: signing and verifying with the bundled xmlsec and lxml 6.1 works,
a tampered assertion is rejected. Revisit if a CVE is left unfixed.

**D2. One service provider per organisation**, named by a random UUID
(`SamlConfig.sp_id`) in every URL (entity ID = metadata URL, ACS). Not the
slug, which changes on rename; not the numeric id, which is enumerable.

**D3. The assertion must be signed** (`wantAssertionsSigned`); a signed
Response around an unsigned assertion is refused. SHA-1 refused.
Keycloak's default (sign the document only) therefore needs *Sign
assertions* on; documented.

**D4. Pending requests are kept server-side** (Django cache, 15 minutes,
single use, bound to the organisation), not in a browser cookie: the
identity provider posts cross-site, so a cookie would need SameSite=None,
which needs https, and lab installs run plain http. The cost: an
SP-initiated response is not bound to the browser that started it. Sign-in
started at the identity provider has no such binding by nature; it can be
switched off per organisation (`allow_idp_initiated`, on by default because
Entra ID's My Apps and Okta tiles use it).

**D5. Replay protection in Postgres** (`SamlAssertion`, unique assertion ID),
kept until issue time + maximum age + 2 × skew; expired rows are deleted as
new ones arrive (no Celery job needed). On top of the identity provider's
NotOnOrAfter, SerOps refuses assertions issued more than 10 minutes ago, so
the replay table never needs to hold an assertion longer than that.

**D6. Clock skew 180 s** (python3-saml's default is 300 s), setting
`SAML_CLOCK_SKEW_SECONDS`.

**D7. Group mapping is shared with OIDC.** `complete_sign_in` in
`Users/sso_views.py` (Community) now holds the account, role, team and token
handoff logic for both protocols; the OIDC callback calls it. The SAML
groups attribute is `SecuritySettings.sso_groups_claim`, read as an
attribute name (not a dotted path: Entra ID's claim names contain dots).

**D8. "Enforced SSO" did not exist; added as `sso_enforced`, in Community.**
The brief asks that SAML respect enforced SSO. It is a security control,
so per `ee/licensing/features.py` it belongs in Community and applies to
OIDC too. Admins keep password sign-in (break-glass); enforcement applies
only while the SSO is usable, so an expired SAML license cannot lock an
organisation out. Checked after the password, so it reveals nothing.

**D9. Single logout skipped**, documented. SerOps sessions are Knox tokens
with the organisation's session timeout; an SLO endpoint would have to map
NameID/SessionIndex to tokens. Not asked for by name by buyers so far.

**D10. Community code never imports `ee`.** The SAML sign-in start is a
handler registered in `Utils.edition` (`register_sso_protocol`), like the
license provider; Community asks `edition.sso_protocol('saml')`, which is
None without the code or the license. The UI uses the same pattern
(`securitySections` in `src/ee/*/index.js`).

**D11. RelayState is ignored**: the browser always lands on the app after
sign-in, so the field cannot be an open redirect.

**D12. Metadata publishes the encryption certificate always**, so an
identity provider importing it can encrypt; requiring encryption is the
per-organisation setting.

**D13. Repeated attribute names are merged** (Keycloak sends one
`groups` attribute element per group).

**D14. No system libxmlsec1/libxml2 packages; a missing library stops the
backend** (2026-11-14, after CI failed with 35 failures and 3 errors, all 404s).
The cause was not the library: both CI files set `API_URL` without the `/api`
that every deployment uses (helm, quick-start, `.env.example`), so the tests
posted to `/ee/saml/…` instead of `/api/ee/saml/…`. Reproduced in `python:3.12`
with the CI variables (fails), then with `/api` (58 OK). The xmlsec 1.3.18
and lxml 6.1.3 wheels bundle libxml2 2.14.6 and are now pinned together;
installing system libxmlsec1 would add packages to the image and invites the
libxml2 version mismatch that makes xmlsec refuse to load, so we do not. The
SAML routes were never behind a try/except. `ee.apps.load_saml_protocol` now
turns an import failure into `ImproperlyConfigured` with a clear message, at
startup, licensed or not (the licence is read after startup). The tests pin
`API_URL`. The CI files use `/api`, and the system check `ee.W001` flags an
`API_URL` without `/api`, which would give the identity provider dead URLs.

## SCIM 2.0 (feature `scim`)

**D15. SCIM has its own tokens, not user tokens.** `serops_scim_…`, 32
random bytes, stored as a SHA-256 hash with a short prefix for display,
shown once, one organisation each, revocable at once. A SCIM request is
authenticated as the token's organisation, never as a user (the request
user is anonymous), so no user's permissions or session apply. A Knox user
token is refused on the SCIM endpoints. Creating and revoking tokens takes
every permission of an admin, since a token can create admins. Revoking
works without the licence, so a token can always be cut off.

**D16. One set of access rules.** SCIM applies the SSO group rules
(roles, default role, teams, "Update roles at every sign-in") instead of
a separate SCIM mapping, so an organisation cannot have SSO and SCIM
disagree about someone's role. Groups match on display name or external ID
(Entra ID sends the object ID there, which is what its SAML/OIDC group
claim carries too).

**D17. "Refuse sign-in" as default creates inactive accounts.** Entra ID
and Okta create the user first and add it to groups afterwards; the account
becomes active when it joins a mapped group, rather than being refused at
creation (which would make the identity provider retry forever).

**D18. Deprovisioning deactivates; it does not delete.** `active: false`,
leaving every mapped group (with "Refuse sign-in"), or `DELETE` deactivates
the account and deletes all its Knox tokens in the same request. `DELETE`
also unlinks SCIM and removes SCIM groups and SSO teams. The account is kept
for the audit trail and the incidents it touched; an admin deletes it in
Settings → Team.

**D19. The last active admin is never deactivated or demoted by SCIM**
(warning in the log; `DELETE` answers `409`), as for SSO role sync.

**D20. Existing members are linked, other organisations' emails refused.**
A `POST` for an email that already has an account in the organisation
links that account (people invited before SCIM). An email that belongs to
another organisation, or to the demo account, answers `409 uniqueness`:
a SCIM token never reaches across organisations.

**D21. Accepted and ignored.** Attributes SerOps does not keep (title,
manager, locale, phone numbers, the enterprise extension) are accepted and
ignored, and so is a password Okta sends (accounts get an unusable password;
sign-in is by SSO). Only `attr eq "value"` filters on the attributes Entra
ID and Okta use; no bulk, sort, ETag or password change
(ServiceProviderConfig says so).

**D22. Group PATCH answers 204**, which both Entra ID and Okta accept;
it avoids returning thousands of members after each change.

**D23. 600 requests a minute per token.** Entra ID syncs in bursts on its
40-minute cycle; a first sync of a large tenant stays well under it, and a
leaked token cannot hammer the database.

**D24. CV-01, the SSO half (Community).** When an OIDC or SAML sign-in is
refused because the person is in no mapped group, their existing Knox
tokens are deleted (they could otherwise keep a 30-day session). The
account is not deactivated: a refused sign-in can come from a rule typed
wrong, and the admin fixes the rule rather than reactivating people. The
last active admin keeps their tokens. With SCIM, deprovisioning is
immediate (D18) and does not wait for a sign-in.

**D25. Loud startup, environment-free tests** (as D14). `ee.apps.load_scim`
imports the SCIM modules in `ready()` and turns a failure into
`ImproperlyConfigured`; SCIM has no dependency outside Django, DRF and
Knox. The SCIM tests pin `API_URL` (the Tenant URL comes from it).

## Audit streaming (feature `audit_streaming`)

**D26. Transactional outbox, not a cursor.** A post_save receiver (connected
by `ee`, so Community code is unchanged) writes one `AuditStreamPending` row
per enabled destination in the same transaction as the audit entry. A
"last id delivered" cursor would lose events: ids are allocated before
commit, so a long transaction can commit an id below one already sent.
Rows cascade with the audit entry, so retention also bounds the queue.
`bulk_create` of audit entries would bypass the receiver; no code path
uses it outside the demo seed.

**D27. At least once, ordered per destination, never dropped.** Delivery
sends due events in id order, in batches of 200, under a per-destination
row lock (`FOR NO KEY UPDATE SKIP LOCKED`, so new outbox rows, which only
take KEY SHARE, never wait). Failures back off 30 s → 1 h; the beat task
retries every minute. The event id is stable across retries for
deduplication. No event is dropped for age or queue size (known gap: a
destination down for long keeps the queue growing until retention).

**D28. Two transports: syslog and HTTPS.** Syslog RFC 5424 over TLS (RFC
5425, octet counting), TCP or UDP covers rsyslog, syslog-ng, QRadar,
ArcSight and the Sentinel forwarder. HTTPS with three bodies (JSON array,
NDJSON, Splunk HEC) and a configurable header covers Splunk, Datadog,
Vector, Logstash and webhooks. Not CEF/LEEF (known gap), no vendor SDKs.

**D29. One JSON event schema (`serops.audit.v1`) for every transport.**
Syslog carries it as MSG, facility 13 (log audit), severity notice, or
warning for failed/denied/deactivate/revoke/delete actions; no structured
data (no private enterprise number to use). No UTF-8 BOM: Vector keeps it
in the message and JSON parsing downstream then fails (found in the live
test); RFC 5424 MSG-ANY allows its absence.

**D30. Outbound policy as for every integration.** HTTPS through
`GuardedSession`, redirects not followed. Syslog resolves the host once,
checks each address with `validate_outbound_url` and connects to the
checked address (no DNS rebinding between check and connect), trying
each allowed address in turn (a host listing IPv6 first, such as
"localhost" on CI runners, still reaches an IPv4-only collector); TLS 1.2+,
host name verified, optional private CA (both kinds). Plain http only to a
private address on an install that allows private destinations.

**D31. Turning a stream off is itself streamed.** Disabling or removing a
destination is recorded while it is still on and delivered synchronously
before the change, so a SIEM sees the stream stop instead of going quiet.
Without the license, destinations can be turned off and removed (never
stuck sending), not added or changed; nothing is queued or sent, and
events already queued go out when a license returns.

**D32. Admins only, secrets write-only.** Reading the list takes
`team.manage` (the audit log's permission); writing takes every admin
permission, since a destination receives the whole audit trail. Header
value and signing secret are encrypted (`rotate_secrets` covers them) and
never returned. The HMAC signature (`X-SerOps-Signature`, over
"<timestamp>.<body>") lets a receiver reject forged or replayed posts.

**D33. Celery wiring only when ee/ is present.** The beat entry and routes
(queue `normal`, consumed by every worker in the chart and quick-start) are
added in `api/celery.py` behind `find_spec('ee')`, like the app in
settings, so a Community worker never receives a task it does not know.
`ee.apps.load_audit_streaming` imports the modules at startup and fails
loudly (as D14, D25).
