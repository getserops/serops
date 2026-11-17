import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key, opts) => (opts && 'count' in opts ? `${key}:${opts.count}` : key),
  }),
}));

const { default: MTTRCard } = await import('../MTTRCard');

describe('MTTRCard', () => {
  it('shows the sample size and no trend for a small sample', () => {
    render(<MTTRCard data={{
      overall_mttr_hours: 2, sample_size: 2, period_days: 30, trend: 'INSUFFICIENT_DATA',
      by_severity: { WARNING: { avg_hours: 2, count: 1 }, INFO: { avg_hours: 2, count: 1 } },
    }} />);
    expect(screen.getByText(/dashboard\.mttrSample:2/)).toBeTruthy();
    expect(screen.getByText(/dashboard\.window\.lastDays:30/)).toBeTruthy();
    expect(screen.getByText(/dashboard\.trend\.insufficient/)).toBeTruthy();
    expect(screen.queryByText(/dashboard\.trend\.stable/)).toBeNull();
    // INFO has its own row, not folded into WARNING.
    expect(screen.getByText('issues.info:')).toBeTruthy();
  });

  it('says not enough data when nothing was resolved', () => {
    render(<MTTRCard data={{ overall_mttr_hours: null, sample_size: 0, trend: 'INSUFFICIENT_DATA', by_severity: {} }} />);
    expect(screen.getByText('dashboard.notEnoughData')).toBeTruthy();
  });

  it('shows the trend from a large enough sample', () => {
    render(<MTTRCard data={{ overall_mttr_hours: 5, sample_size: 20, trend: 'IMPROVING', by_severity: {} }} />);
    expect(screen.getByText(/dashboard\.trend\.improving/)).toBeTruthy();
  });
});
