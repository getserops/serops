---
seo_title: "Install SerOps on Google Kubernetes Engine (GKE)"
description: "Install SerOps 1.3.0 on GKE with the Helm chart: TLS from cert-manager, NetworkPolicies enforced by Dataplane V2, Google Cloud Logging and Monitoring with a three-permission role, and the exact commands we ran."
---
# Install on GKE

!!! success "Tested on 2026-11-12"
    SerOps 1.3.0 on GKE 1.36.4 (Standard, zonal `europe-west1-b`, 2 ×
    `e2-standard-2`), Dataplane V2: a fresh install in 76 seconds, TLS from
    Let's Encrypt through cert-manager, NetworkPolicies enforced, Google Cloud
    Logging and Monitoring for logs and metrics with a three-permission custom
    role, and an incident found by an investigation. Every command below is
    one we ran.

The repository ships the scripts we used: `deploy/cloud/gke/cluster.sh`
(cluster, ingress, cert-manager, a test Postgres and Redis, the reader role,
teardown) and `deploy/cloud/common/workload/workload.sh` (a sample application
and an incident). For production, use Cloud SQL for PostgreSQL and Memorystore
for Redis instead of the in-cluster ones.

## 1. Verify what you install

The same commands as on [AKS](aks.md#1-verify-what-you-install): cosign 3
for the images and the chart, `gh attestation verify` for the provenance.

## 2. Cluster, ingress, cert-manager

```bash
gcloud auth login
PROJECT=<project> deploy/cloud/gke/cluster.sh up
export KUBECONFIG=~/.kube/serops-gke-validate
```

What `up` runs, if you prefer your own cluster:

```bash
gcloud container clusters create <cluster> --zone europe-west1-b \
  --num-nodes 2 --machine-type e2-standard-2 --disk-type pd-standard --disk-size 50 \
  --enable-dataplane-v2 --release-channel regular --logging=SYSTEM,WORKLOAD --monitoring=SYSTEM
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx --version 4.15.1 \
  -n ingress-nginx --create-namespace --set controller.service.externalTrafficPolicy=Local
helm upgrade --install cert-manager jetstack/cert-manager --version v1.21.3 \
  -n cert-manager --create-namespace --set crds.enabled=true
kubectl apply -f deploy/cloud/common/cluster-issuer.yaml
```

* **NetworkPolicy needs Dataplane V2** (or Calico on older clusters). With
  it, the chart's policies are enforced: checked, a pod in another namespace
  cannot reach the backend or the frontend.
* The script's kubeconfig holds a 12-hour token of a service account that
  exists only in the cluster, so no Google credential sits on disk and the
  `gke-gcloud-auth-plugin` is not needed (`cluster.sh token` renews it).
* Chart versions before 1.2.14 refused GKE's version string
  (`v1.36.4-gke.…`); 1.3.0 installs.

## 3. Secrets, values, install

As on AKS: [secrets and values](aks.md#3-secrets-and-values), then

```bash
helm install serops oci://ghcr.io/getserops/charts/serops --version 1.3.0 \
  -n serops -f gke-values.yaml --wait --timeout 15m
kubectl -n serops get certificate serops-tls      # READY True after ~30 s
```

Install `--version 1.3.1`: the same chart, with the fix for plain-text
errors on stdout found on this test (see [Known issues](#known-issues)).

Open `https://HOST`, register the first account (registration then closes),
and only then restrict the load balancer if you want to (`cluster.sh lock`).

Checked after install: HSTS with `includeSubDomains`, plain HTTP redirected
(308), PodDisruptionBudgets for backend, frontend and worker, the migration
job completed, every SerOps pod on the `serops` ServiceAccount.

## 4. Google Cloud Logging and Monitoring

GKE sends container logs and metrics to Google by default: nothing to install
in the cluster.

**Service account.** Logs Viewer and Monitoring Viewer work. Three permissions
are enough; `cluster.sh reader` creates that custom role and grants it:

| Permission | For |
|---|---|
| `logging.logEntries.list` | Reading log entries |
| `monitoring.timeSeries.list` | Container CPU and memory |
| `monitoring.metricDescriptors.list` | The health check |

SerOps reads Google only with the service-account JSON key you give it, never
with the node's identity (see [Google Cloud](../integrations/gcp.md)). New
Google Cloud organisations block key creation
(`iam.disableServiceAccountKeyCreation`): an organisation policy
administrator has to allow it for the project.

In SerOps: **Settings → Integrations → Log Providers**, add **Google Cloud**:
the project ID, the key's JSON, topology **Kubernetes** (the onboarding
wizard's GKE checkbox), logs and metrics ticked.
Then the project's **Data** tab → **Check my data**. GKE logs carry no project
name: the check lists the namespaces it sees; **Use** the one your services
run in (`namespace = production` for us), or name the namespace after the
project.

On our test the bad rollout of the sample application (`workload.sh
incident`: a database pool of 2) was found by an investigation in 41 seconds:
the payments pool exhausted, 503s turning into 502s upstream. The same result
with the three-permission role (31 seconds).

## Known issues

* **Plain-text errors on stdout, 1.3.0.** GKE rates every plain-text stdout
  line INFO, and 1.3.0 left those lines out of the analysis even when they
  say `ERROR`: our first investigation collected 1 log out of 1,000 errors.
  Fixed in 1.3.1 (we validated the fix on this cluster). On 1.3.0, write
  errors to stderr or log JSON with a `severity` field.
* **The AI provider test can time out.** The connection test under
  **Settings → AI** waits for the provider's answer; when it takes over 60
  seconds the ingress returns 504. Gemini took 37 seconds to answer
  "Say OK" that evening. Investigations run in the worker and are not
  affected.
* **Free trial.** The trial's quota allows the two `e2-standard-2` nodes;
  one zonal cluster's management fee is covered by the free tier.

## Tear down

```bash
PROJECT=<project> deploy/cloud/gke/cluster.sh reader-builtin   # if you ran `reader`
PROJECT=<project> deploy/cloud/gke/cluster.sh down
```

`down` deletes the namespaces first, so the load balancer and the persistent
disks go with them, then the cluster, and lists what is left (clusters,
disks, forwarding rules, addresses, firewall rules).
