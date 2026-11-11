# Changelog

All notable changes to the SerOps backend are documented in this
file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
starting from `v1.0.0` (see [versioning guide](https://serops.ai/docs/deployment/versioning/)).

## [Unreleased]

## [1.3.0] - 2026-11-11

Users, roles and teams, the Enterprise edition, and a security release. Migrations Users 0014-0016, Data 0057-0059, Organisations 0014, Projects 0017 (and ee 0001 with the `ee/` directories) run on their own. `SEROPS_ENCRYPTION_KEY` is now required, then run `rotate_secrets` once; the Helm chart refuses an ingress without TLS. Set `SEROPS_VERSION=1.3.0` or `--version 1.3.0`; read Upgrading → 1.3.0 first.

### Security

- Stored credentials have their own key, `SEROPS_ENCRYPTION_KEY`, instead of a hash of `DJANGO_SECRET_KEY`, so a leaked signing key no longer opens them. The key can be changed with `rotate_secrets`, and a value that cannot be decrypted is reported rather than read as empty. **Required on upgrade:** see the docs, Upgrading.
- Erasing an account now removes the email from the audit log, where it stayed in `details`, and application logs in the account code name users by ID. The sole admin of an organisation is refused (409), as documented: it used to delete the organisation and every other member with it.
- HSTS was never sent behind a proxy (the Helm ingress, Caddy), though 1.2.14 said so: the proxy talks plain HTTP to the backend, which saw every request as insecure. With `SEROPS_HTTPS` the backend now trusts the proxy's `X-Forwarded-Proto`. The same cause made **Setup webhook** register an `http://` URL with GitHub and GitLab on an HTTPS install, and `SECURE_SSL_REDIRECT=True` behind a load balancer, which the docs advised, redirected forever; the docs now say to keep `SEROPS_HTTPS` and let the load balancer redirect.
- Changing your email needs your password and a link sent to the new address; every session then ends and the old address is told. A stolen session could move the account to another address for good, or squat an address another organisation's SSO claims. SSO accounts keep their identity provider's email.
- OpenID Connect: each sign-in is bound to the browser that started it, and uses a nonce and PKCE. Before, someone could get a victim to load their callback URL and sign the victim in to their own account. A provider must now say the email is verified: providers that leave `email_verified` out are refused unless their host is in `SSO_TRUST_MISSING_EMAIL_VERIFIED` (default `login.microsoftonline.com`).
- The session timeout in Settings → Security is now enforced, including the 8-hour default: nothing read it before. Set it to Never to keep the previous behaviour.
- Failed logins are in the audit log: JSON clients, so every normal login, were never recorded.
- New passwords are validated when changed from the profile and when set from an invitation, as they already were on registration and reset.
- The backend refuses to start outside DEBUG with `replace-me` or a similar placeholder as a secret, or with a `DJANGO_SECRET_KEY` under 32 characters.
- Per-project access, from an internal review before release (2026-11-05). A member outside a restricted project could still read it through:
  - its issues, by batch id (`/api/data/issues/<batch_id>/`);
  - "similar issues" and post-mortem drafts of an open project, which drew on the restricted project's resolved incidents;
  - the CI/CD pipeline and deployment lists;
  - AI Chat's code context, which took commits from the whole organisation;
  - a cluster's workload list, and the legacy repository detail and pipeline logs.

  A viewer whose team was admin of one project could rewrite or delete any legacy repository, set its webhooks and change onboarding: those routes now need the organisation role. Changing the SSO identity provider needs every permission of an admin (a custom role with `settings.manage` could point SSO at its own provider and sign in as anyone). The last-admin check counts active admins only.

### Added

- Added `ee/` (SerOps Enterprise License): offline Ed25519 license key (`ee.licensing`), `InstalledLicense` model (migration `ee.0001_initial`), `GET/PUT/DELETE /api/ee/license/`, `manage.py ee_license_sign`. Community: `Utils.edition` registry (never imports `ee`), `GET /api/organisation/edition/`, platform permission `license.manage`; `ee` is added to `INSTALLED_APPS` and `/api/ee/` only when the directory exists.
- SSO group → role mapping (`Users/sso_roles.py`): `SecuritySettings.sso_groups_claim` (dotted path), `sso_extra_scopes`, ordered `sso_role_mappings`, `sso_default_role` (or `deny`), `sso_sync_role`, `sso_domains` (JIT accounts only for listed domains; staff-only on multi-org; `manage.py sso_domains`). Claims merge userinfo + ID token. Audit `SSO_PROVISION`, `SSO_DENIED`, `TEAM_ROLE_CHANGE` (`source: sso`). Migrations `Users 0013`, `Data 0054`.
- Custom roles (management is Enterprise, feature `custom_roles`): `Users.CustomRole` (org, name, permissions), `User.role='custom'` + `custom_role` (PROTECT). `rbac.role_permissions`, `normalise_permissions` (ALWAYS_GRANTED + IMPLIES), `can_grant` (no escalation, checked by team invite/update/remove, role CRUD, SSO rule edits), role keys `custom:<id>`. `GET /api/organisation/roles/` (Community, org.read); writes in `ee/access/roles.py` at `/api/ee/roles/` (team.manage; POST/PUT need the license, DELETE never; 409 when in use or named by SSO). Without the license, assigning a custom role a member doesn't already have, and new SSO rules naming one, are refused (`Utils.edition.require`, 403 `enterprise_license_required`). Audit `ROLE_CREATE/UPDATE/DELETE`. `UserSerializer.role_key`, `role_name`. Notification defaults follow permissions. Migrations `Users 0014`, `Data 0055`.
- Teams and per-project access (`Middlewares/project_access.py`): `Organisations.Team`/`TeamMembership`, `Projects.ProjectTeamAccess`, `Project.access_mode`; project-scoped querysets everywhere (`scope`, `ProjectScoped`, `scope_request`), `/api/organisation/teams/` (Community), access management in `ee/access/projects.py` at `/api/ee/projects/<id>/access/` (restricting or adding/raising grants needs the license `project_access`; opening, lowering and removing never do), `manage.py project_access_open` (Community way back), per-project `permissions` on project responses, `sso_team_mappings`, subscriptions checked at send time, cache keys carry the scope. `test_project_scope_coverage.py`; walkers use real tokens. Migrations `Organisations 0014`, `Projects 0016`, `Users 0015`, `Data 0056`.

### Changed

- `sso/exchange` returns the full `UserSerializer` (permissions). SSO no longer creates accounts for emails outside `sso_domains`.

### Removed

- `password_policy` from `GET` and `PUT /api/data/settings/security/`, and the redaction settings the docs described: no code applied them. Password rules are fixed.

## [1.2.14] - 2026-11-07

Security and Kubernetes release. Migrations Data 0056, integrations 0011, org_settings 0021 run on their own. Set `SEROPS_VERSION=1.2.14` or `--version 1.2.14`; read Upgrading → 1.2.14 first (SSO domains, alert webhooks on shared installs, activation links). SerOps installs on and reads GKE, and the analysis sees Kubernetes rollouts, CPU throttling, per-service trace timings and traffic.

### Security
- Outbound requests: the CI/CD sync (GitLab, GitHub pipelines) goes through the outbound URL policy (it called the provider directly and followed redirects, so a server that passed the check could bounce it to an internal address) and no longer returns the connection error, which named addresses and ports. Embeddings to an OpenAI-compatible base URL are checked and do not follow redirects, like chat.
- Google Cloud keys: only Google's token endpoint is accepted (`token_uri`, `universe_domain`); a key naming another URL made the server POST to it and showed part of the answer in the health check, which no longer echoes provider errors.
- Changing an integration's host requires its credentials again: kept, anyone allowed to edit integrations could send another admin's key to their own server.
- SSO: a sign-in creates an account only for an email of a listed SSO domain (with none listed, any address the identity provider asserted got one); invited and existing members still sign in. On an install with several organisations, only the operator sets the SSO domains: one organisation could claim another company's domain.
- Alert webhooks: the global per-source secret (and Sentry's client secret) authenticate only on a single-organisation install; shared by every organisation, they let one post alerts into another's analyses. Rotate a per-organisation secret (`POST /api/organisation/alert-secret/rotate/`).
- Account activation links are signed for that purpose and expire after 7 days, and do not reactivate an account that signed in before: a deactivated user could reactivate it by replaying the first email.
- Redaction catches secrets in escaped JSON (`{\"password\": ...}`, Docker log lines), `key => value` and URL-encoded `key%3Dvalue`.
- Kubernetes state (kube-state-metrics) is read only from the project's namespaces: with none found, every namespace of the cluster reached the analysis. Project and environment names are escaped in PromQL.
- The unused `GET /api/data/logs` (any index of the log store, no project filter) is removed.
- `pyasn1` 0.6.5: four denial-of-service fixes in ASN.1 parsing (used by the Google and other authentication libraries), found by an image scan.
- Behind HTTPS (Helm with an HTTPS public URL, the quick-start's Caddy), session and CSRF cookies are Secure and responses send HSTS (`SEROPS_HTTPS`). They were sent over plain HTTP too, because only `SECURE_SSL_REDIRECT` enabled them, and the chart never set it (a redirect in Django would bounce the plain-HTTP health probes).
- Helm chart: no pod mounts a Kubernetes service-account token (SerOps never calls the Kubernetes API). The quick-start's HSTS header no longer covers every subdomain of the domain SerOps runs on.
- The demo stayed writable with a lowercase token header (`token <value>`): the read-only guard matched `Token ` exactly while Knox accepts any case. The check now also runs where Knox parses the token. Found by an external review.
- Deleting old batches deleted every organisation's old batches, not only the caller's. Found by an external review.

### Added

Found running Google's Online Boutique like production (2026-11-02): two incidents out of six were only half right because the analysis could not see what was done to the services.

- Kubernetes changes reach the analysis (Prometheus in Kubernetes mode, from kube-state-metrics): rollouts in the window and the 30 minutes before it, with the image change, the memory limit change, or "image unchanged" for a configuration change; scale changes; containers that cannot start (ImagePullBackOff, CrashLoopBackOff, ...); Deployments short of replicas. A rollout of checkout with a wrong payment address was blamed on payments, and a release with an image that does not exist left no pod to log anything. A new prompt rule makes a change to a service the first suspect for what follows it.
- Per-service trace timings in the analysis: span count, p50 / p95, errors and SELF time (time inside the service, not waiting on the services it called) for each service, compared with the window before. The top-5 slowest spans were all the frontend waiting on a slow product catalogue, and the frontend was blamed.
- Sentinel analyses a window with Kubernetes restarts, containers that cannot start or missing replicas (trigger `kubernetes_failure`): a crash loop can log nothing new.
- Sentinel analyses a window where a service's traces slowed down or started failing, against the window before (triggers `trace_latency_spike`: p95 self time 3x and +200 ms, 20 spans or more in both windows; `trace_error_spike`: 5 error spans or more, 5% of its spans, twice the rate before). A dependency going from 20 ms to 900 ms with no errors read as quiet until the forced review, up to 3 hours later (external review of v1.2.13). The batch task now takes the native trace snapshot before the Sentinel gate instead of after it, so it is still one query.

### Changed

- Sentinel active mode is the default (migration `org_settings` 0021): quiet windows skip the AI call, as the docs said. Shadow mode as the default meant an AI call every window on a fresh install, up to 96 a day per project and environment. Organisations that never saved Settings → Sentinel (no row, or a row created only by opening the page) move to active mode; a mode an admin saved is kept.
- CPU throttling reaches the analysis: the share of time each service was paused for exceeding its CPU limit (cAdvisor, Kubernetes mode, 25% or more), and rollouts report CPU limit changes (`cpu limit 200m -> 10m`). Found with the Cloudflare-2019 scenario on Online Boutique: a rollout cut the catalogue's CPU limit to 10m, requests queued before reaching its code so its own spans looked fast, and the analysis could only guess at "resource throttling".
- A rollout whose new pods never become ready while the previous version still serves every replica is reported as such (`kube_deployment_status_replicas_updated`), and the prompt rates it WARNING, not CRITICAL. Found with the Fastly-2021 scenario: a crash-looping new currency pod was called a CRITICAL outage while the old pod served every request.

### Fixed

- An AI provider account with no credit left now fails as `OUT_OF_CREDIT` ("add credit or a payment method, or choose another provider"). Anthropic's "credit balance is too low" read as `UNKNOWN_ERROR`, and OpenAI's `insufficient_quota` as a rate limit that "will retry automatically"; neither fixes itself. Found when our own Anthropic account ran dry (2026-11-04).
- A quota error says when it resets when the provider says so: Gemini's free tier (20 requests a day) now reads "The AI provider's daily quota is used up. It resets in about 46 min." instead of "Will retry automatically". The wait is also in the batch error as `retry_after_seconds`.
- AI Chat and manual log analysis name the provider's problem (no credit, quota, key) with a 502 instead of "Failed to process chat request".
- A traffic surge is no longer blamed on code. The trace context gives each service's traffic (spans) in the window and in the window before, counted in full, and the total ("Traffic: 41000 spans in this window, 8100 in the window before (x5.1)"); a new prompt rule checks traffic before blaming a service when everything slows down at once, and still treats more traffic with healthy latency as absorbed. The timings come from at most 500 traces per window, so in a surge both windows hit that cap and looked alike. Found on Online Boutique on AKS (scenario R9: a 5x load-generator surge blamed on recommendationservice's client code). New tuned benchmark incident `t01_traffic_surge`.

Found running SerOps on a live GKE cluster (Online Boutique, 2026-11-05): SerOps could neither be installed on GKE nor read anything from it.

- Helm chart: installs on GKE. `kubeVersion: ">= 1.25.0"` rejected GKE's `v1.36.4-gke.2046003`, whose suffix Helm reads as a pre-release (EKS versions carry one too); it is now `">= 1.25.0-0"`.
- A Google service-account key can be saved. It is about 2,300 characters and the integration's password held 1,000, so a Google Cloud integration could not be created from the UI or the API (migration `integrations 0011`, password is now text). The onboarding wizard asks for the Google project ID and whether the services run on GKE; it saved Google integrations without a project, so every query failed.
- GKE logs are read: the service comes from the pod's `app` label (else its Deployment, else the container), the host from the node, and a project reads the namespace named after it or after one of its environments. Project rules on `namespace`, `cluster` or `container` target the log's resource. GKE logs carry no `project_name` or `service_name`, so every project found none of them.
- A plain-text stderr line on GKE has the level it names, not ERROR: GKE rates every stderr line ERROR, and one chatty container filled the error search with INFO lines (4,287 of 5,000).
- Google Cloud logs are found by filter, without locations, like Loki. SerOps searched only the log names of the last 100 entries, joined with commas into one name that matched nothing: Check my data said "no logs at all" next to thousands of container logs. Google's audit logs are left out.
- GKE metrics work. Every query raised on the SDK's timestamps (`DatetimeWithNanoseconds`) and returned nothing, and the labels SerOps filtered on exist on no GKE metric. CPU is now a rate per workload (cores), memory the share of the container's limit in use, both scoped to the project's namespaces; `discover_hosts` lists that namespace's pods, not every pod of the cluster.
- A failed Google Cloud health check says why ("Google refused access to project X: check the project ID, and that the service account has the Logs Viewer role on it"), not "Health check failed".

- Commits are timed against when they reached the batch's environment, not when they were made: deployments already selected the commits, but the correlator and the prompt still used the commit time, so a stack-trace match scored HIGH 30 minutes after the commit and produced nothing at 5 hours, even for a commit deployed 10 minutes before the error. A commit deployed after the errors began is no longer blamed for them. The prompt shows "deployed to production at ...; committed ..." and the commit time only when no deployment was recorded. CI/CD failures stay timed against the commit, which CI builds before any deploy. Found by an external review of v1.2.13.
- An analysis shows each issue at the severity it reported, not the issue's highest ever: a recurring issue once rated CRITICAL showed as CRITICAL on every later analysis, even one that rated it WARNING. The issue itself keeps its peak severity. Analysis page, its issue list, filter, sort and counts.
- A stuck rollout (new pods failing, the previous version serving every replica) was still rated CRITICAL by Claude, which wrote that users were unaffected. Its issue is now capped at WARNING from the measured Kubernetes state, unless the workload is also short of replicas now.
- A crash-looping rollout of a single-replica workload was still called CRITICAL while the old pod served every request: Kubernetes counts the new pod as "updated" (1/1), so the stuck-rollout check never fired. Not-ready new pods are now read from `replicas_unavailable`, and the analysis says "1 new pod(s) not ready, 1/1 available". Found with the config-change scenario on Online Boutique.
- A rollback read as the bad release again ("rolled out twice to v0.10.99", the second time back to v0.10.7): each rollout's image and limit change is now taken from the pods it created and the pods it replaced. Workloads short of replicas also say how many are available now, so a recovery shows ("0/1 at worst, 1/1 now"). Found with the rollback scenario on Online Boutique.
- A recurring issue kept the text of its first sighting forever, so the analysis page of a new incident showed the previous one's description, timestamps included. A recurrence now takes the newest analysis's description, root cause, recommendation and reasoning.
- Restarts and OOMKills were looked up in a namespace named after the environment, so they were missed whenever the two differ (Online Boutique: namespace `boutique`, environment `production`). The project's namespaces now come from its cAdvisor series. They are reported per workload rather than per container name, which was `server` for every Online Boutique service.
- A project could hold two services with the same name (two "frontend"): logs, metrics and traces find their service by name, so SerOps could not tell them apart. The second one is now refused (case-insensitive, per project).
- Check my data with Loki, for a new project whose logs still carry another project's label, said "no index, log group or stream" and asked for an index pattern or log groups, which Loki does not have. It now goes on and shows which project and environment values the logs carry.
- AI Chat said "No AI provider" on an install that analyses with a local Ollama-compatible model: providers that need no key were left out of the chat's model list even with their URL saved.
- Similar past incidents work for every install, without an environment variable (external review of v1.2.13). Embeddings used to need `OPENAI_API_KEY` in the environment, contradicting "AI keys are never read from the environment"; without it they were random hashes, so similar incidents never matched (Ollama, Claude, DeepSeek and air-gapped installs included). Embeddings now use the organisation's own AI provider when it offers them (OpenAI, Gemini, Ollama / OpenAI-compatible; `embedding_model` in the key's extra config overrides the model), and local lexical similarity otherwise. `OPENAI_API_KEY` is no longer read (`manage.py check` now warns about it like the other provider keys) and the Helm chart's `ai.embeddings.*` values are gone.
- The past incidents added to an analysis prompt are the resolved issues most similar to the batch's errors, not the most recent ones; same environment, team-confirmed root cause and recency break ties, and at most one recent non-matching issue fills a free slot.
- Open issues show similar past incidents: they are embedded on first request instead of returning nothing. Each vector is stored with the model that produced it (`Issue.embedding_model`, migration `Data 0056`, which clears the old unattributed vectors), and vectors from different models or dimensions are never compared.
- Deleting an organisation (or the account of its last admin) with days of traces was killed for running out of memory: the cascade loaded every span and trace into the backend. They are now deleted in chunks inside the database first.

### Changed

- Helm chart: the backend, frontend and worker replicas are spread one per node by default (soft topology spread; a single node still runs them). Two replicas on one node were lost together when it went down (found on a 2-node AKS cluster). `nodeSelector`, `tolerations`, `affinity` and `topologySpreadConstraints` now apply to every component: the frontend and worker silently ignored them.

### Security

Fixes from the external security review (2026-11).

- A trace's identity is now its organisation plus its trace id. The trace id was the table's primary key, global across the install, so an organisation sending a trace id another organisation already had added its spans to that organisation's trace. Migration `traces 0003` gives traces a surrogate key and keeps every existing trace and span (irreversible).
- The OTLP trace receiver inflated gzip and deflate bodies without a limit: a 10 MB body of compressed zeros became gigabytes in the backend. Inflating now stops at 50 MB (`OTLP_MAX_DECOMPRESSED_BYTES`) and the request gets 413.
- CI/CD and deploy webhooks act only inside the organisation of the binding they authenticate with. The project, repository and commit ids in a payload were looked up across all organisations, so an organisation could write to another's pipelines, commits and deployments with its own webhook secret. A GitLab payload must now name the binding's GitLab project (else 403); commits are unique per organisation (migration `providers 0018`), and a commit with no organisation is no longer saved. The unbound GitLab webhook route `/api/providers/webhook/` (no binding id, always refused) is removed.
- AI Chat and re-analysis / compare ignored the monthly AI budget: they called the model directly instead of going through the budget check batch analysis uses, and chat spend was not recorded at all, so it never counted. Both are now refused with 409 (`over_budget`) once the budget is used up, a re-analysis already queued stops before calling the model, and chat tokens are recorded.
- Server-side requests to URLs users configure no longer follow redirects to another host, and the URL is checked again before every request, not only when saved: a server that passed the check could redirect the backend, with the integration's credentials, to the cloud metadata endpoint. Covers observability adapters, SCM and CI calls (GitLab, GitHub, Bitbucket, Azure DevOps, Jenkins), AI provider base URLs, the Ollama probe, the Slack and Teams test, and SSO discovery. The metadata check now refuses the whole link-local range and IPv4-mapped spellings. URLs that were saved with no check now get one: AI provider base URL, GitLab project URL on update, SSO discovery URL, and the Datadog site (Datadog domains only). New setting `SEROPS_OUTBOUND_ALLOW_PRIVATE` (default `true`, keeps in-cluster targets working); set it to `false` on an install shared by several organisations.
- Logs, commit messages, diffs, CI/CD output, span names, Kubernetes labels, project descriptions, past analyses and chat history went into AI prompts verbatim, so text in them could pass for instructions (prompt injection). They are now enclosed in `<<<DATA …>>>` / `<<<END DATA>>>` blocks, the system prompts (analysis, chat, post-mortem) say the content is data and never instructions, and the markers are neutralised inside the content so it cannot close its own block.

Found by an external review of v1.2.13: "only redacted context goes to the AI provider" was not true.

- Every AI call is redacted at the one place they all go through (`generate_text_unified`): the prompt and the system prompt. Chat, re-analysis and model comparison, CI/CD job errors and post-mortem commit messages used to reach the provider unredacted; only batch logs were redacted.
- Redaction fails closed: if it raises, nothing is sent and the call returns `REDACTION_FAILED`. Batch logs that failed redaction used to go out as they were. Embeddings fall back to the local hash instead of sending unredacted text to OpenAI.
- New patterns: `docker login -p` / `--password`, `Authorization: Basic` (and Token, Digest, ...), `sk-ant-` / `sk-` / `sk-proj-` and Google `AIza` keys, `user:password@` in URLs, "mot de passe" and other non-English password key words, public IPv4 addresses (`[PUBLIC_IP]`; loopback, link-local and netmasks are left), and the whole body of a private key (only the BEGIN line was masked; a key with no END line is masked to the end of the text).
- Bare numbers are no longer masked as phone numbers or SSNs: byte counts, Unix timestamps, counters, pipeline ids and diff hunk headers stay readable now that the whole prompt is redacted (an OOM analysis lost its memory limit). A phone needs phone formatting or a `phone=`/`tel:` label, an SSN its dashes or an `ssn` label. `DATABASE_URL is not set` stays as written.

## [1.2.13] - 2026-11-01

Integrations release, no migration. Set `SEROPS_VERSION=1.2.13` or `--version 1.2.13`. Azure Monitor (AKS with Container Insights, Application Insights), Datadog APM and Grafana alerts now run end to end against real services.

### Fixed

Found with Grafana alerting (journey suite):

- An alert's resolution from Alertmanager or Grafana arriving within 5 minutes of the alert was dropped as a duplicate (it carries the alert's fingerprint), so the alert never showed as resolved. The state is part of the duplicate check.

Found against a live Azure account, AKS with Container Insights and Application Insights (journey suite):

- AKS logs never reached SerOps: Container Insights' `ContainerLogV2` has no `Properties` or `SeverityLevel`, so every query failed, and the failure was reported as no logs. Queries and parsing follow each table (line from `LogMessage`, service from `ContainerName`, level from the line); Check my data offers `PodNamespace` as a project rule; records get an id (the analysis dropped them all without one).
- The scheduler found no Azure log table (its discovery query was not valid KQL). It lists the tables with records, and searches them one by one.
- A refused Azure query was reported as no logs; it names what to fix (role, client secret, workspace id), and so does Test connection.
- AKS metrics were wrong: a percentage read as bytes, memory in use read as free, a CPU percentage read as cores, one series for the whole cluster. With the workspace, CPU and memory come per service from Container Insights; without it, the cluster in bytes and cores.
- Application Insights logs shipped by an OpenTelemetry collector arrive with SeverityLevel Information, `ERROR` lines included, and were never fetched. Their level is read from the text; OpenTelemetry's `service.name` (`AppRoleName`) names the service.
- CI/CD events were searched on Log Analytics, where SerOps writes none, with an invalid query on every run.

Found in the journey suite (organisation deletion):

- "Delete organisation" and "Delete my account" failed with an error while the organisation's apps were still sending traces (or a scheduled analysis was being written): a row arriving during the deletion broke it. The ingest keys are deactivated first and the organisation is locked while it is deleted.


Found pulling traces from a real Datadog APM account (journey suite):

- No trace was ever pulled from Datadog APM: every span search lacked `data.type = search_request` and Datadog answered 400. Span durations read 0 (Datadog sends start and end, no duration), and a trace looked up by id was searched over the last 15 minutes only.
- "Test connection" never tested a trace source (Datadog APM, Jaeger, Zipkin, Tempo): a traces-only integration got no result. For Datadog it now tries a span search and names the missing `apm_read` scope, which the docs' scope list lacked.

Found checking Datadog's documented monitor webhook payloads:

- A Datadog **Recovered** notification was read as a new alert, and service and environment were always empty with the default payload (no tags; `$EVENT_TYPE` is the monitor type). They are read from the notification title (`[Recovered on {env:production,service:payments}] …`), or from `$ALERT_TRANSITION`, `$ALERT_SCOPE` and `$TAGS` in the custom payload the docs now give.
- A resolved alert, from any source, started a second analysis of a system already recovered (Alertmanager sends resolutions by default). It is recorded and starts none.

## [1.2.12] - 2026-10-31

Cloud integrations release, no migration. Set `SEROPS_VERSION=1.2.12` or `--version 1.2.12`. Datadog and AWS CloudWatch were run end to end against real accounts, including Kubernetes with the Datadog Agent and Container Insights.

### Changed

- A project with a single active environment also reads the logs that carry no environment at all (common on AWS: Lambda and ECS logs with only the project in the group name). With two or more environments, such logs still stay out. Applies to every log store; on CloudWatch a group whose name says another environment (`-staging`) stays out.

### Fixed

Found with a real Datadog Agent on Kubernetes (journey suite):

- Datadog Kubernetes mode never returned a metric: it asked for `kubernetes.cpu.usage.total` and `kubernetes.memory.usage`, which the current Agent does not send, grouped by a `service_name` tag no Agent sets. It reads the container metrics the Agent sends (`container.cpu.usage`, `container.memory.limit`, `container.memory.usage`), summed per `service`.
- The Datadog Kubernetes docs: the Helm values they gave did not install (`datadog.env` must be a list), log collection was left off, and agent-level tags put every pod of the node in the project. They now tag by namespace label.

Found with a real CloudWatch agent on Kubernetes (journey suite):

- CloudWatch Kubernetes mode returned no memory and a CPU about 100 times too high. Container Insights publishes percentages only: memory read `pod_memory_working_set`, never published as a metric, and CPU was the node percentage the pipeline treated as cores. Memory is now `pod_memory_utilization_over_pod_limit` (of the node when no pod has a limit) and CPU is in cores. Metrics were also kept only from a namespace named after the project; the environment's namespace counts too.
- Kubernetes logs shipped without pod labels (Container Insights) never had an environment, so a project with several environments analysed none of them, and Check my data offered no way out. A project rule whose value names an environment (`kubernetes.namespace_name = production`) now also puts its logs in that environment, on every log store.
- An analysis of CloudWatch logs crashed and never ran ("can't compare offset-naive and offset-aware datetimes"): Logs Insights returns timestamps without an offset. They are read as UTC.
- On CloudWatch, CI/CD events were written to `/serops/cicd/<org>` but searched in `serops-cicd-<org>` (the Elasticsearch index name), a group that never exists: pipeline failures were never correlated, and every scheduled run logged an error.
- The CloudWatch Kubernetes docs: the Container Insights quickstart command left four placeholders, so `kubectl` rejected the manifest; and they said pod labels reach Container Insights, which they do not (logs are shipped with `Labels Off`).

Found against a real Datadog account:

- Datadog metrics: an organisation whose name has a space ("Acme Cloud") got no metrics, because the query was not even parsed. Tag values are written as Datadog stores them (`acme_cloud`).
- Datadog metrics were averaged over every host, so one host running out of memory read as a fleet at half capacity. They come one series per host, with UTC timestamps.
- Check my data offers the Datadog Agent's `kube_namespace` and `kube_app_part_of` tags as project log rules.
- The Datadog site entered in the form ("Datadog Site", e.g. `datadoghq.eu`) was ignored: every EU, US3 and US5 install called the US site and saw its valid keys refused. It is used now, also when pasted as `app.datadoghq.eu` or a URL.
- Datadog "Test connection" only checked the API key; it also checks that the application key can read logs and query metrics, and says what is wrong.
- The application key is required in Settings and in the onboarding wizard (the wizard had no field for it, so a Datadog source added there could never search logs).
- The onboarding "Setup is …% done" box and the floating wizard sat above Settings dialogs and covered their buttons ("Create" in New log provider). They now stay below every dialog.
- Datadog VM CPU (`system.cpu.user`) is a percentage; it was differentiated as a CPU-seconds counter.

Found against a real AWS account (CloudWatch):

- Check my data said "Everything is in place" while most errors were missed: CloudWatch logs seldom carry a project field, the log group says it. A record in a group named after the project (`/ecs/shop-payments`, `/aws/lambda/shop-checkout`) belongs to it unless the record names another project, and the environment can be a word of the group name (`/ecs/shop-orders-prod`). Plain-text lines count too.
- EKS Container Insights log groups, named after the cluster, are searched; Check my data offers the `kubernetes.namespace_name` rule for them.
- Lambda logs got the service "2026" from the dated stream name; they get the function name. ECS streams give the container.
- A refused, failed or timed-out Logs Insights query was reported as "no logs"; Check my data now says the store refused the query and why. Searching all groups no longer asks for a nonexistent `/aws/application` group.
- CloudWatch metrics never worked: "Test connection" and host discovery always failed (an invalid ListMetrics parameter), and no metric was ever returned (SerOps labels were sent as dimensions). Metrics now come one series per host from the CloudWatch agent, CPU falls back to EC2 `CPUUtilization`, and CPU is read as the percentage it is.
- CloudWatch "Test connection" starts a query and reads a metric, and names the missing IAM permission.

Found against a real Datadog account (log search):

- Every Datadog log search with a time range was refused (the time was sent as `…+00:00Z`), so scheduled analyses on Datadog found no logs. Times are sent in the format Datadog reads.
- A refused search came back as "no logs": a run then said there were no errors. It is reported as the log store refusing the query, with Datadog's message.
- SerOps listed Datadog indexes from an endpoint that does not exist, and an empty list made the scheduler skip the project. It uses `/api/v1/logs/config/indexes`, and searches every index when the list cannot be read.
- Check my data offered another standard environment's name ("use staging for Production") when the project had no such environment. It no longer does.

## [1.2.11] - 2026-10-31

Small fix release, no migration. Set `SEROPS_VERSION=1.2.11` or `--version 1.2.11`.

### Changed

- The UI quality gate checks the project Data tab (accessibility in light and dark, phone width, table alignment) on every CI run.

### Fixed

- Errors that come with both a code and a sentence (the read-only demo's `demo_read_only`, investigation limits) showed the code. The sentence is shown.
- The tables of Check my data started 20 px inside the section's text; they line up now.

## [1.2.10] - 2026-10-31

Data collection release: logs as real shippers write them reach the analysis,
**Check my data** says why a project gets none, and a project can be mapped
onto how its logs are already grouped. Two migrations (Data 0055, Projects
0016) run on their own. Set `SEROPS_VERSION=1.2.10` or `--version 1.2.10`.

After upgrading, SerOps finds logs it used to miss: expect more analyses and
issues for a few batches, until Sentinel's baseline catches up.

### Added

- **Project log rules**: a project's logs no longer need a `project_name` field. Map the project onto how your services are already grouped (`service.namespace = shop`, a Kubernetes namespace, an `app.kubernetes.io/part-of` or `team` label); logs carrying the project name or matching any rule belong to the project, in every log store. **Check my data** lists how untagged logs are grouped and sets a rule in one click.
- **Check my data** (**Projects → [project] → Data**): sends the query the scheduled analysis sends to your log store, one filter at a time (logs found → tagged with the project → in the environment → errors and warnings → from listed services), and says at the first empty step what to change. It lists the project, environment and service values your logs carry, and fixes two things in one click: list a service seen in your errors, or accept the environment value your logs carry (offered also when only some logs carry it, e.g. one team tags `live` and another `prod`; a value another environment of the project uses is never offered). It shows values such as service names, never log messages.
- The project page says what the last scheduled run of each environment did and why it made no analysis: no services, no log integration, nowhere to read logs from, no errors in the window, errors only from unlisted services, the log store refused the query.
- The onboarding wizard shows Check my data when the first analysis has not arrived after two minutes, or when the scheduler already found nothing to analyse, instead of a spinner that never ends.
- An environment's **log label value** (stored before, never used) is now queried: logs tagged with it count for that environment in every provider.

### Fixed

- Log files (`django.log`, `user_actions.log`) grew without limit: they now rotate at `SEROPS_LOG_FILE_MAX_MB` (default 50) and keep `SEROPS_LOG_FILE_BACKUPS` copies (default 5).
- Log warnings never reached the AI. Every provider's warnings are stored as `WARN`, but the prompt filter only kept levels starting with `WARNING`, so warnings were dropped unless their text contained an error keyword. They now reach the analysis and count in the batch's warning total. Found by the RCA benchmark: the decisive `chronyd` clock warning in its clock-skew scenario never reached the model.
- Log redaction blanked ordinary error text. The password and generic-secret patterns treated a plain space after words like `token`, `auth`, `password` or `credential` as the start of a secret, so `token rejected: issued in the future` reached the AI as `[SECRET]: issued in the future` and `password reset failed` as `***** failed`. A secret now needs `:` or `=`, or a value after the space that looks like one (it contains a digit).
- On Kubernetes, the host of a log was often the log shipper (Filebeat, Fluent Bit and the OpenTelemetry Collector write their own name to `host.name`), not where the container ran. The Kubernetes node is preferred now, so "fails on one node only" is visible to the analysis.
- The onboarding wizard showed the whole Check my data panel while waiting for the first analysis: the floating wizard grew taller than the screen, its Minimize button went off-screen and a new customer could not get it out of the way. It now says why nothing was analysed and links to Check my data on the project page.
- During an incident, a finding from reviewing the code (an unused import, a lowered timeout) came out as a second WARNING naming a commit: it read as a second suspect, notified on-call and pointed to an innocent commit. Such findings are now code review notes: INFO, no commit linked, left out of notifications and the incident summary, and shown apart on the analysis page. Outside an incident, code review works as before.
- The logs table of an analysis showed "—" as the service of every log whose shipper did not write `service_name` (Pino, Elastic Common Schema, OpenTelemetry), and the service filter left them out. It reads the service SerOps parsed.
- A batch stored an Elastic Common Schema record's whole `service` object (`{"name": "checkout-api", ...}`) as the service, in place of the name. The parsed name is kept, and the environment is kept wherever the record carried it.
- Errors that differ only by a duration ("failed after 1003ms", "1004ms") were not grouped, so one recurring error could fill the analysis with near-identical lines. Durations are now ignored when grouping, like ids and timestamps.
- Logs written by the OpenTelemetry Collector's Elasticsearch exporter in `otel` mode (the setup Elastic recommends) had no message, service or environment in SerOps: they sit in `body_text` and under `resource.attributes`. Both are read now.
- An issue linked every commit its root cause named, including a commit the analysis named only to clear it ("commit 8a9b0c1d only added a test fixture"), so an innocent commit was shown as the cause. The analysis now lists the commits at fault (`caused_by_commits`), and only those are linked.
- The AI never saw which host a log came from, so a failure confined to one node read like a service-wide one. Log lines now carry the host, and a repeated line says which hosts it came from.

Logs as real shippers write them now reach the analysis. Before, many standard setups silently got no data:

- Elasticsearch and OpenSearch only searched indices named `application-logs-<project>*`, so logs in `logs-*` (Elastic Agent, the OpenTelemetry Collector, our own Elasticsearch guide), `filebeat-*` or `logstash-*` were never read and the project was skipped. SerOps now falls back to those patterns, and a new **Index pattern** setting on the integration names them explicitly.
- Providers were asked for exactly `ERROR`/`WARNING`/`CRITICAL`, so `WARN`, lowercase levels, numeric levels (Pino, Bunyan) and logs with no level field were never fetched from Elasticsearch, OpenSearch, CloudWatch, Splunk or Datadog. Every spelling and case is now queried, numeric levels are read on their own scale, and lines without a level field are reached through their text. A numeric `level` field in one index no longer makes the whole search fail.
- Records in Elastic Common Schema (Filebeat, Elastic Agent) crashed the batch (`service` is an object) or lost their level (`log.level` was not read), and Pino's numeric levels crashed it too. One alias list now serves both querying and reading, flat or nested, with the Elastic Common Schema and OpenTelemetry names added.
- Datadog matched only log attributes (`@env`), not tags (`env:`), so logs tagged through the Agent or Unified Service Tagging were never found. Both are matched now.
- Logs tagged `prod` never matched an environment named `production` (and the reverse), although the guide said they would. Every spelling is queried.
- CloudWatch read every event as INFO with no service, discovered only `/aws/<project>` log groups and passed several groups as one name. Events are now read field by field (JSON) or from the line (text), groups containing the project name are found too, a new **Log groups** setting names them explicitly, and several groups are queried together.
- The first batch of a project queried no time range, so Elasticsearch returned an arbitrary 5000 records and the first analysis was usually empty. It now queries its own window, newest records first.
- `system-*` indices found on one organisation's cluster were added to every organisation's query.
- The metric examples in the data collection guide still used the old `org_id` / `project_id` labels.

## [1.2.9] - 2026-10-27

Security and Sentry release. Migration: Data 0054 (choice only). Containers now run as non-root: see the upgrade note.

### Added

- Sentry alerts: `POST /api/webhooks/alerts/sentry/<org_id>/` receives a Sentry internal integration's webhooks (issue alerts, metric alerts, new issues), verifies the `Sentry-Hook-Signature` HMAC against `SEROPS_SENTRY_CLIENT_SECRET`, and starts an analysis. Migration Data 0054 (choice only).
- The alert that triggered an analysis (any source) is now part of the prompt, fenced as reported evidence: title, state, severity, service and summary, which for Sentry holds the exception, culprit, release and top in-app frames. An alert alone is enough for an analysis.

### Fixed

- Batch creation crashed (`index_pattern` unset) for organisations with no log integration, so a window with only traces, metrics or an alert produced no batch.
- Helm: alert secrets set inline in values (`alertSecrets.*`) were stored under keys the backend didn't read, so they never took effect; only `existingSecret` worked.

### Security

- The legacy GitLab project registration (`POST /api/providers/`, members with `project.write`) had the same flaw as the project check fixed in 1.2.8 (any URL, raw replies echoed) and, on installs with several organisations, answered with another organisation's project and sent that organisation's webhook secret to the caller's GitLab URL. It now applies the same URL rules and refuses a project registered by another organisation (409) without revealing it.
- Integration URLs (`base_url`, observability `host`, connection test) refuse cloud-metadata addresses; private addresses stay allowed. GitLab pipeline logs no longer echo GitLab's raw error. Slack and Teams deliveries no longer follow redirects past the URL check.
- The backend image runs as an unprivileged user (uid 10001) and cannot modify its own code. If the logs directory isn't writable (a volume created by an earlier, root-run release), logging falls back to standard output instead of failing at startup. Celery beat keeps its schedule in `/tmp`. The Helm chart runs every pod under the restricted Pod Security Standard (non-root, no privilege escalation, capabilities dropped, seccomp, read-only root with `emptyDir` scratch space).

## [1.2.8] - 2026-10-26

Security release. No migrations.

### Fixed

- A failure that recovered ("request failed, retrying" then "succeeded on retry 1") reached the AI without its recovery line, which the severity filter dropped as INFO, so a transient blip on a healthy deploy was reported as a warning. The filter now keeps recovery lines for services that already have an error or warning line. Found by the RCA benchmark (h09).

### Added

- `manage.py rca_benchmark`: incidents with a known root cause, run through the real analysis with your own AI key and scored by fixed rules (`backend/rca_benchmark/`).

### Security

- Dependencies with known vulnerabilities, found by an image scan (Trivy) of the published 1.2.7 images: certifi 2026.10.23 (drops emSign roots with compromised intermediates), Django REST Framework 3.18.3 (denial-of-service and an authorization fix), Pillow 13.0.0 (image-decoder memory-safety fixes). The backend image now applies Debian security updates and upgrades setuptools and wheel at build time, and removes pip once requirements are installed (it vendors old urllib3 and msgpack). The frontend and docs images apply Alpine updates (brotli, expat, libX11).
- `POST /api/providers/verify-project/` (GitLab project check, open to members with `project.write`) could be pointed at any URL: it now refuses cloud-metadata addresses, keeps the project id inside `/api/v4/projects/<id>` (no `../`, `?` or `#` escape), doesn't follow redirects, sets a timeout, returns only known project and pipeline fields instead of the server's raw reply, and no longer reads or writes another organisation's GitLab project with the same id. Private addresses stay allowed for self-hosted GitLab.

## [1.2.7] - 2026-10-25

Security: cached dashboard views vary on Authorization and Cookie (`cache_per_user`), so one organisation's cached response is never served to another. No migrations.

## [1.2.6] - 2026-10-25

See the full notes in docs/src/changelog.md (journey-suite fixes, Argo CD / Flux integrations, SSO sign-in domains).
Migrations: providers 0015-0017, Users 0013.

## [1.2.5] - 2026-10-21

No migrations.

### Fixed

- Personal project-subscription notifications (email, in-app, digests) were never sent since the 2026-09 notifications cleanup: `notifications.dispatcher` still imported the retired `NotificationSettings` model and every dispatch raised. The dispatcher now uses only the user's preferences and subscription; team-wide Slack/Teams delivery stays with Delivery Channels and Routing Rules. The user's own severity choices now apply (they were ignored), deactivated users and users who left the organisation are skipped, and daily/weekly digests arrive at 09:00 in the user's time zone. Dead per-org sender-name lookup removed from `notifications.services`.

## [1.2.4] - 2026-10-21

No backend changes (frontend-only release); image rebuilt at 1.2.4 so versions match.

## [1.2.3] - 2026-10-20

`UserSerializer.organisation` is the organisation's name (read-only) plus `organisation_id` for login, profile and demo-login; demo-login returns the full serializer (permissions). No migrations.

## [1.2.2] - 2026-10-20

Security release (roles, tenancy, webhooks, dependencies), issue resolution
with the team's root cause, one issue per shared cause, logos and avatars in
the database. Migrations Data 0051–0053, Projects 0015, Organisations 0013,
Users 0012. Full notes in the [project changelog](https://serops.ai/docs/changelog/).

### Security

- SCM webhook receiver fails closed: bindings get a webhook secret on creation (`SCMBinding.save`), the receiver rejects a secretless binding, and existing rows are backfilled (migration `Projects 0015`). Previously a secretless binding accepted unauthenticated payloads.
- Role gaps closed and cross-tenant GitLab webhook actions blocked (see commits); AI provider catalogue writes need platform staff on multi-org installs.
- `/images/` media route removed (unused; under `DEBUG=True` it served `MEDIA_ROOT` = the backend directory). Helm: `/metrics` removed from the default ingress paths (unauthenticated by default; scrape in-cluster via `serviceMonitor`).
- `CICDBinding._sync_legacy_gitlab_project` no longer moves another organisation's `GitlabProject` row (global `project_id` uniqueness let a binding take it over, token included).
- Body ids limited to the requester's organisation (`Utils/scoped_relations.limit_relations`): service `project` (create and update), project-subscription and escalation-rule `project`, project-service `project`/`gitlab_project`/`provider_integration`, deployment `environment` (must be the project's) and `cluster`. Notification and Issue relations and `UserSerializer.organisation` are read-only. `Middlewares/tests/test_body_relations.py` fails on any writable relation left open.
- Superuser tenancy bypass removed (30 `is_superuser` branches in Data, Projects, notifications, ai_model, Organisations views): superusers could read, change and delete other organisations' objects via the API. `BatchIssuesView` also refused a user without an organisation only when the batch had one.
- `Middlewares/tests/test_tenant_coverage.py`: walks every API route as another org's admin and superuser (marker scan on lists, `TARGETS` map for routes with ids, no 5xx).
- `ACCESS_DENIED` audit entries from `Requires` (cache-deduplicated per user/method/path, 10 min); migration `Data 0053`. `get_client_ip` takes the `X-Forwarded-For` entry added by the trusted proxy (`NUM_PROXIES`).
- One RBAC model (`Middlewares/rbac.py`): `PERMISSIONS` catalogue, cumulative `ROLE_PERMISSIONS`, platform permissions (`ai_catalogue.manage`, `platform.manage`), one `has_permission()`. Every API view declares `Requires(...)` per method or viewset action; undeclared requests are denied. `Middlewares/tests/test_permission_coverage.py` fails on any route without full coverage (public endpoints are allowlisted with how they authenticate). Removed: `Users/permissions.py` (`IsAdminRole`, `ReadOnlyForViewer`, `IsUserOrAdmin`, `CanManageSharedSettings`), `require_role`, `Middlewares/OrganisationMiddleware.py`, in-view role checks, and the unrouted `JobList` and `Gitlab_save_logs` views.

### Added

- Issue resolution: `resolved_by`, `resolution_root_cause`, `resolution_fix` (migration `Data 0052`). `POST /api/data/issues/<id>/resolve/` accepts optional `root_cause` and `fix`; bulk resolve records `resolved_by`. Past-incident memory and issue embeddings prefer the team's root cause and fix, rank confirmed resolutions first and label corrections.

### Changed

- `UserSerializer` (login, profile) returns `permissions`, the user's sorted permission list.
- Viewers lose read access to retention, data usage and AI budget (`settings.read`); users gain the observability source health check (`integration.use`).
- One issue per root cause: the analysis prompt asks for one issue on the component where a shared cause lives, with the other services in the new `Issue.affected_services` (merged on recurrence; the issue `component` filter matches it). Migration `Data 0051`.

### Fixed

- `NodeMemoryRawView` / `NodeCPURawView` returned 500 without a metric integration; `APIKeysView` GET on the detail URL returned 500 (now returns that key; POST there is 405).
- Organisation logos and profile photos are stored in the database as
  small PNGs (they were never served with `DEBUG` off). Profile photos are
  served at `GET /api/auth/avatar/<key>`; `DELETE
  /api/auth/profile/upload-avatar/` and an empty `logo` remove them.
  Migrations `Organisations 0013`, `Users 0012`.

## [1.2.1] - 2026-10-19

Fixes: the AI sees every data source a batch carries (sections were hidden
when no integration was configured), diff hunk headers survive redaction,
a rejected Gemini key reads as an auth error; SerOps "SO" logo; Helm docs.
Full notes in the [project changelog](https://serops.ai/docs/changelog/).

## [1.2.0] - 2026-10-18

A redesigned app (full-width pages, grouped navigation, environment
picker, dark mode everywhere), AI analysis that reads the diff hunks the
stack traces point at, diff text for GitHub/Bitbucket/Azure DevOps, code
redaction before the AI, and Azure DevOps repositories. No migrations.
Full notes in the [project changelog](https://serops.ai/docs/changelog/).

## [1.1.1] - 2026-10-17

Fixes: Sentinel skips recurring errors, OTLP JSON span status, chat model
selection, Argo CD/Flux deploy webhook authentication; Slack/Teams URL
validation and required deploy webhook signatures.
Full notes in the [project changelog](https://serops.ai/docs/changelog/).

## [1.1.0] - 2026-10-17

UI release: incident-first Overview and incident page, Issues side panel
and filters, ⌘K search, dark mode, phone layouts, WCAG 2 AA.
Full notes in the [project changelog](https://serops.ai/docs/changelog/).

## [1.0.3] - 2026-10-15

Security and feature release: SSO tenant isolation, Investigate
(on-demand analysis), and scheduled/alert analysis fixed on Kubernetes.
Full notes in the [project changelog](https://serops.ai/docs/changelog/).

## [1.0.2] - 2026-10-14

Bug-fix release: the Helm chart's backend now starts, plus dashboard
fixes. Full notes in the
[project changelog](https://serops.ai/docs/changelog/).

## [1.0.1] - 2026-10-13

Security and bug-fix release. Full notes in the
[project changelog](https://serops.ai/docs/changelog/).

## [1.0.0] - 2026-10-11

First public release.

### Added
- Auto-detect enabled data sources per project (capability registry).
- OTLP HTTP receiver + Trace/Span models + IngestKey auth.
- Trace adapters for Jaeger, Zipkin, Datadog APM, Grafana Tempo.
- Unified event timeline API (`/api/data/batches/<id>/timeline/`)
  with engine-backed causal pairs.
- Real-time alert webhooks (Alertmanager, Grafana, Datadog Monitors).
- Native ArgoCD + Flux GitOps deploy webhooks.
- Multi-cluster K8s model + cluster-scoped observability integrations.
- Post-RCA notification channels: Slack, Teams, PagerDuty, OpsGenie.
- Prometheus self-metrics `/metrics/` endpoint.
- Kubernetes Helm chart (OCI + classic repo publish on `v*.*.*`).
- Similar-incidents suggestion + post-mortem draft generator.
- Per-org monthly AI cost budget + `/api/settings/ai/budget/`.
- First-class on-prem Ollama support + admin-only probe endpoint.
- `DataSourceContext` dataclass — replaces 13-kwarg fan-out on the
  prompt builder.
- AI adapter error classification for timeout / overloaded /
  server_error / network_error / (Gemini) content_blocked.
- `/api/version/` endpoint exposing version + git sha + build time.

### Changed
- AI adapter clients now explicit 120s request timeout (was
  provider-default 600s / Gemini none).
- ES helper now defaults to `verify_certs: True`.
- Password policy validators now fire through DRF serializers.

### Fixed
- IDOR: `providers.views.JobList` scoped pipeline query to project.
- Password-reset user enumeration (constant-response).
- Invitation / verification / reset tokens no longer logged verbatim.
- AI chat prompt no longer logged at INFO.

### Security
- Explicit cookie hardening (`SESSION_COOKIE_HTTPONLY`,
  `SESSION_COOKIE_SAMESITE=Lax`, same for CSRF).
- Ollama probe endpoint rejects cloud-metadata IPs (SSRF guard).
- File upload capped at 10MB.
- Base-text XSS closed in `renderFormattedText` (frontend).

### Removed
- 19 unused pip packages (previous 10 + Batch 36's 9-package
  aiohttp/threadpoolctl/watchdog transitive chain).

[Unreleased]: https://github.com/getserops/serops/compare/v1.0.2...HEAD
[1.0.2]: https://github.com/getserops/serops/releases/tag/v1.0.2
[1.0.1]: https://github.com/getserops/serops/releases/tag/v1.0.1
[1.0.0]: https://github.com/getserops/serops/releases/tag/v1.0.0
