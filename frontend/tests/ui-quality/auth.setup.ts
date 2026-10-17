import { test as setup } from '@playwright/test';

// Sign in once as the seeded read-only demo user; every test reuses it.
setup('sign in as the demo user', async ({ page }) => {
  await page.goto('/login');
  await page.getByRole('button', { name: /Try the live demo/ }).click();
  await page.waitForURL(/\/dash/);
  await page.context().storageState({ path: 'tests/ui-quality/.auth/demo.json' });
});
