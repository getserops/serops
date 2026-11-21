import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const i18n = vi.hoisted(() => ({ t: (key, fallback) => (typeof fallback === 'string' ? fallback : key) }));
vi.mock('react-i18next', () => ({ useTranslation: () => i18n }));
vi.mock('react-toastify', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() } }));
const ROWS = [{ id: 1, name: 'Fleet GitHub', provider_type: 'github', category: 'devops', display_url: 'https://github.com',
  is_active: true, is_verified: false, created_at: '2026-11-18T10:00:00Z' }];
vi.mock('../../services/integration.service', () => ({
  IntegrationService: { getAll: vi.fn().mockImplementation(() => Promise.resolve(ROWS)), create: vi.fn(), update: vi.fn(), delete: vi.fn() },
}));
vi.mock('../../services/observability.service', () => ({ default: { getAll: vi.fn().mockResolvedValue([]), list: vi.fn().mockResolvedValue([]) } }));
vi.mock('../settings/ObservabilitySettings', () => ({ LogProviderPanel: () => null, MetricProviderPanel: () => null, TraceProviderPanel: () => null }));
vi.mock('../../utils/permissions', () => ({ usePermissions: () => () => true }));
const who = vi.hoisted(() => ({ demo: false }));
vi.mock('../../utils/demo', () => ({ isDemoUser: () => who.demo }));
vi.mock('axios', () => ({ default: { get: vi.fn().mockResolvedValue({ data: {} }) } }));

import SettingsIntegrations from '../SettingsIntegrations';

const show = () => render(<MemoryRouter initialEntries={['/dash/settings/integrations?tab=cicd']}><SettingsIntegrations /></MemoryRouter>);

describe('SettingsIntegrations: the demo shows integrations without an address', () => {
  it('a normal organisation sees the address of the integration', async () => {
    who.demo = false;
    show();
    expect(await screen.findByText('Fleet GitHub')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /github\.com/ })).toHaveAttribute('href', 'https://github.com');
  });

  it('the demo sees the name and no address or link', async () => {
    who.demo = true;
    show();
    expect(await screen.findByText('Fleet GitHub')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /github\.com/ })).toBeNull();
    expect(screen.queryByText(/github\.com/)).toBeNull();
  });

  it('a normal organisation sees the age, the service count and the buttons of a card', async () => {
    who.demo = false;
    show();
    expect(await screen.findByText('Fleet GitHub')).toBeInTheDocument();
    expect(screen.getByText('Services')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Verify Connection/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Actions for Fleet GitHub' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Add Integration/ })).toBeInTheDocument();
  });

  it('the demo sees no age, no service count and no button that changes or tests the connection', async () => {
    who.demo = true;
    show();
    expect(await screen.findByText('Fleet GitHub')).toBeInTheDocument();
    expect(screen.queryByText('Services')).toBeNull();
    expect(screen.queryByText(/ago$|^Just now$/)).toBeNull();
    expect(screen.queryByRole('button', { name: /Verify Connection/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Actions for Fleet GitHub' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Add Integration/ })).toBeNull();
  });
});
