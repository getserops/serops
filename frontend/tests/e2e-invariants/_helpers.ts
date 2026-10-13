/**
 * Shared helpers for the UI-invariant gauntlet.
 *
 * Login flow: hit ``/api/auth/login`` for a Knox token, then seed
 * ``localStorage.token`` before navigating. Same shape the frontend
 * uses (``api-client.js`` sends ``Authorization: Token <t>`` from
 * ``localStorage.token``).
 */
import type { Page, APIRequestContext, ConsoleMessage, Request } from '@playwright/test';

export const CONFIG = {
  baseURL: process.env.GAUNTLET_BASE_URL || 'https://localhost',
  user: process.env.GAUNTLET_USER || 'gauntlet@serops.internal',
  password: process.env.GAUNTLET_PWD || 'Gauntlet-Str0ngP4ss-2026',
};

export interface LoginBundle {
  token: string;
  user: Record<string, unknown>;
}

/**
 * Log in via the API and return the Knox token + user record. Fails
 * the test if the login endpoint returns anything other than 200.
 */
export async function login(request: APIRequestContext): Promise<LoginBundle> {
  const r = await request.post(`${CONFIG.baseURL}/api/auth/login`, {
    data: { email: CONFIG.user, password: CONFIG.password },
    headers: { 'Content-Type': 'application/json' },
  });
  if (r.status() !== 200) {
    throw new Error(
      `Gauntlet login failed (${r.status()}) for ${CONFIG.user}. ` +
      `Provision the user via backend/tests_gauntlet/README.md — ` +
      `body: ${(await r.text()).slice(0, 200)}`,
    );
  }
  const body = await r.json();
  if (!body.token) throw new Error('Login response missing "token"');
  return { token: body.token as string, user: (body.user || {}) as Record<string, unknown> };
}

/**
 * Seed the auth token AND the user record into localStorage, then
 * navigate to ``path``. Combines Playwright's addInitScript pattern
 * with a first-visit navigation so subsequent goto()s carry both.
 *
 * Accepts either a bare token string (legacy call sites) or a
 * ``LoginBundle`` — passing the bundle lets the Sidebar render the
 * org name from the same shape ``Login.jsx`` stores after a real
 * login, avoiding the "NO ORGANISATION" placeholder we saw during
 * the 2026-09-20 UI review.
 */
export async function loginAndGoto(
  page: Page,
  auth: string | LoginBundle,
  path: string,
): Promise<void> {
  const bundle: LoginBundle = typeof auth === 'string'
    ? { token: auth, user: {} }
    : auth;
  await page.addInitScript((b) => {
    try {
      window.localStorage.setItem('token', (b as LoginBundle).token);
      window.localStorage.setItem('user', JSON.stringify((b as LoginBundle).user || {}));
    } catch {}
  }, bundle);
  await page.goto(path);
}

/**
 * Attach console + response listeners that record every error-shaped
 * event. Callers assert on the returned arrays after the test body.
 *
 * "Error shaped" excludes:
 *   - non-error console levels (info/log/debug)
 *   - 3xx / 4xx / 5xx to assets we deliberately probe (favicons, /health)
 */
export function watchForErrors(page: Page) {
  const consoleErrors: string[] = [];
  const badResponses: string[] = [];

  page.on('console', (msg: ConsoleMessage) => {
    if (msg.type() === 'error') {
      // Filter React devtools warning and known-benign source-map noise
      const text = msg.text();
      if (/react-devtools|source ?map/i.test(text)) return;
      consoleErrors.push(text);
    }
  });

  page.on('response', (resp) => {
    const status = resp.status();
    const url = resp.url();
    if (status < 400) return;
    // Ignore 4xx on optional endpoints the app tolerates
    if (/\/(favicon|robots\.txt|apple-touch-icon)/.test(url)) return;
    // A 401 on demo-login is expected (demo mode disabled)
    if (status === 401 && /demo-login/.test(url)) return;
    // 404s on onboarding status when not-yet-onboarded are informational
    badResponses.push(`${status} ${url}`);
  });

  page.on('pageerror', (err) => {
    consoleErrors.push(`pageerror: ${err.message}`);
  });

  return { consoleErrors, badResponses };
}

/**
 * Return every visible text run on the page as one flattened string.
 * Used by invariants that assert on rendered content (e.g. no
 * ``[object Object]`` slipping through).
 */
export async function visibleText(page: Page): Promise<string> {
  return page.evaluate(() => (document.body?.innerText || '').trim());
}
