import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import en from '../../locales/en.json';

// One t for every render, as react-i18next gives. A new function per render
// made fetchIntegrations (a useCallback on [t]) change on every render, so
// its useEffect refetched after every render: a render loop that ran for the
// whole test, made its duration depend on the machine's load (it timed out
// at 5 s on busy runners) and went on after it, outside act().
const i18n = vi.hoisted(() => ({ t: null }));
// The real English strings, with {{values}} filled in, so the test reads
// what a person reads.
i18n.t = (key, opts = {}) => {
  const text = key.split('.').reduce((o, k) => o?.[k], en);
  if (typeof text !== 'string') return typeof opts === 'string' ? opts : (opts.defaultValue ?? key);
  return text.replace(/\{\{(\w+)\}\}/g, (_, name) => opts[name] ?? '');
};
vi.mock('react-i18next', () => ({ useTranslation: () => i18n }));
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
    fireEvent.click(await screen.findByRole('button', { name: /Add Integration/ }));
    fireEvent.click(await screen.findByRole('radio', { name: 'Jenkins' }));
    // Choosing a provider opens the form after a 100 ms timer: wait for it here
    // rather than let it fire after the test.
    const url = screen.getByRole('textbox', { name: 'Jenkins URL' });
    await waitFor(() => expect(url.closest('.collapse')).toHaveClass('show'));
    // One change event per field: typing character by character re-renders
    // this whole page 43 times, which is what made the test slow under load.
    const enter = (field, value) => fireEvent.change(field, { target: { value } });
    enter(url, 'http://jenkins.example.com:8080');
    enter(screen.getByRole('textbox', { name: 'Username' }), 'ci-bot');
    const test = screen.getByRole('button', { name: /Test Connection/ });
    expect(test).toBeDisabled();
    enter(screen.getByLabelText('API Token'), 'abc123');
    expect(test).toBeEnabled();
    expect(screen.getByRole('link', { name: /Generate token/ }))
      .toHaveAttribute('href', 'http://jenkins.example.com:8080/user/ci-bot/security');
  });
});
