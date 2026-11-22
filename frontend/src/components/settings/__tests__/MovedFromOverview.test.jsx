import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// Structure review, section 3: the Sentinel figures and the workloads per
// cluster left the Overview; they sit on the settings page they belong to.
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key) => key, i18n: { language: 'en' } }) }));
vi.mock('react-toastify', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
const useQuery = vi.fn(() => ({ data: { total_batches: 14 }, isLoading: false }));
vi.mock('@tanstack/react-query', () => ({ useQuery: (o) => useQuery(o) }));
vi.mock('../../../context/ClusterContext', () => ({
  useCluster: () => ({ currentCluster: { id: 7 }, clusters: [], loading: false, filter: { environment: 'production' }, refresh: vi.fn() }),
}));
vi.mock('../../../services/settings.service', () => ({ default: { getSentinelConfig: vi.fn().mockResolvedValue({ active_mode: true, error_spike_multiplier: 0, z_score_threshold: 0, max_quiet_batches: 12 }) } }));
vi.mock('../../../services/dash.service', () => ({ default: { getSentinelStats: vi.fn() } }));
vi.mock('../../../services/cluster.service', () => ({ default: { list: vi.fn().mockResolvedValue([]) } }));
vi.mock('../../SentinelStatsCard', () => ({ default: ({ data }) => <div data-testid="sentinel-stats">{data?.total_batches}</div> }));
vi.mock('../../WorkloadsByCluster', () => ({ default: () => <div data-testid="workloads-by-cluster" /> }));
vi.mock('../../PageHeader', () => ({ default: ({ title }) => <h1>{title}</h1> }));

const { default: SentinelSettings } = await import('../SentinelSettings');
const { default: ClusterSettings } = await import('../ClusterSettings');

describe('cards moved off the Overview', () => {
  it('Settings > Sentinel opens on the Sentinel figures, for the filter of the top bar', async () => {
    const { container } = render(<SentinelSettings />);
    const stats = screen.getByTestId('sentinel-stats');
    expect(stats.textContent).toBe('14');
    expect(useQuery.mock.calls[0][0].queryKey).toEqual(['sentinel-stats', 'production', 7]);
    // Above the first settings section.
    const first = container.querySelector('.settings-section').children[1];
    expect(first).toContainElement(stats);
    await waitFor(() => expect(container.querySelector('.spinner-border')).toBeNull());
  });

  it('Settings > Clusters shows the workloads per cluster', async () => {
    render(<ClusterSettings />);
    await waitFor(() => expect(screen.getByTestId('workloads-by-cluster')).toBeTruthy());
  });
});
