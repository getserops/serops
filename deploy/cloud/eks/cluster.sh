#!/usr/bin/env bash
# A small EKS cluster to install SerOps on, and its teardown.
#
#   deploy/cloud/eks/cluster.sh up      EKS cluster with eksctl (VPC CNI with network policy
#                                       enforcement, EBS CSI driver, the Amazon CloudWatch
#                                       Observability add-on sending container logs and
#                                       Container Insights metrics to CloudWatch; nodes in
#                                       public subnets, no NAT gateway), a gp3 default
#                                       StorageClass, ingress-nginx behind a Network Load
#                                       Balancer, cert-manager with a Let's Encrypt issuer,
#                                       Postgres and Redis in the serops namespace
#   deploy/cloud/eks/cluster.sh token   a fresh 12 h kubeconfig token
#   deploy/cloud/eks/cluster.sh lock    restrict the load balancer to this machine's public
#                                       IP (after the certificate is issued)
#   deploy/cloud/eks/cluster.sh open    accept the internet again
#   deploy/cloud/eks/cluster.sh reader  IAM user with only the five read actions the
#                                       CloudWatch integration calls; its access key goes
#                                       to $READER_OUT
#   deploy/cloud/eks/cluster.sh down    load balancer, namespaces (their EBS volumes), the
#                                       cluster and its CloudFormation stacks, the reader
#                                       user, the Container Insights log groups; then list
#                                       what is left
#   deploy/cloud/eks/cluster.sh status  what is left in the region
#
# Needs: kubectl, helm, eksctl and the AWS CLI v2 signed in (`aws login`). Without a
# local AWS CLI v2, set AWS_DOCKER_CONFIG to a directory and the official aws-cli
# container is used with it as its ~/.aws (sign in once with `docker run -it --rm
#  -v "$AWS_DOCKER_CONFIG:/root/.aws" amazon/aws-cli login --remote`); eksctl then
# gets its credentials from that container through credential_process.
# The kubeconfig holds a 12 h token of a service account that exists only in the
# cluster (no AWS credential); it goes to $KUBECONFIG_OUT, never the repository.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
CLUSTER=${CLUSTER:-serops-validate} REGION=${REGION:-eu-central-1} K8S_VERSION=${K8S_VERSION:-1.36}
SIZE=${SIZE:-t3.medium} NODES=${NODES:-3} NS=${NS:-serops}
KUBECONFIG_OUT=${KUBECONFIG_OUT:-$HOME/.kube/serops-eks-validate}
READER_USER=${READER_USER:-serops-validate-reader}
READER_OUT=${READER_OUT:-$HOME/.config/serops-validate/aws-reader.env}
EKSCTL=${EKSCTL:-eksctl}
# What the integration calls (checked on EKS 2026-11-13): Logs Insights queries,
# the log group list, and the metric list and values.
READER_ACTIONS='"logs:StartQuery","logs:GetQueryResults","logs:DescribeLogGroups","cloudwatch:ListMetrics","cloudwatch:GetMetricData"'
INGRESS_NGINX_VERSION=4.15.1 CERT_MANAGER_VERSION=v1.21.3

if [ -n "${AWS_DOCKER_CONFIG:-}" ]; then
  aws() { docker run --rm -i -v "$AWS_DOCKER_CONFIG:/root/.aws" amazon/aws-cli:latest "$@"; }
  # eksctl reads credentials through the container (refreshed as they expire).
  EKSCTL_AWS_CONFIG=$(mktemp); chmod 600 "$EKSCTL_AWS_CONFIG"
  trap 'rm -f "$EKSCTL_AWS_CONFIG"' EXIT
  printf '[default]\nregion = %s\ncredential_process = docker run --rm -v %s:/root/.aws amazon/aws-cli:latest configure export-credentials --format process\n' \
    "$REGION" "$AWS_DOCKER_CONFIG" > "$EKSCTL_AWS_CONFIG"
  E() { AWS_CONFIG_FILE=$EKSCTL_AWS_CONFIG AWS_SHARED_CREDENTIALS_FILE=/dev/null "$EKSCTL" "$@"; }
else
  E() { "$EKSCTL" "$@"; }
fi
A() { aws --region "$REGION" --output text "$@"; }
K() { kubectl --kubeconfig "$KUBECONFIG_OUT" "$@"; }
H() { helm --kubeconfig "$KUBECONFIG_OUT" "$@"; }

cluster_config() {
  cat <<EOF
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig
metadata: {name: $CLUSTER, region: $REGION, version: "$K8S_VERSION"}
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
    # Container logs (Fluent Bit) and Container Insights metrics, without the
    # per-pod "enhanced observability" and Application Signals.
    configurationValues: '{"agent":{"config":{"logs":{"metrics_collected":{"kubernetes":{"enhanced_container_insights":false}}}}}}'
managedNodeGroups:
  - name: nodes
    instanceType: $SIZE
    desiredCapacity: $NODES
    volumeSize: 30
    volumeType: gp3
    privateNetworking: false
    iam:
      attachPolicyARNs:
        - arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy
        - arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy
        - arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly
        - arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy
        - arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy
EOF
}

