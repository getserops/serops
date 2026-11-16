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
import { SettingsService } from '../../../services/settings.service';

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

  it('lists alerts that matched no service and were not analysed', async () => {
    SettingsService.getAlertIngestSecret.mockResolvedValue({
      unmatched_alerts: {
        count: 2, days: 7,
        latest: [{ alertname: 'KubePodCrashLooping', source: 'alertmanager', service: '',
                   environment: 'production', received_at: '2026-11-16T10:00:00Z',
                   detail: 'no service matched (tried: kube-state-metrics)' }],
      },
    });
    render(<IncidentChannelsSettings />);
    const notice = await screen.findByTestId('unmatched-alerts');
    expect(notice.textContent).toContain('2 alerts in the last 7 days matched no service');
    expect(notice.textContent).toContain('KubePodCrashLooping');
    expect(notice.textContent).toContain('tried: kube-state-metrics');
  });

  it('shows no notice when every alert matched', async () => {
    SettingsService.getAlertIngestSecret.mockResolvedValue({ unmatched_alerts: { count: 0, days: 7, latest: [] } });
    render(<IncidentChannelsSettings />);
    await screen.findByRole('button', { name: /incidentChannels.new/ });
    expect(screen.queryByTestId('unmatched-alerts')).toBeNull();
  });

  it('Slack does not show the recipients field', async () => {
    render(<IncidentChannelsSettings />);
    await userEvent.click(await screen.findByRole('button', { name: /incidentChannels.new/ }));
    expect(screen.queryByLabelText('incidentChannels.recipients')).toBeNull();
  });
});
