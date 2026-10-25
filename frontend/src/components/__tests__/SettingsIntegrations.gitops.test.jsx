import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key, fallback) => (typeof fallback === 'string' ? fallback : key) }),
}));
vi.mock('react-toastify', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() } }));
const create = vi.fn().mockResolvedValue({ id: 9 });
vi.mock('../../services/integration.service', () => ({
  IntegrationService: { getAll: vi.fn().mockResolvedValue([]), create: (...a) => create(...a), update: vi.fn(), delete: vi.fn() },
}));
vi.mock('../../services/observability.service', () => ({ default: { getAll: vi.fn().mockResolvedValue([]), list: vi.fn().mockResolvedValue([]) } }));
vi.mock('../settings/ObservabilitySettings', () => ({ LogProviderPanel: () => null, MetricProviderPanel: () => null }));
vi.mock('../../utils/permissions', () => ({ usePermissions: () => () => true }));

import SettingsIntegrations from '../SettingsIntegrations';

// A team deploying with Argo CD but building elsewhere had no integration to
// bind its services to (journey suite, B22).
describe('SettingsIntegrations — Argo CD', () => {
  it('is offered on the CI/CD tab and created with a name only', async () => {
    render(<MemoryRouter initialEntries={['/dash/settings/integrations?tab=cicd']}><SettingsIntegrations /></MemoryRouter>);
    userEvent.click(await screen.findByRole('button', { name: /Add Integration/ }));
    userEvent.click(await screen.findByRole('radio', { name: 'Argo CD' }));
    expect(screen.getByText(/nothing to connect to/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Test Connection/ })).not.toBeInTheDocument();
    userEvent.type(screen.getByRole('textbox', { name: 'Integration Name' }), 'Argo CD prod');
    userEvent.click(screen.getByRole('button', { name: 'Create Integration' }));
    await vi.waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0][0]).toMatchObject({ provider_type: 'argocd', name: 'Argo CD prod' });
    expect(create.mock.calls[0][0].access_token).toBeUndefined();
  });
});
