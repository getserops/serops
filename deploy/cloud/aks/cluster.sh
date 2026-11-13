#!/usr/bin/env bash
# A small AKS cluster to install SerOps on, and its teardown.
#
#   deploy/cloud/aks/cluster.sh up      resource group, AKS (Azure CNI overlay with
#                                       the Cilium dataplane, which enforces
#                                       NetworkPolicy), ingress-nginx, cert-manager
#                                       with a Let's Encrypt issuer, Postgres and
#                                       Redis in the serops namespace
#   deploy/cloud/aks/cluster.sh lock    restrict the load balancer to this machine's
#                                       public IP (after the certificate is issued:
#                                       Let's Encrypt must reach port 80 first)
#   deploy/cloud/aks/cluster.sh open    accept the internet again (a new certificate)
#   deploy/cloud/aks/cluster.sh monitoring
#                                       Log Analytics workspace in the resource group
#                                       and Container Insights on the cluster
#   deploy/cloud/aks/cluster.sh reader  service principal for the Azure Monitor
#                                       integration with a custom role holding only
#                                       the five read actions SerOps calls, on the
#                                       workspace and the cluster; its tenant, client
#                                       id, secret and workspace id go to $READER_OUT
#   deploy/cloud/aks/cluster.sh down    delete the reader's app registration (it lives in
#                                       the tenant, not the resource group), then the
#                                       resource group: cluster, disks, load balancer,
#                                       public IP, Log Analytics workspace
#   deploy/cloud/aks/cluster.sh status  what is left in the subscription
#
# Needs: kubectl, helm, and the Azure CLI signed in (`az login`). Without a
# local az, set AZ_DOCKER_CONFIG to a directory and the official azure-cli
# container is used with that directory as its config (sign in once with
# `docker run -it --rm --network host -e DISPLAY=:0 -e BROWSER=echo
#  -v "$AZ_DOCKER_CONFIG:/root/.azure" mcr.microsoft.com/azure-cli az login`).
# No credential is written to the repository: the kubeconfig goes to $KUBECONFIG_OUT.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
RG=${RG:-serops-validate} CLUSTER=${CLUSTER:-serops-validate} LOC=${LOC:-francecentral}
SIZE=${SIZE:-Standard_D2as_v7} NODES=${NODES:-2} NS=${NS:-serops}
KUBECONFIG_OUT=${KUBECONFIG_OUT:-$HOME/.kube/serops-aks-validate}
READER_OUT=${READER_OUT:-$HOME/.config/serops-validate/azure-reader.env}
WORKSPACE=${WORKSPACE:-serops-validate-logs} READER_NAME=${READER_NAME:-serops-validate-reader}
ROLE_NAME=${ROLE_NAME:-SerOps Azure Monitor reader ($RG)}
# What the integration calls, checked on AKS 2026-11-11: Log Analytics queries
# (logs, and Container Insights metrics in the Perf table) and Azure Monitor
# metrics. Log Analytics Reader + Monitoring Reader also work, more broadly.
ROLE_ACTIONS='"Microsoft.OperationalInsights/workspaces/read","Microsoft.OperationalInsights/workspaces/query/read","Microsoft.OperationalInsights/workspaces/query/*/read","Microsoft.Insights/metrics/read","Microsoft.Insights/metricDefinitions/read"'
SUBSCRIPTION=${SUBSCRIPTION:-}   # default: the CLI's current subscription
INGRESS_NGINX_VERSION=4.15.1 CERT_MANAGER_VERSION=v1.21.3

az() {
  if [ -n "${AZ_DOCKER_CONFIG:-}" ]; then
    docker run --rm -i -v "$AZ_DOCKER_CONFIG:/root/.azure" -v "$HERE/..:/work:ro" \
      mcr.microsoft.com/azure-cli:latest az "$@"
  else command az "$@"; fi
}
sub() { [ -n "$SUBSCRIPTION" ] && echo "--subscription $SUBSCRIPTION" || true; }
K() { kubectl --kubeconfig "$KUBECONFIG_OUT" "$@"; }
H() { helm --kubeconfig "$KUBECONFIG_OUT" "$@"; }

