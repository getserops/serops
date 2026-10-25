import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key) => key }),
}));
vi.mock('react-toastify', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }));

const create = vi.fn();
vi.mock('../../../services/incidentChannels.service', () => ({
  default: {
    list: vi.fn().mockResolvedValue([]),
    create: (...args) => create(...args),
    update: vi.fn(),
    remove: vi.fn(),
    test: vi.fn(),
  },
}));
vi.mock('../../../services/settings.service', () => ({
  SettingsService: {
    getAlertIngestSecret: vi.fn().mockResolvedValue({}),
    rotateAlertIngestSecret: vi.fn(),
  },
}));

import IncidentChannelsSettings from '../IncidentChannelsSettings';

describe('IncidentChannelsSettings', () => {
  beforeEach(() => create.mockReset().mockResolvedValue({}));

  it('an Email channel asks for recipients and saves them as extra_config.to', async () => {
    render(<IncidentChannelsSettings />);
    await userEvent.click(await screen.findByRole('button', { name: /incidentChannels.new/ }));
    await userEvent.type(screen.getByPlaceholderText('SRE Slack'), 'On-call email');
    const kind = screen.getAllByRole('combobox')[0];
    await userEvent.selectOptions(kind, 'email');
    await userEvent.type(screen.getByLabelText('incidentChannels.recipients'), 'sre@acme.test, oncall@acme.test');
    await userEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create.mock.calls[0][0]).toMatchObject({
      kind: 'email',
      extra_config: { to: ['sre@acme.test', 'oncall@acme.test'] },
    });
  });

  it('Slack does not show the recipients field', async () => {
    render(<IncidentChannelsSettings />);
    await userEvent.click(await screen.findByRole('button', { name: /incidentChannels.new/ }));
    expect(screen.queryByLabelText('incidentChannels.recipients')).toBeNull();
  });
});
