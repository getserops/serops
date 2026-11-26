---
seo_title: "License (AGPL-3.0)"
description: "SerOps is open source under the GNU AGPL-3.0; what that means for self-hosting, modifying and offering it as a service."
---
# License

SerOps is open-source software licensed under the **GNU Affero General Public License, Version 3** ("AGPL-3.0"). It covers the whole repository — backend (`backend/`), frontend (`frontend/`), deployment files (`deploy/`) and this documentation site (`docs/`) — except the Enterprise directories described [below](#enterprise-code-ee-directories).

Copyright © 2026 SerOps contributors.

The full license text is in the `LICENSE` file at the root of the repository, and available online at [gnu.org/licenses/agpl-3.0.html](https://www.gnu.org/licenses/agpl-3.0.html).

## What you can do freely (no permission needed)

- **Self-host SerOps** — download, install, and run it for your team, company, or personal use
- **Modify the code** for your own use, without publishing your changes
- **Fork the repository** and develop your own version
- **Distribute** modified or unmodified copies (with the AGPL license attached)
- **Use SerOps commercially** inside your own organisation

You do **not** need to contact us, sign anything, or ask permission for any of the above.

## What AGPL asks in return

Two obligations, only:

1. **Keep the license** — the `LICENSE` file, copyright notices, and change annotations must travel with any copy you redistribute.
2. **Share modifications you host to third parties** — if you modify SerOps and offer the modified version *as a network service to other users*, you must make the modified source code available to those users under AGPL-3.0.

The second point is the difference between AGPL and MIT/Apache: it closes the "someone runs a modified version as a SaaS without contributing back" gap.

For strictly internal use — even at a large company — the second obligation does not apply. Your internal deployment, modified or not, stays internal.

## When you might want a commercial license instead

The AGPL is a great fit for most users. Three cases need an agreement with us:

1. Your organisation's **policy rules out AGPL software**. Business includes a commercial license for internal use, as an alternative to the AGPL, for your organisation and the companies it controls.
2. You want to **build a product on SerOps**, embed it, redistribute it or run it for clients. A Business or Enterprise license does not cover this: it needs a separate written agreement, on request, with no public price ([Enterprise Terms, section 4.3](legal/enterprise-terms.md#4-license-key-and-use)).
3. You want **support or contractual terms**. Business comes with email support and the standard terms; an SLA, your own contract terms or a security review with your teams is Enterprise ([pricing](https://serops.ai/pricing)).

If any of those apply, write to **licensing@serops.ai**; [`LICENSE-COMMERCIAL.md`](https://github.com/getserops/serops/blob/main/LICENSE-COMMERCIAL.md) at the repository root says what to include.

## Enterprise code (`ee/` directories)

Two directories, `backend/ee/` and `frontend/src/ee/`, hold SerOps Enterprise code under the [SerOps Enterprise License](https://github.com/getserops/serops/blob/main/backend/ee/LICENSE) instead of the AGPL. The code is readable; using it in production needs a paid license (Business or Enterprise) and its license key.

- **SerOps Community is complete without them.** Delete both directories and you have SerOps under the AGPL only. CI tests it that way on every change.
- **Enterprise only adds** governance features for large organisations. No Community feature moves to Enterprise: see the [open source promise](open-source-promise.md).
- **The published images include the `ee/` code, switched off.** Without a license key no Enterprise feature runs, and nothing is sent anywhere: the key is checked offline. To build images with no Enterprise code at all, delete the two directories before `docker build`.

Production use of Enterprise follows the [SerOps Enterprise Terms](legal/enterprise-terms.md). The licensor is SerOps (a Tunisian SUARL, Ariana).

## Trademark

"SerOps" and the SerOps logo are trademarks. The AGPL grants rights to the software; it does not grant rights to the trademarks. If you distribute a fork, please rebrand — this protects both users (who might otherwise be confused) and the reputation of the project.

## Contributions

Code contributions need a signed [Contributor License Agreement](https://github.com/getserops/serops/blob/main/CLA.md): you keep your copyright and grant SerOps the right to ship your work in the Community edition (AGPL-3.0), the Enterprise edition and commercially licensed releases. On your first pull request a bot asks you to accept it with one comment. The agreement is being finalised; until then, code pull requests are reviewed but not merged (see [CONTRIBUTING.md](https://github.com/getserops/serops/blob/main/CONTRIBUTING.md)).
