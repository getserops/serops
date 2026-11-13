---
seo_title: "Install SerOps on Amazon EKS"
description: "Install SerOps 1.3.0 on Amazon EKS with the Helm chart: a Network Load Balancer, TLS from cert-manager, NetworkPolicies enforced by the VPC CNI, CloudWatch Container Insights with a five-action IAM policy, and the exact commands we ran."
---
# Install on EKS

!!! success "Tested on 2026-11-13"
    SerOps 1.3.0 on EKS 1.36 (`eu-central-1`, 3 × `t3.medium`, Amazon Linux
    2023), with the VPC CNI enforcing NetworkPolicy: a fresh install in 55
    seconds, TLS from Let's Encrypt through cert-manager behind a Network Load
    Balancer, CloudWatch Container Insights for logs and metrics read with a
    five-action IAM policy, and an incident found by an investigation. Every
    command below is one we ran.

The repository ships the scripts we used: `deploy/cloud/eks/cluster.sh`
(cluster, add-ons, ingress, cert-manager, a test Postgres and Redis, the
reader user, teardown) and `deploy/cloud/common/workload/workload.sh` (a sample
application and an incident). For production, use Amazon RDS for PostgreSQL
and ElastiCache for Redis instead of the in-cluster ones.

## 1. Verify what you install

