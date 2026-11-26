---
seo_title: "Security overview"
description: "SerOps security in two pages: architecture, data flow, what leaves your network, masking, access control, audit, license-key checking and how to report a vulnerability."
---
# Security overview

Part of the [security pack](../legal/security-pack.md). Two pages for a security
review: every point links to the page or file that shows it. Where this page
and the [Enterprise Terms](../legal/enterprise-terms.md) differ, the Terms apply.

## Architecture

SerOps is **self-hosted**: it runs on your infrastructure, with
[Docker Compose](../deployment/production.md) or the
[Helm chart](../deployment/helm.md). There is no hosted SerOps service today.

- **Components:** an API (Django), a web front end, Celery workers and a
  scheduler, PostgreSQL and Redis. With Helm, PostgreSQL and Redis are yours.
- **Containers** run as non-root users (backend user 10001, front end user
  101: `backend/Dockerfile`, `frontend/Dockerfile`). The Helm chart enables a
  NetworkPolicy and a PodDisruptionBudget by default.
- **We have no access.** SerOps the company has no account on your systems
  and no remote access to them ([vendor facts](../legal/vendor-facts.md#what-serops-can-access)).

## Data flow

1. For each time window, SerOps reads what you connected: logs, CPU and
   memory metrics and traces from your observability backends, and commits,
   pipelines and deploys from your source control and CI/CD.
2. It deduplicates, detects anomalies and **masks secrets and personal data**.
3. It asks the AI provider **you** configured, with **your** key, for a root
   cause: one call per window. With Sentinel in active mode (the default),
   quiet windows skip the AI call.
4. Results (issues, analyses, chat) are stored in your PostgreSQL.

SerOps never clones or indexes a repository: it reads only the diffs of
commits deployed in the window ([data protection](data-protection.md#what-serops-reads-from-your-repositories)).

## What leaves your network

- **To your AI provider:** the masked context of each analysis, under your
  own agreement with that provider. With a local model through Ollama,
  nothing leaves your network.
- **To your integrations:** the queries SerOps makes to the backends you
  connected. Cloud metadata and link-local addresses are always refused;
  private addresses are allowed by default, because a self-hosted install
  reaches its own backends there, and an install shared by several
  organisations can refuse them ([outbound requests](data-protection.md#outbound-requests)).
- **To SerOps the company: nothing.** No usage statistics, no error reports,
  no update check ([vendor facts](../legal/vendor-facts.md#telemetry)).

## Masking

Every AI call (analysis, chat, re-analysis, post-mortem drafts) goes through
one masking step, for the prompt and the system prompt alike. If masking
fails, the call stops and **nothing is sent**. Masking is pattern-based:
formats it does not recognise pass through unless they match the generic
secret patterns. The patterns and the limits are listed in
[data protection](data-protection.md#current-limits).

## Access control

- **Sign-in:** passwords (Django's salted PBKDF2 hashing), or single sign-on
  with OpenID Connect (Community) or SAML 2.0 (paid license). Groups from
  your identity provider can set roles and teams.
  [Require single sign-on](authentication.md#require-single-sign-on) refuses
  password sign-in for members; admins keep a password as a way back in.
- **Multi-factor authentication** is not built in: use your identity
  provider's, through single sign-on.
- **Provisioning:** SCIM 2.0 from your identity provider (paid license).
- **Roles:** admin, user and viewer, with permissions checked on every
  request; custom roles and per-project access with a paid license.
- **Sessions** end after an inactivity period the admin sets (8 hours by
  default). Failed sign-ins are rate-limited
  ([authentication](authentication.md#token-authentication)).
- **Tenants:** several organisations on one installation are isolated at
  the query level ([multi-tenancy](../architecture/multi-tenancy.md)).
- **Secrets at rest** (AI keys, integration credentials, webhook URLs) are
  encrypted with a key you hold (`SEROPS_ENCRYPTION_KEY`) and never returned
  by the API. SCM and custom service tokens, infrastructure service connection
  strings and webhook signing secrets are the exception: they are stored in plain text
  ([secrets at rest](data-protection.md#secrets-at-rest)).

## Audit

The audit log records sign-ins, failed sign-ins, refused requests and
administrative changes, and exports to CSV
([compliance](compliance.md)). With a paid license it streams in real time
to a SIEM over syslog with TLS or HTTPS. Tamper evidence for the audit
export is **not yet** built; it is planned for Community
([open source promise](../open-source-promise.md)).

## License-key checking

A paid license is a signed file (Ed25519), checked offline against public
keys shipped in the release. There is no license server and no network
call, so SerOps also runs air-gapped. When a key expires, the paid features
switch off; no data is deleted and every Community feature keeps working.

## Release integrity

Images and the Helm chart are built in public GitHub Actions workflows from
the tagged commit. Each image is scanned with Trivy (a critical or high
finding with a fix blocks the release), carries an SBOM and SLSA provenance,
and is signed with cosign. CodeQL and dependency review run on the public
repository. How to verify: [support and security](support.md).

## Reporting a vulnerability

Email **security@serops.ai**, never a public issue. Acknowledgement within
24 hours, triage within 72 hours, a fix for high and critical issues within
30 days, then a public advisory
([SECURITY.md](https://github.com/getserops/serops/blob/main/SECURITY.md)).
An external penetration test is planned and has not been done yet.
