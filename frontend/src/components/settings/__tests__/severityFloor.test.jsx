import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import en from '../../../locales/en.json';
import fr from '../../../locales/fr.json';
import { floorChoice, floorToSave } from '../../../utils/severityFloor';

// 1.5.6: the "Min severity" dropdowns offered LOW, MEDIUM and HIGH, levels no
// issue carries. They now offer Any, Info, Warning and Critical, in the
// user's language, and a floor saved with an old value shows its equivalent.
let locale = en;
const translate = (key, opts = {}) => {
  const text = key.split('.').reduce((o, k) => o?.[k], locale);
  if (typeof text !== 'string') return typeof opts === 'string' ? opts : (opts.defaultValue ?? key);
  return text.replace(/\{\{(\w+)\}\}/g, (_, name) => opts[name] ?? '');
};
const i18n = { t: (...a) => translate(...a) };
vi.mock('react-i18next', () => ({ useTranslation: () => i18n }));
vi.mock('react-toastify', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), warn: vi.fn() } }));

const channels = { list: vi.fn(), create: vi.fn(), update: vi.fn() };
vi.mock('../../../services/incidentChannels.service', () => ({
  default: {
    list: (...a) => channels.list(...a),
    create: (...a) => channels.create(...a),
    update: (...a) => channels.update(...a),
    remove: vi.fn(),
    test: vi.fn(),
  },
}));
const rules = { list: vi.fn(), create: vi.fn(), update: vi.fn() };
vi.mock('../../../services/settings.service', () => ({
  SettingsService: {
    getAlertIngestSecret: vi.fn().mockResolvedValue({}),
    rotateAlertIngestSecret: vi.fn(),
    listRoutingRules: (...a) => rules.list(...a),
    listDeliveryChannels: vi.fn().mockResolvedValue([]),
    createRoutingRule: (...a) => rules.create(...a),
    updateRoutingRule: (...a) => rules.update(...a),
    deleteRoutingRule: vi.fn(),
  },
}));

import IncidentChannelsSettings from '../IncidentChannelsSettings';
import RoutingRulesSettings from '../RoutingRulesSettings';

const optionTexts = (select) => within(select).getAllByRole('option').map((o) => o.textContent);
const selectedText = (select) => select.options[select.selectedIndex].textContent;

describe('severity floor values', () => {
  it('shows every stored floor as one of the four choices', () => {
    expect(['', 'INFO', 'low', 'WARNING', 'MEDIUM', 'CRITICAL', 'HIGH', 'bogus', null].map(floorChoice))
      .toEqual(['', 'INFO', 'INFO', 'WARNING', 'WARNING', 'CRITICAL', 'CRITICAL', '', '']);
  });

  it('saves the level\'s own word, old values included', () => {
    expect(['', 'INFO', 'WARNING', 'CRITICAL', 'LOW', 'MEDIUM', 'HIGH', 'bogus'].map(floorToSave))
      .toEqual(['', 'INFO', 'WARNING', 'CRITICAL', 'INFO', 'WARNING', 'CRITICAL', '']);
  });
});

