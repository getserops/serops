---
seo_title: "Audit streaming to a SIEM"
description: "Stream every SerOps audit event to your SIEM as it happens: syslog over TLS (RFC 5424), Splunk HEC, Datadog, or any HTTPS collector. Event format, delivery guarantees, signatures and troubleshooting."
---
# Audit streaming to a SIEM

!!! info "SerOps Enterprise"
    Audit streaming needs an Enterprise license that lists `audit_streaming`
    (**Settings → Enterprise license**). Without one nothing is sent; your
    destinations are kept and can still be turned off or removed. The audit
    log itself, its filters and its CSV export are part of every edition:
    see [Audit trail](../admin/team.md#audit-trail).

SerOps sends each audit event (sign-ins, role and team changes, SSO and
SCIM provisioning, settings changes, API key changes…) to your SIEM within
seconds of it being recorded, so it sits next to the rest of your security
data and SerOps admins cannot quietly remove it.

## Set it up

1. **Settings → Audit Streaming → Add a destination.**
2. Choose **HTTPS** or **Syslog** and fill in the destination (below).
3. **Save**, then **Send a test event**: SerOps sends one synthetic event
   (`AUDIT_STREAM_TEST`) and tells you whether the destination accepted it.

Adding, changing or removing a destination takes every permission of an
admin; reading the list takes the audit log's permission. Every change to a
destination is itself an audit event, and a destination receives its own
creation first. When a destination is turned off or removed, that change is
sent to it before it stops, so the SIEM sees the stream end.

## Destinations

### Syslog

RFC 5424 messages, over **TCP with TLS** (RFC 5425, port 6514, the
default), plain **TCP** (port 514) or **UDP** (port 514). Over TCP, messages
are framed with octet counting.

- **Host** and **Port** of your syslog server or forwarder (rsyslog,
  syslog-ng, Vector, a QRadar or ArcSight collector, the Azure Monitor agent
  on a Linux forwarder for Microsoft Sentinel).
- **CA certificate**: when the server's certificate is signed by your own CA,
  paste that CA (PEM). Empty uses the public CAs of the SerOps image. The
  host name must match the certificate.

Each message:

```text
<109>1 2026-11-14T09:30:12.123456Z serops.acme.example serops - LOGIN - {"schema":"serops.audit.v1",...}
```

- Facility 13, *log audit*. Severity *notice* (5), or *warning* (4) for
  failed or denied sign-ins, deactivations, revocations and deletions.
- APP-NAME `serops`, MSGID the action (`LOGIN`, `TEAM_ROLE_CHANGE`…),
  HOSTNAME the host of your SerOps URL.
- MSG: the event as JSON (below), UTF-8 without a byte-order mark.

Prefer TLS. UDP gives no delivery check: SerOps cannot tell whether a
message arrived, so use it only towards a forwarder on the same network.

### HTTPS

SerOps POSTs batches of up to 200 events.

| Format | Body | For |
|---|---|---|
| JSON array | `[{event}, {event}]` | Datadog, Vector, Logstash `http` input, most webhooks |
| Newline-delimited JSON | one event per line | Vector, Fluent Bit, Loki-style collectors |
| Splunk HEC | `{"time":…,"host":…,"source":"serops","sourcetype":"serops:audit","event":{event}}` back to back | Splunk HTTP Event Collector |

- **Authorization header**: a header name and its value, for example
  `Authorization` / `Splunk <token>`, `Authorization` / `Bearer <token>`, or
  `DD-API-KEY` / `<key>`. The value is stored encrypted and never shown again.
- **Signing secret** (optional): each request then carries
  `X-SerOps-Timestamp` (Unix seconds) and `X-SerOps-Signature: sha256=<hex>`,
  the HMAC-SHA256 of `<timestamp>.<body>` with the secret.
- **CA certificate**: as for syslog.

HTTPS is required. Plain `http://` is accepted only for a collector on a
private network, and only when the install allows private destinations.
Redirects are not followed: a `3xx` answer counts as a failure.

**Splunk.** URL `https://<splunk>:8088/services/collector/event`, format
*Splunk HEC*, header `Authorization` = `Splunk <HEC token>`.

**Datadog.** URL `https://http-intake.logs.datadoghq.com/api/v2/logs`
(`datadoghq.eu` for the EU site), format *JSON array*, header `DD-API-KEY` =
your API key.

**Elastic.** Elasticsearch's `_bulk` API needs action lines, so send to an
Elastic Agent, Logstash (`http` input) or Vector in front of it, with *JSON
array* or *Newline-delimited JSON*.

To check a signature on the receiving side:

```python
import hashlib, hmac, time

def valid(secret: bytes, timestamp: str, body: bytes, signature: str) -> bool:
    if abs(time.time() - int(timestamp)) > 300:
        return False  # replayed or delayed
    expected = 'sha256=' + hmac.new(secret, timestamp.encode() + b'.' + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
```

## Event format

Every destination receives the same JSON object (schema `serops.audit.v1`):

```json
{
  "schema": "serops.audit.v1",
  "id": 4211,
  "time": "2026-11-14T09:30:12.123456Z",
  "organisation": {"id": 3, "name": "Acme"},
  "action": "TEAM_ROLE_CHANGE",
  "action_label": "Team Role Changed",
  "outcome": "success",
  "actor": {"type": "user", "id": 17, "email": "ana@acme.example"},
  "client": {"ip": "203.0.113.7", "user_agent": "Mozilla/5.0 …"},
  "details": {"affected_user": "bo@acme.example", "role": "admin", "old_role": "user"},
  "source": {"product": "SerOps", "version": "1.4.0", "host": "serops.acme.example"}
}
```

| Field | Meaning |
|---|---|
| `id` | The audit entry's id: unique on the install, the same on every retry. Use it to drop duplicates. |
| `time` | When SerOps recorded it, UTC. |
| `action`, `action_label` | What happened; the list is in **Settings → Audit Log** (filter by action). |
| `outcome` | `failure` for `*_FAILED` and `*_DENIED` actions, else `success`. |
| `actor` | `user` (with id and email), `scim` (the identity provider, through SCIM) or `system`. |
| `client` | Address and browser of the request, when there was one. |
| `details` | What the audit log shows for this action. |

New fields may be added to `serops.audit.v1`; existing ones keep their
meaning. A change that breaks that gets a new schema name.

## Delivery

- **In real time.** An event is queued in the same database transaction that
  records it, and sent as soon as that transaction commits. An action that
  fails and rolls back is never sent.
- **At least once, in order.** Events go to each destination in the order
  they were recorded. If the destination fails (unreachable, TLS error, a
  non-2xx answer), the batch waits and is retried after 30 seconds, then
  60, 120… at most every hour, until it is accepted. A retry can repeat an
  event the destination had already received: drop duplicates by `id`.
- **Nothing is dropped.** Events wait as long as needed. They leave the queue
  when delivered, or when the audit entry itself is deleted by the audit
  retention policy ([Audit log retention](../admin/data-retention.md#audit-log-retention)).
- **A slow or failing destination does not slow SerOps down**: the request
  that records an event never waits for delivery (except turning a
  destination off or removing it, which sends that change first), and each
  destination is delivered to on its own.

The destination list shows, for each one, whether it is delivering, how many
events wait and the last error.

## API

Admin endpoints, with a SerOps session or API token:

| Endpoint | |
|---|---|
| `GET /api/ee/audit-streams/` | Destinations, their state, and `licensed` |
| `POST /api/ee/audit-streams/` | Add one: `name`, `kind` (`http` or `syslog`), then `url`, `http_format`, `auth_header_name`, `auth_header_value`, `signing_secret`, or `host`, `port`, `transport` (`tls`, `tcp`, `udp`); `ca_certificate`, `enabled` |
| `GET`, `PUT`, `DELETE /api/ee/audit-streams/{id}/` | One destination. In `PUT`, a secret omitted is kept, `""` removes it. |
| `POST /api/ee/audit-streams/{id}/test/` | Send a test event: `{"ok": true}` or `{"ok": false, "error": "…"}` |

Secrets are never returned: `auth_header_configured` and
`signing_secret_configured` say whether they are set.

## Troubleshooting

**"TLS certificate not trusted".** The server's certificate is signed by a
CA the SerOps image does not know: paste that CA in **CA certificate**. Check
also that the host you entered is a name in the certificate.

**"The destination answered HTTP 401" or 403.** The authorization header or
its value is wrong (Splunk wants `Splunk <token>`, not `Bearer`).

**"Destination refused by the outbound policy".** The address is a cloud
metadata or link-local address, which SerOps never contacts, or a private
address on an install that only allows public destinations
(`SEROPS_OUTBOUND_ALLOW_PRIVATE=false`).

**Events wait but nothing is retried.** Retries are run by the Celery worker
and beat (the `normal` queue): check both are running.
