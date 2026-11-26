---
seo_title: "Support and security: where to ask, how to report a vulnerability"
description: "Where to ask a question about SerOps, where to report a bug, how to report a vulnerability privately, and how to verify the signatures, SBOM and provenance of the images and the Helm chart."
---
# Support and security

Where to go, depending on what you need. Nothing on this page is new policy:
each point links to the document that governs it.

## Where to ask

| You have | Go to |
|---|---|
| A question, an idea, a setup you want to share | [GitHub Discussions](https://github.com/getserops/serops/discussions) |
| A bug | [GitHub issues](https://github.com/getserops/serops/issues) (pick the bug report form) |
| A feature request | [GitHub issues](https://github.com/getserops/serops/issues) (pick the feature request form) |
| A vulnerability | **security@serops.ai**, never a public issue (see below) |
| A question about a paid or commercial license | **licensing@serops.ai** |
| A paid license and a support question | **support@serops.ai** |

For SerOps Community, questions and bugs are handled in public, through
Discussions and issues.

Support for paid license holders (Business and Enterprise) is by email,
during Business Hours: 09:00 to 18:00 Central European Time, Monday to
Friday, excluding public holidays in Tunisia. On Business, the first reply
is targeted within one working day: a target, not a guarantee. On
Enterprise, the level is the one written in your contract
([Enterprise terms, section 7](../legal/enterprise-terms.md#5-support-and-updates)).
There is no 24×7 support today.

Before you write, two pages answer most install questions:
[Troubleshooting](../troubleshooting.md) and
[Upgrading](../deployment/upgrading.md).

## Report a vulnerability

Do not open a public issue. Email **security@serops.ai** (PGP key on request)
with:

- a description of the issue and its impact;
- steps to reproduce, or a minimal proof of concept;
- the affected versions or commit hashes;
- a suggested fix, if you have one.

What happens next:

| Stage | Timeline |
|---|---|
| Acknowledgement of receipt | within 24 hours |
| Triage and severity assessment | within 72 hours |
| Fix released for high and critical issues | within 30 days |
| Fix released for medium and low issues | in the next scheduled release |

After the fix is released, a security advisory is published on the
repository's GitHub Security Advisories tab, and reporters who wish to be
named are credited. Disclosure is coordinated over a 90-day window from the
day the report is received. There is no paid bounty today.

Security fixes go to the current `main` branch and the most recent release;
older releases get fixes for critical issues only.

The full policy, with what is in and out of scope, is
[SECURITY.md](https://github.com/getserops/serops/blob/main/SECURITY.md) in
the repository. If this page and that file ever differ, the file applies.

## Signing, SBOM and provenance

What every published image carries, as described in
[SECURITY.md, "Release integrity"](https://github.com/getserops/serops/blob/main/SECURITY.md#release-integrity):

| | Status |
|---|---|
| Vulnerability scan before the push | Yes: a critical or high finding with an available fix blocks the release |
| SBOM | Yes: SPDX, attached to each image |
| Provenance | Yes: SLSA provenance attestation and GitHub artifact attestation |
| Signature | Yes: cosign, keyless; the certificate names the repository and the build workflow |
| Helm chart | Signed the same way |
| GitHub Actions used by the workflows | Each pinned to a commit SHA |
| External penetration test | Planned, not done yet |

Images and the chart are built and published by the GitHub Actions workflows
in the public repository, from `main` and from release tags. `latest` moves
only with a release tag.

To check an image before you run it (cosign 3; cosign 2.4 and older do not
find these signatures), replace the tag with the one you pull:

```bash
# Signature
cosign verify ghcr.io/getserops/backend:1.5.6 \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp '^https://github.com/getserops/serops/\.github/workflows/docker\.yml@refs/tags/v'

# Provenance: which commit and workflow built it
gh attestation verify oci://ghcr.io/getserops/backend:1.5.6 --owner getserops

# SBOM attached to the image
docker buildx imagetools inspect ghcr.io/getserops/backend:1.5.6 \
  --format '{{ json .SBOM }}'
```

The command for the Helm chart is in SECURITY.md, next to these.

## Related pages

- [Data protection](data-protection.md): what is masked before anything
  reaches an AI provider.
- [Vendor and security facts](../legal/vendor-facts.md): for procurement and
  security reviews.
- [Open source promise](../open-source-promise.md).
