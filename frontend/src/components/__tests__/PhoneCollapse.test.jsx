import React from 'react';
import fs from 'node:fs';
import path from 'node:path';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import PhoneCollapse from '../PhoneCollapse';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key, opts) => `${key} ${opts?.title || ''}`.trim() }) }));

// A4: on a phone the Overview stacked every panel, 4,837 px. The panels
// under the recent analyses are reduced to their header.
const Panel = () => (
  <div className="chart-card"><div className="chart-header"><h2>7-day trend</h2></div><div className="chart-container">chart</div></div>
);

describe('PhoneCollapse', () => {
  it('renders the panel as it is anywhere but on a phone', () => {
    const { container } = render(<PhoneCollapse phone={false} title="7-day trend"><Panel /></PhoneCollapse>);
    expect(container.firstChild.className).toBe('chart-card');
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('is collapsed on a phone and opens on a tap', () => {
    const { container } = render(<PhoneCollapse phone title="7-day trend"><Panel /></PhoneCollapse>);
    const button = screen.getByRole('button', { name: 'dashboard.panel.show 7-day trend' });
    expect(button.getAttribute('aria-expanded')).toBe('false');
    expect(container.firstChild.className).toContain('is-collapsed');
    fireEvent.click(button);
    expect(container.firstChild.className).toContain('is-open');
    expect(screen.getByRole('button', { name: 'dashboard.panel.hide 7-day trend' }).getAttribute('aria-expanded')).toBe('true');
  });

  it('keeps the header and hides the rest while collapsed, in the stylesheet', () => {
    const css = fs.readFileSync(path.resolve(__dirname, '../Dashboard.css'), 'utf8');
    expect(css).toContain('.phone-collapse.is-collapsed .chart-card > :not(.chart-header) { display: none; }');
    expect(css).toMatch(/@media \(max-width: 767px\) \{\s*\.heatmap-grid \{ grid-template-columns: minmax\(0, 1fr\); gap: 0; \}/);
  });

  // 1.5.6: as in 1.5.5, the panels below "Needs attention now" are reduced
  // to their header on a phone; the status card and the open issues stay open.
  it('wraps the lower panels on the Overview, not the status or the open issues', () => {
    const src = fs.readFileSync(path.resolve(__dirname, '../Dashboard.jsx'), 'utf8');
    expect((src.match(/<PhoneCollapse phone=\{isPhone\}/g) || []).length).toBe(5);
    for (const panel of ['ServicesPanel', 'AIAnalysisFeed', 'RecentDeploymentsCard', 'TrendAnalysisChart', 'CausesBar']) {
      expect(src).toMatch(new RegExp(`<PhoneCollapse[^>]*>\\s*<${panel}`));
    }
    expect(src).not.toMatch(/<PhoneCollapse[^>]*>\s*<(StatusCard|NeedsAttention)/);
  });

  it('a glance panel keeps its title and summary while collapsed, in the stylesheet', () => {
    const css = fs.readFileSync(path.resolve(__dirname, '../overview/Overview.css'), 'utf8');
    expect(css).toContain('.phone-collapse.is-collapsed .glance-panel > :not(.glance-panel-title):not(.glance-panel-sub) { display: none; }');
  });
});
