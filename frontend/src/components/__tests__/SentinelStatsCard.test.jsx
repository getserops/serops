import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import SentinelStatsCard from '../SentinelStatsCard';
import en from '../../locales/en.json';

// The real English strings, with {{values}} filled in, so the test reads
// what a person reads.
const translate = (key, opts = {}) => {
  const text = key.split('.').reduce((o, k) => o?.[k], en);
  if (typeof text !== 'string') return key;
  return text.replace(/\{\{(\w+)\}\}/g, (_, name) => opts[name] ?? '');
};
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: translate }),
}));

const signIn = (user) => window.localStorage.getItem.mockImplementation(
  (k) => (k === 'user' ? JSON.stringify(user) : null),
);

const DATA = {
  period_days: 7, total_batches: 17, decisions: { alert: 12, quiet: 5 },
  ai_analyzed: 12, ai_skipped: 5, skip_rate_percent: 29, estimated_tokens_saved: 42500,
};

describe('SentinelStatsCard tokens saved', () => {
  beforeEach(() => window.localStorage.getItem.mockReset());

  it('shows the tokens saved to a user of a real organisation', () => {
    signIn({ username: 'alice', is_demo: false });
    render(<SentinelStatsCard data={DATA} loading={false} />);
    expect(screen.getByText('~42.5K tokens saved')).toBeInTheDocument();
    expect(screen.getByText('5 batches skipped')).toBeInTheDocument();
  });

  it('leaves the tokens saved out of the demo, and nothing else', () => {
    signIn({ username: 'demo', is_demo: true });
    render(<SentinelStatsCard data={DATA} loading={false} />);
    expect(screen.queryByText(/tokens saved/)).toBeNull();
    expect(screen.getByText('5 batches skipped')).toBeInTheDocument();
    expect(screen.getByText('29%')).toBeInTheDocument();
  });
});
