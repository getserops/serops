import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import en from '../../locales/en.json';
import fr from '../../locales/fr.json';

// Phone and tablet rework (work order of 22 Nov 2026, items A2, A3, A7, A9),
// checked in the source: the layouts themselves are measured in a browser
// by the UI-quality suite.
const read = (file) => fs.readFileSync(path.resolve(__dirname, '..', file), 'utf8');
const phone = (css) => css.split('@media (max-width: 767px)').slice(1).join('\n');

describe('A2: the first screen on a phone', () => {
  const dash = read('Dashboard.css');

  it('puts the demo banner on one line, the rest behind "More"', () => {
    expect(phone(dash)).toMatch(/\.demo-banner:not\(\.is-expanded\) \.demo-banner-text \{[^}]*white-space: nowrap/);
    expect(phone(dash)).toContain('.demo-banner:not(.is-expanded) .demo-banner-selfhost { display: none; }');
    expect(dash).toMatch(/^\.demo-banner-more \{ display: none; \}/m);
  });

  it('keeps the top bar in one row, the pickers behind one button', () => {
    expect(phone(dash)).toMatch(/\.app-topbar \{ flex-wrap: nowrap;/);
    expect(phone(dash)).toContain('.app-topbar-pickers { display: none; }');
    expect(dash).toMatch(/^\.app-topbar-pickers \{ display: contents; \}/m);
    expect(dash).toMatch(/^\.app-topbar-filters \{ display: none; \}/m);
    const navbar = read('Navbar.jsx');
    expect(navbar).toContain("aria-label={t('nav.filters')}");
    expect(navbar).toContain('aria-expanded={pickersOpen}');
  });

  it('drops the subtitle of the page header and shortens the settings note', () => {
    expect(phone(read('../styles/design.css'))).toContain('.page-header-subtitle { display: none; }');
    expect(phone(read('settings/SettingsLayout.css'))).toMatch(/\.settings-readonly-notice:not\(\.is-expanded\) \{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; \}/);
  });

  it('has its new labels in English and French', () => {
    for (const [a, b] of [[en.demo.banner.more, fr.demo.banner.more], [en.demo.banner.less, fr.demo.banner.less], [en.nav.filters, fr.nav.filters],
      [en.dashboard.panel.show, fr.dashboard.panel.show], [en.dashboard.panel.hide, fr.dashboard.panel.hide], [en.data.details, fr.data.details]]) {
      expect(a).toBeTruthy();
      expect(b).toBeTruthy();
    }
    expect(fr.dashboard.panel.show).toContain('{{title}}');
  });
});

describe('A3: the top bar stays in place on a phone and a tablet', () => {
  it('does not make the main pane a scroll container up to 860 px', () => {
    const block = read('Dashboard.css').split('@media (max-width: 860px)').pop();
    expect(block).toContain('.dashboard-main { overflow-x: clip; }');
    expect(block).toMatch(/html \{ scroll-padding-top: calc\(var\(--topbar-real-h, var\(--topbar-h\)\)/);
  });
});

describe('A7: tap targets on touch devices', () => {
  const css = read('../styles/primitives.css');
  // The two touch blocks sit just before the .ds-input rule.
  const coarse = css.slice(css.indexOf('@media (pointer: coarse)'), css.indexOf('\n.ds-input {'));

  it('defines the two sizes once, as tokens', () => {
    const tokens = read('../styles/design.css');
    expect(tokens).toMatch(/--tap-min: 44px;/);
    expect(tokens).toMatch(/--tap-floor: 24px;/);
    expect(coarse).not.toMatch(/\b44px|\b24px/);
  });

  it('makes buttons, menu rows, tabs, fields and row actions 44 px high in the shared styles', () => {
    for (const selector of ['.ds-btn', '.btn', '.dropdown-item', '.app-nav-item', '.nav-link', '[role="tab"]', '.form-select', '.ds-input', '.tap-target', '.app-topbar-icon', '.app-picker-toggle']) {
      expect(coarse).toContain(selector);
    }
    expect((coarse.match(/min-height: var\(--tap-min\)/g) || []).length).toBeGreaterThanOrEqual(4);
    // A link of the onboarding window (MUI) stood alone at 16 px high.
    expect(coarse).toContain('.MuiLink-root');
  });

  it('never applies to a mouse: every rule sits under (pointer: coarse)', () => {
    expect(css.split('@media (pointer: coarse)')[0]).not.toContain('--tap-min');
  });
});

describe('A9: an analysis is a compact card on a phone', () => {
  it('keeps the identifier and the Sentinel decision behind "Details"', () => {
    const css = phone(read('Data.css'));
    expect(css).toMatch(/\.data-compact tr\.data-row > :is\(\.data-cell-id, \.data-cell-sentinel\) \{ order: 9; display: none;/);
    expect(css).toContain('.data-compact tr.data-row.is-expanded > :is(.data-cell-id, .data-cell-sentinel) { display: block;');
    const data = read('Data.jsx');
    expect(data).toContain("aria-expanded={expandedRows.has(item.id)}");
    expect(data).toContain("{t('data.details')}");
  });

  it('hides the Details button above a phone and adds no column to the table', () => {
    expect(read('Data.css')).toMatch(/^\.data-row-more \{ display: none !important; \}/m);
    expect(read('Data.jsx')).not.toContain('data-cell-more');
  });
});
