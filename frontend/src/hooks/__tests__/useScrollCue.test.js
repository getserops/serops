import { describe, it, expect } from 'vitest';
import { scrollPosition } from '../useScrollCue';

// A10: a table that scrolls sideways shows on which side more columns are.
describe('scrollPosition', () => {
  it('is "none" when everything fits', () => {
    expect(scrollPosition({ scrollLeft: 0, scrollWidth: 702, clientWidth: 702 })).toBe('none');
  });
  it('is "start", "middle" then "end" as the table is scrolled', () => {
    expect(scrollPosition({ scrollLeft: 0, scrollWidth: 1042, clientWidth: 702 })).toBe('start');
    expect(scrollPosition({ scrollLeft: 120, scrollWidth: 1042, clientWidth: 702 })).toBe('middle');
    expect(scrollPosition({ scrollLeft: 340, scrollWidth: 1042, clientWidth: 702 })).toBe('end');
  });
});
