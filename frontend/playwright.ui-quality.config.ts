/**
 * UI quality gate: accessibility (axe, light + dark), phone layout and
 * table alignment on every main page, signed in as the seeded demo user.
 *
 * Runs in CI against the quick-start stack (see .github/workflows/ci.yml,
 * job "ui-quality"); locally point it at any running SerOps:
 *   UI_BASE_URL=http://192.168.67.2 npx playwright test -c playwright.ui-quality.config.ts
 * The instance needs the demo org: `python manage.py seed_demo_org`.
 */
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/ui-quality',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : 4,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report-ui' }]],
  timeout: 60_000,
  use: {
    baseURL: process.env.UI_BASE_URL || 'https://localhost',
    ignoreHTTPSErrors: true,       // quick-start serves localhost from Caddy's own CA
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    {
      name: 'desktop',
      dependencies: ['setup'],
      testIgnore: /auth\.setup\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 }, storageState: 'tests/ui-quality/.auth/demo.json' },
    },
  ],
});
