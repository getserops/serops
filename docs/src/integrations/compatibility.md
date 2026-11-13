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
| [Datadog](datadog.md) | Cloud service | Datadog EU, Agent 7 (Helm chart 3.264) | Live-tested |
| [AWS CloudWatch](cloudwatch.md) | Cloud service (Logs Insights) | `eu-central-1`: ECS and Lambda log groups, Container Insights (Fluent Bit 3.0); EKS 1.36 with the CloudWatch Observability add-on, SerOps 1.3.0, 2026-11-13, five-action IAM policy | Live-tested |
| [Google Cloud Logging](gcp.md) | Cloud service | GKE 1.36.4 container logs (stdout, stderr); SerOps 1.3.0, 2026-11-12, three-permission custom role | Live-tested |
| [Azure Monitor](azure.md) | Cloud service (Log Analytics) | AKS Container Insights (`ContainerLogV2`), Application Insights from an OpenTelemetry collector (`AppTraces`); SerOps 1.3.0 on AKS 1.36.5, 2026-11-11, least-privilege custom role | Live-tested |

Log shippers used in the tests, with the configurations on the integration
pages: Promtail 3.5.0 (Loki), Fluent Bit 3.1.9 (Elasticsearch, OpenSearch,
and Splunk through HEC).

## Metric backends

| Integration | Supported | Tested end to end | Maturity |
|---|---|---|---|
| [Prometheus](prometheus.md) | 2.x and 3.x | 2.55.1, 3.1.0 | Live-tested |
| [VictoriaMetrics](victoriametrics.md) | Single node 1.x | 1.106.1 | Live-tested |
| [Grafana Mimir](mimir.md) | 2.x | 2.14.2 (multi-tenant) | Live-tested |
| [Datadog](datadog.md) | Cloud service | Datadog EU, Agent 7: host and Kubernetes container metrics | Live-tested |
| [AWS CloudWatch](cloudwatch.md) | Cloud service | `eu-central-1`: CloudWatch agent 1.300074, host and Container Insights metrics; EKS 1.36, 2026-11-13 (per-service metrics need 1.3.1 when another cluster in the region has the same namespace) | Live-tested |
| [Google Cloud Monitoring](gcp.md) | Cloud service | GKE 1.36.4: per-workload container CPU and memory; SerOps 1.3.0, 2026-11-12 | Live-tested |
| [Azure Monitor](azure.md) | Cloud service | AKS: per-container metrics from Container Insights, cluster metrics. VM metrics not yet live-tested | Live-tested |

## Traces

| Integration | Supported | Tested end to end | Maturity |
|---|---|---|---|
| [OTLP over HTTP](traces.md) (native) | OTLP/HTTP, JSON or protobuf | OpenTelemetry Collector 0.111.0 | Live-tested |
| [Jaeger](traces.md) (pull) | Query API of 1.x | 1.62.0 | Live-tested |
| [Zipkin](traces.md) (pull) | API v2 | 3.4 | Live-tested |
| [Grafana Tempo](traces.md) (pull) | 2.x | 2.6.1 | Live-tested |
| [Datadog APM](datadog.md) (pull) | Cloud service | Datadog EU, Agent 7 receiving OTLP | Live-tested |

## Alerts

| Integration | Supported | Tested end to end | Maturity |
|---|---|---|---|
| [Prometheus Alertmanager](alerts.md) | Webhook payload v4 | 0.27.0 | Live-tested |
| [Grafana alerts](alerts.md) | Grafana 9 and later (documented) | 11.3.0 (contact point + rule, alert and resolution) | Live-tested |
| [Datadog monitors](alerts.md) | Webhook integration | — | Unit-tested |
| [Sentry](alerts.md#sentry) | Internal integration webhooks (signed) | — | Unit-tested |

## Source control and CI/CD

| Integration | Supported | Tested end to end | Maturity |
|---|---|---|---|
| [GitLab](gitlab.md) (SCM + CI) | 17.11 and later (CE / EE) | 17.11 CE (2026-09-13) | Live-tested |
| [Jenkins](jenkins.md) | Current LTS line | 2.541.3 LTS | Live-tested |
| [GitHub](github.md) (SCM + Actions) | github.com, GitHub Enterprise Server | github.com (2026-11-02, fine-grained read-only token; commits, Actions runs and deployments via Sync and polling; webhooks not yet tested live; fixes on `main`, not yet in a release). GitHub Enterprise Server not tested | Live-tested (github.com) |
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
| [Microsoft Entra ID](../deployment/aks.md#6-sign-in-with-entra-id-enterprise) | Entra ID (v2.0 endpoint), groups as object IDs in the ID token | SerOps 1.3.0, 2026-11-12: role and team rules, default deny | Live-tested |
| Okta, Google | Any OpenID Connect provider with a discovery URL | — | Not yet tested |

## Not yet validated

- **Managed Kubernetes, one run per cloud**: EKS, GKE and AKS were each
  validated with the cloud's own logs and metrics: EKS on 2026-11-13
  (SerOps 1.3.0 on EKS 1.36, three nodes, CloudWatch Container Insights, see
  [Install on EKS](../deployment/eks.md)), GKE on 2026-11-12 (SerOps 1.3.0 on
  GKE 1.36.4, two nodes, Google Cloud Logging and Monitoring, see
  [Install on GKE](../deployment/gke.md)), AKS in November 2026 (Azure
  Monitor with Container Insights, on one node and then two; SerOps 1.3.0
  upgrade and install on 2026-11-11, see [Install on AKS](../deployment/aks.md)).
  The rest of the Kubernetes testing above ran on one node of a local
  cluster. See [Tested environments](overview.md#tested-environments).
- **containerd vs Docker runtime**: the suite runs on minikube's Docker
  runtime as well as the containerd one the integration pages were written
  for. On a Docker runtime, add the `docker` parser to Promtail and Fluent
  Bit, as the [Loki](loki.md#docker-runtime) and
  [Elasticsearch](elasticsearch.md#docker-runtime) pages show.
