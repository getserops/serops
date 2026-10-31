import type { Page } from '@playwright/test';

/**
 * Pages reached by a few clicks rather than a URL, rendered the way a person
 * with edit rights sees them. The demo account is read-only and its log store
 * is not real, so the project Data tab is filled with a sample "Check my
 * data" result (network stub) and the edit controls are shown. This checks
 * the screen (contrast, labels, layout), not the check itself: the journey
 * suite and the unit tests cover that.
 */
const RUNS = [
  { environment: null, ran_at: '2026-10-31T06:00:00Z', outcome: 'skipped', reason: 'no_log_location', detail: '', counts: {} },
  { environment: 1, ran_at: '2026-10-31T06:05:00Z', outcome: 'empty', reason: 'no_registered_service',
    detail: 'Errors and warnings came only from services this project does not list: cart (12).', counts: {} },
  { environment: 2, ran_at: '2026-10-31T06:05:00Z', outcome: 'batch', reason: '', detail: '', counts: {} },
];

const REPORT = {
  project: 'shop', environment: 'production', environment_values: ['production', 'prod', 'prd'],
  window_minutes: 60, sample_size: 1000,
  locations: ['logstash-2026.10.31', 'filebeat-8.15.3', 'logs-generic-default', 'application-logs-shop', 'system-logs'],
  stages: [
    { key: 'found', count: 1000, capped: true },
    { key: 'project', count: 640, capped: false },
    { key: 'environment', count: 412, capped: false },
    { key: 'level', count: 37, capped: false },
    { key: 'services', count: 25, capped: false },
  ],
  seen: {
    project: [{ value: 'shop', count: 640, field: 'project_name' }],
    environment: [{ value: 'prod', count: 300, field: 'env' }, { value: 'live', count: 112, field: 'service.environment' }],
    service: [{ value: 'payments', count: 200, registered: true }, { value: 'checkout-api', count: 12, registered: false }],
    level: [{ value: 'ERROR', count: 30 }, { value: 'WARN', count: 7 }],
    groupings: [
      { field: 'resource.attributes.service.namespace', value: 'shop', count: 210, matches_name: true },
      { field: 'kubernetes.namespace', value: 'kube-system', count: 90, matches_name: false },
    ],
  },
  project_rules: [{ field: 'kubernetes.namespace_name', value: 'shop-prod' }],
  diagnosis: { code: 'ok', message: 'Everything is in place: 25 errors and warnings would be analysed now.', count: 25 },
  fixes: [
    { action: 'use_environment_label', environment: 1, value: 'live' },
    { action: 'register_services', names: ['checkout-api'] },
    { action: 'add_project_rule', field: 'resource.attributes.service.namespace', value: 'shop' },
  ],
};

async function projectData(page: Page) {
  const grant = (user: Record<string, unknown>) => ({
    ...user, permissions: Array.from(new Set([...((user.permissions as string[]) || []), 'integration.use', 'project.write'])),
  });
  await page.addInitScript(() => {
    try {
      const u = JSON.parse(localStorage.getItem('user') || '{}');
      u.permissions = Array.from(new Set([...(u.permissions || []), 'integration.use', 'project.write']));
      localStorage.setItem('user', JSON.stringify(u));
    } catch { /* storage blocked: the page renders read-only */ }
  });
  await page.route('**/auth/profile', async (route) => {
    const res = await route.fetch();
    route.fulfill({ response: res, json: grant(await res.json()) });
  });
  await page.route('**/projects/*/data-check/', (route) =>
    route.fulfill({ json: route.request().method() === 'GET' ? { runs: RUNS } : REPORT }));
  await page.goto('/dash/projects');
  await page.getByRole('row').nth(1).getByRole('button', { name: 'Services' }).click();
  await page.getByRole('tab', { name: 'Data' }).click();
  const region = page.getByRole('region', { name: 'Check my data' });
  await region.getByRole('button', { name: 'Check my data' }).click();
  await region.getByRole('status').waitFor();
}

export const FLOWS: Record<string, (page: Page) => Promise<void>> = {
  'project-data': projectData,
};
