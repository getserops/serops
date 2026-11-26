import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

// Review item 17: one <main> landmark, and a "Skip to content" link as the
// first focusable element, so the keyboard does not walk the whole menu
// (26 Tab presses to reach the Issues table before).
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key) => key }) }));
vi.mock('@tanstack/react-query', () => ({ useQuery: () => ({ data: undefined, isLoading: false }) }));
vi.mock('@mui/material', () => ({ useMediaQuery: () => false }));
vi.mock('../../services/dash.service', () => ({ default: {} }));
vi.mock('../../services/data.service', () => ({ default: {} }));
vi.mock('../../context/ClusterContext', () => ({ useCluster: () => ({ currentCluster: null, loading: false, filter: {} }) }));
vi.mock('../../hooks/useFilterUrlSync', () => ({ default: () => {} }));
vi.mock('../../utils/permissions', () => ({ usePermissions: () => () => false }));
vi.mock('../../utils/demo', () => ({ isDemoUser: () => false }));
vi.mock('../Sidebar', () => ({ default: () => <nav><a href="/dash">menu entry</a></nav> }));
vi.mock('../Navbar', () => ({ default: () => <header><button type="button">top bar button</button></header> }));
vi.mock('../CommandPalette', () => ({ default: () => null }));
vi.mock('../DemoBanner', () => ({ default: () => null }));
vi.mock('../onboarding', () => ({ OnboardingWizard: () => null, OnboardingResumeChip: () => null }));
vi.mock('../PageHeader', () => ({ default: ({ title }) => <h1>{title}</h1> }));
for (const card of ['overview/StatusCard', 'overview/ServicesPanel', 'overview/CausesBar', 'TrendAnalysisChart',
  'RecentDeploymentsCard', 'WorkloadsByCluster', 'CorrelationInsightsCard', 'AIAnalysisFeed',
  'SentinelStatsCard', 'NeedsAttention']) {
  vi.doMock(`../${card}`, () => ({ default: () => null }));
}

const { default: Dashboard } = await import('../Dashboard');

const at = (path) => render(
  <MemoryRouter initialEntries={[path]}>
    <Routes>
      <Route path="/dash" element={<Dashboard />}>
        <Route path="issues" element={<button type="button">first control of the page</button>} />
      </Route>
    </Routes>
  </MemoryRouter>,
);

describe('signed-in layout: landmark and skip link', () => {
  it.each(['/dash', '/dash/issues'])('%s has exactly one main landmark', (path) => {
    at(path);
    const mains = screen.getAllByRole('main');
    expect(mains).toHaveLength(1);
    expect(mains[0].id).toBe('main-content');
  });

  it('the skip link is the first focusable element and comes before the menu', () => {
    const { container } = at('/dash/issues');
    const first = container.querySelector('a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])');
    expect(first).toBe(screen.getByRole('link', { name: 'nav.skipToContent' }));
  });

  it('the skip link moves the focus to the page content', () => {
    at('/dash/issues');
    fireEvent.click(screen.getByRole('link', { name: 'nav.skipToContent' }));
    const main = screen.getByRole('main');
    expect(document.activeElement).toBe(main);
    expect(main).toContainElement(screen.getByText('first control of the page'));
  });
});
