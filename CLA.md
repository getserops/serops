# SerOps Contributor License Agreement

> **Status: draft pending legal review.** This document was prepared from the
> structure of the Apache Software Foundation's Individual CLA, which is the
> most widely used and widely understood shape in open source. It has **not**
> been reviewed by a lawyer. Section 11 lists the specific clauses that need
> that review and why. Do not require signatures against this text until it has
> been reviewed.

## Why this exists

SerOps is published under the [GNU Affero General Public License v3](./LICENSE),
and a [commercial license](./LICENSE-COMMERCIAL.md) is offered to organisations
that cannot accept AGPL copyleft, or that want to build a proprietary product on
top of SerOps.

Offering that second license requires the project to hold sufficient rights over
**all** of the code it covers. A contribution accepted without those rights
cannot be included in a commercially licensed release, and the practical
consequence is awkward: either the commercial release has to omit the
contribution, or every past contributor has to be tracked down for permission
years later.

This agreement keeps that from happening. It does not take your copyright — you
keep it, and you remain free to use your own contribution however you like. It
grants SerOps the rights it needs to ship your work in both the open-source and
the commercially licensed editions.

If you would rather not sign, that is a legitimate choice. Bug reports, issue
triage, reproduction cases, documentation feedback and design discussion are all
valuable and need no agreement at all.

---

## 1. Definitions

**"You"** means the individual accepting this agreement, or the legal entity on
whose behalf it is accepted. For a legal entity, "You" includes entities that
control, are controlled by, or are under common control with that entity.

**"Contribution"** means any work of authorship, including any modification or
addition to existing work, that You intentionally submit to the Project for
inclusion in it. "Submit" means any form of communication sent to the Project
or its maintainers, including source code, documentation, configuration, and
issue or pull-request content — excluding anything You conspicuously mark in
writing as **"Not a Contribution."**

**"Project"** means the SerOps software distributed from the SerOps repository,
together with the project's maintainers and its designated commercial steward.

---

## 2. Copyright license You grant

You retain all ownership of Your Contribution.

Subject to the terms below, You grant the Project a perpetual, worldwide,
non-exclusive, royalty-free, irrevocable copyright license to reproduce,
prepare derivative works of, publicly display, publicly perform, sublicense and
distribute Your Contribution and such derivative works.

**This license expressly includes the right to distribute Your Contribution
under terms other than the AGPL-3.0, including proprietary and commercial
terms, and to sublicense those rights to third parties.** This is the clause
that allows Your Contribution to appear in a commercially licensed SerOps
release. It does not restrict You: You keep every right You had before, and may
license Your own Contribution to anyone else on any terms.

---

## 3. Patent license You grant

You grant the Project a perpetual, worldwide, non-exclusive, royalty-free,
irrevocable patent license to make, have made, use, offer to sell, sell, import
and otherwise transfer Your Contribution, where that license applies only to
those patent claims licensable by You that are necessarily infringed by Your
Contribution alone or by combination of Your Contribution with the work to which
it was submitted.

If any entity institutes patent litigation alleging that Your Contribution, or
the work it was submitted to, constitutes direct or contributory patent
infringement, any patent license granted under this agreement for that
Contribution terminates as of the date such litigation is filed.

---

## 4. You confirm that You are entitled to grant this

You represent that each Contribution is Your original creation, and that You are
legally entitled to grant the licenses above.

If Your employer has rights to intellectual property You create — which is
common in employment contracts — You represent that You have received permission
to make the Contribution on behalf of that employer, that Your employer has
waived such rights, or that Your employer has signed the Corporate section in
§8 below.

---

## 5. Third-party material

If You submit work that is not Your original creation, You may submit it
separately from any Contribution, identifying its source and any license or
other restriction of which You are aware, and conspicuously marking it as
**"Submitted on behalf of a third party: [name]."**

Do not paste code from another project into a pull request without saying so.
A single unattributed AGPL-incompatible snippet is a licensing problem for every
downstream user of SerOps, and it is far cheaper to resolve before merge.

