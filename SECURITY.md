# Security Policy

## Reporting a Vulnerability

Please **do not open a public GitHub issue** for security vulnerabilities.

Email **security@serops.ai** (PGP key on request) with:

- A description of the issue and its impact
- Steps to reproduce (or a minimal proof of concept)
- The affected version(s) or commit hashes
- Any suggested fix

You can expect:

| Stage | Timeline |
|---|---|
| Acknowledgement of receipt | Within **24 hours** |
| Initial triage + severity assessment | Within **72 hours** |
| Fix released for **HIGH / CRITICAL** issues | Within **30 days** |
| Fix released for **MEDIUM / LOW** issues | Within the next scheduled release |

Once a fix is released we will publish a security advisory on the
GitHub Security Advisories tab and credit reporters who wish to be
named.

## Supported Versions

We publish security updates for:

- The current `main` branch
- The most recent tagged release

Older versions receive fixes only for CRITICAL severity issues.

## Scope

In scope: everything in this repository — `backend/`, `frontend/`, `docs/` and
the deployment manifests under `deploy/`.

Out-of-scope:

- Vulnerabilities in third-party dependencies unless SerOps ships a
  vulnerable configuration — report those upstream.
- The public demo (serops.ai) — we run it read-only for evaluation.
  Denial-of-service against the demo is not eligible for disclosure
  credit.
- Social engineering, phishing, physical access.

## Release integrity

SerOps is developed on GitLab (gitlab.com/serops/serops) and mirrored to
GitHub (github.com/getserops/serops) by a maintainer, commit for commit,
after a secrets scan and a deny-list check of the tree. Images and the Helm
chart are built and published by the GitHub Actions workflows in this
repository, from `main` (images tagged `main`, `<sha>` and `edge`) and from
release tags `v*` (`<version>`, `<major>.<minor>`, `<sha>` and `latest`).
`latest` only moves with a release tag. Publishing needs write access to
`main` or the right to create a `v*` tag; both are held by the maintainers
only.

Every published image is scanned before the push (a fixable CRITICAL or
HIGH finding blocks the release), carries an SPDX SBOM and SLSA provenance
attestation, is signed with [cosign](https://docs.sigstore.dev) keyless
(the certificate names this repository and the `docker.yml` workflow) and
attested through GitHub artifact attestations. The chart pushed to
`oci://ghcr.io/getserops/charts/serops` is signed the same way.

Verify before you run (cosign 3; cosign 2.4 and older do not find these
signatures):

```bash
# Image signature (replace the tag you pull)
cosign verify ghcr.io/getserops/backend:1.3.1 \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp '^https://github.com/getserops/serops/\.github/workflows/docker\.yml@refs/tags/v'

# GitHub attestation (provenance): which commit and workflow built it
gh attestation verify oci://ghcr.io/getserops/backend:1.3.1 --owner getserops

# SBOM and SLSA provenance attached to the image
docker buildx imagetools inspect ghcr.io/getserops/backend:1.3.1 \
  --format '{{ json .SBOM }}'

# Helm chart. A tag publishes it; a failed publish is redone by hand from
# main without moving the tag (chart 1.3.0 was), hence both refs.
cosign verify ghcr.io/getserops/charts/serops:1.3.1 \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp '^https://github.com/getserops/serops/\.github/workflows/helm-release\.yml@refs/(tags/v|heads/main$)'
```

Every GitHub Action the workflows use is pinned to a commit SHA, and
Dependabot opens the bumps.

## Coordinated Disclosure

We follow a **90-day disclosure window** from the day we receive a
report. If we cannot ship a fix within that window we will notify the
reporter and agree an extension. Reporters are free to publish after
the window if we have not shipped a fix and have not requested an
extension.

## Bounty

SerOps is bootstrapped and does not currently run a paid bounty
programme. Public credit + a spot in the release notes are what we
can offer today. This may change once the project has commercial
funding — check back here for updates.
