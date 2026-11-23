import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { issuesTier, fixedWidth, MIN_DESCRIPTION, TIER_COLUMNS, OPTIONAL_COLUMNS } from '../issuesLayout';

// A1: fixed columns of 726 px in a 728 px card left the Description column
// 0 px wide (1024 px window), and at 768 px the Actions column lay outside
// the card. The list now picks its layout from the width of its own card.
describe('Issues list layout', () => {
  it('keeps every column at full width where Description still gets its minimum', () => {
    expect(issuesTier(1144)).toBe('full');   // 1440 px window, menu open
    expect(issuesTier(1070)).toBe('full');   // 1366 px
  });

  it('trims the columns at 1280 px, moves two under the description at 1024 px', () => {
    expect(issuesTier(984)).toBe('medium');  // 1280 px
    expect(issuesTier(728)).toBe('compact'); // 1024 px: was a 0 px Description
    expect(issuesTier(796)).toBe('compact'); // 860 px, menu closed
  });

  it('uses one card per issue where no table fits', () => {
    expect(issuesTier(704)).toBe('cards');   // 768 px
    expect(issuesTier(727)).toBe('cards');
    expect(issuesTier(604)).toBe('cards');   // 900 px, menu open
    expect(issuesTier(343)).toBe('cards');   // 375 px
  });

  it('never leaves Description under its minimum, whatever the width', () => {
    for (let width = 300; width <= 1600; width += 7) {
      const tier = issuesTier(width);
      if (tier !== 'cards') expect(width - fixedWidth(tier)).toBeGreaterThanOrEqual(MIN_DESCRIPTION);
    }
  });

  it('counts the columns a person switched on', () => {
    expect(issuesTier(1144, { age: true, correlations: true })).not.toBe('full');
    expect(fixedWidth('full', { id: true })).toBe(fixedWidth('full') + OPTIONAL_COLUMNS.id);
    expect(fixedWidth('full', { count: false })).toBe(fixedWidth('full') - TIER_COLUMNS.full.count);
  });

  it('shows the full table until the card is measured', () => {
    expect(issuesTier(null)).toBe('full');
  });

  it('has the same column widths as Issues.css', () => {
    const css = fs.readFileSync(path.resolve(__dirname, '../../components/Issues.css'), 'utf8');
    const width = (selector) => Number(css.match(new RegExp(`${selector.replace(/[.]/g, '\\.')}[^{}]*\\{ (?:max-)?width: (\\d+)px; \\}`))?.[1]);
    expect(width('.issues-table-wrap th.issue-col-component')).toBe(TIER_COLUMNS.full.component);
    expect(width('.issues-table-wrap th.issue-col-count')).toBe(TIER_COLUMNS.full.count);
    expect(width('.issues-table-wrap th.issue-col-seen, .issues-table-wrap th.issue-col-age')).toBe(TIER_COLUMNS.full.lastSeen);
    expect(width('.issues-table-wrap th.issue-col-severity')).toBe(TIER_COLUMNS.full.severity);
    expect(width('.issues-table-wrap th.issue-col-status')).toBe(TIER_COLUMNS.full.status);
    expect(Number(css.match(/^\.issue-col-actions \{ width: (\d+)px;/m)[1])).toBe(TIER_COLUMNS.full.actions);
    expect(width('.issues-table-wrap.issues-tier-medium th.issue-col-seen')).toBe(TIER_COLUMNS.medium.lastSeen);
    expect(width('.issues-table-wrap.issues-tier-medium th.issue-col-count')).toBe(TIER_COLUMNS.medium.count);
    expect(width('.issues-table-wrap.issues-tier-medium .issue-col-actions, .issues-table-wrap.issues-tier-compact .issue-col-actions')).toBe(TIER_COLUMNS.medium.actions);
    expect(width('.issues-table-wrap.issues-tier-medium th.issue-col-severity, .issues-table-wrap.issues-tier-compact th.issue-col-severity')).toBe(TIER_COLUMNS.medium.severity);
    expect(width('.issues-table-wrap.issues-tier-medium th.issue-col-status, .issues-table-wrap.issues-tier-compact th.issue-col-status')).toBe(TIER_COLUMNS.compact.status);
    expect(width('.issues-table-wrap.issues-tier-compact th.issue-col-component')).toBe(TIER_COLUMNS.compact.component);
    expect(TIER_COLUMNS.compact.actions).toBe(TIER_COLUMNS.medium.actions);
    expect(width('.issues-table-wrap th.issue-col-type')).toBe(OPTIONAL_COLUMNS.type);
    expect(OPTIONAL_COLUMNS.age).toBe(TIER_COLUMNS.full.lastSeen);
    expect(width('.issues-table-wrap th.issue-col-correlations')).toBe(OPTIONAL_COLUMNS.correlations);
  });

  it('does not let the card hide the overflow of its own table', () => {
    const css = fs.readFileSync(path.resolve(__dirname, '../../components/Issues.css'), 'utf8');
    expect(css.match(/^\.issues-page-card \{[^}]*\}/m)[0]).not.toContain('overflow');
  });
});
