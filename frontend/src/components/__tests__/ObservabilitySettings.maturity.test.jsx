import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('react-toastify', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() } }));
vi.mock('../../services/observability.service', () => ({ default: { create: vi.fn(), update: vi.fn(), delete: vi.fn(), healthCheck: vi.fn() } }));
vi.mock('../../services/cluster.service', () => ({ default: { list: vi.fn().mockResolvedValue([]) } }));
vi.mock('../../utils/permissions', () => ({ usePermissions: () => () => true }));

import { LogProviderPanel } from '../settings/ObservabilitySettings';

describe('Log provider picker — maturity', () => {
  it('marks the three cloud adapters live-tested with platform, version and date, and no other provider', async () => {
    render(<LogProviderPanel integrations={[]} onRefresh={() => {}} />);
    userEvent.click(await screen.findByRole('button', { name: /Add log provider/ }));

    const aws = await screen.findByRole('radio', { name: /AWS CloudWatch/ });
    expect(within(aws).getByText('Live-tested')).toHaveAttribute('title', 'Live-tested: EKS 1.36, SerOps 1.3.0, 2026-11-13');
    expect(within(aws).getByText('EKS 1.36, SerOps 1.3.0, 2026-11-13')).toBeInTheDocument();
    expect(within(screen.getByRole('radio', { name: /Google Cloud/ })).getByText(/GKE 1\.36, SerOps 1\.3\.0, 2026-11-12/)).toBeInTheDocument();
    expect(within(screen.getByRole('radio', { name: /Azure Monitor/ })).getByText(/AKS 1\.36, SerOps 1\.3\.0, 2026-11-11/)).toBeInTheDocument();

    expect(within(screen.getByRole('radio', { name: /Grafana Loki|Loki/ })).queryByText('Live-tested')).toBeNull();
    expect(screen.getAllByText('Live-tested')).toHaveLength(3);
  });
});
