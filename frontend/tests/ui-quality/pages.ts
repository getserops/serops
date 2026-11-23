// Every main page, using batches and settings the demo seed creates.
// Seeded batch ids come from the seed file name and never change: this is
// the Studio pricing analysis, which has logs, metrics, code changes and a
// trace snapshot.
export const BATCH = 'acme-studio-l10-r1';

export const PAGES: [string, string][] = [
  ['dashboard', '/dash'],
  ['issues', '/dash/issues'],
  ['data', '/dash/data'],
  ['batch', `/dash/data/details/${BATCH}`],
  ['sample incident', '/dash/data/details/sample'],
  ['batch-metrics', `/dash/metrics/${BATCH}`],
  ['batch-code', `/dash/code-changes/${BATCH}`],
  ['batch-traces', `/dash/traces/batch/${BATCH}`],
  ['batch-timeline', `/dash/timeline/${BATCH}`],
  ['investigate', '/dash/investigate'],
  ['chat', '/dash/chat'],
  ['projects', '/dash/projects'],
  ['project-data', 'flow:project-data'],  // Projects → [project] → Data, check result shown (flows.ts)
  ['traces', '/dash/traces'],
  ['notifications', '/dash/notifications'],
  ['profile', '/dash/profile'],
  ['email-confirm', '/email/confirm/preview-token'],
  ['settings', '/dash/settings'],
  ['settings-team', '/dash/settings/team'],
  ['settings-roles', '/dash/settings/roles'],
  ['settings-teams', '/dash/settings/teams'],
  ['settings-delivery', '/dash/settings/delivery'],
  ['settings-routing', '/dash/settings/routing-rules'],
  ['settings-ai', '/dash/settings/ai'],
  ['settings-sentinel', '/dash/settings/sentinel'],
  ['settings-data', '/dash/settings/data'],
  ['settings-integrations', '/dash/settings/integrations'],
  ['settings-integrations-cicd', '/dash/settings/integrations?tab=cicd'],
  ['settings-integrations-logs', '/dash/settings/integrations?tab=logs'],
  ['settings-integrations-metrics', '/dash/settings/integrations?tab=metrics'],
  ['settings-security', '/dash/settings/security'],
  ['settings-audit', '/dash/settings/audit'],
  ['settings-preferences', '/dash/settings/preferences'],
  ['settings-traces', '/dash/settings/traces'],
  ['settings-clusters', '/dash/settings/clusters'],
  // Enterprise (src/ee/): visible to the demo admin of a single-organisation install.
  ['settings-license', '/dash/settings/license'],
];

// Phone and tablet checks (work order of 22 Nov 2026): the screens people
// open on a phone, at the four widths where a layout changes.
export const RESPONSIVE_WIDTHS: [number, number][] = [[375, 812], [768, 1024], [1024, 768], [1280, 800]];
export const RESPONSIVE_PAGES: [string, string][] = [
  ['dashboard', '/dash'],
  ['issues', '/dash/issues'],
  ['data', '/dash/data'],
  ['batch', `/dash/data/details/${BATCH}`],
  ['batch-traces', `/dash/traces/batch/${BATCH}`],
  ['investigate', '/dash/investigate'],
  ['chat', '/dash/chat'],
  ['traces', '/dash/traces'],
  ['profile', '/dash/profile'],
  ['settings', '/dash/settings'],
  ['settings-ai', '/dash/settings/ai'],
  ['settings-audit', '/dash/settings/audit'],
  ['settings-clusters', '/dash/settings/clusters'],
  // Settings pages of the paid features (src/ee/), as the demo shows them.
  ['settings-roles', '/dash/settings/roles'],
  ['settings-audit-streaming', '/dash/settings/audit-streaming'],
  ['settings-security', '/dash/settings/security'],
  ['settings-license', '/dash/settings/license'],
];
