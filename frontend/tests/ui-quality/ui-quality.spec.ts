import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { PAGES } from './pages';

const open = async (page: Page, path: string, theme: 'light' | 'dark' = 'light') => {
  await page.addInitScript((t) => {
    localStorage.setItem('seropsSettings', JSON.stringify({ theme: t }));
  }, theme);
  await page.goto(path);
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {});
  // Charts and lazy panels settle after the last request.
  await page.waitForTimeout(800);
};

// WCAG 2 A/AA, light and dark: no serious or critical violation anywhere.
for (const theme of ['light', 'dark'] as const) {
  test.describe(`accessibility (${theme})`, () => {
    for (const [name, path] of PAGES) {
      test(`${name}`, async ({ page }, info) => {
        await open(page, path, theme);
        const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
        const blocking = violations
          .filter((v) => v.impact === 'serious' || v.impact === 'critical')
          .map((v) => `${v.id} (${v.impact}): ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`);
        await info.attach(`${name}-${theme}.png`, { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });
        expect(blocking, `axe violations on ${path} (${theme})`).toEqual([]);
      });
    }
  });
}

// Phones: nothing pushes the page wider than the screen.
test.describe('phone layout', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  for (const [name, path] of PAGES) {
    test(`${name}`, async ({ page }, info) => {
      await open(page, path);
      const width = await page.evaluate(() => document.documentElement.scrollWidth);
      await info.attach(`${name}-phone.png`, { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });
      expect(width, `page width on ${path}`).toBeLessThanOrEqual(390);
    });
  }
});

// A table sits flush with the search / filter row above it in the same card.
test.describe('table alignment', () => {
  for (const [name, path] of PAGES) {
    test(`${name}`, async ({ page }) => {
      await open(page, path);
      const misaligned = await page.evaluate(() => {
        const vis = (el: Element) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 40 && r.height > 8 && s.visibility !== 'hidden' && s.display !== 'none'; };
        const CARD = '.ds-card, .card, .chart-card, .issues-page-card, .settings-section, .data-page-container';
        const out: string[] = [];
        for (const card of Array.from(document.querySelectorAll(CARD)).filter(vis)) {
          const cw = card.getBoundingClientRect().width;
          const inCard = (el: Element) => vis(el) && el.closest(CARD) === card;
          const tables = Array.from(card.querySelectorAll('table')).filter((t) => inCard(t) && t.getBoundingClientRect().width > cw * 0.5);
          const bars = Array.from(card.querySelectorAll('input[type=search], input[placeholder*="earch"], .issues-toolbar, [class*=toolbar], [class*=search], [class*=filter-bar], [class*=filters]')).filter(inCard);
          for (const t of tables) {
            const tb = t.getBoundingClientRect();
            for (const bar of bars) {
              let row: Element = bar;
              while (row.parentElement && row.parentElement !== card && row.parentElement.getBoundingClientRect().width <= tb.width + 60) row = row.parentElement;
              const rb = row.getBoundingClientRect();
              if (rb.bottom > tb.top + 4) continue;
              const dl = Math.round(tb.left - rb.left), dr = Math.round(rb.right - tb.right);
              const off = (d: number) => Math.abs(d) >= 2 && Math.abs(d) <= 48;
              if (off(dl) || off(dr)) out.push(`table is ${dl}px/${dr}px inside "${(row.textContent || '').trim().slice(0, 30)}"`);
            }
          }
        }
        return Array.from(new Set(out));
      });
      expect(misaligned, `misaligned tables on ${path}`).toEqual([]);
    });
  }
});
