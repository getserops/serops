# Known gaps: Enterprise SAML, SCIM and audit streaming (1.4.0)

What the 2026-11-13 brief asked for and is not done, or done differently,
with the reason. Newest at the end.

## SAML 2.0

- **Single logout (SLO)**: not implemented (decision D9). Signing out of
  SerOps does not sign out of the identity provider.
- **Okta**: documented from Okta's documentation, not live-tested.
- **SP-initiated responses are not bound to the browser** that started the
  sign-in (decision D4); IdP-initiated sign-in can be turned off.
- **Signed AuthnRequests**: SerOps does not sign its requests (no identity
  provider among Entra ID, Okta, Keycloak requires it by default).
- **Entra ID token encryption** needs Entra ID P1/P2; covered by the unit
  test (AES-256-CBC, RSA-OAEP) and the Keycloak encrypted-assertion test.

## SCIM 2.0

- **Live tests**: not run against Entra ID or Okta yet. They need an app
  with provisioning at the identity provider, and a public URL for the local
  instance (owner's word on a temporary tunnel). Covered meanwhile by
  replaying the documented Entra ID and Okta request sequences
  (`ee/tests/test_scim_conformance.py`).
- **Not supported** (D21): filters other than `eq` on the lookup
  attributes, bulk, sorting, ETags, password changes.
- **Accounts are deactivated, never deleted** by SCIM (D18).
- **Community SSO deny** revokes sessions but leaves the account active
  (D24); full deprovisioning is SCIM.
- ~~"Planned: SCIM" on the open-source promise page and in the README~~:
  updated in the 1.4.0 wrap-up, on the owner's word (2026-11-14).

## Audit streaming

- **No CEF or LEEF** (D28). SIEMs that need them parse the JSON MSG instead,
  or a forwarder converts.
- **No age or size cap on the queue** (D27): a destination down for weeks
  keeps its events until the audit retention deletes them.
- **UDP has no delivery check**: a lost datagram is not retried.
- **Live-tested against Vector 0.42** (syslog TLS and TCP, HTTPS JSON with
  header and signature). Splunk HEC and Datadog are documented from their
  documentation, not live-tested.
- **Delivery of a disabled/removed destination's last event is best
  effort**: if it is unreachable at that moment, the change still applies
  and the event is not sent there.