case "${1:-}" in
  up)
    az group create -n "$RG" -l "$LOC" $(sub) -o none
    if ! az aks show -g "$RG" -n "$CLUSTER" $(sub) -o none 2>/dev/null; then
      az aks create -g "$RG" -n "$CLUSTER" -l "$LOC" $(sub) --tier free \
        --node-count "$NODES" --node-vm-size "$SIZE" \
        --network-plugin azure --network-plugin-mode overlay --network-dataplane cilium \
        --generate-ssh-keys -o none
    fi
    mkdir -p "$(dirname "$KUBECONFIG_OUT")"
    ( umask 077; az aks get-credentials -g "$RG" -n "$CLUSTER" $(sub) --file - > "$KUBECONFIG_OUT" )
    K get nodes -o wide

    H repo add ingress-nginx https://kubernetes.github.io/ingress-nginx >/dev/null 2>&1 || true
    H repo add jetstack https://charts.jetstack.io >/dev/null 2>&1 || true
    H repo update >/dev/null
    # The Azure load balancer probes /healthz; the default probe path (/) gets 404.
    H upgrade --install ingress-nginx ingress-nginx/ingress-nginx --version "$INGRESS_NGINX_VERSION" \
      -n ingress-nginx --create-namespace \
      --set controller.service.externalTrafficPolicy=Local \
      --set 'controller.service.annotations.service\.beta\.kubernetes\.io/azure-load-balancer-health-probe-request-path=/healthz' \
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

    IP=$(K -n ingress-nginx get svc ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
    echo "load balancer: $IP   host: ${IP//./-}.sslip.io   kubeconfig: $KUBECONFIG_OUT"
    ;;
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
  monitoring)
    az monitor log-analytics workspace create -g "$RG" -n "$WORKSPACE" -l "$LOC" $(sub) -o none
    WS_ID=$(az monitor log-analytics workspace show -g "$RG" -n "$WORKSPACE" $(sub) --query id -o tsv)
    az aks enable-addons -g "$RG" -n "$CLUSTER" $(sub) -a monitoring --workspace-resource-id "$WS_ID" -o none
    K -n kube-system rollout status ds/ama-logs --timeout=10m
    echo "Container Insights -> $WORKSPACE"
    ;;
  reader)
    WS_ID=$(az monitor log-analytics workspace show -g "$RG" -n "$WORKSPACE" $(sub) --query id -o tsv)
    WS_GUID=$(az monitor log-analytics workspace show -g "$RG" -n "$WORKSPACE" $(sub) --query customerId -o tsv)
    AKS_ID=$(az aks show -g "$RG" -n "$CLUSTER" $(sub) --query id -o tsv)
    RG_ID=$(az group show -n "$RG" $(sub) --query id -o tsv)
    if [ -z "$(az role definition list --name "$ROLE_NAME" $(sub) --query '[0].id' -o tsv)" ]; then
      az role definition create $(sub) -o none --role-definition "{\"Name\":\"$ROLE_NAME\",\"IsCustom\":true,
        \"Description\":\"Read access for the SerOps Azure Monitor integration\",\"Actions\":[$ROLE_ACTIONS],
        \"NotActions\":[],\"AssignableScopes\":[\"$RG_ID\"]}"
      sleep 30  # a new role definition takes a moment to be assignable
    fi
    mkdir -p "$(dirname "$READER_OUT")"
    ( umask 077
      az ad sp create-for-rbac -n "$READER_NAME" --query '[tenant,appId,password]' -o tsv | tr -d '\r' | {
        read -r tenant; read -r app; read -r secret
        printf 'AZ_TENANT_ID=%s\nAZ_CLIENT_ID=%s\nAZ_CLIENT_SECRET=%s\nAZ_WORKSPACE_ID=%s\nAZ_RESOURCE_URI=%s\n' \
          "$tenant" "$app" "$secret" "$WS_GUID" "$AKS_ID" > "$READER_OUT"
        for scope in "$WS_ID" "$AKS_ID"; do
          az role assignment create --assignee "$app" --role "$ROLE_NAME" --scope "$scope" $(sub) -o none
        done
      } )
    echo "reader $READER_NAME: \"$ROLE_NAME\" on $WORKSPACE and $CLUSTER; settings in $READER_OUT"
    ;;
  down)
    APP=$(az ad sp list --display-name "$READER_NAME" --query '[0].appId' -o tsv 2>/dev/null || true)
    [ -n "$APP" ] && az ad app delete --id "$APP" && echo "deleted app registration $READER_NAME"
    rm -f "$READER_OUT"
    az group delete -n "$RG" $(sub) --yes -o none
    # The custom role is defined at subscription level; its assignments went
    # with the resource group.
    az role definition delete --name "$ROLE_NAME" $(sub) 2>/dev/null && echo "deleted role $ROLE_NAME" || true
    # AKS creates NetworkWatcherRG on the first cluster in a region; remove it
    # when it holds nothing but the watcher it was created for.
    if az group exists -n NetworkWatcherRG $(sub) | grep -q true; then
      n=$(az resource list -g NetworkWatcherRG $(sub) --query "length([?type!='Microsoft.Network/networkWatchers'])" -o tsv)
      [ "$n" = 0 ] && az group delete -n NetworkWatcherRG $(sub) --yes -o none && echo "deleted NetworkWatcherRG"
    fi
    rm -f "$KUBECONFIG_OUT"
    echo "deleted resource group $RG (and the AKS node resource group with it)"
    ;;
  status)
    az group list $(sub) --query "[].{name:name,location:location}" -o table
    ;;
  *) sed -n '2,24p' "$0"; exit 1 ;;
esac
