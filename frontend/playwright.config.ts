/**
 * Playwright config for the SerOps UI-invariant gauntlet (PR-UI1).
 *
 * Runs 6 cross-cutting invariants against ~10 fixture batches on the
 * e2e server. Deliberately NOT wired into CI yet — CI is broken; the
 * gauntlet is invoked manually or from a Playwright container.
 *
 * Env overrides (all optional):
 *   GAUNTLET_BASE_URL     https://178-104-127-241.nip.io (default)
 *   GAUNTLET_USER         gauntlet@serops.internal (default)
 *   GAUNTLET_PWD          Gauntlet-Str0ngP4ss-2026 (default)
 */
import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.GAUNTLET_BASE_URL || 'https://178-104-127-241.nip.io';

export default defineConfig({
  testDir: './tests/e2e-invariants',
  fullyParallel: false,           // one browser at a time — e2e is a shared server
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  timeout: 60_000,
  expect: { timeout: 8_000 },

  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    // e2e uses a self-signed nip.io cert
    ignoreHTTPSErrors: true,
  },

  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'mobile',
      use: { ...devices['iPhone 13'] },
      grep: /@mobile/,
    },
  ],
});
