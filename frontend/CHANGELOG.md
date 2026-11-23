# Changelog

All notable changes to the SerOps frontend are documented in this
file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
starting from `v1.0.0`.

Frontend and backend versions are coordinated — a `v1.0.0` release
means backend + frontend + Helm chart appVersion all match.

## [Unreleased]

## [1.5.3] - 2026-11-23

### Fixed

- **French: the rest of the interface**: about 890 sentences, labels and
  messages outside the Issues page were written in the code and stayed in
  English in the French interface: integrations and AI providers settings,
  routing rules, incident channels, observability, the add-service wizard and
  service details, onboarding, sign-up and password pages, Analyses, the
  analysis page and its timeline, the sensitive-data warning, chat, Sentinel
  figures, the top bar, and the server-error messages of the sign-in forms.
  They are in the translation files; the English text is unchanged. A test now
  fails on a new message, accessible name or title written in English in a
  component.
- **Phones, Analyses (A9)**: each analysis was a 318 px card of ten stacked
  lines. It is a 136 px card: project, status and the link on the first line;
  time, environment, trigger and issue count on the second; the identifier and
  the Sentinel decision behind "Details".
- **Phones and tablets, tap targets (A7)**: on touch devices, buttons, menu
  rows, tabs, pickers, fields and row actions are 44 px high, and nothing is
  under 24 by 24 px. On Issues, 39 of 43 controls were under 44 px; now only
  the row checkboxes are (24 px, in a 44 px cell). One block in the shared
  styles; a mouse keeps the compact sizes. The Traces filters wrap two per
  line below 1,200 px.
- **Phones, Overview (A4)**: six panels stacked made a 4,837 px page, the
  service health map alone 1,587 px. "Needs attention now", the three numbers
  and the recent analyses stay open; recent deployments, the 7-day trend, the
  root causes and service health show their title and one-line summary and
  open on a tap. Service health is one line per service, the worst first. The
  page is 2,601 px.
- **Phones and tablets, navigation (A3)**: the top bar left the screen with
  the page, so the menu was out of reach after scrolling. It stays in place up
  to 860 px, and a link to a place in the page stops under it.
- **Phones, first screen (A2)**: the page started at 369 px (Overview) and 352
  px (settings) on a 382 by 791 phone. The demo banner is one line with the
  rest behind "More" (it can still be closed); the top bar is one row, with
  the environment and cluster pickers behind one button; the page header drops
  its subtitle; the read-only note of the demo's settings is one line. The
  page now starts at 151 to 177 px.
- **Phones and tablets, smaller items (A10)**: no text under 12 px up to 1,024
  px (menu group labels, unread count, feed badges, "+2"); the Analyses table,
  which scrolls sideways on a tablet, shows a soft edge where more columns are
  and keeps the checkbox and the time in place; the menu drawer takes the
  focus when it opens, keeps Tab inside, closes on Escape, gives the focus
  back to the menu button and stops the page behind from scrolling.
- **Phones, Issues cards (A8)**: the cards showed "1 day ago" and "1×" with no
  label, because the header row is hidden. Each value carries the name of its
  column, as on the other stacked tables.
- **Phones and tablets, fields (A6)**: 86 fields had text under 16 px, which
  makes an iPhone zoom in on focus. One shared rule sets every text field,
  select and text area to 16 px on touch devices. Pinch zoom stays on; a mouse
  keeps the compact sizes. The Issues filters take a line each when their
  label needs it.
- **Phones, chat (A5)**: the message box ended below the screen (803 px on a
  791 px screen). The chat is sized from the measured height of the top bar
  and of the demo banner, and from the screen a person really sees, so the box
  stays above the on-screen keyboard. No stylesheet assumes a 56 px top bar
  any more.
- **Phones and tablets, Issues table (A1)**: between 768 and about 1,090 px
  the Description column was 0 px wide, and at 768 px the Actions column lay
  outside the card, which cut it. The list now picks its layout from the width
  of its own card: every column; the same columns trimmed (1,280 px:
  Description 246 px, was 198); Last seen and Occurrences as a line under the
  description, with their sort controls in the Description header (1,024 px);
  one card per issue where no table fits. Description always has 240 px or
  more, and the card no longer hides overflow. Unchanged from 1,366 px.

