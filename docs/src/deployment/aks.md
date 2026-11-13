---
seo_title: "Install SerOps on Azure Kubernetes Service (AKS)"
description: "Install SerOps 1.3.0 on AKS with the Helm chart: TLS from cert-manager, NetworkPolicies enforced by Cilium, Azure Monitor for logs and metrics, and the exact commands we ran."
---
# Install on AKS

!!! success "Tested on 2026-11-11"
    SerOps 1.3.0 on AKS 1.36.5 (France Central, free tier, 2 × `Standard_D2as_v7`),
    Azure CNI overlay with the Cilium dataplane: an upgrade from 1.2.14 and a fresh
    install, TLS from Let's Encrypt through cert-manager, NetworkPolicies enforced,
    Azure Monitor (Container Insights) for logs and metrics, an incident found by an
    investigation, the Enterprise license, per-project access and Entra ID sign-in.
    Every command
    below is one we ran.

The repository ships the scripts we used: `deploy/cloud/aks/cluster.sh` (cluster,
ingress, cert-manager, a test Postgres and Redis, Azure Monitor, teardown) and
`deploy/cloud/common/workload/workload.sh` (a sample application and an incident).
For production, use Azure Database for PostgreSQL and Azure Cache for Redis instead
of the in-cluster ones.

## 1. Verify what you install

```bash
cosign verify ghcr.io/getserops/backend:1.3.0 \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp '^https://github.com/getserops/serops/\.github/workflows/docker\.yml@refs/tags/v'
gh attestation verify oci://ghcr.io/getserops/backend:1.3.0 --owner getserops
```

The same for `frontend` and the chart: see [Verifying what you pull](helm.md#verifying-what-you-pull).
cosign 3 is needed.

## 2. Cluster, ingress, cert-manager

```bash
az login
deploy/cloud/aks/cluster.sh up      # RG serops-validate, AKS, ingress-nginx, cert-manager,
                                    # a Let's Encrypt ClusterIssuer, Postgres + Redis
export KUBECONFIG=~/.kube/serops-aks-validate
```

What `up` runs, if you prefer your own cluster:

```bash
az aks create -g <rg> -n <cluster> --tier free --node-count 2 --node-vm-size Standard_D2as_v7 \
  --network-plugin azure --network-plugin-mode overlay --network-dataplane cilium
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx --version 4.15.1 \
  -n ingress-nginx --create-namespace \
  --set controller.service.externalTrafficPolicy=Local \
  --set 'controller.service.annotations.service\.beta\.kubernetes\.io/azure-load-balancer-health-probe-request-path=/healthz'
helm upgrade --install cert-manager jetstack/cert-manager --version v1.21.3 \
  -n cert-manager --create-namespace --set crds.enabled=true
kubectl apply -f deploy/cloud/common/cluster-issuer.yaml
```

* **NetworkPolicy needs an enforcing CNI.** The Cilium dataplane enforces the
  chart's policies (checked: a pod in another namespace cannot reach the
  backend or the frontend). With plain kubenet nothing is enforced.
