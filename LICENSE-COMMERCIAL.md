# SerOps — Commercial License

SerOps is published under the [GNU Affero General Public License v3](./LICENSE) ("AGPL-3.0"). That license is the right fit for the vast majority of users — individuals, teams, companies of any size deploying SerOps internally.

You may want a **commercial license instead** if one of these describes your situation:

1. **Your organisation's policy rules out AGPL software.** Business includes a commercial license for internal use, as an alternative to the AGPL, for your organisation and the companies it controls.

2. **Running SerOps for clients, embedding it in a product or redistributing it** — this is a separate agreement, on request, with no public price. A Business or Enterprise license covers only your own organisation and the companies it controls.

3. **Contractual guarantees** — you need support, a security review or contractual assurances the AGPL cannot provide on its own. Business comes with standard terms and email support; an SLA, your own contract terms or a security review with your teams is Enterprise ([pricing](https://serops.ai/pricing)).

## Two licenses in one repository

| Where | License | What it means |
|-------|---------|---------------|
| Everything except the `ee/` directories | AGPL-3.0 | SerOps Community: the full root cause analysis, free in production |
| `backend/ee/`, `frontend/src/ee/` | [SerOps Enterprise License](backend/ee/LICENSE) | Source-available; production use needs a paid license (Business or Enterprise) and its license key |

The two don't mix: Community code never depends on `ee/` (CI deletes it and runs every test). A Business or Enterprise license includes both: the commercial license for internal use, instead of the AGPL, and the paid features. No Community feature ever moves into `ee/`; see the [open source promise](https://serops.ai/docs/open-source-promise/).

## How to reach us

Email **licensing@serops.ai** with:

- your company name and the country you're incorporated in
- how many production installations you will run (one installation is one SerOps database with its replicas and standby)
- which of the three scenarios above applies
- the SerOps version you're deploying (or planning to)

We'll get back to you within two business days. Prices for Business and Enterprise are public on the [pricing page](https://serops.ai/pricing).

## What a commercial license does not do

A commercial license does not:

- restrict what anyone else can do with the AGPL version
- change the AGPL license on the public repositories
- imply that AGPL users are getting a "lesser" product — the commercial license covers the same source code

## What it does do

- lets your organisation and the companies it controls use SerOps for their own internal use under a commercial license instead of the AGPL, for the term of the license
- gives your legal team written terms to point at: the [SerOps Enterprise Terms](https://serops.ai/docs/legal/enterprise-terms/), as they are (Business) or changed in your order (Enterprise)
- comes with email support (Business) or the SLA written into your contract (Enterprise)

---

The terms of every paid license are the [SerOps Enterprise Terms](https://serops.ai/docs/legal/enterprise-terms/). An Enterprise order can change or add to them.
