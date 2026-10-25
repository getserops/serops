---
seo_title: "Compatibility: supported and tested versions"
description: "Which versions of each log, metric and trace backend, CI/CD tool, GitOps controller and identity provider SerOps supports, and which versions were tested end to end."
---
# Compatibility

What SerOps supports, and what we actually ran it against.

## Support policy

- **Supported** means the oldest version we have run end to end, up to
  the versions the vendor still supports. We do not claim a version we have
  not run.
- **Older versions** may work, but are not tested and fixes are not
  guaranteed. If you run one, an
  [issue](https://github.com/getserops/serops/issues) saying what worked
  is welcome.
- **Tested** versions are run by an end-to-end suite that installs SerOps
  with the Helm chart on Kubernetes and goes through each integration the
  way a person does: configure it in the UI, follow these docs to send data,
  break a service, and check the analysis finds the cause. The table says
  when.

Each integration has a **maturity** level:

| Level | Meaning |
|---|---|
| **Live-tested** | Run end to end against a real instance of the version listed. |
| **Unit-tested** | Implemented and covered by tests against recorded API responses; not yet run against a live account. |

Last full run: **2026-10-24**, SerOps `main` after 1.2.5, Kubernetes 1.31
(minikube, single node), Helm chart from the same commit.

## Log backends

| Integration | Supported | Tested end to end | Maturity |
|---|---|---|---|
| [Elasticsearch](elasticsearch.md) | 7.17 and later (8.x) | 7.17.25, 8.15.3 | Live-tested |
| [OpenSearch](opensearch.md) | 1.3 and later (2.x, 3.x) | 1.3.20, 2.17.1, 3.1.0 | Live-tested |
| [Grafana Loki](loki.md) | 2.9 and later (3.x) | 2.9.10, 3.2.1 | Live-tested |
| [Splunk Enterprise](splunk.md) | 8.2 and later (9.x) | 8.2.12, 9.3.2 | Live-tested |
| [Datadog](datadog.md) | Cloud service | — | Unit-tested |
| [AWS CloudWatch](cloudwatch.md) | Cloud service (Logs Insights) | — | Unit-tested |
| [Google Cloud Logging](gcp.md) | Cloud service | — | Unit-tested |
| [Azure Monitor](azure.md) | Cloud service (Log Analytics) | — | Unit-tested |

Log shippers used in the tests, with the configurations on the integration
pages: Promtail 3.5.0 (Loki), Fluent Bit 3.1.9 (Elasticsearch, OpenSearch,
and Splunk through HEC).

## Metric backends

| Integration | Supported | Tested end to end | Maturity |
|---|---|---|---|
| [Prometheus](prometheus.md) | 2.x and 3.x | 2.55.1, 3.1.0 | Live-tested |
| [VictoriaMetrics](victoriametrics.md) | Single node 1.x | 1.106.1 | Live-tested |
| [Grafana Mimir](mimir.md) | 2.x | 2.14.2 (multi-tenant) | Live-tested |
| [Datadog](datadog.md) | Cloud service | — | Unit-tested |
| [AWS CloudWatch](cloudwatch.md) | Cloud service | — | Unit-tested |
| [Google Cloud Monitoring](gcp.md) | Cloud service | — | Unit-tested |
| [Azure Monitor](azure.md) | Cloud service | — | Unit-tested |

## Traces

| Integration | Supported | Tested end to end | Maturity |
|---|---|---|---|
| [OTLP over HTTP](traces.md) (native) | OTLP/HTTP, JSON or protobuf | OpenTelemetry Collector 0.111.0 | Live-tested |
| [Jaeger](traces.md) (pull) | Query API of 1.x | 1.62.0 | Live-tested |
| [Zipkin](traces.md) (pull) | API v2 | 3.4 | Live-tested |
| [Grafana Tempo](traces.md) (pull) | 2.x | 2.6.1 | Live-tested |
| [Datadog APM](datadog.md) (pull) | Cloud service | — | Unit-tested |

## Alerts

| Integration | Supported | Tested end to end | Maturity |
|---|---|---|---|
| [Prometheus Alertmanager](alerts.md) | Webhook payload v4 | 0.27.0 | Live-tested |
| [Grafana alerts](alerts.md) | Grafana 9 and later (documented) | — | Unit-tested |
| [Datadog monitors](alerts.md) | Webhook integration | — | Unit-tested |

## Source control and CI/CD

| Integration | Supported | Tested end to end | Maturity |
|---|---|---|---|
| [GitLab](gitlab.md) (SCM + CI) | 17.11 and later (CE / EE) | 17.11 CE (2026-09-13) | Live-tested |
| [Jenkins](jenkins.md) | Current LTS line | 2.541.3 LTS | Live-tested |
| [GitHub](github.md) (SCM + Actions) | github.com, GitHub Enterprise Server | — | Unit-tested |
| [Bitbucket](bitbucket.md) | Bitbucket Cloud | — | Unit-tested |
| [Azure DevOps](azure-devops.md) | Azure DevOps Services | — | Unit-tested |

## GitOps

| Integration | Supported | Tested end to end | Maturity |
|---|---|---|---|
| [Argo CD](gitops.md) | 2.13 and later | 2.13.1 | Live-tested |
| [Flux](gitops.md) | 2.4 and later | 2.4.0 | Live-tested |

## Sign-in (OIDC)

| Integration | Supported | Tested end to end | Maturity |
|---|---|---|---|
| [Keycloak](../security/authentication.md) | 26 | 26.0 | Live-tested |
| Okta, Microsoft Entra ID, Google | Any OpenID Connect provider with a discovery URL | — | Not yet tested |

## Not yet validated

- **Managed Kubernetes** (EKS, GKE, AKS) and **multi-node clusters**: all
  the Kubernetes testing above ran on one node. See
  [Tested environments](overview.md#tested-environments).
- **containerd vs Docker runtime**: the suite runs on minikube's Docker
  runtime as well as the containerd one the integration pages were written
  for. On a Docker runtime, add the `docker` parser to Promtail and Fluent
  Bit, as the [Loki](loki.md#docker-runtime) and
  [Elasticsearch](elasticsearch.md#docker-runtime) pages show.