describe('Delivery channels, Min severity', () => {
  beforeEach(() => {
    locale = en;
    channels.list.mockReset().mockResolvedValue([]);
    channels.create.mockReset().mockResolvedValue({});
    channels.update.mockReset().mockResolvedValue({});
  });

  it('offers Any, Info, Warning and Critical', async () => {
    render(<IncidentChannelsSettings />);
    await userEvent.click(await screen.findByRole('button', { name: /New channel/ }));
    const floor = screen.getByLabelText('Min severity');
    expect(optionTexts(floor)).toEqual(['any', 'INFO', 'WARNING', 'CRITICAL']);
  });

  it('in French too', async () => {
    locale = fr;
    render(<IncidentChannelsSettings />);
    await userEvent.click(await screen.findByRole('button', { name: new RegExp(fr.incidentChannels.new) }));
    const floor = screen.getByLabelText(fr.incidentChannels.minSeverity);
    expect(optionTexts(floor)).toEqual(['toutes', 'INFO', 'AVERTISSEMENT', 'CRITIQUE']);
  });

  it('shows an old floor as its equivalent, in the list and in the form', async () => {
    channels.list.mockResolvedValue([
      { id: 1, name: 'Ops Slack', kind: 'slack', kind_display: 'Slack', min_severity: 'HIGH', is_active: true, trigger_events: [] },
    ]);
    render(<IncidentChannelsSettings />);
    const row = (await screen.findByText('Ops Slack')).closest('tr');
    expect(within(row).getByText('CRITICAL')).toBeTruthy();
    expect(within(row).queryByText('HIGH')).toBeNull();
    await userEvent.click(within(row).getByTitle('Edit'));
    const floor = screen.getByLabelText('Min severity');
    expect(selectedText(floor)).toBe('CRITICAL');
    await userEvent.selectOptions(floor, 'WARNING');
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(channels.update).toHaveBeenCalledTimes(1));
    expect(channels.update.mock.calls[0][1]).toMatchObject({ min_severity: 'WARNING' });
  });
});

describe('Routing rules, Min severity', () => {
  beforeEach(() => {
    locale = en;
    rules.list.mockReset().mockResolvedValue([]);
    rules.create.mockReset().mockResolvedValue({});
    rules.update.mockReset().mockResolvedValue({});
  });

  it('offers Any, Info, Warning and Critical, in English and French', async () => {
    const { unmount } = render(<RoutingRulesSettings />);
    await userEvent.click(await screen.findByRole('button', { name: en.settings.routing.addRuleAria }));
    expect(optionTexts(screen.getByLabelText(en.settings.routing.minSeverityAria)))
      .toEqual(['any severity', 'INFO', 'WARNING', 'CRITICAL']);
    unmount();

    locale = fr;
    render(<RoutingRulesSettings />);
    await userEvent.click(await screen.findByRole('button', { name: fr.settings.routing.addRuleAria }));
    expect(optionTexts(screen.getByLabelText(fr.settings.routing.minSeverityAria)))
      .toEqual(['toute sévérité', 'INFO', 'AVERTISSEMENT', 'CRITIQUE']);
  });

  it('shows an old floor as its equivalent and saves the new word', async () => {
    rules.list.mockResolvedValue([
      { id: 7, name: 'Prod pager', is_active: true, min_severity: 'MEDIUM', environments: [], services: [], event_types: [], target_ids: [], priority: 100 },
    ]);
    render(<RoutingRulesSettings />);
    const row = (await screen.findByText('Prod pager')).closest('tr');
    expect(within(row).getByText(/WARNING/)).toBeTruthy();
    await userEvent.click(within(row).getByRole('button', { name: en.settings.routing.editRuleAria.replace('{{name}}', 'Prod pager') }));
    const floor = screen.getByLabelText(en.settings.routing.minSeverityAria);
    expect(selectedText(floor)).toBe('WARNING');
    await userEvent.selectOptions(floor, 'INFO');
    await userEvent.click(screen.getByRole('button', { name: en.settings.routing.saveRule }));
    await waitFor(() => expect(rules.update).toHaveBeenCalledTimes(1));
    expect(rules.update.mock.calls[0][1]).toMatchObject({ min_severity: 'INFO' });
  });

  it('treats an unknown stored floor as any', async () => {
    rules.list.mockResolvedValue([
      { id: 8, name: 'Odd rule', is_active: true, min_severity: 'SEVERE', environments: [], services: [], event_types: [], target_ids: [], priority: 100 },
    ]);
    render(<RoutingRulesSettings />);
    const row = (await screen.findByText('Odd rule')).closest('tr');
    expect(within(row).getByText('any incident', { exact: false })).toBeTruthy();
  });
});
