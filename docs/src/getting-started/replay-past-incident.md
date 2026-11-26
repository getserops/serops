---
seo_title: "Replay your last incident"
description: "Point SerOps at the log store that holds a past incident, analyse that window with Investigate, and compare the root cause with what you found at the time. What a new install sees, and what it does not."
---
# Replay your last incident

The quickest way to judge SerOps is an incident you already know: you
remember what broke and why, so you can tell whether the analysis gets it
right. SerOps reads the logs your log store still holds, so you can analyse
a past window with [Investigate](../user-guide/investigate.md) as soon as it
is connected, without waiting for a new incident.

## What you need

- SerOps installed ([Quick start](quick-start-self-hosted.md), steps 1 to
  5) with an AI provider key, or [Ollama](../how-to/on-prem-ai-ollama.md)
  if nothing may leave your network.
- Read access to the log store that holds the incident (Elasticsearch,
  OpenSearch, Loki, Splunk, Datadog, CloudWatch, Google Cloud Logging or
  Azure Monitor).
- The incident's start and end:
    - within the last 30 days;
    - at most 6 hours long;
    - still inside your log store's own retention.

## What a new install will not see

The analysis has whatever your stores still hold for that window and
SerOps can find. On a new install, some of it is missing:

| Source | For a window before you installed SerOps |
|---|---|
| Logs | Yes, as stored, if the log store still keeps them. |
| Metrics | Only if they carried the SerOps labels at the time (`organisation_name`, `project_name`, `environment`; see [Required labels for metrics](../how-to/configure-data-collection.md#required-labels-for-metrics)). Labels added today do not apply to past samples. On Google Cloud Monitoring a project rule on the namespace is enough. |
| Deployments and commits | Mostly not. A repository's first **Sync** fetches the last 7 days of commits (up to 100). CI/CD runs come from polling of the last 2 hours, or the last 20 runs on a manual sync. Argo CD and Flux deploys are only known from the moment their webhook is set up. |
| Traces | From Jaeger, Zipkin, Grafana Tempo or Datadog APM, yes, within their retention. Through SerOps' own OTLP receiver, only from when you start sending them. |
| Similar past incidents | None yet: this memory is built from issues resolved in SerOps. |

Without deploys, the analysis cannot point at the change that caused the
incident, which it does when it knows the deploy. The
[known limits](../changelog.md) of 1.5.0 apply too: logs that stop part-way
through a window are read as healthy, one noisy service can fill the 5,000
newest records of a window, and a failure seen only in INFO lines or
request metrics is missed.

## 1. Connect the log store

Open **Integrations** and add the log store that holds the incident; the
[provider pages](../integrations/overview.md) give the fields for each one.
Its health check must pass.

## 2. Create a project and let SerOps find your logs

Create a project for the system that had the incident
([First project](first-project.md), step 1). Your logs do not need SerOps'
fields:

1. Open **Projects →** your project **→ Data** and click **Check my data**,
   with **Look back: Last 24 hours**.
2. If your logs carry no `project_name`, **How your other logs are
   grouped** lists the fields they do carry, for example a Kubernetes
   namespace or an OpenTelemetry `service.namespace`. Click **Use for this
   project** next to the one that is this system. A project can have up to
   five such rules.
3. Run the check again. Under **Services seen in your errors and warnings,
   not listed in this project**, click **List … services**.

The check looks back 24 hours at most: it reads the logs your services
write now, with the same labels as during the incident. If the system has
been quiet for longer, add the services yourself
([First project](first-project.md), step 4); their names must match
`service_name` (or `app`, or `service.name`) in your logs.

## 3. Investigate the incident window

Open **Investigate** in the sidebar:

1. **Project**: the one you created.
2. **Environment**: the incident's environment. If your logs carry no
   environment field, choose **Any environment**: with an environment
   selected, logs without one are left out and the run ends in **No
   data**.
3. **Services**: leave it empty for every service of the project.
4. **Time window**: enter **From** and **To**, the incident's start and
   end. A little before the first symptom helps: the cause usually comes
   first.
5. **What are you seeing?** (optional): the symptom as you first saw it,
   for example *"Checkout failed for customers from about 20:15"*. It is
   given to the AI as a symptom to confirm or rule out. Do not write the
   answer you expect, or you test your sentence, not the analysis.
6. Click **Run investigation**.

The run shows its steps (queued, collecting, AI analysis, done) and what
it found per source: logs, metric points, spans, code changes and CI/CD
runs. The log count is the number of distinct entries after identical
errors are folded together, not the number of lines.

## 4. Read the result

- **Done**: **Open analysis** shows the issues found, each with its root
  cause, the evidence it rests on and a suggested fix. See
  [Analyses](../user-guide/batches.md).
- **No data**: nothing was found for that scope and window, with the
  count per source. Check the window, the project rule, and the
  environment: logs without an environment field are only found with
  **Any environment**.
- **Failed**: the reason is shown, for example no AI provider configured,
  the monthly AI budget used up, or an AI provider error.

Compare the root cause with what you found at the time. If the analysis
misses, the table above and the known limits usually say why: a cause
that only shows in metrics without labels, or in a deploy SerOps never
saw.

## Next

From now on SerOps analyses on its own, every 15 minutes by default. For
the next incident to have the full picture:

- label metrics with the SerOps fields
  ([Configure data collection](../how-to/configure-data-collection.md));
- connect source control and CI/CD, and the Argo CD or Flux webhook, so
  deploys are known when they happen
  ([Deployments](../user-guide/deployments.md)).
