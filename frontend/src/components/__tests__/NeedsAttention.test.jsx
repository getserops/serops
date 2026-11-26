import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
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
    affected_services: ['catalog', 'web'],
  };
  const rows = (container) => [...container.querySelectorAll('article.glance-issue')];

  // 1.5.6: the three issues in the same shape, a warning included.
  it('shows every open issue in the same shape, worst first', () => {
    queryResult.data = { results: [issue(LONG), issue({ id: 12, severity: 'CRITICAL', description: 'Redis is full.' }),
      issue({ id: 13, severity: 'WARNING', description: 'Cache cold.' })], pagination: { total_issues: 5 } };
    const { container } = renderIt();
    const all = rows(container);
    expect(all).toHaveLength(3);
    for (const row of all) {
      expect(within(row).getByText('dashboard.glance.whatIsBroken')).toBeTruthy();
      expect(within(row).getByText('dashboard.attention.why')).toBeTruthy();
      expect(within(row).getByText('dashboard.glance.firstStep')).toBeTruthy();
      expect(within(row).getByRole('link', { name: 'dashboard.attention.openIssue' })).toBeTruthy();
    }
    expect(all[2].className).toContain('glance-issue-warning');
    expect(within(all[0]).getByRole('link', { name: 'dashboard.attention.openIssue' }).className).toContain('ds-btn-primary');
    expect(within(all[1]).getByRole('link', { name: 'dashboard.attention.openIssue' }).className).toContain('ds-btn-secondary');
    expect(screen.getByText(/dashboard.attention.viewOpen:5/).closest('a').getAttribute('href')).toBe('/dash/issues?status=OPEN');
  });

  it('who: severity, service, also affects, project and environment', () => {
    queryResult.data = { results: [issue(LONG)], pagination: { total_issues: 1 } };
    const { container } = renderIt();
    const who = container.querySelector('.glance-issue-who');
    expect(who.textContent).toContain('backend-api');
    expect(who.textContent).toContain('issues.panel.alsoAffects');
    expect(who.textContent).toContain('acme · production');
  });

  it('what is broken: the headline, cut at a word boundary, the whole text in the tooltip', () => {
    queryResult.data = { results: [issue(LONG)], pagination: { total_issues: 1 } };
    renderIt();
    const headline = screen.getByText(/^Since the pricing rollout/);
    expect(headline.textContent).toBe('Since the pricing rollout at 00:24:45, every /price call for SKU-1001 fails with decimal.InvalidOperation…');
    expect(headline.className).toContain('glance-clamp-2');
    expect(headline.getAttribute('href')).toBe('/dash/issues?id=11');
    expect(headline.getAttribute('title')).toBe(LONG.description);
    expect(screen.queryByText(/pricing returns HTTP 500/)).toBeNull();
  });

  it('why: the first sentence of the root cause, held to three lines', () => {
    queryResult.data = { results: [issue(LONG)], pagination: { total_issues: 1 } };
    renderIt();
    const why = screen.getByText(/^The pricing service started failing/);
    expect(why.textContent).toBe('The pricing service started failing in its price-rounding code (app.py line 78) as soon as the new version went live.');
    expect(why.className).toContain('glance-clamp-3');
    expect(screen.queryByText(/Commit c9cabe46/)).toBeNull();
  });

  it('the first step, and how many more the issue holds', () => {
    queryResult.data = { results: [issue(LONG)], pagination: { total_issues: 1 } };
    renderIt();
    expect(screen.getByText('Roll back pricing to the version before the 00:24:45 rollout (the pre-c9cabe46 build) to restore /price.')).toBeTruthy();
    expect(screen.getByText('dashboard.glance.moreSteps:3')).toBeTruthy();
  });

  it('a one-step action has no "more steps"; no action, no step; no cause, no why', () => {
    queryResult.data = { results: [issue(), issue({ id: 12, recommendation: '', root_cause: '' })], pagination: { total_issues: 2 } };
    const { container } = renderIt();
    const [one, bare] = rows(container);
    expect(within(one).getByText('Move it to a replica.')).toBeTruthy();
    expect(within(one).queryByText(/moreSteps/)).toBeNull();
    expect(within(bare).queryByText('dashboard.glance.firstStep')).toBeNull();
    expect(within(bare).queryByText('dashboard.attention.why')).toBeNull();
  });

  // Session A is making the AI's text shorter: an action written as a
  // numbered list gives its first item as the first step.
  it('a short text with a numbered action', () => {
    queryResult.data = { results: [issue({ root_cause: 'The pool shrank to 20. Workers wait.',
      recommendation: '1. Raise the pool to 50.\n2. Restart the worker.\n3. Watch the wait time.' })], pagination: { total_issues: 1 } };
    renderIt();
    expect(screen.getByText('The pool shrank to 20.')).toBeTruthy();
    expect(screen.getByText('Raise the pool to 50.')).toBeTruthy();
    expect(screen.getByText('dashboard.glance.moreSteps:2')).toBeTruthy();
  });

  it('each Open issue button is described by its headline', () => {
    queryResult.data = { results: [issue()], pagination: { total_issues: 1 } };
    renderIt();
    const open = screen.getByRole('link', { name: 'dashboard.attention.openIssue' });
    expect(document.getElementById(open.getAttribute('aria-describedby')).textContent).toBe('Checkout writes blocked');
  });
});
