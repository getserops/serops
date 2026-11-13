#!/usr/bin/env bash
# A small GKE cluster to install SerOps on, and its teardown.
#
#   deploy/cloud/gke/cluster.sh up      zonal GKE Standard cluster (Dataplane V2, which
#                                       enforces NetworkPolicy; logs and metrics to Cloud
#                                       Logging / Monitoring), ingress-nginx, cert-manager
#                                       with a Let's Encrypt issuer, Postgres and Redis in
#                                       the serops namespace
#   deploy/cloud/gke/cluster.sh token   a fresh 12 h kubeconfig token
#   deploy/cloud/gke/cluster.sh lock    restrict the load balancer to this machine's public
#                                       IP (after the certificate is issued)
#   deploy/cloud/gke/cluster.sh open    accept the internet again
#   deploy/cloud/gke/cluster.sh reader  custom role with only the permissions the Google
#                                       Cloud integration calls, granted to $READER_SA
#                                       in place of Logs Viewer + Monitoring Viewer
#   deploy/cloud/gke/cluster.sh reader-builtin
#                                       back to Logs Viewer + Monitoring Viewer, custom role deleted
#   deploy/cloud/gke/cluster.sh down    delete the cluster, wait, then list what is left
#                                       (clusters, disks, forwarding rules, addresses,
#                                       firewall rules)
#   deploy/cloud/gke/cluster.sh status  what is left in the project
#
# Needs: kubectl, helm, and gcloud signed in. Without a local gcloud, set
# GC_DOCKER_CONFIG to a directory and the official google-cloud-cli container is
# used with it as its config (sign in once with `docker run -it --rm
#  -v "$GC_DOCKER_CONFIG:/root/.config/gcloud" gcr.io/google.com/cloudsdktool/google-cloud-cli:stable
#  gcloud auth login --no-launch-browser`).
# The kubeconfig holds a 12 h token of a service account that exists only in the
# cluster (no Google credential); it goes to $KUBECONFIG_OUT, never the repository.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
PROJECT=${PROJECT:?set PROJECT to your Google Cloud project id}
CLUSTER=${CLUSTER:-serops-validate} ZONE=${ZONE:-europe-west1-b}
SIZE=${SIZE:-e2-standard-2} NODES=${NODES:-2} NS=${NS:-serops}
KUBECONFIG_OUT=${KUBECONFIG_OUT:-$HOME/.kube/serops-gke-validate}
READER_SA=${READER_SA:-serops-reader@$PROJECT.iam.gserviceaccount.com}
ROLE_ID=${ROLE_ID:-seropsMonitoringReader}
# What the integration calls (checked on GKE 2026-11-12): Cloud Logging
# entries.list, Cloud Monitoring timeSeries.list and metricDescriptors.list.
ROLE_PERMISSIONS=logging.logEntries.list,monitoring.timeSeries.list,monitoring.metricDescriptors.list
INGRESS_NGINX_VERSION=4.15.1 CERT_MANAGER_VERSION=v1.21.3

gcloud() {
  if [ -n "${GC_DOCKER_CONFIG:-}" ]; then
    docker run --rm -i -v "$GC_DOCKER_CONFIG:/root/.config/gcloud" \
      gcr.io/google.com/cloudsdktool/google-cloud-cli:stable gcloud "$@"
  else command gcloud "$@"; fi
}
G() { gcloud --project "$PROJECT" -q "$@"; }
K() { kubectl --kubeconfig "$KUBECONFIG_OUT" "$@"; }
H() { helm --kubeconfig "$KUBECONFIG_OUT" "$@"; }

