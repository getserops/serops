import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key) => key }),
}));
vi.mock('react-toastify', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }));
vi.mock('../AIBudgetCard', () => ({ default: () => null }));

const update = vi.fn();
vi.mock('../../../services/settings.service', () => ({
  default: {
    getAIProviders: vi.fn().mockResolvedValue([
      { id: 1, name: 'gemini', display_name: 'Google Gemini', default_model: 'flash', is_active: true, requires_api_key: true },
      { id: 2, name: 'ollama', display_name: 'Ollama (Local)', default_model: 'qwen', is_active: true, requires_api_key: false },
    ]),
    getAISettings: vi.fn().mockResolvedValue({ default_provider: 2, fallback_provider: null, use_custom_keys: false, monthly_budget_usd: null, budget_warn_pct: 80 }),
    getAPIKeys: vi.fn().mockResolvedValue([]),
    updateAISettings: (...args) => update(...args),
  },
}));

import AISettings from '../AISettings';

describe('AISettings primary model', () => {
  beforeEach(() => { update.mockReset(); update.mockResolvedValue({}); });

  it('is saved as soon as it is chosen, without the Save button at the bottom', async () => {
    render(<AISettings />);
    await userEvent.click(await screen.findByRole('radio', { name: /Google Gemini/ }));
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1));
    expect(update.mock.calls[0][0]).toMatchObject({ default_provider: 1 });
    // The budget is the budget card's: sending the stale null erased it.
    expect(update.mock.calls[0][0]).not.toHaveProperty('monthly_budget_usd');
    expect(update.mock.calls[0][0]).not.toHaveProperty('budget_warn_pct');
    expect(screen.getByRole('radio', { name: /Google Gemini/ })).toBeChecked();
  });

  it('goes back to the saved model when saving fails', async () => {
    let refuse;
    update.mockImplementation(() => new Promise((_, reject) => { refuse = reject; }));
    render(<AISettings />);
    await userEvent.click(await screen.findByRole('radio', { name: /Google Gemini/ }));
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1));
    refuse({ response: { data: { error: 'refused' } } });
    await waitFor(() => expect(screen.getByRole('radio', { name: /Ollama/ })).toBeChecked());
  });
});
