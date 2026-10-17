import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
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
});
