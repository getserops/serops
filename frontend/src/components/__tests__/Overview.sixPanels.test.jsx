import React from 'react';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// 1.5.6, the approved mock-up: status, needs attention, services beside the
// recent analyses (Recent Deployments under them when shown), then the week.
const answers = {
  'recent-deployments': { services: [{ service_id: 1, latest_pipeline: { id: 'a1' } }] },
};
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key) => key }) }));
vi.mock('@tanstack/react-query', () => ({ useQuery: ({ queryKey }) => ({ data: answers[queryKey[0]], isLoading: false }) }));
vi.mock('@mui/material', () => ({ useMediaQuery: () => false }));
vi.mock('../../services/dash.service', () => ({ default: {} }));
vi.mock('../../context/ClusterContext', () => ({ useCluster: () => ({ currentCluster: null, loading: false, filter: {} }) }));
vi.mock('../../hooks/useFilterUrlSync', () => ({ default: () => {} }));
vi.mock('../../utils/permissions', () => ({ usePermissions: () => () => false }));
vi.mock('../Sidebar', () => ({ default: () => null }));
vi.mock('../Navbar', () => ({ default: () => null }));
vi.mock('../CommandPalette', () => ({ default: () => null }));
vi.mock('../DemoBanner', () => ({ default: () => null }));
vi.mock('../onboarding', () => ({ OnboardingWizard: () => null, OnboardingResumeChip: () => null }));
vi.mock('../PageHeader', () => ({ default: ({ title }) => <h1>{title}</h1> }));
const PANELS = ['overview/StatusCard', 'NeedsAttention', 'overview/ServicesPanel', 'AIAnalysisFeed', 'RecentDeploymentsCard',
  'TrendAnalysisChart', 'overview/CausesBar'];
for (const card of PANELS) {
  vi.doMock(`../${card}`, () => ({ default: () => <div data-testid="panel">{card}</div> }));
}

const { default: Dashboard } = await import('../Dashboard');
const show = () => render(<MemoryRouter initialEntries={['/dash']}><Dashboard /></MemoryRouter>);

describe('Overview: clear at a glance', () => {
  it('shows the panels in the order of the mock-up and nothing else', () => {
    show();
    expect(screen.getAllByTestId('panel').map((p) => p.textContent)).toEqual(PANELS);
  });

  it('services beside the analyses, the two panels of the week side by side', () => {
    const { container } = show();
    expect([...container.querySelector('.glance-cols').children].map((c) => c.textContent))
      .toEqual(['overview/ServicesPanel', 'AIAnalysisFeed']);
    expect([...container.querySelector('.glance-week').children].map((c) => c.textContent))
      .toEqual(['TrendAnalysisChart', 'overview/CausesBar']);
  });

  it('the gauge, the number tiles, the donut and the 12-tile map are gone', () => {
    const { container } = show();
    expect(container.querySelector('.overview-numbers')).toBeNull();
    for (const file of ['HealthScoreCard.jsx', 'RootCausePie.jsx', 'ServiceHealthHeatmap.jsx', 'MTTRCard.jsx', 'ServiceRankingChart.jsx']) {
      expect(existsSync(resolve(__dirname, '..', file))).toBe(false);
    }
  });

  describe('Recent Deployments keeps its rule', () => {
    const kept = answers['recent-deployments'];
    afterEach(() => { answers['recent-deployments'] = kept; window.localStorage.getItem.mockReset(); });
    const asDemo = () => window.localStorage.getItem.mockImplementation(
      (k) => (k === 'user' ? JSON.stringify({ username: 'demo', is_demo: true }) : null));

    it('demo user with nothing to list: hidden', () => {
      asDemo();
      answers['recent-deployments'] = { services: [] };
      show();
      expect(screen.queryByText('RecentDeploymentsCard')).toBeNull();
    });

    it('no CI/CD connected: shown, it carries the hint to add it', () => {
      answers['recent-deployments'] = { services: [] };
      show();
      expect(screen.getByText('RecentDeploymentsCard')).toBeTruthy();
    });

    it('CI/CD connected but no run yet: hidden', () => {
      answers['recent-deployments'] = { services: [{ service_id: 1, latest_pipeline: null }] };
      show();
      expect(screen.queryByText('RecentDeploymentsCard')).toBeNull();
    });
  });
});
