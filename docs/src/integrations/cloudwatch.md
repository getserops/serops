---
seo_title: "AWS CloudWatch logs and metrics integration"
description: "Connect AWS CloudWatch Logs Insights and metrics to SerOps with one integration, using the integration's own IAM access key."
---
# AWS CloudWatch

AWS CloudWatch is a monitoring and observability service from Amazon Web Services. SerOps integrates with CloudWatch as a dual provider supporting both log retrieval (via CloudWatch Logs Insights) and metric queries (via GetMetricData) in a single integration.

| | |
|---|---|
| **Type** | Logs + Metrics |
| **Auth** | AWS Credentials |
| **Query Language** | CloudWatch Insights (logs), GetMetricData (metrics) |

## Prerequisites

- An AWS account with CloudWatch access
- An IAM user or role with permissions for `logs:StartQuery`, `logs:GetQueryResults`, `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`, `logs:DescribeLogGroups`, `cloudwatch:GetMetricData`, `cloudwatch:ListMetrics`
- AWS access key ID and secret access key
- Network access from the SerOps backend to the AWS CloudWatch API endpoint

## Configuration

In the UI: **Integrations → Log Providers → Add Integration → AWS CloudWatch**, then fill in
the region, the access key ID, the secret access key and, optionally, the log
groups to search. Through the API:

```json
{
  "provider": "cloudwatch",
  "display_name": "AWS Production",
  "capabilities": ["logs", "metrics"],
  "username": "AKIA...",
  "password": "<secret access key>",
  "extra_config": {
    "aws_region": "us-east-1",
    "log_groups": "/ecs/shop-api, /aws/lambda/checkout"
  }
}
```

## Authentication

CloudWatch authenticates with an IAM user's access key, and both halves are
required:

- **Access Key ID** goes in `username`.
- **Secret Access Key** goes in `password`, which SerOps encrypts at rest.

SerOps never falls back to the server's own AWS credentials (environment
variables, an EC2 instance profile or an EKS pod role). On an instance shared by
several organisations, that would let one of them read CloudWatch with the
server's permissions. An integration without both halves of the key fails to
load with an error saying so.

Temporary credentials (session tokens) are not supported: they expire, and a
stored integration needs credentials that keep working.

## Extra Configuration

| Field | Type | Description |
|-------|------|-------------|
| `aws_region` | string | AWS region for CloudWatch (e.g., `eu-west-1`). Defaults to `us-east-1`. |
| `log_groups` | string | Log groups to search, comma-separated, up to 50. Left empty, SerOps searches the groups whose name starts with `/aws/<project>` or contains the project name, plus the EKS Container Insights application groups (`/aws/containerinsights/<cluster>/application`) |
| `default_log_group` | string | Log group for searches that name none, such as the log explorer. Left empty, the first 50 groups of the account and region |

### How log events are read