kubeconfig() {
  # Bootstrap with a 15 min EKS token of the AWS identity, then keep only the
  # token of a service account that lives in the cluster.
  local server ca boot token
  server=$(A eks describe-cluster --name "$CLUSTER" --query cluster.endpoint)
  ca=$(A eks describe-cluster --name "$CLUSTER" --query cluster.certificateAuthority.data)
  write() { printf 'apiVersion: v1\nkind: Config\nclusters: [{name: %s, cluster: {server: "%s", certificate-authority-data: %s}}]\nusers: [{name: u, user: {token: "%s"}}]\ncontexts: [{name: %s, context: {cluster: %s, user: u}}]\ncurrent-context: %s\n' \
    "$CLUSTER" "$server" "$ca" "$1" "$CLUSTER" "$CLUSTER" "$CLUSTER" > "$2"; }
  boot=$(mktemp); chmod 600 "$boot"
  write "$(aws --region "$REGION" eks get-token --cluster-name "$CLUSTER" --query status.token --output text)" "$boot"
  if ! kubectl --kubeconfig "$boot" -n kube-system get sa serops-admin >/dev/null 2>&1; then
    kubectl --kubeconfig "$boot" -n kube-system create sa serops-admin >/dev/null
    kubectl --kubeconfig "$boot" create clusterrolebinding serops-admin --clusterrole=cluster-admin \
      --serviceaccount=kube-system:serops-admin >/dev/null
  fi
  token=$(kubectl --kubeconfig "$boot" -n kube-system create token serops-admin --duration=12h)
  rm -f "$boot"
  mkdir -p "$(dirname "$KUBECONFIG_OUT")"
  ( umask 077; write "$token" "$KUBECONFIG_OUT" ); unset token
}

lb_host() { K -n ingress-nginx get svc ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'; }

leftovers() {
  echo "clusters:         $(A eks list-clusters --query clusters)"
  echo "stacks:           $(A cloudformation list-stacks --query "StackSummaries[?StackStatus!='DELETE_COMPLETE' && starts_with(StackName,'eksctl-')].StackName")"
  echo "instances:        $(A ec2 describe-instances --filters Name=instance-state-name,Values=pending,running,stopping,stopped --query 'Reservations[].Instances[].InstanceId')"
  echo "volumes:          $(A ec2 describe-volumes --query 'Volumes[].VolumeId')"
  echo "load balancers:   $(A elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName') $(A elb describe-load-balancers --query 'LoadBalancerDescriptions[].LoadBalancerName')"
  echo "elastic IPs:      $(A ec2 describe-addresses --query 'Addresses[].PublicIp')"
  echo "NAT gateways:     $(A ec2 describe-nat-gateways --filter Name=state,Values=pending,available --query 'NatGateways[].NatGatewayId')"
  echo "log groups:       $(A logs describe-log-groups --log-group-name-prefix "/aws/containerinsights/$CLUSTER" --query 'logGroups[].logGroupName')"
  echo "reader user:      $(A iam list-users --query "Users[?UserName=='$READER_USER'].UserName")"
}

case "${1:-}" in
  up)
    if ! A eks describe-cluster --name "$CLUSTER" --query cluster.name >/dev/null 2>&1; then
      cluster_config | E create cluster -f - --write-kubeconfig=false
    fi
    kubeconfig
    K get nodes -o wide

    K apply -f - >/dev/null <<EOF
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gp3
  annotations: {storageclass.kubernetes.io/is-default-class: "true"}
