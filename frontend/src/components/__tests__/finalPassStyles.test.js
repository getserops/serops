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

  it('draws gauge and span tracks from a token, for the dark theme', () => {
    expect(read('TraceDetail.jsx')).not.toContain('#f1f3f5');
    expect(read('HealthScoreCard.jsx')).not.toContain('#e9ecef');
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