## [1.5.2] - 2026-11-22

### Added

- **Design rules**: `frontend/DESIGN.md` says where the tokens are, which
  shared classes to use, the colour rules and the date rule.
- **Guard rail**: `npm run lint` now fails on a new literal colour (`#hex`,
  `rgb()`, `hsl()`) outside `src/styles/design.css`. The 1,040 literals in 52
  files that were there are in a baseline
  (`scripts/literal-colours-baseline.json`): a file may go down, never up.
  Both pipelines already run `npm run lint`.

### Changed

- **One name per page**: the menu entry, the page heading and the browser
  tab now say the same thing, in English and French. Overview (the tab said
  "Dashboard"), Issues (heading "System Issues"), AI Chat ("AI Assistant"),
  Traces (the tab showed a raw key), AI Providers, Sentinel, Data retention,
  Trace ingest keys, Clusters, Security, Notification preferences. Delivery
  channels and Routing rules are the two tabs of one page, "Alerts &
  routing"; its heading is no longer English in French.
- **French wording**: an issue is a "problème" on the Overview card too
  (it said "incident"), and titles use French sentence case ("Tableau de
  bord", "Journal d'audit", "Paramètres généraux").
- **Demo landing page**: a real `<h1>`, "See how SerOps finds the root
  cause", one sentence on what SerOps does and three points on what the
  demo shows; the tab reads "Live demo"; the footer is "© 2026 SerOps.".
- **Issues table**: the "Age" column is hidden by default (it repeats
  "Last seen" for most issues) and stays available under Columns; a saved
  choice of columns is kept. Description gets the room.
- **Overview**: "Recent Deployments" is not shown on the public demo, which
  has no deployment to list, nor when CI/CD is connected and no service has
  a run yet; "Recent AI Analyses" takes the full width. A workspace with no
  CI/CD connected still sees the panel and its hint to add it.
- **Colour rules**: red now means "needs action". An issue that is resolved
  or muted keeps its severity as an outlined neutral chip, with no red or
  amber accent on its row, no coloured icon and no coloured occurrence
  count (Issues table, issue drawer, analysis page). The "Open" status is
  the brand tone instead of amber, "Acknowledged" is neutral, "Resolved"
  green, "Muted" gray, the same on every page; the analysis header no
  longer shows "Open" in red or amber (the severity chip beside it does).
  Rows have no severity tint. Informational notices use one info tone
  instead of amber: the demo banner, the chat's demo note and the
  notification panel's read-only note. One helper decides these tones
  (`utils/tones.js`).
- **Dates and time zones**: every date on screen comes from one utility
  (`utils/dates.js`) and follows the time zone and the language of the user
  menu; before, about 30 places asked the browser directly and ignored
  both. Detail views show the exact time with its zone ("21 Nov 2026,
  00:57:21 UTC": issue drawer, analysis page, audit log, investigations,
  settings). Tables show relative time in one style ("2 days ago", no more
  "1d ago" in some places) with the exact time and zone in the tooltip:
  Issues, Analyses, Traces, recent analyses and deployments, notifications,
  integrations. The log table on the analysis page names its zone in the
  column heading, "Timestamp (UTC)", because the log line beside it often
  carries its own time in another zone.
- **Analysis page**: when an analysis found exactly one issue, the "1 issue
  detected" card is gone: it repeated the title of the page header and the
  text of "Suggested fix". With several issues the list stays, and the first
  issue's fix is no longer repeated under its row. The issue is still one
  click away under Related > Issues.
- **Overview**: six panels instead of eleven, in this order: Needs
  attention now; three key numbers (Open critical, Open issues, System
  Health); Recent analyses beside Recent deployments; the 7-day trend beside
  the root cause breakdown; Service health. At 1440 x 900 the first screen
  holds Needs attention now and the key numbers completely (the row ended at
  894 px of 900, now 852). The mean-time-to-resolve tile and the AI
  recommendations tile are gone from the page; the two count tiles open the
  Issues list with the matching filter.
  "Needs attention now" is a neutral card with a red accent on the left
  instead of a red background. Service health is one panel: the coloured
  tiles and the "Top Failing Services" chart became neutral tiles, worst
  first, each with the name, the health and the open issues.
  Moved, with the same data: Sentinel figures to the top of Settings >
  Sentinel, AI correlation insights to one line above the Analyses list,
  workloads by cluster to Settings > Clusters under the table.
- **Issue headlines**: wherever an issue is shown by its title (Overview,
  Issues table, issue drawer, analysis page header and issue list, command
  palette) the title is a headline: the first sentence of the description,
  and when that is over 120 characters it is cut at a word boundary, never
  inside a word or inside quoted error text, and ends with "…". The whole
  text is in the title attribute; the drawer shows it once under the title.
  The analysis page header no longer cuts in the middle of a word. Computed
  in the browser; stored texts unchanged.
- **Issues table**: the Component column is wide enough for a service name
  ("shippingservice" showed as "shippi…"). The room comes from the
  Occurrences column and, for about 36 px at 1440 px, from Description.
  The Description shows the headline on two lines instead of one line with
  the root cause under it, so a row keeps its height and the headline is no
  longer cut after three words; the root cause is in the issue drawer.
- **Keyboard and screen readers**: every signed-in page has one `<main>`
  landmark, and "Skip to content" is the first stop of the Tab key (English
  and French). Reaching the Issues table took 26 Tab presses.
  The chat box and the inputs of General, Sentinel, My Notification
  Preferences and Audit Log settings (17 controls) have an accessible name,
  taken from the label already shown next to them.
- **Notifications panel**: it is a named dialog that takes the focus, closes
  on Escape and on a click outside, gives the focus back to the bell, and
  closes when the command palette opens. Escalations read "Escalation level
  2: Pod crash in Shopfront" instead of "ESCALATION (Level 2): POD_CRASH in
  Shopfront", and a new issue reads "Critical: Pod crash on shippingservice"
  instead of "[CRITICAL] POD_CRASH on shippingservice" (English and French;
  the stored subject stays in the tooltip). The levels of one issue show as one
  entry at its highest level; marking it read or deleting it acts on every
  level. The count badge sits on the corner of the bell, not over it.
- **Public demo**: the controls that would write are switched off, with the
  read-only sentence as their tooltip, instead of failing on click: Resolve,
  Mute, Acknowledge and Reopen in the issue drawer, the same entries in the
  Issues row menu, the bulk bar and the `r` / `m` shortcuts; New Project,
  edit and delete on Projects; Add new Service and delete on a project;
  Edit, Update Password and the photo controls on the profile; Mark all as
  read, Clear all and the per-item actions in the notifications panel.
  Unchanged for every other user.
- **Public demo**: a visitor can close the banner for the session. Settings
  no longer shows a second tinted banner under it: the read-only sentence is
  a line of the page.
- **Wording**: the key and the features it turns on are called "paid
  license" and "paid features" ("licence payante" in French) instead of
  "Enterprise license" and "SerOps Enterprise": Settings menu and license
  page, the notices on SAML, SCIM, audit streaming, custom roles and project
  access, and the badge on those features. The paid features start with the
  Business plan, so the old name was wrong for a Business buyer. Names only:
  no key, feature or behaviour changes.

### Removed

- The mean-time-to-resolve card and the service ranking chart, with their
  tests, styles, service call and texts: no page has shown them since the
  six-panel Overview.

### Fixed

- **Dark theme**: the timeline on the analysis page drew white lanes, white
  marker outlines and a light frame, and the page buttons of Analyses and
  Issues were white with pale text. They use the theme's tokens now.
- **AI Chat on the public demo**: the conversation card no longer runs below
  the screen. Its height ignored the demo banner above the top bar; the
  banner now publishes its height (`--demo-banner-h`) and the chat subtracts
  it.
- **Issues page in French**: about 70 sentences of the list were written in
  the code and stayed in English whatever the language (filters, column
  names, the Columns menu, the selection bar, the mute window, keyboard
  shortcuts, confirmation messages, the "CRITICAL" and "WARNING" chips, also
  in the side panel). They are in the translation files; the English text is
  unchanged. The severity and status filters size to their longest choice,
  and the "Last seen" and "Severity" columns are wider, so French fits.
- **AI Providers on a phone**: at 375 px the provider's name broke one letter
  per line. Each column name now sits above its cell and the content takes
  the full width; the saved key has its own line.
- **Final read before 1.5.2** (every page, English and French, light and
  dark, 1440 and 375 px):
  - French: about 180 labels were still in English title case ("Politique de
    Rétention", "Enregistrer les Modifications"); they are in sentence case.
    Eleven sentences said "incident" where the English says "issue"; they say
    "problème", as the menu does. "Le diagnostic AI" reads "IA".
  - Names: the General settings page is headed "General", as its menu entry;
    the issues of one analysis are headed "Issues" (it was "1 Issues
    Detected", in English in both languages); the command palette lists
    "Analyses", not "Data"; the tabs of Audit Streaming and Paid license
    carry their own name.
  - Cut text: on a phone, the counts of "Workloads by cluster" ran off the
    screen; the scope filters of Issues cut their French labels ("Tous les
    environ"). The span tables of an analysis have translated column names.
  - Tone: the "read-only demo" notice of Investigate is an information
    notice, not amber; a service type is a neutral chip, not amber; an empty
    message in the error spans is no longer red.
  - Dark theme: the track of the health and usage gauges and of the span
    bars of a trace is no longer near-white.

## [1.5.1] - 2026-11-22

### Changed

- **Analysis page**: the page downloads an analysis once instead of twice.
  The envelope, the log list and the metric charts each asked for the whole
  answer; calls made at the same time now share one download. On the demo's
  Fleet analysis that is 553 KB instead of 1,106 KB before compression.
- **Overview**: less text on the first screen. In "Needs attention now" the
  headline is the first sentence of the issue's description, on two lines at
  most; "Why it is happening" shows three lines with "Show more"; "What to
  do" is a numbered list, one sentence per step, three shown and the rest
  behind "Show more". The rows below show one whole first sentence instead of
  a line cut by an ellipsis. Display only: the stored texts are unchanged and
  the full description is in the tooltip and on the issue.
- **Public demo**: a shorter banner: "Example data: analyses SerOps got right,
  from our own test environments. The misses are on the benchmark page."
  The French banner says the same.

### Fixed

- **Read-only demo**: a write the server refused is never shown as a
  success. Creating a project showed "Project created successfully!"
  although the server had refused it; the project form, the add-service
  wizard and the delete actions now show the read-only notice and nothing
  else, and a refused delete of a chat conversation no longer clears the
  open conversation.
- **AI Chat**: two bold paragraphs in a row are no longer shown on one
  line. The clean-up of empty `**` pairs also removed the pair that closes
  one bold paragraph and opens the next, with the blank line between them.

## [1.5.0] - 2026-11-21

### Added

- Analyses list: a Trigger column (Scheduled, Alert received, Investigation) and a separate Sentinel column (Signals found, Periodic check, AI skipped: nothing new, First analysis, Shadow mode; "Not consulted" for investigations), with the reasons as a tooltip. A scheduled run that Sentinel let through used to show as "ALERT".
- Analysis page: the subtitle and the Response card show the trigger, the card has a Sentinel row, and Sentinel's reasons show as words, not codes.
- Alerts & routing → Delivery Channels: a notice lists the alerts of the last week that matched no service and were not analysed, with the labels tried.
- Overview, Issues and Analyses keep the environment and cluster filters in the address. When the address carries any filter it decides alone; the stored choice fills only an address with none. Issues and Analyses follow the global environment filter instead of a page-local one.
- Settings → Integrations, Elasticsearch and OpenSearch forms: a **Verify TLS certificate** checkbox, checked by default.
- Investigations: a finished investigation with no traces says latency is not observable.
- Check my data and the project's Data tab show the new `errors_unreadable` and `logs_not_tagged` messages (English and French).
- Analyses list: a failed analysis shows "AI provider account reached its spending limit" for `SPEND_LIMIT`.
- Usage counting for an operator's public demo instance, off by default. The app asks `/api/client-config/` once; unless the operator set `SEROPS_USAGE_SCRIPT_PATH` and `SEROPS_USAGE_WEBSITE_ID`, it loads nothing and sends nothing. When set, a same-origin Umami-compatible script reports page names only (`/dash/data/details/:id`, never the id; no query string, no text) and a few events (`demo_signin`, `analysis_opened`, `chat_opened`, and for links that leave the app `github_click`, `docs_click` or `outbound_click`); Do Not Track is respected. SerOps itself still sends no usage data to anyone.
- The analysis page says "Showing N of M log lines" above the log table when the API reports that it kept fewer log lines than the analysis read (`data.logs_kept` and `data.logs_total` on the batch). Nothing is shown when the counts are absent or equal.
- AI Chat: tables, headings and lists in an answer render as tables, headings and lists (they showed as lines of bars, `#` signs and dashes). A wide table scrolls inside the message. The demo's Chat page lists the stored conversations to read.

### Changed

- Overview: System Health says "Open issues now"; MTTR shows its window and sample size, and "Not enough data" for a small sample instead of "Stable"; the tiles count open issues ("AI recommendations / On open issues", "Open critical"); the Service Health Map legend uses 85 and 60 like System Health; Top Failing Services lists by open issues, worst health first; the correlation card says "Commit links" and "Most correlated components"; the Sentinel card shows shadow and manual analyses and how many the AI analysed. Every panel states its time window.
- The environment picker offers "development" instead of "dev", which matched nothing.
- Analyses list: the model name moves from the "Analyzed" badge to its tooltip; below 1440 px the Trigger and Sentinel chips may wrap onto two lines.
- CI/CD binding form: the field asks for `owner/repo` for GitHub Actions and `group/project or project ID` for GitLab CI.
- The demo sign-in page says "example incidents", not "real incidents" (English and French).
- The built-in sample incident's reasoning steps cite only what an analysis reads.
- Public demo: the banner on every signed-in page says that these are analyses SerOps got right, selected from benchmark runs on test environments and shown under the name Acme Cloud, that two of them are healthy windows, and links to the benchmark page for the misses. Its "Self-host SerOps" link is translated (English and French).
- Public demo: the Sentinel card no longer shows "tokens saved". The figure is the average tokens of an analysis times the batches skipped, and in the demo that average is only a size estimate. Unchanged for every other organisation.
- Public demo: the analysis page no longer shows a token figure (no token count was recorded with the demo's analyses; the figure was a size estimate), and integration cards no longer show an age, a service count or the buttons that add, edit, delete or test a connection. Unchanged for every other organisation.
- Public demo: the Overview hides the mean-time-to-resolve tile (its figure would come from the test schedule of the seeded runs), Settings → Integrations hides "Add Integration", and the Team page hides the invite button, the Actions column and the text about inviting or removing people. The server refuses those actions in the demo. Unchanged for every other organisation.
- Dependencies: the image is built on Node 26.13.1 (was 22.12); Vite 8 with `@vitejs/plugin-react` 6 and Vitest 4; framer-motion 14; react-icons 5.7 (the CloudWatch tile uses `FaAws`); bootstrap 5.3.9; rollup-plugin-visualizer 7.1; `@iconify/react` removed (unused).

### Security

- Eight `console.error` calls in the data and project services pass ids as arguments instead of inside the format string.

### Fixed

- The Actions column stays inside the Analyses table at 1440 px after the Sentinel column was added.
- An analysis address with an unknown id shows "Analysis not found" with a way back, instead of an empty page under the id.
- The analysis header says Resolved or Muted when its issues are, instead of "Acknowledged" next to an issue marked Resolved.
- An analysis that found nothing says so in the Root cause card, which used to be left with only its heading.
- Settings → Integrations: the card shows the instance's own address (a self-hosted GitLab showed gitlab.com) and when it was added (it showed "Unknown").
- Settings → AI: providers are described by the API they speak, not by a Python class name; the monthly spend and its percentage no longer run together when read as text.
- A reference with nothing to open is plain text instead of a link that leads to an empty page: a trace id whose trace was not stored (`trace_stored: false` on the span; analysis traces, timeline and its chart, the issue list's trace badge, the chat's trace card, the evidence chips) and a commit the analysis holds no code change for (`in_batch: false`; issue panel and evidence chips). Payloads without these fields link as before.
- One word for one thing in titles: "analysis" replaces "batch" in the Analyses page, its table, the timeline and traces pages, the browser title and the notification type (English and French).
- Analysis pages: the "By service" heading of the metrics table and the note above the log table line up with the first column.

## [1.4.0] - 2026-11-15

The Enterprise panels for SAML, SCIM and audit streaming, and the Enterprise notices shown in their place without a license. Same version as the backend and the chart.

### Added

- Settings → Security → Single Sign-On: choose the protocol (OpenID Connect, or SAML 2.0 marked Enterprise), and **Require single sign-on**. With the SAML license the Enterprise panel (`src/ee/saml`) shows what to register at the identity provider, reads its metadata, and sets attributes and security options; without it the page explains the feature and links to the pricing page.
- Settings → Security → Provisioning (SCIM): with the SCIM license the Enterprise panel (`src/ee/scim`) shows the Tenant URL and manages SCIM tokens (created and shown once, listed by prefix, revoked); without it the page explains the feature and links to the pricing page.
- Settings → Audit Streaming (`src/ee/audit_stream`, Enterprise): destinations (syslog or HTTPS), their delivery state, a test button, and the form to add or change one; without the license, existing destinations can be turned off or removed. The Audit Log page explains the feature when it is not licensed.

## [1.3.1] - 2026-11-13

Dependency updates. Same version as the backend and the chart.

### Changed

- Dependencies: minor and patch updates (React 19.3, React Router 7.18.5, TanStack Query 5.107, axios 1.21, Playwright 1.65 and its CI image). react-icons stays on 5.5: 5.7 removed an icon the integrations page uses.

## [1.3.0] - 2026-11-11

Roles, teams and per-project access screens, Settings → Enterprise license, the sample incident and the email-change confirmation. Same version as the backend and the chart.

### Security

- Changing your email asks for your current password and is finished from a link sent to the new address (`/email/confirm/:token`).
- SSO sign-in sends the cookie that binds it to this browser.

### Added

- A sample incident, offered from the setup wizard and from the empty analyses card: the real incident page on made-up data, labelled as such, so a new install shows what SerOps produces before anything is connected. It stores nothing in the organisation and calls no AI provider
- Added `src/ee/` (SerOps Enterprise License) with Settings → Enterprise license; `utils/edition.js` (`useEdition`, `hasFeature`, Enterprise settings pages found with `import.meta.glob`, empty without `src/ee/`). `index.html` carries the serops.ai description and link-preview metadata.
- Settings → Security → SSO: rules from identity-provider groups to roles (ordered, add / move / remove), default role or refuse, sync at every sign-in, email domains. Login explains a refused SSO sign-in (`?sso=denied`); Team says when roles come from the identity provider.
- Settings → Roles (Enterprise, `src/ee/access`): custom roles built from grouped permissions (always-included and prerequisite permissions locked), member counts, edit/delete. Team invites and edits offer custom roles; SSO rules can target them; Profile and Team show the role name.
- Settings → Teams (members, SSO-sourced badge, project grants) and the project Access tab (Enterprise, `src/ee/access`, registered through `enterpriseProjectTabs`; without the license it can only open, lower or remove). `withEnterprisePages` places Enterprise menu items (`after`). Project buttons use the project's own `permissions` (`canOnProject`); New project needs the organisation role. SSO team rules. The Team page is labelled Members; page titles and the command palette know Roles and Teams.

### Fixed

- Profile: a refused save, or a refused new password, says why.
- The onboarding reminder chip (z-index 1300) covered Bootstrap dialogs' buttons; now 1040.

## [1.2.14] - 2026-11-07

### Security

- Content-Security-Policy: script only from SerOps itself. The login token is in the browser's storage, so a script injected through any future rendering bug could have taken over the account; it is now blocked. The unused inline script in `index.html` is gone and collapsible sections no longer use an inline `onclick`. The UI quality gate fails on any page the policy blocks something on.
- Fonts (Inter, IBM Plex Mono) ship with the app instead of loading from Google Fonts: every visitor's browser contacted Google, air-gapped installs fell back to system fonts, and the Content-Security-Policy blocks it.
- nginx no longer sends its version (`server_tokens off`).
- The image build honours `--build-arg VITE_BASE_URL` (the committed `.env.production` silently won), and a developer's local `.env*.local` or `node_modules` no longer reach the image (`.dockerignore`).

### Added

- Analysis page, Metrics: Kubernetes changes (rollouts with their image change, scale changes), containers that cannot start and Deployments short of replicas, next to the container terminations.
- Analysis page, Metrics: services throttled by their CPU limit.
- Analysis page, Metrics: rollouts that are not completing while the previous version still serves.
- Analyses list: labels for the Sentinel triggers `trace_latency_spike` and `trace_error_spike`.

### Changed

- Settings → Sentinel shows active mode as the default while it loads.

### Fixed

- Onboarding, Google Cloud: the wizard asks for the project ID, the service-account key and whether the services run on GKE, and no longer shows the host, username and API key fields Google does not use. It saved Google integrations without a project, so they never worked.
- Loading spinners have an accessible name ("Loading", or "Setup progress" for the onboarding ring): screen readers announced an unnamed progress bar (axe `aria-progressbar-name`).
- A failed analysis's tooltip names the new provider errors: no credit left, overloaded, server error, redaction failed.

- Analysis page, Metrics: a stuck rollout says how many new pods are not ready instead of "1 of 1 updated".
- Analysis page, Metrics: a workload back to full strength says it has recovered.
- An analysis where the AI ran and found nothing said "Sentinel skipped AI analysis" next to the model name and token count. The page now says which it was: skipped by Sentinel (no model or tokens shown), analysed with nothing wrong found, or not analysed yet.
- Phones: buttons in stacked table cards keep their size (Projects' Services and Batches were squeezed, their words broken letter by letter); the AI Chat no longer pushes the top bar off the screen or cuts its placeholder; the Traces list shows 20 traces a page (50 cards made a page about 13,000 px long); the issue menu and audit-log toggles are 32 px tap targets.
- AI settings: saving the primary model sent back the monthly budget loaded with the page and erased a budget saved a moment before (the spending cap silently gone). It now sends only the model fields.
- Analysis page on phones: the title (the whole first issue sentence) is at most four lines; log messages use the card's full width (a stack trace was squeezed into a narrow column, ~2000 px a line).
- Choosing the primary AI model saves it at once: it waited for the Save button at the bottom of the page, and leaving without it kept the old model with nothing said.
- Project services list: the count read "1 - 5 of 10" for six services (and "6 - 2 of 2" on page 2); it shows ten a page and opens the page of a service just created, which used to land on a later page with nothing visible changing.
- An address that matches no page shows "Page not found" instead of an empty area; `/dash/` with a trailing slash is the Overview.
- The AI Chat no longer labels its greeting "gemini" before the organisation's models load.
- AI Chat: the sensitive-data warning said a message is sent "without modifications"; secrets in it are now masked by the backend before it reaches the AI provider, and the warning says so.

## [1.2.13] - 2026-11-01

### Changed

- Azure Monitor integration form: the workspace and resource URI fields say what each is for (the workspace also gives per-service AKS metrics; the resource URI is optional for AKS).

## [1.2.12] - 2026-10-31

### Fixed

- Metrics page: the CPU "Peak reading across N services" caption sat under the Memory chart; it is under the CPU chart.
- The onboarding box and the floating wizard covered Settings dialogs' buttons; they stay below every dialog.
- The onboarding wizard asks for the Datadog application key.

## [1.2.11] - 2026-10-31

## [1.2.10] - 2026-10-31

## [1.2.9] - 2026-10-27

### Security

- The image is built on nginx's official unprivileged image and runs as uid 101 (port 3000 unchanged).

## [1.2.8] - 2026-10-26

### Security

- The image applies Alpine security updates at build time (brotli fix). No application changes.

## [1.2.7] - 2026-10-25

No frontend changes; image rebuilt at 1.2.7 so versions match.

## [1.2.6] - 2026-10-25

See the full notes in docs/src/changelog.md (journey-suite fixes, Argo CD / Flux integrations, SSO sign-in domains).

## [1.2.5] - 2026-10-21

No frontend code changes; `.env.example` recommends the relative `VITE_BASE_URL=/api` in production. Image rebuilt at 1.2.5 so versions match.

## [1.2.4] - 2026-10-21

Fixed: Integrations screens follow dark mode and the design system (ObservabilitySettings `.obs-*` tokens, ChoiceGroup provider pickers, shared `IntegrationsSectionHeader`, `?tab=` in the URL, labelled form controls; 0 axe violations on 69 provider screens). Removed unused `SettingsOrg` and the ObservabilitySettings default export.

## [1.2.3] - 2026-10-20

Fixed: the sidebar crashed when the stored organisation was an id (after a profile save); General settings guards the same value.

## [1.2.2] - 2026-10-20

Permissions from the server, hidden controls and settings pages per role,
resolve form with root cause, organisation logo in the sidebar, Access Denied
in the audit log. Full notes in the [project changelog](https://serops.ai/docs/changelog/).

### Added

- Organisation logo in the sidebar; remove logo / remove photo actions.
- Resolve form in the issue panel (confirm or correct the root cause and fix); resolved issues show the confirmed root cause and what the AI said.
- Clickable evidence on the analysis page (commit, metric, pipeline, failing trace) and commit links in the issue panel; Code changes highlights `?sha=`.

### Changed

- Issues show the other services a cause affects ("+N" in the list, "also affects" in the panel and on the analysis page).
- Smaller SerOps mark in the sidebar; profile photo updates without a reload.
- Analysis page issue rows show the status chip; the link reads "View issue" (translated) instead of a hard-coded "Open".
- Permissions come from the server (`user.permissions`, refreshed when the app loads): `utils/permissions.js` exposes `can()` / `usePermissions()` and no longer keeps a role table. The Settings menu lists only the pages a role can open; Dashboard setup, integration and source management, AI catalogue and delete controls use named permissions. The unused `RoleGuard` component was removed.
- Audit log shows **Access Denied** entries (red, with the missing permission).

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
- OTLP traces UI (ingest keys, traces dashboard, trace waterfall).
- Multi-cluster picker in navbar + cluster-scoped Dashboard / Data /
  Issues views.
- Per-batch trace view (`BatchTraces`) reading `batch.data.traces`.
- Unified batch timeline (`BatchTimeline`) — SVG chart with per-kind
  lanes, engine-backed causal arrows, lane/severity filters,
  brush-to-filter time-window selection.
- Similar-incidents card + post-mortem draft modal.
- Incident notification channels UI (Slack, Teams, PagerDuty,
  OpsGenie) with test-send action.
- AI cost budget snapshot on Settings → AI.
- Audit log user filter, clear filters, expandable JSON details.
- Error boundary around the routed app tree (per-region crash
  containment with Retry).
- On-prem Ollama documentation link + admin "Test connection" probe.

### Changed
- Traces removed from top-level sidebar (peer to logs / metrics /
  code / CI-CD as data source, not workflow).
- Timeline promoted out of Data-type dropdown into its own peer
  button on batch detail.
- Sidebar accessibility: real `<button>` elements, aria-expanded on
  Settings group, focus-visible outline on mobile backdrop.
- All API service files migrated to `apiClient` interceptor (401 →
  login redirect, consistent auth-header handling).

### Fixed
- Model dropdown fallback no longer hardcodes `[Gemini, DeepSeek]`
  when the org has no API keys configured; empty state links to
  Settings → AI instead.
- Chat renderer base-text now HTML-escaped (`<script>` in bot
  output no longer executes via `dangerouslySetInnerHTML`).
- Tab-nabbing hardening: every `target="_blank"` carries
  `rel="noopener noreferrer"`.

[Unreleased]: https://github.com/getserops/serops/compare/v1.0.2...HEAD
[1.0.2]: https://github.com/getserops/serops/releases/tag/v1.0.2
[1.0.1]: https://github.com/getserops/serops/releases/tag/v1.0.1
[1.0.0]: https://github.com/getserops/serops/releases/tag/v1.0.0