* Keep the controller in a namespace named `ingress-nginx`, or set
  `networkPolicy.ingressFrom` (see [Helm](helm.md#network-policies-disruption-budgets-service-account)).
* The Azure load balancer probes `/healthz`; without the annotation it probes `/`
  and marks the controller down.

## 3. Secrets and values

```bash
kubectl -n serops create secret generic serops-db-secret \
  --from-literal=database-url="postgres://serops:<password>@<host>:5432/serops"
kubectl -n serops create secret generic serops-broker-secret \
  --from-literal=broker-url="redis://:<password>@<host>:6379/0"
kubectl -n serops create secret generic serops-django \
  --from-literal=django-secret-key="$(openssl rand -hex 64)" \
  --from-literal=encryption-key="$(openssl rand -base64 32 | tr '+/' '-_')"
```

Back up `encryption-key`: without it the stored credentials cannot be read.

```yaml
# aks-values.yaml (HOST: your DNS name; we used <lb-ip-with-dashes>.sslip.io)
ingress:
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt
    nginx.ingress.kubernetes.io/proxy-body-size: 20m
  hosts:
    - host: HOST
      paths:
        - { path: /api, pathType: Prefix, service: backend }
        - { path: /, pathType: Prefix, service: frontend }
  tls:
    - hosts: [HOST]
      secretName: serops-tls
database: { existingSecret: serops-db-secret }
broker: { existingSecret: serops-broker-secret }
django:
  existingSecret: serops-django
  allowedHosts: "HOST"
  corsAllowedOrigins: "https://HOST"
celeryWorker:
  resources:
    requests: { cpu: 250m, memory: 512Mi }   # two 2-vCPU nodes; drop on bigger nodes
```

## 4. Install and sign in

```bash
helm install serops oci://ghcr.io/getserops/charts/serops --version 1.3.0 \
  -n serops -f aks-values.yaml --wait --timeout 15m
kubectl -n serops get certificate serops-tls      # READY True after ~30 s
```

Install `--version 1.3.1`: the same chart, with the fixes found on GKE and
EKS and dependency updates ([changelog](../changelog.md)).

Open `https://HOST`, register the first account (it becomes the admin; open
registration then closes by itself), and only then restrict the load balancer
if you want to (`cluster.sh lock`): Let's Encrypt has to reach port 80 to issue
the certificate.

Checked after install: HSTS with `includeSubDomains` on the API, plain HTTP
redirected (308), PodDisruptionBudgets for backend, frontend and worker, every
pod on the `serops` ServiceAccount.

## 5. Azure Monitor for logs and metrics

```bash
deploy/cloud/aks/cluster.sh monitoring   # Log Analytics workspace + Container Insights
deploy/cloud/aks/cluster.sh reader       # service principal, read-only custom role
```

**Permissions.** The integration needs only these five actions, on the
workspace and on the cluster (a custom role, which `reader` creates):

| Action | For |
|---|---|
| `Microsoft.OperationalInsights/workspaces/read` | The workspace |
| `Microsoft.OperationalInsights/workspaces/query/read` | Log Analytics queries (logs, and the `Perf` table for container metrics) |
| `Microsoft.OperationalInsights/workspaces/query/*/read` | Reading each table |
| `Microsoft.Insights/metrics/read` | Azure Monitor metrics of the cluster |
| `Microsoft.Insights/metricDefinitions/read` | Listing those metrics |

The built-in **Log Analytics Reader** (workspace) and **Monitoring Reader**
(cluster) also work, with more than SerOps uses.

In SerOps: **Settings → Integrations → Add log provider → Azure Monitor**, with
the tenant, client ID, secret, workspace ID and the cluster's resource ID,
**Topology mode: Kubernetes**, logs and metrics ticked. Then the project's
**Data** tab → **Check my data**: Container Insights does not collect pod
labels, so the check reports the logs as not tagged and offers the namespace
(`PodNamespace = production`); accept it. Container Insights delivers records
after 2 to 6 minutes.

On our test the bad rollout of the sample application (`workload.sh incident`:
a database pool of 2) was found by an investigation in 31 seconds: the payments
pool exhausted, 503s turning into 502s upstream.

## 6. Sign-in with Entra ID (Enterprise)

Tested with three Entra users in three security groups, mapped to Admin,
Viewer (plus the team SRE) and a custom role.

1. **App registration** (single tenant), redirect URI
   `https://HOST/api/auth/sso/callback`, a client secret. In its manifest set
   `"groupMembershipClaims": "SecurityGroup"` and add the optional ID-token
   claims `email` and `groups`. Entra sends groups as **object IDs** in the ID
   token, not names: map the IDs.
2. **Admin consent** once for the tenant (`openid profile email User.Read`),
   or every user meets a "Permissions requested" screen at first sign-in.
3. Users need the `mail` attribute set: SerOps takes the email from it.
4. In SerOps, **Settings → Security → Single Sign-On (SSO)**: provider OIDC,
   discovery URL `https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration`,
   groups claim `groups`, role rules by group ID, default role **Refuse sign-in**,
   **Update roles at every sign-in** on, team rules, and your Entra domain under
   **Sign-in domains** so a first sign-in creates the account.

Checked: each user landed with the mapped role (Admin; Viewer and a member of
SRE, so it saw the restricted project; the custom role), the audit log shows
`SSO_PROVISION` with the group IDs and `TEAM_UPDATE` with source `sso`, and a
user in no mapped group is sent back to `/login?sso=denied` (`SSO_DENIED`).

!!! warning "Removing a user from the groups does not sign them out"
    The next sign-in is refused, but the SerOps account keeps its role and any
    session already open stays valid (up to 30 days). When someone leaves,
    also remove or deactivate them in **Settings → Users**.

A custom role without `project.read` sees no project at all: include it in
roles meant for on-call work.

Entra **security defaults** make every new user register the Microsoft
Authenticator app at first sign-in; that is the identity provider, not SerOps.

## Known issues

* **Upgrades on small nodes.** A rolling update needs free CPU for the largest
  pod (a worker requests 500m). On two 2-vCPU nodes the 1.2.14 → 1.3.0 upgrade
  waited on a `Pending` worker until we lowered its request. See
  [Helm → Upgrading](helm.md#upgrading).
* **Migrations run after the new pods are ready** (a post-upgrade hook), so a
  blocked rollout also delays them.
* **Your own Postgres and Redis in the cluster** are not covered by the chart's
  NetworkPolicies: add your own, or use the managed services.
* **Free trial.** `Standard_D2als_v7` was refused in some zones of France
  Central for the trial subscription; the trial's quota is 4 vCPU per region.
* **Entra ID sign-in**: see section 6 above and [Authentication](../security/authentication.md).

## Tear down

```bash
deploy/cloud/aks/cluster.sh down   # app registration, resource group, custom role
```