---

## 6. No obligation and no warranty

Nothing here obliges the Project to accept, merge, or keep any Contribution. The
decision is the maintainers'.

Except for the representations in §4 and §5, You provide Your Contribution
**"AS IS"**, without warranties or conditions of any kind, either express or
implied, including any warranty of merchantability, fitness for a particular
purpose, title, or non-infringement.

---

## 7. Notification

You agree to notify the Project in writing if You become aware of any fact or
circumstance that would make any representation in this agreement inaccurate.

---

## 8. Corporate contributions

If You are contributing in the course of employment, or Your employer owns
rights in Your work, the employer must accept this agreement as the "You". An
authorised signatory should provide:

| Field | |
|---|---|
| Legal entity name | |
| Address | |
| Authorised signatory (name, title) | |
| Contact email for license matters | |
| Schedule of authorised contributors (names and accounts) | |

The schedule may be updated by written notice; contributions from accounts not
on the schedule are not covered.

---

## 9. How to accept

Until the repository is public, signatures are handled by email —
**abdelmalek.awayni@gmail.com** — with the subject `SerOps CLA` and the
following statement:

> I have read the SerOps Contributor License Agreement and I accept it.
> Name: …
> Email: …
> Repository account: …
> Date: …

Once the repository is published, acceptance will be collected automatically on
each pull request by a CLA assistant bot, which records the signature against
the account and blocks merge until it is present. That is the mechanism to wire
up at publish time; see `CONTRIBUTING.md`.

---

## 10. Scope

This agreement covers Contributions to the SerOps repository: `backend/`,
`frontend/`, `docs/`, and `deploy/`. It governs only the rights described above
and creates no employment, partnership, or agency relationship.

---

## 11. For legal review

The clauses below are the ones that carry real consequence, and the reasons they
need a lawyer's eye rather than a template's:

1. **§2 relicensing right.** This is the clause the entire commercial-license
   business depends on, and it is also the clause contributors scrutinise most.
   Confirm the wording is broad enough to permit proprietary redistribution and
   sublicensing, while remaining narrow enough that contributors are willing to
   sign. Compare against the Apache ICLA (grant-based) and the alternative of
   outright copyright assignment, which is stronger for the project and
   materially more off-putting to contributors.

2. **Grant versus assignment.** This draft deliberately chooses a broad license
   grant over assignment, following Grafana's model. Confirm a grant is
   sufficient in the jurisdictions that matter for enforcement, and in
   particular whether it survives in jurisdictions with strong inalienable
   moral rights.

3. **§3 patent termination.** Check the trigger is not broader than intended —
   as drafted, litigation by *any* entity terminates the license, which may be
   wider than you want.

4. **§4 employer permission.** Verify this is sufficient for the jurisdictions
   where contributors are likely to be employed, or whether a signed Corporate
   CLA should be mandatory rather than an alternative.

5. **§6 warranty disclaimer.** Confirm enforceability, particularly against
   consumer-protection rules in the EU and UK.

6. **Enforceability of click/email acceptance.** Confirm that the §9 mechanisms
   form a binding agreement in the relevant jurisdictions, and that records are
   retained in a form that would be adequate as evidence.

7. **Governing law and venue.** This draft deliberately states none. A lawyer
   should advise whether to add them and which, balancing enforceability against
   deterring international contributors.

8. **Data protection.** Collecting contributor names and email addresses is
   processing personal data. Confirm the lawful basis, retention period, and
   whether a privacy notice must accompany the signing flow under GDPR.

9. **Interaction with AGPL §13.** Confirm nothing here conflicts with the
   obligations AGPL-3.0 already imposes on the project's own distribution.

10. **Prior contributions.** If any contribution is accepted before this
    agreement is in force, it is not covered. Decide whether to require
    retroactive acceptance or to treat affected files as AGPL-only — which
    would need tracking, because it constrains what the commercial release can
    contain.
