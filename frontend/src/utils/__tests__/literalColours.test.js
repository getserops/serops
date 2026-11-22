import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { countColours, compare, scan, BASELINE } from '../../../scripts/check-literal-colours.mjs';

// Guard rail of the design review (item 27): a new literal colour fails the
// lint; the ones that were there when the rule arrived are in a baseline.
describe('literal colour check', () => {
  it('counts hex, rgb and hsl colours', () => {
    expect(countColours('a { color: #fff; background: #1F2333; border-color: #1f233380 }')).toBe(3);
    expect(countColours("style={{ color: 'rgba(0, 0, 0, 0.5)', background: 'hsl(230, 15%, 22%)' }}")).toBe(2);
  });

  it('does not count tokens, ids, anchors or issue numbers', () => {
    expect(countColours('a { color: var(--text-primary); background: var(--tone-red-soft) }')).toBe(0);
    expect(countColours('<a href="#main-content">#{issue.id}</a> #root #add-button')).toBe(0);
  });

  it('a file may hold fewer literals than its baseline, never more; a new file none', () => {
    const baseline = { 'a.css': 2, 'b.css': 5 };
    expect(compare({ 'a.css': 2, 'b.css': 3 }, baseline)).toEqual({ over: [], under: [{ file: 'b.css', allowed: 5, found: 3 }] });
    expect(compare({ 'a.css': 3, 'b.css': 5 }, baseline).over).toEqual([{ file: 'a.css', allowed: 2, found: 3 }]);
    expect(compare({ 'a.css': 2, 'b.css': 5, 'new.jsx': 1 }, baseline).over).toEqual([{ file: 'new.jsx', allowed: 0, found: 1 }]);
  });

  it('the source tree has no literal colour beyond the baseline', () => {
    const baseline = JSON.parse(readFileSync(BASELINE, 'utf8'));
    expect(compare(scan(), baseline).over).toEqual([]);
  });

  it('the files this review wrote hold none', () => {
    const counts = scan();
    for (const file of ['utils/tones.js', 'utils/dates.js', 'components/CorrelationStrip.jsx', 'components/ServiceHealthHeatmap.jsx',
      'components/NeedsAttention.css']) expect(counts[file]).toBeUndefined();
  });
});
