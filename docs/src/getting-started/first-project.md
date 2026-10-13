# First Project

Create your first project and get SerOps analyzing incidents in your
own stack. Time budget: **~20 minutes** end-to-end if you already
have a log provider (Elasticsearch, Loki, Datadog, CloudWatch, ...).

If you haven't installed SerOps yet, start with the
[Quick Start](quick-start-self-hosted.md).

---

## What you'll build

By the end you'll have:

* A **project** grouping the services you care about.
* One or more **environments** (production, staging, ...) mapped to
  your Git branch names.
* At least one **service** connected to your source control (SCM)
  and/or CI/CD provider.
* A working log-provider connection so SerOps can pull the raw logs
  it analyzes.
* A first **batch** with an AI-authored incident summary.

---

## Step 1 — Create the project

1. Log in.
2. Click **Projects** in the left sidebar.
3. Click **+ New Project**.
4. Fill in:
    - **Name** — short and stable (`checkout-api`, `payments-platform`).
      Used in prompts + notifications.
    - **Description** — optional but recommended. The AI reads this
      and uses it when reasoning about incidents ("the checkout API
      handles Stripe webhooks..."). A one-liner is fine.
5. Click **Create**.

---

## Step 2 — Configure environments

The batch pipeline uses environments to answer "which env is this
incident from." Without this, all logs land in a single bucket.

1. On your new project, click ⚙️ **Settings**.
2. Open the **Environments** tab.
3. Enable the environments you actually deploy to:
   - ✅ Production
   - ⬜ Staging (if applicable)
   - ⬜ Development (if applicable)
4. Adjust **branch patterns** so SerOps can auto-tag which env a
   commit belongs to:

    | Environment | Typical branch pattern |
    |---|---|
    | Production | `main`, `master`, `release/*` |
    | Staging | `develop`, `staging` |
    | Development | `feature/*`, `dev/*` |

   The default patterns work for most GitHub-Flow / GitLab-Flow repos.

---

## Step 3 — Connect an integration

SerOps needs at least one **source-of-signal**. The most common trio
is **logs + SCM + CI/CD** but any subset works (see
[auto-detect](../architecture/multi-tenancy.md) — the AI adapts to
what's available).

1. Go to **Settings > Global Integrations**.
2. Click **+ Add Integration** and pick a provider.
3. Fill the connection form and click **Save**.
4. Click **Verify** to confirm the credentials work.

Recommended first integrations:

* **Source Control** — GitLab, GitHub, Bitbucket, or Azure DevOps.
  Powers "what code changed just before this error?".
* **Observability** — Elasticsearch, Loki, Datadog, CloudWatch,
  OpenSearch, or Splunk. Provides the logs the AI analyzes.
* **CI/CD** — GitLab CI, GitHub Actions, Jenkins, Bitbucket Pipelines,
  or Azure Pipelines. Provides failed-job outputs for post-deploy
  incidents.

See [Connect Your First Provider](../how-to/connect-provider.md) for
per-provider setup.

---

## Step 4 — Add services to the project

Services are the "unit of ownership" — one microservice, one API, one
worker fleet.

1. Back on the project page, click **+ New Service**.
2. Pick the binding type:
   - **Source Control (SCM)** — one repo per service. Enables
     code-change correlation.
   - **CI/CD** — one pipeline per service (a service can have many).
     Enables deploy-timestamp correlation + failed-job analysis.
3. Choose the provider and pick a repository / project from the
   dropdown. If nothing shows up, re-verify the integration.
4. Follow the wizard.

You can add multiple services per project. The AI reasons about the
whole project as one system.

---

## Step 5 — Wire the webhook (real-time updates)

Batch pipelines run on a schedule, but webhooks let SerOps react
**immediately** to a push, merge, or failed CI job.

1. Open the service detail.
2. Copy the **Webhook URL** and **Secret**.
3. Paste both into your provider's webhook settings:
   - GitHub: repo **Settings > Webhooks > Add webhook**
   - GitLab: project **Settings > Webhooks**
   - Bitbucket: repo **Repository settings > Webhooks**
   - Jenkins: use the "Generic Webhook Trigger" plugin
4. Trigger a push and confirm SerOps receives the event (**Data**
   page will show fresh activity).

If the webhook fires but nothing appears in SerOps, check
[Troubleshooting > Integrations](../troubleshooting.md#integrations).

---

## Step 6 — Wait for the first batch

SerOps aggregates logs, metrics, distributed traces, code changes, and CI/CD
outputs into a **batch** at a configurable interval (default: every few
minutes; see **Settings > Data Management**).

1. Go to the **Data** page.
2. When your first batch appears, click it to open the detail view.
3. Scroll to **AI Analysis** — you'll see the AI-authored summary,
   detected issues, and root-cause hypotheses.

The first batch may take a few minutes if your log provider is warm
or if the AI provider is under load. Subsequent batches are typically
sub-minute end-to-end.

---

## Step 7 — Verify AI cost tracking (optional but recommended)

If you're paying for a hosted AI provider (OpenAI, Anthropic,
Google), enable a monthly budget cap early so a runaway loop can't
burn through your quota:

1. **Settings > AI Providers > Monthly Budget**.
2. Set a conservative cap (start with $50-$100).
3. The dashboard warns at 80% by default and pauses AI at 100%
   until the calendar month resets. Rule-based issue creation
   continues either way.

See [Track AI Costs](../how-to/ai-costs.md) for the full breakdown
and [Troubleshooting > Cost budget](../troubleshooting.md#cost-budget-q33)
for what to do when the cap trips.

---

## Common first-project issues

| Issue | Solution |
|-------|----------|
| No batches ever appear | Check that at least one service is connected + the log provider is verified. Check **Settings > Data Management** for batch cadence. |
| Batches appear but are empty | Log provider isn't returning matches for the batch time window. Verify the `service_name` field in your logs matches the SerOps service name exactly — see [Configure Data Collection Agents](../how-to/configure-data-collection.md). |
| Batches analyzed but AI shows "No API key configured" | Add an AI provider under **Settings > AI Providers** and click **Test Connection**. |
| Analysis fails with `AUTH_ERROR` / `QUOTA_EXCEEDED` | See the [AI Analysis error table](../troubleshooting.md#ai-analysis). |
| AI says "no logs provided" but you have logs | Log-provider filter mismatch. Check that the SerOps service name matches your logs' `service_name`. |

---

## Next steps

- [Explore the Dashboard](../user-guide/dashboard.md) — cross-project
  view, incident heatmap, cost tracking
- [Use AI Chat](../user-guide/ai-chat.md) — ask questions across all
  batches
- [Set up Notifications](../admin/notifications.md) — Slack, Teams,
  PagerDuty, OpsGenie
- [Configure Sentinel](../how-to/sentinel.md) — tiered intelligence
  that filters low-signal batches
- [Auto-detect data sources](../architecture/multi-tenancy.md) — how
  SerOps adapts to whatever subset of logs / metrics / traces / SCM
  you actually have
