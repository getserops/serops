import React from 'react';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// Structure review, section 3: the Overview has six panels, in this order:
// needs attention, three key numbers, recent analyses beside recent
// deployments, the 7-day trend beside the causes, service health.
const answers = {
  'issue-stats': [{ name: 'CRITICAL', value: 2 }, { name: 'WARNING', value: 1 }],
  'open-issue-count': { results: [{}], pagination: { total_issues: 5 } },
  'system-health': { health_score: 40, status: 'CRITICAL' },
  'recent-deployments': { services: [{ service_id: 1, latest_pipeline: { id: 'a1' } }] },
};
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key) => key }) }));
vi.mock('@tanstack/react-query', () => ({ useQuery: ({ queryKey }) => ({ data: answers[queryKey[0]], isLoading: false }) }));
vi.mock('@mui/material', () => ({ useMediaQuery: () => false }));
vi.mock('../../services/dash.service', () => ({ default: {} }));
vi.mock('../../services/data.service', () => ({ default: {} }));
vi.mock('../../context/ClusterContext', () => ({ useCluster: () => ({ currentCluster: null, loading: false, filter: {} }) }));
vi.mock('../../hooks/useFilterUrlSync', () => ({ default: () => {} }));
vi.mock('../../utils/permissions', () => ({ usePermissions: () => () => false }));
vi.mock('../Sidebar', () => ({ default: () => null }));
vi.mock('../Navbar', () => ({ default: () => null }));
vi.mock('../CommandPalette', () => ({ default: () => null }));
vi.mock('../DemoBanner', () => ({ default: () => null }));
vi.mock('../onboarding', () => ({ OnboardingWizard: () => null, OnboardingResumeChip: () => null }));
vi.mock('../PageHeader', () => ({ default: ({ title }) => <h1>{title}</h1> }));
const PANELS = ['NeedsAttention', 'HealthScoreCard', 'AIAnalysisFeed', 'RecentDeploymentsCard', 'TrendAnalysisChart',
  'RootCausePie', 'ServiceHealthHeatmap'];
const GONE = ['SentinelStatsCard', 'CorrelationInsightsCard', 'WorkloadsByCluster'];
for (const card of [...PANELS, ...GONE]) {
  vi.doMock(`../${card}`, () => ({ default: () => <div data-testid="panel">{card}</div> }));
}

const { default: Dashboard } = await import('../Dashboard');
const show = () => render(<MemoryRouter initialEntries={['/dash']}><Dashboard /></MemoryRouter>);

describe('Overview: six panels', () => {
  it('shows the panels in the decided order and nothing else', () => {
    show();
    expect(screen.getAllByTestId('panel').map((p) => p.textContent)).toEqual(PANELS);
  });

  describe('Recent Deployments with nothing to list', () => {
    const kept = answers['recent-deployments'];
    afterEach(() => { answers['recent-deployments'] = kept; window.localStorage.getItem.mockReset(); });
    const asDemo = () => window.localStorage.getItem.mockImplementation(
      (k) => (k === 'user' ? JSON.stringify({ username: 'demo', is_demo: true }) : null));

    it('demo user: the panel is hidden and the analyses take the width', () => {
      asDemo();
      answers['recent-deployments'] = { services: [] };
      const { container } = show();
      expect(screen.queryByText('RecentDeploymentsCard')).toBeNull();
      expect(container.querySelector('.overview-side')).toBeNull();
      expect(screen.getByText('AIAnalysisFeed')).toBeTruthy();
    });

    it('no CI/CD connected: the panel stays, it carries the hint to add it', () => {
      answers['recent-deployments'] = { services: [] };
      show();
      expect(screen.getByText('RecentDeploymentsCard')).toBeTruthy();
    });

    it('CI/CD connected but no run yet: the panel is hidden', () => {
      answers['recent-deployments'] = { services: [{ service_id: 1, latest_pipeline: null }] };
      const { container } = show();
      expect(screen.queryByText('RecentDeploymentsCard')).toBeNull();
      expect(container.querySelector('.overview-side')).toBeNull();
    });
  });

  it('has no mean-time-to-resolve card, and the moved cards are not on the page', () => {
    show();
    for (const card of GONE) expect(screen.queryByText(card)).toBeNull();
    // The two cards that went nowhere else are deleted, not just unused.
    for (const file of ['MTTRCard.jsx', 'ServiceRankingChart.jsx']) {
      expect(existsSync(resolve(__dirname, '..', file))).toBe(false);
    }
  });

  it('key numbers: open critical, open issues, system health, in that order', () => {
    const { container } = show();
    const row = container.querySelector('.overview-numbers');
    const tiles = Array.from(row.children);
    expect(tiles).toHaveLength(3);
    expect(within(tiles[0]).getByText('dashboard.openCritical')).toBeTruthy();
    expect(within(tiles[0]).getByText('2')).toBeTruthy();
    expect(tiles[0].getAttribute('href')).toBe('/dash/issues?status=OPEN&severity=Critical');
    expect(within(tiles[1]).getByText('dashboard.openIssuesLabel')).toBeTruthy();
    expect(within(tiles[1]).getByText('5')).toBeTruthy();
    expect(tiles[1].getAttribute('href')).toBe('/dash/issues?status=OPEN');
    expect(tiles[2].textContent).toBe('HealthScoreCard');
  });

  it('open critical is red only when there is one', () => {
    const { container, unmount } = show();
    expect(container.querySelector('.overview-numbers').children[0].className).toContain('metric-danger');
    unmount();
    answers['issue-stats'] = [{ name: 'CRITICAL', value: 0 }];
    const calm = show();
    const tile = calm.container.querySelector('.overview-numbers').children[0];
    expect(tile.className).not.toContain('metric-danger');
    expect(within(tile).getByText('dashboard.allClear')).toBeTruthy();
  });
});

describe('Needs attention: neutral card', () => {
  const css = readFileSync(resolve(__dirname, '../NeedsAttention.css'), 'utf8');
  it('marks an urgent issue with a red accent on the left, not a tinted background', () => {
    expect(css).not.toMatch(/background:\s*var\(--tone-red-soft\)/);
    expect(css).toMatch(/\.attention-critical,\s*\.attention-high \{ box-shadow: inset 3px 0 0 var\(--tone-red-solid\); \}/);
  });
});
