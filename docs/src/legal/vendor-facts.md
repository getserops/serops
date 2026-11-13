---
seo_title: "Vendor and security facts"
description: "For procurement and security reviews: who licenses SerOps, what SerOps can and cannot access, telemetry, release integrity, continuity, support, personal data, and how employees are counted."
---
# Vendor and security facts

For procurement and security reviews of SerOps Enterprise. Each point links
to the document that governs it; where this page and the
[Enterprise Terms](enterprise-terms.md) differ, the Terms apply.

## Who you contract with

- **Licensor:** SerOps, a Tunisian single-member limited liability company
  (SUARL), registered under RNE 1750909V, Ariana Center, Block C, Office
  C408, Avenue du 18 Janvier, 2080 Ariana Ville, Tunisia.
- **Contract:** the [Enterprise Terms](enterprise-terms.md) plus your order.
  Tunisian law and the courts of Tunis, unless the order states otherwise.
- **Ownership of the code:** the founder wrote the code. A written
  assignment of its copyright from the founder to SerOps is signed in
  December 2026, before the first Enterprise order is signed. External
  contributions come in under the
  [Contributor License Agreement](https://github.com/getserops/serops/blob/main/CLA.md).

## What SerOps can access

- **Nothing of yours, by design.** SerOps is self-hosted: it runs on your
  infrastructure, and your logs, metrics, traces, code and analyses stay
  there. We have no account on your systems and no remote access to them.
- **You see something only if you send it.** When you share data with us
  for support, we use it only for that support and delete it when it is no
  longer needed ([Terms, section 6](enterprise-terms.md#6-your-data)).
- **AI runs on your key.** SerOps calls the AI provider you configure, with
  your own API key, under your agreement with that provider. With a local
  model (Ollama) nothing leaves your network. Secrets and personal data are
  redacted from logs and code diffs before they reach a provider
  ([data protection](../security/data-protection.md)).

## Telemetry

**None.** SerOps sends nothing to us: no usage statistics, no error
reports, no update check. The Enterprise license key is a signed file
checked offline (Ed25519): no license server and no network call, so
SerOps also runs air-gapped. When a key expires, Enterprise features switch
off; no data is deleted and Community features keep working.

## Release integrity

- Images and the Helm chart are built in public GitHub Actions workflows
  from the tagged commit.
- Each image is scanned with Trivy (a critical or high finding blocks the
  release), carries an SPDX SBOM and SLSA provenance, is signed with
  cosign (keyless) and attested with GitHub artifact attestations. The
  chart is signed the same way.
- The commands to verify all of this are in
  [SECURITY.md](https://github.com/getserops/serops/blob/main/SECURITY.md#release-integrity).

## Vulnerabilities and testing

- Report to **security@serops.ai**. Acknowledgement within 24 hours,
  triage within 72 hours, a fix for high and critical issues within 30
  days, then a public advisory
  ([SECURITY.md](https://github.com/getserops/serops/blob/main/SECURITY.md)).
- Security fixes go to the current release; older releases get fixes for
  critical issues only.
- An external penetration test is planned. Its report will be available to
  customers under NDA.

## Continuity

The source of everything you run is public: the Community edition under the
AGPL-3.0, and the Enterprise code in the same repository under the
[SerOps Enterprise License](https://github.com/getserops/serops/blob/main/backend/ee/LICENSE).
If SerOps stopped trading, you would keep the full source of the version you
run, the right to build and modify it, and every Community feature under the
AGPL. See the [open source promise](../open-source-promise.md) and the
[license page](../license.md).

## Support

- By email to **support@serops.ai**, during Business Hours: 09:00 to 18:00
  Central European Time, Monday to Friday, excluding public holidays in
  Tunisia ([Terms, section 5](enterprise-terms.md#5-support-and-updates)).
- Business band: standard terms, best effort, security review from public
  documentation.
- Enterprise and Strategic bands: a business-hours response time written
  into the order.

## Personal data

- In your SerOps installation, you are the controller and SerOps (the
  company) is not a processor: we do not receive that data.
- SerOps processes only the contact details needed to license and support
  you: the names and email addresses on the order, invoicing details, and
  the messages you send us. See the
  [privacy policy](https://serops.ai/privacy).

## How employees are counted

The Business, Enterprise and Strategic bands are set by Headcount, never by
seats ([Terms, section 2](enterprise-terms.md#2-order-and-subscription)):

- **Headcount** is the total number of employees of the organisation that
  signs, plus the employees of each affiliate (more than 50% common control)
  that uses the Enterprise features.
- You declare it on the order form, and again at each renewal. It is a
  commercial declaration.
- **Nothing is counted in the product.** SerOps does not count or limit
  users, projects, services or data.
- A change during a term does not change that term's price; the band is
  reviewed at renewal. If the number declared was too low, the difference
  is due for that term.
