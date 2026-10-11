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

```json
{
  "provider": "cloudwatch",
  "display_name": "AWS Production",
  "capabilities": ["logs", "metrics"],
  "host": "https://logs.us-east-1.amazonaws.com",
  "extra_config": {
    "aws_region": "us-east-1",
    "aws_access_key_id": "AKIA...",
    "aws_secret_access_key": "secret",
    "default_log_group": "/serops/production"
  }
}
```

## Authentication Options

CloudWatch uses AWS IAM credentials for authentication. All credentials are provided in `extra_config`:

- **Access Key ID** (`aws_access_key_id`): The AWS access key identifier.
- **Secret Access Key** (`aws_secret_access_key`): The AWS secret access key.
- **Session Token** (`aws_session_token`): Optional temporary session token for assumed roles or federated access.

## Extra Configuration

| Field | Type | Description |
|-------|------|-------------|
| `aws_region` | string | AWS region for CloudWatch (e.g., `us-east-1`) |
| `aws_access_key_id` | string | AWS access key ID |
| `aws_secret_access_key` | string | AWS secret access key |
| `aws_session_token` | string | Optional AWS session token for temporary credentials |
| `default_log_group` | string | Default CloudWatch log group to query (e.g., `/serops/production`) |

## Metric Mapping

SerOps automatically maps Prometheus-style metric names to CloudWatch metrics:

| SerOps Metric | CloudWatch Metric |
|--------------|-------------------|
| `node_memory_MemTotal_bytes` | `CWAgent/mem_total` |
| `node_memory_MemFree_bytes` | `CWAgent/mem_free` |
| `node_memory_MemAvailable_bytes` | `CWAgent/mem_available` |
| `node_cpu_seconds_total` | `AWS/EC2/CPUUtilization` |

## Limitations

- **14-day max query window**: CloudWatch Logs Insights queries are limited to a 14-day time range.
- **No high cardinality**: CloudWatch metrics do not support high-cardinality label sets like Prometheus-based providers.
- **No histograms**: CloudWatch does not natively support histogram metric types.

## Kubernetes setup (EKS Container Insights)

Set the integration's `topology_mode` to `kubernetes` to switch SerOps from `AWS/EC2` + `CWAgent` namespaces to `ContainerInsights` (pod-level metrics):

| Query | VM mode | Kubernetes mode |
|-------|---------|-----------------|
| CPU | `AWS/EC2/CPUUtilization` | `ContainerInsights/pod_cpu_utilization` |
| Memory total | `CWAgent/mem_total` | `ContainerInsights/pod_memory_working_set` |
| Memory usage | `CWAgent/mem_free` | `ContainerInsights/pod_memory_utilization` |

**Prerequisites** for EKS:

1. **Enable Container Insights** on the cluster:

    ```bash
    ClusterName=<your-eks-cluster>
    RegionName=us-east-1
    curl https://raw.githubusercontent.com/aws-samples/amazon-cloudwatch-container-insights/latest/k8s-deployment-manifest-templates/deployment-mode/daemonset/container-insights-monitoring/quickstart/cwagent-fluent-bit-quickstart.yaml \
      | sed "s/{{cluster_name}}/${ClusterName}/;s/{{region_name}}/${RegionName}/" \
      | kubectl apply -f -
    ```

    This installs the CloudWatch Agent DaemonSet + Fluent Bit for log forwarding.

2. **Tag your pods with SerOps' canonical labels** (via Deployment `metadata.labels` or a mutating webhook):

    ```yaml
    metadata:
      labels:
        service_name: checkout
        environment: production
        organisation_name: acme
        project_name: shop
    ```

    Container Insights picks these up automatically as dimensions on pod-level metrics.

3. **IAM permissions** — the CloudWatch agent's IAM role needs `CloudWatchAgentServerPolicy`; SerOps' credentials additionally need `cloudwatch:GetMetricData` scoped to the `ContainerInsights` namespace.

**Verify with the ingest validator**:

```bash
docker compose exec backend python manage.py check_ingest --integration <ID>
```

The report will show whether `ContainerInsights` metrics carry the required dimensions.

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
| "Connection refused" | Verify `host` URL is reachable from SerOps backend |
| "InvalidAccessKeyId" | Check that `aws_access_key_id` is correct and the IAM user is active |
| "SignatureDoesNotMatch" | Check that `aws_secret_access_key` is correct |
| "AccessDenied" | Verify the IAM user/role has the required CloudWatch permissions |
| "No data returned" | Verify the time range has data; check `default_log_group` exists and `capabilities` includes the expected type |

## Related Pages

- [Observability Overview](observability-overview.md)
- [API Reference](../api/observability.md)
