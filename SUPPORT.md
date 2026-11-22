# Support

Where to go depends on what you need. This file sums up
[Support and security](https://serops.ai/docs/security/support/) in the
documentation. If the two ever differ, that page applies, together with the
documents it links to.

## Where to ask

| You have | Go to |
|---|---|
| A question, an idea, or a setup you want to share | [GitHub Discussions](https://github.com/getserops/serops/discussions) |
| A bug | [GitHub issues](https://github.com/getserops/serops/issues), with the bug report form |
| A feature request | [GitHub issues](https://github.com/getserops/serops/issues), with the feature request form |
| A vulnerability | **security@serops.ai**. Never open a public issue for one; see [SECURITY.md](SECURITY.md) |
| A question about a paid or commercial license | **licensing@serops.ai** |
| A paid license and a support question | **support@serops.ai** |

## SerOps Community

Questions and bugs about SerOps Community are handled in public, in
Discussions and issues.

Two pages answer most install questions; read them before you write:

- [Troubleshooting](https://serops.ai/docs/troubleshooting/)
- [Upgrading](https://serops.ai/docs/deployment/upgrading/)

A useful bug report gives:

- the SerOps version, from `curl https://your-serops-host/api/version/`;
- how you deploy it (Docker Compose or Helm);
- the integrations and the AI provider in use;
- the steps to reproduce the bug;
- the logs, with secrets, tokens and personal data removed.

## Paid licenses (Business and Enterprise)

- **Business:** support is by email to **support@serops.ai**, during
  Business Hours. We target a first reply within one Business Day. This is
  a target, not a guarantee, and not a service level.
- **Enterprise:** support (channels, hours and response times) is as written
  in your order. Without a stated level, the Business terms apply.
- **Business Hours** are 09:00 to 18:00 Central European Time, Monday to
  Friday, except public holidays in Tunisia.
- There is no 24×7 support today.

Source: [Enterprise Terms, section 7](https://serops.ai/docs/legal/enterprise-terms/#5-support-and-updates).

## Supported versions

Security fixes go to the current `main` branch and to the most recent
release. Older releases get fixes only for critical issues
([SECURITY.md](SECURITY.md#supported-versions)).

Releases follow Semantic Versioning: a patch release only fixes bugs, a
minor release adds features and removes none, and a major release is reached
through the last minor release of the major before it
([Versioning](https://serops.ai/docs/deployment/versioning/)). What changed
in each release, and how to upgrade, is in the
[changelog](https://serops.ai/docs/changelog/).

## What is planned

See [ROADMAP.md](ROADMAP.md).