Logs Insights queries are asked for the raw event. JSON events are read field
by field (`log_level` / `level` / `log.level`, `service_name` / `service` /
`service.name`, `environment` / `env` ..., see
[field aliases](../how-to/configure-data-collection.md#alias-support-datadog-usm-opentelemetry-kubernetes));
plain-text events get their level from the line (`ERROR`, `[warn]`,
`level=error`). An event that names no service gets the function name in a
Lambda group (`/aws/lambda/shop-checkout`), else the container in the stream
name (the ECS `awslogs` driver names streams `prefix/container/task-id`).

### Which logs belong to a project

CloudWatch logs seldom carry a project or environment field: the log group
says it. For project `shop` and environment Production:

| Log | Belongs to the project | Belongs to Production |
|-----|------------------------|-----------------------|
| `/ecs/shop-payments`, any event without a project field | Yes: the group name contains `shop` | Yes when Production is the project's only environment. Otherwise only with an environment field, or a group name with `prod` in it |
| `/ecs/shop-orders-prod`, plain-text lines | Yes | Yes: `prod` is a word of the group name |
| `/ecs/shop-orders-staging` | Yes | No |
| `/acme/shop`, event with `"project_name": "blog"` | No: the event's own field wins | |
| `/aws/containerinsights/prod/application`, pod in namespace `shop` | Once you accept the rule **Check my data** offers (`kubernetes.namespace_name = shop`) | Yes: `prod` is a word of the group name |
| `/aws/containerinsights/eks-1/application`, pod in namespace `production` | Once you accept the rule `kubernetes.namespace_name = production` | Yes: the rule's value names the environment |

The environment words are the environment's name, its usual spellings
(`production`, `prod`, `prd`) and the labels set on it. A word must stand
between `/`, `-`, `_` or `.`: `/aws/lambda/product-api` is not Production.

When the project has a single active environment, a log with no environment
field belongs to it, unless its group name names another environment
(`/ecs/shop-orders-staging` stays out).

## Metric Mapping

SerOps reads the CloudWatch agent (`CWAgent` namespace), one series per
`host`:

| SerOps Metric | CloudWatch Metric |
|--------------|-------------------|
| `node_memory_MemTotal_bytes` | `CWAgent/mem_total` |
| `node_memory_MemFree_bytes` | `CWAgent/mem_free` |
| `node_memory_MemAvailable_bytes` | `CWAgent/mem_available` |
| `node_cpu_seconds_total` | `CWAgent/cpu_usage_active` (series `cpu = cpu-total`), else `AWS/EC2/CPUUtilization` per `InstanceId` |

CPU is a percentage in both cases. The agent's default configurations send
`mem_used_percent` only: add the memory measurements SerOps reads to the
agent configuration (`/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json`):

```json
"metrics_collected": {
  "mem": {"measurement": ["mem_used_percent", "mem_total", "mem_available", "mem_free"]},
  "cpu": {"measurement": ["cpu_usage_active"], "totalcpu": true}
}
```

AWS metrics carry the dimensions AWS gives them (`host`, `InstanceId`, ...),
not a project or an environment, so SerOps reads every host of the account and
region. When your series do carry a `project_name` or `environment` dimension,
SerOps keeps only the matching ones.

## Limitations

- **14-day max query window**: CloudWatch Logs Insights queries are limited to a 14-day time range.
- **No high cardinality**: CloudWatch metrics do not support high-cardinality label sets like Prometheus-based providers.
- **No histograms**: CloudWatch does not natively support histogram metric types.

## Kubernetes setup (Container Insights)

!!! note "Tested with a real CloudWatch agent"
    Checked in October 2026 with AWS's Container Insights quickstart
    (CloudWatch agent 1.300074, Fluent Bit 3.0) on a local Kubernetes
    cluster, sending to AWS `eu-central-1`: logs, Check my data, metrics per
    service and an investigation. Not yet on EKS itself.
    See [Tested environments](overview.md#tested-environments).

Set the integration's **Topology mode** to **Kubernetes** (Settings →
Integrations, in the integration's form) to read pod metrics per Kubernetes
Service instead of host metrics:

| Query | VM mode | Kubernetes mode |
|-------|---------|-----------------|
| CPU | `CWAgent/cpu_usage_active` or `AWS/EC2/CPUUtilization` | `pod_cpu_utilization` × `node_cpu_limit` × `service_number_of_running_pods`, in cores |
| Memory | `CWAgent/mem_total`, `mem_free`, `mem_available` | `pod_memory_utilization_over_pod_limit`, a percentage of the pods' memory limit |

Container Insights publishes percentages, not bytes. Memory is measured
against each pod's memory limit, like the Prometheus and Datadog Kubernetes
modes, so a pod close to being OOMKilled shows it. When no pod in the
namespace has a memory limit, SerOps falls back to `pod_memory_utilization`,
a percentage of the node, where a small pod on a large node looks idle: set
memory limits.

**1. Install Container Insights.** On EKS, the
[Amazon CloudWatch Observability add-on](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/install-CloudWatch-Observability-EKS-addon.html)
does it. Otherwise, AWS's quickstart installs the CloudWatch agent and
Fluent Bit as DaemonSets. Its manifest has six placeholders, and `kubectl`
rejects it when one is left:

```bash
ClusterName=<your-cluster>
RegionName=<your-region>
curl -s https://raw.githubusercontent.com/aws-samples/amazon-cloudwatch-container-insights/latest/k8s-deployment-manifest-templates/deployment-mode/daemonset/container-insights-monitoring/quickstart/cwagent-fluent-bit-quickstart.yaml \
  | sed "s/{{cluster_name}}/${ClusterName}/;s/{{region_name}}/${RegionName}/;s/{{http_server_toggle}}/\"On\"/;s/{{http_server_port}}/\"2020\"/;s/{{read_from_head}}/\"Off\"/;s/{{read_from_tail}}/\"On\"/" \
  | kubectl apply -f -
```

The agents need AWS credentials: on EKS, the node role with
`CloudWatchAgentServerPolicy`. The quickstart expects EC2 nodes; outside AWS
the agent reads its key from a credentials file
(`/root/.aws/credentials`, profile `AmazonCloudWatchAgent`) and verifies the
kubelet's certificate against the cluster CA.

**2. Run each environment in its own namespace**, named after the
environment (`production`) or the project (`shop`). Container Insights cannot
carry your pod labels: metrics have fixed dimensions (`ClusterName`,
`Namespace`, `Service`) and Fluent Bit ships logs with `Labels Off`. SerOps
reads the metric series of the namespace named after the project or the
environment, one per Kubernetes Service.

**3. Claim the logs in Check my data.** Logs land in
`/aws/containerinsights/<cluster>/application`, one JSON record per line with
`log` (the container's line) and `kubernetes.namespace_name`,
`kubernetes.container_name`, `kubernetes.pod_name`. SerOps searches that group
without configuration and names the service after the container. Open the
project's **Data** tab, run **Check my data** and accept the grouping it offers
(`kubernetes.namespace_name = production`) to give the namespace's logs to the
project. A namespace named after the environment also puts its logs in that
environment; with a namespace named after the project, give the environment
the namespace's name as a label, or keep one environment per project.

SerOps' own key needs `cloudwatch:ListMetrics` and `cloudwatch:GetMetricData`
(see [Prerequisites](#prerequisites)); nothing else for Kubernetes mode.

## Health Check

```
POST /api/integrations/observability/{id}/health-check/
```

Response:
```json
{
  "integrations": [
    {
      "provider": "CloudWatchLogProvider",
      "provider_type": "log",
      "healthy": true,
      "message": "OK"
    },
    {
      "provider": "CloudWatchMetricProvider",
      "provider_type": "metric",
      "healthy": true,
      "message": "OK"
    }
  ]
}
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "AWS does not recognise this access key, or the secret access key is wrong." | Check both halves of the key, and that the key is active in IAM |
| "The access key is not allowed to call logs:StartQuery" (or another action) | Add that action to the key's IAM policy (list under [Prerequisites](#prerequisites)) |
| **Check my data**: "The log store refused the query" | The message after it is AWS's own; the most common is a missing permission |
| No logs for the project | Check that the group names contain the project name, or set **Log groups**; see [Which logs belong to a project](#which-logs-belong-to-a-project) |
| No memory metrics | The agent sends `mem_used_percent` only by default: add `mem_total`, `mem_available` and `mem_free` (see [Metric Mapping](#metric-mapping)) |
| Logs sent a minute ago are missing | Logs Insights can take a few minutes to show new events; SerOps reads them on its next run |

## Related Pages

- [Observability Overview](observability-overview.md)
- [API Reference](../api/observability.md)
