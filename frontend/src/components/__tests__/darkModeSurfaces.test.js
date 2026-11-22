import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Review item 5: surfaces that stayed white in the dark theme. The timeline
// chart drew its lanes, marker outlines and axis with literal light colours,
// and the page buttons of Analyses and Issues had a white background. They
// take the theme's tokens now; this keeps a literal from coming back.
const read = (file) => readFileSync(resolve(__dirname, '..', file), 'utf8');

describe('dark mode surfaces use tokens', () => {
  it('timeline chart: no literal white or light grey for lanes, outlines and axis', () => {
    const src = read('BatchTimelineChart.jsx');
    for (const literal of ['#fff', '#ffffff', '#f8f9fa', '#e9ecef', '#dee2e6', '#ced4da']) {
      expect(src.toLowerCase()).not.toContain(`'${literal}'`);
      expect(src.toLowerCase()).not.toContain(`"${literal}"`);
      expect(src.toLowerCase()).not.toContain(`, ${literal})`);
    }
    expect(src).toContain("'var(--bg-sunken)' : 'var(--bg-card)'");
  });

  it.each(['Data.css', 'Issues.css'])('%s: page buttons sit on the card colour, not on white', (file) => {
    const css = read(file);
    const rule = /\.page-btn\s*\{[^}]*\}/.exec(css)[0];
    expect(rule).toContain('background: var(--bg-card)');
    expect(rule).not.toMatch(/background:\s*(white|#fff)/i);
  });
});
