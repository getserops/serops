import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key, fallback) => (typeof fallback === 'string' ? fallback : key) }),
}));
vi.mock('react-toastify', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() } }));
vi.mock('../../services/integration.service', () => ({
  IntegrationService: { getAll: vi.fn().mockResolvedValue([]), create: vi.fn(), update: vi.fn(), delete: vi.fn() },
}));
vi.mock('../../services/observability.service', () => ({ default: { getAll: vi.fn().mockResolvedValue([]), list: vi.fn().mockResolvedValue([]) } }));
vi.mock('../settings/ObservabilitySettings', () => ({ LogProviderPanel: () => null, MetricProviderPanel: () => null }));
vi.mock('../../utils/permissions', () => ({ usePermissions: () => () => true }));

import SettingsIntegrations from '../SettingsIntegrations';

describe('SettingsIntegrations — Jenkins', () => {
  it('Test Connection is usable with a Jenkins API token, and the token link opens Jenkins', async () => {
    render(<MemoryRouter initialEntries={['/dash/settings/integrations?tab=cicd']}><SettingsIntegrations /></MemoryRouter>);
    userEvent.click(await screen.findByRole('button', { name: /Add Integration/ }));
    userEvent.click(await screen.findByRole('radio', { name: 'Jenkins' }));
    userEvent.type(screen.getByRole('textbox', { name: 'Jenkins URL' }), 'http://jenkins.example.com:8080');
    userEvent.type(screen.getByRole('textbox', { name: 'Username' }), 'ci-bot');
    const test = screen.getByRole('button', { name: /Test Connection/ });
    expect(test).toBeDisabled();
    userEvent.type(screen.getByLabelText('API Token'), 'abc123');
    expect(test).toBeEnabled();
    expect(screen.getByRole('link', { name: /Generate token/ }))
      .toHaveAttribute('href', 'http://jenkins.example.com:8080/user/ci-bot/security');
  });
});
