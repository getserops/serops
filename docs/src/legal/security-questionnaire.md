---
seo_title: "Pre-filled security questionnaire"
description: "SerOps answers to a security questionnaire, grouped by the domains of the CSA Cloud Controls Matrix v4, each with the document that supports it. Yes, No, Partial, Not yet, Planned or Not applicable."
---
# Pre-filled security questionnaire

Part of the [security pack](security-pack.md). The questions follow the 17
domains of the [CSA Cloud Controls Matrix v4](https://cloudsecurityalliance.org/research/cloud-controls-matrix),
the framework behind the CAIQ questionnaire, so you can map each answer to
your own framework. Download it as a spreadsheet:
[serops-security-questionnaire.csv](../assets/security-pack/serops-security-questionnaire.csv).

**How to read it.** SerOps is software you run yourself: the infrastructure,
its operation and your data are yours, so many controls written for hosted
services are answered *Not applicable*. Every *Yes* is backed by the document
in the last column. *Not yet* and *Planned* mean exactly that. These answers
describe SerOps 1.5.1. Accepting them as they are keeps you on Business;
your own questionnaire filled in is Enterprise
([pricing](https://serops.ai/pricing)).

<!-- The CSV is generated from this table: python3 docs/tools/questionnaire_csv.py (--check fails when it is stale). -->

| ID | Domain | Question | Answer | Source |
|---|---|---|---|---|
| A&A-01 | Audit and assurance | Do you hold an independent certification or audit report (SOC 2, ISO 27001)? | No. SerOps is software you run yourself; SerOps the company holds none of your production data. | [Vendor facts](vendor-facts.md) |
| A&A-02 | Audit and assurance | Has an external penetration test been done? | Planned, not done yet. Its report will be available to customers under NDA. | [Support and security](../security/support.md) |
| AIS-01 | Application and interface security | Is every change tested automatically before release? | Yes. The test suites run in CI on every change, and Community is also tested with the `ee/` directories removed. | [Testing](../development/testing.md), [license](../license.md) |
| AIS-02 | Application and interface security | Is source code scanned for vulnerabilities? | Yes. CodeQL and dependency review run on the public repository. | `.github/workflows/codeql.yml`, `dependency-review.yml` |
| AIS-03 | Application and interface security | How is the API authenticated? | Token authentication (`Authorization: Token`), tokens valid 30 days, with rate limits on sign-in. | [Authentication](../security/authentication.md#token-authentication) |
| BCR-01 | Business continuity | What happens to customers if the vendor stops trading? | The product keeps running: license keys are checked offline. The full source is public (Community under AGPL-3.0, the paid features under the SerOps Enterprise License). | [Vendor facts](vendor-facts.md#continuity) |
| BCR-02 | Business continuity | Are customer data backed up? | Not applicable: the data is in your PostgreSQL. The docs describe backup and restore. | [Backup and restore](../deployment/backup-restore.md) |
| CCC-01 | Change control | Are releases versioned and documented? | Yes. Semantic versioning and a changelog for every release. | [Versioning](../deployment/versioning.md), [changelog](../changelog.md) |
| CCC-02 | Change control | Can the customer verify what it installs? | Yes. Images and the Helm chart are signed with cosign and carry an SBOM and SLSA provenance. | [Support and security](../security/support.md) |
| CEK-01 | Cryptography and key management | Are secrets encrypted at rest? | Yes. AI keys, integration credentials and webhook URLs are encrypted with a key you hold (`SEROPS_ENCRYPTION_KEY`) and never returned by the API. | [Data protection](../security/data-protection.md#secrets-at-rest) |
| CEK-02 | Cryptography and key management | Is data encrypted in transit? | You terminate TLS at your ingress or proxy; the Compose distribution includes Caddy for TLS. | [Production deployment](../deployment/production.md) |
| CEK-03 | Cryptography and key management | How are passwords stored? | Django's salted PBKDF2 hashing. | Django default, `backend/api/settings.py` |
| DCS-01 | Datacenter security | Physical security of the hosting facilities? | Not applicable: SerOps runs on your infrastructure. | [Security overview](../security/overview.md#architecture) |
| DSP-01 | Data security and privacy | What customer data does the vendor receive? | None by design. Only what you send for support, used for that support and deleted when no longer needed. | [Vendor facts](vendor-facts.md#what-serops-can-access) |
| DSP-02 | Data security and privacy | Does the software send telemetry to the vendor? | No. No usage statistics, error reports or update check. | [Vendor facts](vendor-facts.md#telemetry) |
| DSP-03 | Data security and privacy | Is personal data minimised before it reaches an AI provider? | Yes, by pattern-based masking on every AI call; if masking fails, nothing is sent. Formats it does not recognise pass through. | [Data protection](../security/data-protection.md#current-limits) |
| DSP-04 | Data security and privacy | Can the product run without sending data outside the network? | Yes, with a local model through Ollama. | [Security overview](../security/overview.md#what-leaves-your-network) |
| DSP-05 | Data security and privacy | Is retention configurable? | Yes, by the customer. | [Data retention](../admin/data-retention.md) |
| GRC-01 | Governance, risk and compliance | Is there a named security contact? | Yes: security@serops.ai. | [SECURITY.md](https://github.com/getserops/serops/blob/main/SECURITY.md) |
| IAM-01 | Identity and access management | Is single sign-on supported? | Yes. OpenID Connect in Community; SAML 2.0 with a paid license. | [Authentication](../security/authentication.md), [SAML](../enterprise/saml.md) |
| IAM-02 | Identity and access management | Is multi-factor authentication supported? | Not built in. Use your identity provider's, through single sign-on. | [Security overview](../security/overview.md#access-control) |
| IAM-03 | Identity and access management | Can single sign-on be required for every user? | Yes, for members; admins keep a password as a way back in. | [Require single sign-on](../security/authentication.md#require-single-sign-on) |
| IAM-04 | Identity and access management | Is user provisioning automated? | Yes, with SCIM 2.0 (paid license). | [SCIM](../enterprise/scim.md) |
| IAM-05 | Identity and access management | Is access role-based? | Yes. Admin, user and viewer; custom roles and per-project access with a paid license. | [Team](../admin/team.md) |
| IAM-06 | Identity and access management | Do sessions time out? | Yes, after an inactivity period the admin sets, 8 hours by default. | [Authentication](../security/authentication.md#session-management) |
| IAM-07 | Identity and access management | Are failed sign-ins limited? | Yes, rate-limited per account and address. | [Authentication](../security/authentication.md#token-authentication) |
| IPY-01 | Interoperability and portability | Can data be exported? | Yes. Audit logs and analyses export to CSV; everything is in your PostgreSQL. | [Compliance](../security/compliance.md) |
| IVS-01 | Infrastructure and virtualisation security | Do the containers run as non-root? | Yes (backend user 10001, front end user 101). | `backend/Dockerfile`, `frontend/Dockerfile` |
| IVS-02 | Infrastructure and virtualisation security | Is network access restricted on Kubernetes? | Partly. The Helm chart enables a NetworkPolicy by default: inbound traffic only from your ingress controller; outbound is open by default, because SerOps connects to the backends you configure, and you can narrow it. | [Helm chart](../deployment/helm.md) |
| IVS-03 | Infrastructure and virtualisation security | Are tenants isolated? | Yes, at the query level, with automated tests. | [Multi-tenancy](../architecture/multi-tenancy.md) |
| LOG-01 | Logging and monitoring | Are security events logged? | Yes. Sign-ins, failed sign-ins, refused requests and administrative changes. | [Compliance](../security/compliance.md) |
| LOG-02 | Logging and monitoring | Can logs be sent to a SIEM? | Yes, in real time over syslog with TLS or HTTPS (paid license). | [Audit streaming](../enterprise/audit-streaming.md) |
| LOG-03 | Logging and monitoring | Is the audit log tamper-evident? | Not yet. Planned for Community. | [Open source promise](../open-source-promise.md) |
| SEF-01 | Security incident management | How are vulnerabilities reported and handled? | security@serops.ai. Acknowledgement within 24 hours, triage within 72 hours, a fix for high and critical issues within 30 days, then a public advisory. | [SECURITY.md](https://github.com/getserops/serops/blob/main/SECURITY.md) |
| STA-01 | Supply chain | Do you provide an SBOM? | Yes, an SPDX SBOM with each image. | [Support and security](../security/support.md) |
| STA-02 | Supply chain | Which sub-processors handle customer data? | None for the data in SerOps: it stays on your infrastructure, and the AI provider is yours. | [Vendor facts](vendor-facts.md#personal-data) |
| TVM-01 | Threat and vulnerability management | Are images scanned before release? | Yes. Trivy; a critical or high finding with a fix blocks the release. | [Vendor facts](vendor-facts.md#release-integrity) |
| TVM-02 | Threat and vulnerability management | Which releases get security fixes? | The current release; older releases get fixes for critical issues only. | [Vendor facts](vendor-facts.md#vulnerabilities-and-testing) |
