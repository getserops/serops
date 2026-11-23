# Roadmap

What we plan to build next, and what we know does not work yet. Each item
comes from a page of the documentation, linked next to it. There are no
dates: an item ships when it is ready, and the [changelog](docs/src/changelog.md)
records when it did. The one exception is Cloud, which is planned for 2027.

This page is a plan, not a commitment. The one commitment is the
[open source promise](https://serops.ai/docs/open-source-promise/): every
feature in SerOps Community stays in Community, under AGPL-3.0, and we never
add limits on users, projects, services or data.

## How we decide what is paid

A new feature is paid only if it serves the governance needs of a large
organisation: central identity, compliance, administration at scale. If it
serves security, reliability or the root cause analysis itself, it is in
Community. A paid license only adds features; it never takes any away from
Community ([open source promise, "How we decide"](https://serops.ai/docs/open-source-promise/#how-we-decide)).

## Planned for Community

**Security and access**

- Two-factor authentication
  ([README, "What does not work yet"](README.md#what-does-not-work-yet);
  [open source promise](https://serops.ai/docs/open-source-promise/)).
- Tamper-evident audit export: proof that an audit export was not altered
  ([open source promise](https://serops.ai/docs/open-source-promise/);
  [security questionnaire, LOG-03](https://serops.ai/docs/legal/security-questionnaire/)).

**Root cause analysis**

These are the known limits listed with 1.5.0. The
[benchmark page](https://serops.ai/benchmark) shows the incidents they cost.

- The component of an issue can differ between two identical runs. A fix is
  planned.
- Logs that stop part-way through a window are read as healthy.
- One noisy service can crowd the other services out of the analysis.
- Failures that show only in INFO lines or in request metrics are not seen.

Source: [changelog, 1.5.0, "Known limits"](docs/src/changelog.md).

- Similar past incidents are chosen by recency today. Ranking them by
  relevance is planned
  ([AI resilience](https://serops.ai/docs/architecture/ai-resilience/)).
- Analysis from traces alone, when a stack sends no logs. Until then, the
  Loki or Elasticsearch bridge is the recommended path
  ([OpenTelemetry-first setup](https://serops.ai/docs/how-to/otel-first-setup/)).

**Integrations and notifications**

- Inbound Slack and Microsoft Teams interactions, such as acknowledging an
  issue from the chat
  ([README](README.md#what-does-not-work-yet)).
- A Discord channel ([README](README.md#what-does-not-work-yet)).
- Per-cluster dashboard cards. Today the cluster picker filters analyses and
  issues, and the dashboard stays organisation-wide
  ([Clusters](https://serops.ai/docs/admin/clusters/)).

Every integration, including every future one, is in Community.

**Deployment**

- HorizontalPodAutoscaler definitions in the Helm chart
  ([Helm, "Not yet in the chart"](https://serops.ai/docs/deployment/helm/)).
- Multi-process Prometheus exposition for the backend
  ([Helm, "Not yet in the chart"](https://serops.ai/docs/deployment/helm/)).

## Assurance

- An external penetration test: planned, not done yet
  ([Support and security](https://serops.ai/docs/security/support/#signing-sbom-and-provenance)).

## Not yet tested

Some integrations are implemented and unit-tested but have not yet been run
against a live account. Some setups have not been tested at all, for example
Okta and Google as OpenID Connect providers. The
[compatibility page](https://serops.ai/docs/integrations/compatibility/)
gives the status of each integration and lists what is not yet validated.

## Planned for the paid licenses

Business and Enterprise include the same features
([open source promise, "What a paid license adds"](https://serops.ai/docs/open-source-promise/#what-enterprise-adds)):

- Delegated administration across organisations
- Compliance reports

Already shipped: custom roles and per-project access (1.3.0); SAML 2.0
single sign-on, SCIM provisioning and real-time audit streaming to a SIEM
(1.4.0).

## Cloud

SerOps Cloud, the same product run by us, is planned for 2027
([open source promise](https://serops.ai/docs/open-source-promise/)).

## Asking for something

Ideas and feature requests go in
[GitHub Discussions](https://github.com/getserops/serops/discussions) or in
an [issue](https://github.com/getserops/serops/issues) using the feature
request form. See [SUPPORT.md](SUPPORT.md) for where to ask everything else.
