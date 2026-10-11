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
