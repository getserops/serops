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

// Inside a card, the first table column starts on the same line as the
// card's own text: its title, tabs, captions and the "Showing 1-2 of 2"
// footer. Catches a table padded twice, or a footer flush with the edge.
test.describe('table inset', () => {
  for (const [name, path] of PAGES) {
    test(`${name}`, async ({ page }) => {
      await open(page, path);
      const drifts = await page.evaluate(() => {
        const vis = (el: Element) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 4 && r.height > 4 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0'; };
        const textLeft = (el: Element) => {
          const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, { acceptNode: (n) => (n.textContent || '').trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP });
          const n = w.nextNode(); if (!n) return null;
          const r = document.createRange(); r.selectNodeContents(n); const b = r.getBoundingClientRect();
          return b.width ? b.left : null;
        };
        const CARD = '.ds-card, .card, .ds-section, .ds-settings-section, .settings-card, .data-card, .issues-page-card, .notification-card';
        const out: string[] = [];
        for (const card of Array.from(document.querySelectorAll(CARD)).filter(vis)) {
          const cb = card.getBoundingClientRect();
          const table = Array.from(card.querySelectorAll('table')).find((t) => vis(t) && t.closest(CARD) === card && t.getBoundingClientRect().width > cb.width * 0.6);
          const cell = table && (table.querySelector('tbody tr td') || table.querySelector('thead th'));
          if (!cell) continue;
          // Where the first column's content box starts (an avatar or icon
          // inside the cell starts there too).
          const ref = cell.getBoundingClientRect().left + parseFloat(getComputedStyle(cell).paddingLeft);
          const texts = Array.from(card.querySelectorAll('h1,h2,h3,h4,h5,h6,p,small,label,li,span,div,a'))
            .filter((el) => vis(el) && !el.closest('table, .dropdown-menu, .modal, .pagination, button') && el.closest(CARD) === card)
            .filter((el) => Array.from(el.childNodes).some((c) => c.nodeType === 3 && (c.textContent || '').trim()));
          for (const el of texts) {
            const x = textLeft(el);
            if (x == null || x - cb.left > 90) continue; // only text on the left edge
            const d = Math.round(x - ref);
            if (Math.abs(d) >= 3 && Math.abs(d) <= 40) out.push(`"${(el.textContent || '').trim().slice(0, 30)}" starts ${d}px from the first column`);
          }
        }
        return Array.from(new Set(out));
      });
      expect(drifts, `text off the table's first column on ${path}`).toEqual([]);
    });
  }
});

// A column header fits its column: header text spilling past its cell (a
// fixed width too narrow for the label) reads as misaligned with the
// cells below it.
test.describe('table headers fit', () => {
  for (const [name, path] of PAGES) {
    test(`${name}`, async ({ page }) => {
      await open(page, path);
      const overflowing = await page.evaluate(() =>
        Array.from(document.querySelectorAll('thead th'))
          .filter((th) => {
            const r = th.getBoundingClientRect();
            if (r.width === 0 || getComputedStyle(th).display === 'none') return false;
            const range = document.createRange();
            range.selectNodeContents(th);
            const text = range.getBoundingClientRect();
            return text.width > 0 && (text.left < r.left - 1 || text.right > r.right + 1);
          })
          .map((th) => `"${(th.textContent || '').trim()}" is wider than its column`),
      );
      expect(overflowing, `table headers overflowing on ${path}`).toEqual([]);
    });
  }
});

// On a wide screen the page and the top bar share the same edges: the page
// header starts under the Env picker and ends under the avatar.
test.describe('top bar lines up with the page (1920 px)', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });
  for (const [name, path] of PAGES) {
    test(`${name}`, async ({ page }) => {
      await open(page, path);
      const edges = await page.evaluate(() => {
        const box = (sel: string) => document.querySelector(sel)?.getBoundingClientRect();
        const picker = box('.app-topbar .app-picker-toggle');
        const user = box('.app-topbar-user');
        const header = box('.page-header');
        if (!picker || !user || !header) return null;
        return { left: Math.round(picker.left - header.left), right: Math.round(user.right - header.right) };
      });
      test.skip(edges === null, 'page has no standard page header');
      expect(Math.abs(edges!.left), `top bar starts ${edges!.left}px from the page header on ${path}`).toBeLessThanOrEqual(1);
      expect(Math.abs(edges!.right), `top bar ends ${edges!.right}px from the page header on ${path}`).toBeLessThanOrEqual(1);
    });
  }
});

// Every column's cells line up with its header, following the header's own
// alignment: left edges, right edges or centres. Pills, buttons and inputs
// count by their visible box, not the text inside them.
test.describe('table columns line up with their header', () => {
  for (const [name, path] of PAGES) {
    test(`${name}`, async ({ page }) => {
      await open(page, path);
      const misaligned = await page.evaluate(() => {
        const vis = (el: Element) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
        const extent = (cell: Element) => {
          let l = Infinity, r = -Infinity;
          const add = (b: DOMRect) => { if (b.width > 0 && b.height > 0) { l = Math.min(l, b.left); r = Math.max(r, b.right); } };
          const w = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
          let n: Node | null;
          while ((n = w.nextNode())) {
            if (!(n.textContent || '').trim() || !n.parentElement || !vis(n.parentElement)) continue;
            const rg = document.createRange(); rg.selectNodeContents(n);
            for (const b of Array.from(rg.getClientRects())) add(b);
          }
          for (const el of Array.from(cell.querySelectorAll('*'))) {
            if (!vis(el)) continue;
            const cs = getComputedStyle(el);
            const boxed = (cs.backgroundColor !== 'rgba(0, 0, 0, 0)' && cs.backgroundColor !== 'transparent')
              || parseFloat(cs.borderLeftWidth) > 0 || /^(svg|img|input|select|button|textarea)$/i.test(el.tagName);
            if (boxed) add(el.getBoundingClientRect());
          }
          return l === Infinity ? null : { l, r, c: (l + r) / 2 };
        };
        const out: string[] = [];
        for (const table of Array.from(document.querySelectorAll('table')).filter(vis)) {
          const heads = Array.from(table.querySelectorAll('thead tr:last-child th'));
          const rows = Array.from(table.querySelectorAll('tbody tr')).filter(vis).filter((tr) => tr.children.length === heads.length).slice(0, 8);
          if (!heads.length || !rows.length) continue;
          heads.forEach((th, i) => {
            const h = extent(th); if (!h) return;
            const ta = getComputedStyle(th).textAlign;
            const mode = /right|end/.test(ta) ? 'r' : ta === 'center' ? 'c' : 'l';
            let bad = 0, seen = 0, worst = 0;
            for (const tr of rows) {
              const e = extent(tr.children[i]); if (!e) continue; seen++;
              const d = mode === 'l' ? e.l - h.l : mode === 'r' ? e.r - h.r : e.c - h.c;
              if (Math.abs(d) > (mode === 'c' ? 4 : 3)) { bad++; if (Math.abs(d) > Math.abs(worst)) worst = d; }
            }
            if (seen && bad / seen >= 0.5) out.push(`"${(th.textContent || '').trim()}": cells ${Math.round(worst)}px off the header`);
          });
        }
        return Array.from(new Set(out));
      });
      expect(misaligned, `columns off their header on ${path}`).toEqual([]);
    });
  }
});
