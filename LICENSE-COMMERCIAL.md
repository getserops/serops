# SerOps — Commercial License

SerOps is published under the [GNU Affero General Public License v3](./LICENSE) ("AGPL-3.0"). That license is the right fit for the vast majority of users — individuals, teams, companies of any size deploying SerOps internally.

You may want a **commercial license instead** if one of these describes your situation:

1. **AGPL policy conflict** — your organisation prohibits AGPL-licensed dependencies in its production stack (this is common at Google, some large banks, and other enterprises with strict license review). A commercial license removes the AGPL copyleft obligations.

2. **Building a proprietary product on top of SerOps** — you want to modify SerOps and ship the result as a closed-source product or hosted service, without open-sourcing your modifications.

3. **Contractual guarantees** — you need prioritised support SLAs, security-review response times, or contractual assurances the AGPL cannot provide on its own. Terms such as indemnification are discussed case by case.

## Two licenses in one repository

| Where | License | What it means |
|-------|---------|---------------|
| Everything except the `ee/` directories | AGPL-3.0 | SerOps Community: the complete product, free |
| `backend/ee/`, `frontend/src/ee/` | [SerOps Enterprise License](backend/ee/LICENSE) | Source-available; production use needs a subscription and its license key |

The two don't mix: Community code never depends on `ee/` (CI deletes it and runs every test), and a commercial license covers both the copyleft opt-out for the AGPL code and, when bought, the Enterprise features. No Community feature ever moves into `ee/`; see the [open source promise](https://serops.ai/docs/open-source-promise/).

## How to reach us

Email **licensing@serops.ai** with:

- your company name and the country you're incorporated in
- roughly how many people will use SerOps
- which of the three scenarios above applies
- the SerOps version you're deploying (or planning to)

We'll get back within two business days with pricing and a draft agreement.

## What a commercial license does not do

A commercial license does not:

- restrict what anyone else can do with the AGPL version
- change the AGPL license on the public repositories
- imply that AGPL users are getting a "lesser" product — the commercial license covers the same source code

## What it does do

- releases you from the AGPL copyleft obligations for the version and modifications you buy the license for
- provides a written commercial agreement your legal team can point at
- unlocks any support / SLA package you also purchase

---

*This document is a stub. Contract terms are negotiated per customer.*
