---
seo_title: "SerOps Enterprise Terms"
description: "The standard terms for SerOps paid licenses (Business and Enterprise): order, installations, license key and use, fees, support, security pack, data, liability and termination."
---
# SerOps Enterprise Terms

<!-- The <a id> anchors keep the links of version 1.1 (sections 2, 5, 6) working. -->

Version 1.2, 2026-11-22. Replaces version 1.1 of
2026-11-09.

These are the standard terms for the SerOps paid licenses, **Business** and
**Enterprise**. They govern production use of the paid features (the code in
the `ee/` directories of the SerOps repository, licensed under the
[SerOps Enterprise License](https://github.com/getserops/serops/blob/main/backend/ee/LICENSE))
and the commercial license for internal use described in section 4. SerOps
Community, under the GNU AGPL-3.0, is not affected by them.

## 1. Parties

These terms are between **SerOps**, a Tunisian single-member limited liability company (SUARL), Ariana Center, Block C, Office C408, Avenue du 18 Janvier, 2080 Ariana Ville,
Tunisia ("SerOps", "we"), and the organisation named on the order and the
invoice ("Customer", "you"). The person who accepts them confirms they may
bind that organisation.

<a id="2-order-and-subscription"></a>

## 2. Plans, orders and purchase orders

1. A license starts with an **order**: an order form or quote accepted by
   both parties, stating the plan (Business or Enterprise), the number of
   Installations, the term, the price and, for Enterprise, any support level
   or other change to these terms.
2. **Business** is a license on these terms as they are, with the standard
   security pack of section 6 as it is. **Enterprise** is a license whose
   order changes or adds to these terms or to the security pack. If an
   Enterprise order conflicts with these terms, the order wins for that
   point.
3. A purchase order that refers to these terms is an order on these terms.
   Conditions printed on or attached to a purchase order, or in a supplier
   portal, do not apply unless SerOps agrees to them in writing. A Customer
   that needs its own conditions to apply buys Enterprise.
4. Filling in the Customer's supplier registration (company, bank and tax
   details, vendor portal) is administration, not a change to these terms.

## 3. Installations

1. An **Installation** is one SerOps database together with its
   high-availability replicas and its disaster-recovery standby, and
   everything that uses that database.
2. The order states how many Installations in production the license
   covers. Nothing else is counted or limited: not users, employees,
   projects, services, clusters or data. SerOps does not count anything in
   the product; the number of Installations is a commercial declaration.
3. Installations used only for development, testing or staging
   ("Non-production Installations") need no license of their own: you may use
   your license key on them at no extra cost.
4. If you run more production Installations than the order states, you
   order the difference for the rest of the term at the price of the order.

## 4. License key and use

1. For each license SerOps issues a **license key**. It enables the paid
   features on your Installations for the term. It is checked offline:
   SerOps receives no data from your Installations.
2. The license covers the Customer and the companies it controls ("Controlled
   Companies"), control meaning more than 50% of the voting rights. You may
   use the paid features, and SerOps under this commercial license instead of
   the AGPL-3.0, for your own internal use and that of your Controlled
   Companies.
3. Running SerOps for clients, as a service or otherwise, embedding it in a
   product, or redistributing it is not covered: it needs a separate written
   agreement with SerOps.
4. You may not share the key outside the Customer and its Controlled
   Companies, or remove, disable or work around the license key check.
5. Development and testing use is allowed without a license, as the
   Enterprise License states. For evaluation, we issue a free 30-day key on
   request.

## 5. Term, fees and payment

1. A license runs for one year or three years, as the order states, at the
   same yearly price, fixed for the term. Unless the order says otherwise, it
   renews for the same period unless either party gives notice 30 days
   before it ends.
2. Fees are invoiced yearly in advance and payable within 30 days of the
   invoice, by bank transfer.
3. SerOps may change its list price for renewals. A change applies to a
   renewal only if SerOps announced it at least 90 days before that renewal.
4. Fees exclude taxes, which you pay where applicable (other than taxes on
   SerOps' income).
5. If an invoice is unpaid 30 days after a reminder, SerOps may suspend the
   license until it is paid.
6. Where a license is bought through a reseller or merchant of record named
   by SerOps, that seller invoices and collects the fees under its own
   terms, which replace sections 5.2, 5.4 and 5.5. These terms still govern
   everything else.

## 6. Security pack

1. Business includes the standard **security pack**: the security overview,
   the [data-processing terms](data-processing-terms.md) and the pre-filled
   security questionnaire, as published at
   [serops.ai/docs/legal/security-pack](https://serops.ai/docs/legal/security-pack/)
   on the date of the order.
2. Accepting the security pack as it is counts as accepting these terms
   unchanged. A request to change any of its documents, or to fill in the
   Customer's own questionnaire, or a security review with the Customer's
   teams, is an Enterprise order.

<a id="5-support-and-updates"></a>

## 7. Support and updates

1. Your license includes the updates and new versions SerOps publishes
   during its term.
2. **Business:** support is by email to **support@serops.ai**, during
   Business Hours. SerOps targets a first reply within one Business Day. This
   is a target, not a guarantee, and it is not a service level.
3. **Enterprise:** support (channels, hours, response times) is as stated in
   the order. Without a stated level, section 7.2 applies.
4. **Business Hours** are 09:00 to 18:00, Central European Time or Central
   European Summer Time, Monday to Friday, except public holidays in Tunisia;
   a **Business Day** is one such day. A response time counts Business Hours
   only, and measures the first response from a person, not the fix.

<a id="6-your-data"></a>

## 8. Your data

SerOps is self-hosted: your logs, metrics, traces, code and analyses stay on
your Installations, and SerOps does not access them unless you share them
with us for support. The license key check sends nothing. Personal data you
send us for support is processed under the
[data-processing terms](data-processing-terms.md). AI providers you configure
process data under your own agreements with them.

## 9. Confidentiality

Each party keeps confidential the non-public information the other shares
under these terms (prices, keys, security details, support data), and uses
it only for these terms, for their duration and three years after.

## 10. Warranty

1. SerOps warrants that, during the term, the paid features work
   substantially as described in the SerOps documentation. Your remedy for a
   breach of this warranty is that SerOps corrects the issue within a
   reasonable time or, if it cannot, you may terminate and receive a
   pro-rata refund of prepaid fees for the remaining term.
2. Otherwise the software is provided "as is", without other warranties,
   express or implied, to the extent the law allows.

## 11. Liability

1. Neither party is liable for indirect or consequential damages, loss of
   profit, revenue or data, to the extent the law allows.
2. Each party's total liability under these terms is limited to the fees you
   paid for the 12 months before the event giving rise to the claim.
3. These limits do not apply to breach of sections 4.3 or 4.4, to fraud, or
   to liability that cannot be limited by law.

## 12. Expiry and termination

1. Either party may terminate a license if the other breaches these terms
   and does not cure the breach within 30 days of written notice.
2. When a license ends, the paid features switch off. No data is deleted,
   and every SerOps Community feature keeps working under the AGPL-3.0.
3. Sections 8, 9, 11 and 13 survive termination.

## 13. General

1. These terms are governed by the laws of Tunisia. The competent courts of
   Tunis have jurisdiction, unless the order states otherwise.
2. SerOps may update these terms for future licenses and renewals; the
   version in force when an order is accepted applies to it for its term.
3. Neither party may assign a license without the other's consent, except
   to a successor of its business.
4. Contact: **licensing@serops.ai**.
