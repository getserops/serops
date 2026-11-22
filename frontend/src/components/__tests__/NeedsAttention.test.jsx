import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

let queryResult;
vi.mock('@tanstack/react-query', () => ({ useQuery: () => queryResult }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k, o) => (o && o.count != null ? `${k}:${o.count}` : k) }) }));
vi.mock('../../services/data.service', () => ({ default: { getIssues: vi.fn() } }));
vi.mock('../../utils/demo', () => ({ isDemoUser: () => false }));

import NeedsAttention from '../NeedsAttention';

const issue = (over) => ({
  id: 11, severity: 'CRITICAL', description: 'Checkout writes blocked', component: 'backend-api',
  environment: 'production', project: 3, project_name: 'acme', batch_id_str: 'b-1',
  root_cause: 'Row lock held by the monthly aggregate.', recommendation: 'Move it to a replica.',
  created_at: new Date().toISOString(), last_seen_at: new Date().toISOString(), ...over,
});

const renderIt = () => render(<MemoryRouter><NeedsAttention environment="all" clusterId={null} /></MemoryRouter>);

describe('NeedsAttention', () => {
  beforeEach(() => { queryResult = { isLoading: false, data: null }; });

  it('leads with the most severe open issue, its cause and the fix', () => {
    queryResult.data = { results: [issue(), issue({ id: 12, severity: 'WARNING', description: 'Cache cold' })], pagination: { total_issues: 5 } };
    renderIt();
    expect(screen.getByText('Checkout writes blocked').getAttribute('href')).toBe('/dash/issues?id=11');
    expect(screen.getByText('Row lock held by the monthly aggregate.')).toBeTruthy();
    expect(screen.getByText('Move it to a replica.')).toBeTruthy();
    expect(screen.getByText('Cache cold')).toBeTruthy();
    expect(screen.getByText(/dashboard.attention.viewOpen:5/)).toBeTruthy();
    expect(screen.getByText('issues.panel.openAnalysis').closest('a').getAttribute('href')).toBe('/dash/data/details/b-1');
  });

  it('shows a warning-level issue as one line, without the cause and fix', () => {
    queryResult.data = { results: [issue({ severity: 'WARNING', description: 'Cache cold' })], pagination: { total_issues: 1 } };
    renderIt();
    expect(screen.getByText('Cache cold').getAttribute('href')).toBe('/dash/issues?id=11');
    expect(screen.queryByText('Row lock held by the monthly aggregate.')).toBeNull();
    expect(screen.queryByText('dashboard.attention.openIssue')).toBeNull();
  });

  it('says all clear when nothing is open', () => {
    queryResult.data = { results: [], pagination: { total_issues: 0 } };
    renderIt();
    expect(screen.getByText('dashboard.attention.allClear')).toBeTruthy();
  });
  // The stored texts are long (the demo's are 340 to 1,050 characters); the
  // card shows a part of each and never cuts inside a sentence.
  const LONG = {
    description: "Since the pricing rollout at 00:24:45, every /price call for SKU-1001 fails with decimal.InvalidOperation ('quantize result has too many digits for current context') in the rounding step. pricing returns HTTP 500 to catalog. Traces show 1293 error spans out of 2810.",
    root_cause: "The pricing service started failing in its price-rounding code (app.py line 78) as soon as the new version went live. Commit c9cabe46 was deployed to production at 00:24:29.",
    recommendation: "Roll back pricing to the version before the 00:24:45 rollout (the pre-c9cabe46 build) to restore /price. Then inspect pricing's rounding logic (app.py around line 78). Add a test for SKU-1001. Consider cached prices, e.g. for an hour, instead of returning 503.",
  };

  it('uses the first sentence of the description as the headline and keeps the whole text in the tooltip', () => {
    queryResult.data = { results: [issue(LONG)], pagination: { total_issues: 1 } };
    renderIt();
    const headline = screen.getByText(/^Since the pricing rollout/);
    expect(headline.textContent).toBe("Since the pricing rollout at 00:24:45, every /price call for SKU-1001 fails with decimal.InvalidOperation ('quantize result has too many digits for current context') in the rounding step.");
    expect(headline.className).toBe('attention-issue-title');
    expect(headline.getAttribute('title')).toBe(LONG.description);
    expect(screen.queryByText(/pricing returns HTTP 500/)).toBeNull();
  });

  it('lists "What to do" as numbered steps, three shown and the rest behind Show more', () => {
    queryResult.data = { results: [issue(LONG)], pagination: { total_issues: 1 } };
    const { container } = renderIt();
    const steps = () => [...container.querySelectorAll('ol.attention-steps li')].map((li) => li.textContent);
    expect(steps()).toEqual([
      'Roll back pricing to the version before the 00:24:45 rollout (the pre-c9cabe46 build) to restore /price.',
      "Then inspect pricing's rounding logic (app.py around line 78).",
      'Add a test for SKU-1001.',
    ]);
    const more = screen.getByRole('button', { name: 'dashboard.attention.showMore' });
    expect(more.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(more);
    expect(steps()).toHaveLength(4);
    expect(steps()[3]).toBe('Consider cached prices, e.g. for an hour, instead of returning 503.');
    fireEvent.click(screen.getByRole('button', { name: 'dashboard.attention.showLess' }));
    expect(steps()).toHaveLength(3);
  });

  it('shows three steps or fewer without a button, and one sentence as a paragraph', () => {
    queryResult.data = { results: [issue({ recommendation: 'Restore the limit. Confirm the pod is Ready.' })], pagination: { total_issues: 1 } };
    const { container, unmount } = renderIt();
    expect(container.querySelectorAll('ol.attention-steps li')).toHaveLength(2);
    expect(screen.queryByRole('button')).toBeNull();
    unmount();
    queryResult.data = { results: [issue()], pagination: { total_issues: 1 } };
    const again = renderIt();
    expect(again.container.querySelector('ol.attention-steps')).toBeNull();
    expect(screen.getByText('Move it to a replica.').tagName).toBe('P');
  });

  it('holds "Why it is happening" to three lines and offers Show more only when the text does not fit', () => {
    queryResult.data = { results: [issue(LONG)], pagination: { total_issues: 1 } };
    // jsdom has no layout: say that the paragraph is taller than its three lines.
    const scroll = vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(function () { return this.className === 'attention-clamp-3' ? 200 : 0; });
    const client = vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(function () { return this.className === 'attention-clamp-3' ? 66 : 0; });
    const { container, unmount } = renderIt();
    const why = screen.getByText(/^The pricing service started failing/);
    expect(why.textContent).toBe(LONG.root_cause);            // the whole text is in the page
    expect(why.className).toBe('attention-clamp-3');
    fireEvent.click(container.querySelector('.attention-grid > div:first-child .attention-more'));
    expect(screen.getByText(/^The pricing service started failing/).className).toBe('');
    expect(container.querySelector('.attention-grid > div:first-child .attention-more').textContent).toBe('dashboard.attention.showLess');
    unmount(); scroll.mockRestore(); client.mockRestore();
    const fits = renderIt();
    expect(fits.container.querySelector('.attention-grid > div:first-child .attention-more')).toBeNull();
  });

  it('shows the rows below, and a warning shown alone, as one whole first sentence', () => {
    const second = { id: 12, description: "fleet-redis was restarted with maxmemory cut from 128mb to 1mb and eviction set to noeviction. It now rejects writes with 'OOM command not allowed when used memory > maxmemory'." };
    queryResult.data = { results: [issue(), issue(second)], pagination: { total_issues: 2 } };
    const { unmount } = renderIt();
    const row = screen.getByText('fleet-redis was restarted with maxmemory cut from 128mb to 1mb and eviction set to noeviction.');
    expect(row.getAttribute('href')).toBe('/dash/issues?id=12');
    expect(row.getAttribute('title')).toBe(second.description);
    unmount();
    queryResult.data = { results: [issue({ ...second, severity: 'WARNING' })], pagination: { total_issues: 1 } };
    renderIt();
    expect(screen.getByText('fleet-redis was restarted with maxmemory cut from 128mb to 1mb and eviction set to noeviction.').className).toBe('attention-compact-title');
  });
});
