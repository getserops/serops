#!/usr/bin/env bash
# The sample shop used to validate SerOps on a cluster: three services in
# namespace "production" plus a load generator, standard library Python on the
# public python image (no image to build or push).
#
#   workload.sh up        deploy it (the scripts go in ConfigMap shop-scripts)
#   workload.sh incident  a bad rollout: payments 1.1.0 with DB_POOL_SIZE=2; under
#                         the load generator's 15 rps most charges fail with
#                         "503 pool exhausted" and checkout/frontend return 502
#   workload.sh heal      roll payments back to 1.0.0 with a pool of 20
#   workload.sh down      delete the namespace
# Uses the current kubectl context, or KUBECONFIG.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
case "${1:-}" in
  up)
    kubectl apply -f "$HERE/shop.yaml" >/dev/null
    kubectl -n production create configmap shop-scripts --from-file="$HERE/shop.py" \
      --from-file="$HERE/loadgen.py" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    kubectl -n production rollout restart deploy >/dev/null
    kubectl -n production rollout status deploy --timeout=5m
    ;;
  incident) kubectl -n production set env deploy/payments DB_POOL_SIZE=2 VERSION=1.1.0 >/dev/null
            kubectl -n production rollout status deploy/payments --timeout=3m
            date -u +"bad rollout at %Y-%m-%dT%H:%M:%SZ" ;;
  heal)     kubectl -n production set env deploy/payments DB_POOL_SIZE=20 VERSION=1.0.0 >/dev/null
            kubectl -n production rollout status deploy/payments --timeout=3m ;;
  down)     kubectl delete namespace production --wait=false ;;
  *) sed -n '2,13p' "$0"; exit 1 ;;
esac