The same commands as on [AKS](aks.md#1-verify-what-you-install): cosign 3
for the images and the chart, `gh attestation verify` for the provenance.

## 2. Cluster, ingress, cert-manager

```bash
aws login                      # AWS CLI v2
deploy/cloud/eks/cluster.sh up
export KUBECONFIG=~/.kube/serops-eks-validate
```

`up` runs eksctl with this cluster configuration, then installs the rest:

```yaml
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig
metadata: {name: serops-validate, region: eu-central-1, version: "1.36"}
vpc:
  nat: {gateway: Disable}          # nodes in public subnets: no NAT gateway to pay for
iam: {withOIDC: false}             # add-ons use the node role
addons:
  - name: vpc-cni
    configurationValues: '{"enableNetworkPolicy":"true"}'
  - name: coredns
  - name: kube-proxy
  - name: aws-ebs-csi-driver
  - name: amazon-cloudwatch-observability
    configurationValues: '{"agent":{"config":{"logs":{"metrics_collected":{"kubernetes":{"enhanced_container_insights":false}}}}}}'
managedNodeGroups:
  - name: nodes
    instanceType: t3.medium
    desiredCapacity: 3
    volumeSize: 30
    volumeType: gp3
    iam:
      attachPolicyARNs:
        - arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy
        - arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy
        - arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly
        - arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy
        - arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy
```

```bash
# A default StorageClass: EKS no longer marks one default.
kubectl apply -f - <<EOF
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata: {name: gp3, annotations: {storageclass.kubernetes.io/is-default-class: "true"}}
provisioner: ebs.csi.aws.com
parameters: {type: gp3}
volumeBindingMode: WaitForFirstConsumer
EOF
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx --version 4.15.1 \
  -n ingress-nginx --create-namespace --set controller.service.externalTrafficPolicy=Local \
  --set-string 'controller.service.annotations.service\.beta\.kubernetes\.io/aws-load-balancer-type=nlb' \
  --set-string 'controller.service.annotations.service\.beta\.kubernetes\.io/aws-load-balancer-cross-zone-load-balancing-enabled=true'
helm upgrade --install cert-manager jetstack/cert-manager --version v1.21.3 \
  -n cert-manager --create-namespace --set crds.enabled=true
kubectl apply -f deploy/cloud/common/cluster-issuer.yaml
```

* **NetworkPolicy needs the VPC CNI's `enableNetworkPolicy`** (or Calico).
  With it, the chart's policies are enforced: checked, a pod in another
  namespace cannot reach the backend or the frontend, while the ingress
  controller can.
* **Turn on cross-zone load balancing.** With `externalTrafficPolicy=Local`
  and cross-zone off, only the zones that run an ingress-nginx pod answer:
  a name pointing at another zone's address times out, and Let's Encrypt's
  HTTP-01 check with it.
* **Pods per node.** Without prefix delegation the VPC CNI gives a
  `t3.medium` 17 pods. SerOps, the add-ons and a small workload need about
  40: three `t3.medium` nodes, or larger nodes.
* The script's kubeconfig holds a 12-hour token of a service account that
  exists only in the cluster, so no AWS credential sits in it
  (`cluster.sh token` renews it).

## 3. Secrets, values, install

As on AKS: [secrets and values](aks.md#3-secrets-and-values), then

```bash
helm install serops oci://ghcr.io/getserops/charts/serops --version 1.3.0 \
  -n serops -f eks-values.yaml --wait --timeout 15m
kubectl -n serops get certificate serops-tls      # READY True
```

Install `--version 1.3.1`: the same chart, with the fix for several
clusters in one region found on this test (see [Known issues](#known-issues)).

The defaults fit three `t3.medium` nodes: no resource override is needed.
Open `https://HOST`, register the first account (registration then closes),
and only then restrict the load balancer if you want to (`cluster.sh lock`).

Checked after install: HSTS with `includeSubDomains`, plain HTTP redirected
(308), PodDisruptionBudgets for backend, frontend and worker, the migration
job completed, every SerOps pod on the `serops` ServiceAccount.

## 4. CloudWatch logs and metrics

The Amazon CloudWatch Observability add-on (in the cluster configuration
above) ships container logs to `/aws/containerinsights/<cluster>/application`
with Fluent Bit and publishes Container Insights metrics; the node role needs
`CloudWatchAgentServerPolicy`. We turned off enhanced observability, which
adds per-pod metrics SerOps does not read.

**IAM user for SerOps.** Five read actions are enough; `cluster.sh reader`
creates the user, the policy and an access key:

| Action | For |
|---|---|
| `logs:StartQuery`, `logs:GetQueryResults` | Logs Insights queries |
| `logs:DescribeLogGroups` | Finding the Container Insights log group |
| `cloudwatch:ListMetrics`, `cloudwatch:GetMetricData` | Container CPU and memory per Service |

The three write actions on the [CloudWatch](../integrations/cloudwatch.md#prerequisites)
page are needed only to store CI/CD pipeline logs in CloudWatch. SerOps reads
CloudWatch only with the access key you give it, never with the node role
(see [CloudWatch](../integrations/cloudwatch.md)).

In SerOps: **Settings → Integrations → Log Providers**, add **AWS
CloudWatch**: the key, the region, topology **Kubernetes**, logs and metrics
ticked. Then the project's **Data** tab → **Check my data**, and **Use** the
namespace your services run in (`kubernetes.namespace_name = production` for
us).

On our test the bad rollout of the sample application (`workload.sh
incident`: a database pool of 2) was found by an investigation in 92 seconds,
with Claude as the AI provider: the payments pool exhausted, 503s turning
into 502s upstream.

## Known issues

* **Several clusters in one region, 1.3.0.** CloudWatch keeps listing a
  deleted cluster's metrics for two weeks. When another cluster (live, or
  deleted recently) has the same namespace and Service names, 1.3.0 may read
  its series instead of yours: on our test the investigation got no metrics,
  because a cluster deleted two weeks earlier also ran `production/payments`.
  Fixed in 1.3.1 (validated on this cluster: 180 metric points, CPU and
  memory per service). On 1.3.0, use a namespace name no other cluster in
  the region uses.
* **Not on the free plan.** EKS charges for the control plane by the hour
  on top of the nodes, the load balancer and public IPv4 addresses. Our
  cluster ran 70 minutes; by the published `eu-central-1` rates that is
  under one US dollar, CloudWatch ingestion included.

## Tear down

```bash
deploy/cloud/eks/cluster.sh down
```

`down` deletes the ingress Service (and with it the load balancer) and the
namespaces (and with them the EBS volumes), then the cluster and its
CloudFormation stacks, the reader user and the Container Insights log groups,
and lists what is left (clusters, stacks, instances, volumes, load balancers,
addresses, NAT gateways, log groups).