kubeconfig() {
  # Bootstrap with a 1 h Google access token, then keep only the token of a
  # service account that lives in the cluster.
  local server ca boot token
  server=$(G container clusters describe "$CLUSTER" --zone "$ZONE" --format='value(endpoint)')
  ca=$(G container clusters describe "$CLUSTER" --zone "$ZONE" --format='value(masterAuth.clusterCaCertificate)')
  write() { printf 'apiVersion: v1\nkind: Config\nclusters: [{name: %s, cluster: {server: "https://%s", certificate-authority-data: %s}}]\nusers: [{name: u, user: {token: "%s"}}]\ncontexts: [{name: %s, context: {cluster: %s, user: u}}]\ncurrent-context: %s\n' \
    "$CLUSTER" "$server" "$ca" "$1" "$CLUSTER" "$CLUSTER" "$CLUSTER" > "$2"; }
  boot=$(mktemp); chmod 600 "$boot"
  write "$(gcloud auth print-access-token)" "$boot"
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

leftovers() {
  echo "clusters:         $(G container clusters list --format='value(name)' | tr '\n' ' ')"
  echo "disks:            $(G compute disks list --format='value(name)' | tr '\n' ' ')"
  echo "forwarding rules: $(G compute forwarding-rules list --format='value(name)' | tr '\n' ' ')"
  echo "addresses:        $(G compute addresses list --format='value(name)' | tr '\n' ' ')"
  echo "firewall rules:   $(G compute firewall-rules list --filter='name~^(gke-|k8s)' --format='value(name)' | tr '\n' ' ')"
}

case "${1:-}" in
  up)
    if ! G container clusters describe "$CLUSTER" --zone "$ZONE" --format='value(name)' >/dev/null 2>&1; then
      G container clusters create "$CLUSTER" --zone "$ZONE" \
        --num-nodes "$NODES" --machine-type "$SIZE" --disk-type pd-standard --disk-size 50 \
        --enable-dataplane-v2 --release-channel regular \
        --logging=SYSTEM,WORKLOAD --monitoring=SYSTEM
    fi
    kubeconfig
    K get nodes -o wide

    H repo add ingress-nginx https://kubernetes.github.io/ingress-nginx >/dev/null 2>&1 || true
    H repo add jetstack https://charts.jetstack.io >/dev/null 2>&1 || true
    H repo update >/dev/null
    H upgrade --install ingress-nginx ingress-nginx/ingress-nginx --version "$INGRESS_NGINX_VERSION" \
      -n ingress-nginx --create-namespace \
      --set controller.service.externalTrafficPolicy=Local --wait --timeout 10m >/dev/null
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
    if G iam roles describe "$ROLE_ID" --format='value(name)' >/dev/null 2>&1; then
      G iam roles update "$ROLE_ID" --permissions "$ROLE_PERMISSIONS" >/dev/null
    else
      G iam roles create "$ROLE_ID" --title "SerOps Cloud Logging and Monitoring reader" \
        --description "Read access for the SerOps Google Cloud integration" \
        --permissions "$ROLE_PERMISSIONS" --stage GA >/dev/null
    fi
    G projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$READER_SA" \
      --role "projects/$PROJECT/roles/$ROLE_ID" --condition=None >/dev/null
    for r in roles/logging.viewer roles/monitoring.viewer; do
      G projects remove-iam-policy-binding "$PROJECT" --member "serviceAccount:$READER_SA" \
        --role "$r" --condition=None >/dev/null 2>&1 || true
    done
    echo "$READER_SA: only projects/$PROJECT/roles/$ROLE_ID ($ROLE_PERMISSIONS)"
    ;;
  reader-builtin)
    # Back to the documented built-in roles, and drop the custom one.
    for r in roles/logging.viewer roles/monitoring.viewer; do
      G projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$READER_SA" \
        --role "$r" --condition=None >/dev/null
    done
    G projects remove-iam-policy-binding "$PROJECT" --member "serviceAccount:$READER_SA" \
      --role "projects/$PROJECT/roles/$ROLE_ID" --condition=None >/dev/null 2>&1 || true
    G iam roles delete "$ROLE_ID" >/dev/null 2>&1 || true
    echo "$READER_SA: roles/logging.viewer + roles/monitoring.viewer; custom role $ROLE_ID deleted"
    ;;
  down)
    if G container clusters describe "$CLUSTER" --zone "$ZONE" --format='value(name)' >/dev/null 2>&1; then
      # The load balancer's forwarding rule and firewall rules belong to the
      # Service: delete it first so GKE removes them, then the cluster.
      # Persistent disks of PVCs outlive the cluster: delete the PVCs too.
      if [ -f "$KUBECONFIG_OUT" ]; then
        K -n ingress-nginx delete svc ingress-nginx-controller --wait=true --timeout=5m 2>/dev/null || true
        K delete namespace "$NS" production --ignore-not-found --wait=true --timeout=10m || true
      fi
      G container clusters delete "$CLUSTER" --zone "$ZONE"
    fi
    rm -f "$KUBECONFIG_OUT"
    leftovers
    ;;
  status) leftovers ;;
  *) sed -n '2,28p' "$0"; exit 1 ;;
esac
