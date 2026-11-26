import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

// Final pass before 1.5.2: small layout and tone fixes that live in class
// names and style values, checked in the source.
const read = (file) => fs.readFileSync(path.resolve(__dirname, '..', file), 'utf8');

describe('final pass: layout and tone', () => {
  it('lets the head of a "Workloads by cluster" row wrap on a narrow screen', () => {
    expect(read('WorkloadsByCluster.jsx')).toMatch(/className="d-flex align-items-center flex-wrap[^"]*"/);
  });

  it('sizes the scope filters of Issues to their longest choice', () => {
    const rule = read('Issues.css').match(/^\.issues-scope-select \{[^}]*\}/m)[0];
    expect(rule).toContain('width: auto');
    expect(rule).not.toContain('width: 150px !important');
  });

  it('shows a service type as a neutral chip, never amber', () => {
    const source = read('serviceProjects.jsx');
    expect(source).not.toContain('bg-warning');
    expect(source).toContain('className="ds-chip ds-chip-neutral"');
  });

  it('draws span tracks from a token, for the dark theme', () => {
    expect(read('TraceDetail.jsx')).not.toContain('#f1f3f5');
    expect(read('Metrics.jsx')).not.toMatch(/trailColor: "#/);
  });

  it('gives the Investigate notice no colour of its own', () => {
    const rule = read('investigate/Investigate.css').match(/\.investigate-banner \{[^}]*\}/)[0];
    expect(rule).not.toMatch(/hsl\(|#[0-9a-f]{3}/i);
  });

  // At 375 px the provider's name broke one letter per line: three blocks
  // shared what the column name left of one line.
  it('stacks the AI Providers table with the column name above each cell on a phone', () => {
    expect(read('settings/AISettings.jsx')).toContain('className="table settings-table table-stack table-stack-block ai-providers-table"');
    const css = read('../styles/primitives.css');
    const rule = css.match(/\.table-stack\.table-stack-block td \{[^}]*\}/)[0];
    expect(rule).toContain('flex-direction: column');
    expect(rule).toContain('align-items: stretch');
    expect(css.indexOf('@media (max-width: 767px)')).toBeLessThan(css.indexOf(rule));
    expect(css).toMatch(/\.ai-provider-key-row \{ flex-wrap: wrap;/);
  });
});

// A6: 86 fields had text under 16 px on a phone or tablet.
describe('fields on touch devices', () => {
  const css = read('../styles/primitives.css');
  const rule = css.match(/@media \(pointer: coarse\) \{\s*:is\(input, select, textarea\)[^{]*\{[^}]*\}/)?.[0] || '';

  it('sets every text field, select and text area to 16 px, in one shared rule', () => {
    expect(rule).toContain('font-size: 16px !important');
    expect(rule).toMatch(/:not\(\[type="checkbox"\], \[type="radio"\]/);
  });

  it('leaves pinch zoom on', () => {
    const html = fs.readFileSync(path.resolve(__dirname, '../../../index.html'), 'utf8');
    const viewport = html.match(/<meta name="viewport"[^>]*>/)[0];
    expect(viewport).not.toMatch(/user-scalable|maximum-scale/);
  });
});

// A10: smaller phone and tablet items.
describe('phones and tablets: smaller items', () => {
  const css = read('../styles/primitives.css');

  it('has no text under 12 px on a phone or tablet', () => {
    expect(css).toMatch(/@media \(max-width: 1024px\) \{\s*:is\(html, :root\[data-theme\]\) :is\(\.app-nav-group-label, \.app-topbar-badge, \.feed-badge, \.feed-model, \.issue-affected-more\) \{ font-size: var\(--text-xs\); \}/);
  });

  it('marks the Analyses table as scrolling sideways and keeps its first two columns in place', () => {
    const data = read('Data.jsx');
    expect(data).toContain('<div className="ds-scroll-cue">');
    expect(data).toContain('useScrollCue(tableWrapRef)');
    expect(read('Data.css')).toMatch(/\.data-table-wrap \.modern-table :is\(th, td\):nth-child\(-n\+2\) \{ position: sticky;/);
    expect(css).toMatch(/\.ds-scroll-cue:has\(> \[data-scroll="start"\]\)::after/);
  });
});