provisioner: ebs.csi.aws.com
parameters: {type: gp3}
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Delete
EOF

    H repo add ingress-nginx https://kubernetes.github.io/ingress-nginx >/dev/null 2>&1 || true
    H repo add jetstack https://charts.jetstack.io >/dev/null 2>&1 || true
    H repo update >/dev/null
    H upgrade --install ingress-nginx ingress-nginx/ingress-nginx --version "$INGRESS_NGINX_VERSION" \
      -n ingress-nginx --create-namespace \
      --set controller.service.externalTrafficPolicy=Local \
      --set-string 'controller.service.annotations.service\.beta\.kubernetes\.io/aws-load-balancer-type=nlb' \
      --set-string 'controller.service.annotations.service\.beta\.kubernetes\.io/aws-load-balancer-cross-zone-load-balancing-enabled=true' \
      --wait --timeout 10m >/dev/null
    H upgrade --install cert-manager jetstack/cert-manager --version "$CERT_MANAGER_VERSION" \
      -n cert-manager --create-namespace --set crds.enabled=true --wait --timeout 10m >/dev/null
    K apply -f "$HERE/../common/cluster-issuer.yaml"

    K create namespace "$NS" --dry-run=client -o yaml | K apply -f - >/dev/null
    if ! K -n "$NS" get secret serops-data >/dev/null 2>&1; then
      K -n "$NS" create secret generic serops-data \
        --from-literal=postgres-password="$(openssl rand -hex 24)" \
        --from-literal=redis-password="$(openssl rand -hex 24)" >/dev/null
    fi
    K -n "$NS" apply -f "$HERE/../common/data-services.yaml" >/dev/null
    K -n "$NS" rollout status statefulset/postgres --timeout=10m
    K -n "$NS" rollout status deployment/redis --timeout=5m

    # A Network Load Balancer has a DNS name; its per-zone addresses do not
    # change while it exists. With externalTrafficPolicy=Local only the zones
    # running an ingress pod answer, unless cross-zone load balancing is on
    # (above): then any of the addresses works for sslip.io.
    LB=$(lb_host); IP=""
    for _ in $(seq 60); do IP=$(getent ahostsv4 "$LB" | awk 'NR==1{print $1}' || true); [ -n "$IP" ] && break; sleep 10; done
    echo "load balancer: $LB ($IP)   host: ${IP//./-}.sslip.io   kubeconfig: $KUBECONFIG_OUT"
    ;;
  token) kubeconfig; K get nodes ;;
  lock)
    MY=$(curl -s -m 10 https://api.ipify.org)
    H upgrade ingress-nginx ingress-nginx/ingress-nginx --version "$INGRESS_NGINX_VERSION" -n ingress-nginx \
      --reuse-values --set "controller.service.loadBalancerSourceRanges={$MY/32}" --wait >/dev/null
    echo "load balancer now accepts only $MY"
    ;;
  open)
    H upgrade ingress-nginx ingress-nginx/ingress-nginx --version "$INGRESS_NGINX_VERSION" -n ingress-nginx \
      --reuse-values --set 'controller.service.loadBalancerSourceRanges=null' --wait >/dev/null
    echo "load balancer accepts the internet"
    ;;
  reader)
    if ! A iam get-user --user-name "$READER_USER" >/dev/null 2>&1; then
      A iam create-user --user-name "$READER_USER" >/dev/null
    fi
    A iam put-user-policy --user-name "$READER_USER" --policy-name serops-cloudwatch-read \
      --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[$READER_ACTIONS],\"Resource\":\"*\"}]}"
    for k in $(A iam list-access-keys --user-name "$READER_USER" --query 'AccessKeyMetadata[].AccessKeyId'); do
      A iam delete-access-key --user-name "$READER_USER" --access-key-id "$k"
    done
    mkdir -p "$(dirname "$READER_OUT")"
    ( umask 077
      A iam create-access-key --user-name "$READER_USER" \
        --query 'AccessKey.[AccessKeyId,SecretAccessKey]' |
        awk -v r="$REGION" -v c="$CLUSTER" '{print "AWS_KEY_ID="$1; print "AWS_SECRET="$2; print "AWS_REGION="r; print "EKS_CLUSTER="c}' > "$READER_OUT" )
    echo "$READER_USER: only $READER_ACTIONS; key in $READER_OUT"
    ;;
  down)
    if A eks describe-cluster --name "$CLUSTER" --query cluster.name >/dev/null 2>&1; then
      # The Network Load Balancer belongs to the Service and the EBS volumes to
      # the PVCs: delete them first so Kubernetes removes them, then the cluster.
      [ -f "$KUBECONFIG_OUT" ] || kubeconfig || true
      if [ -f "$KUBECONFIG_OUT" ]; then
        K -n ingress-nginx delete svc ingress-nginx-controller --wait=true --timeout=5m 2>/dev/null || true
        K delete namespace "$NS" production --ignore-not-found --wait=true --timeout=10m || true
      fi
      E delete cluster --name "$CLUSTER" --region "$REGION" --wait --disable-nodegroup-eviction
    fi
    rm -f "$KUBECONFIG_OUT"
    if A iam get-user --user-name "$READER_USER" >/dev/null 2>&1; then
      for k in $(A iam list-access-keys --user-name "$READER_USER" --query 'AccessKeyMetadata[].AccessKeyId'); do
        A iam delete-access-key --user-name "$READER_USER" --access-key-id "$k"
      done
      A iam delete-user-policy --user-name "$READER_USER" --policy-name serops-cloudwatch-read 2>/dev/null || true
      A iam delete-user --user-name "$READER_USER"
    fi
    rm -f "$READER_OUT"
    for g in $(A logs describe-log-groups --log-group-name-prefix "/aws/containerinsights/$CLUSTER" --query 'logGroups[].logGroupName') \
             $(A logs describe-log-groups --log-group-name-prefix "/aws/eks/$CLUSTER" --query 'logGroups[].logGroupName'); do
      A logs delete-log-group --log-group-name "$g"
    done
    leftovers
    ;;
  status) leftovers ;;
  *) sed -n '2,30p' "$0"; exit 1 ;;
esac
