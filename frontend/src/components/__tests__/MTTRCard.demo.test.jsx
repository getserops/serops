import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key) => key }) }));
const who = vi.hoisted(() => ({ demo: false }));
vi.mock('../../utils/demo', () => ({ isDemoUser: () => who.demo }));

import MTTRCard from '../MTTRCard';

const DATA = { overall_mttr_hours: 1.3, by_severity: {}, trend: 'INSUFFICIENT_DATA', sample_size: 7, period_days: 30 };

describe('MTTRCard: not shown in the public demo', () => {
  it('a normal organisation sees its mean time to resolve', () => {
    who.demo = false;
    render(<MTTRCard data={DATA} loading={false} />);
    expect(screen.getByText('1.3h')).toBeInTheDocument();
    expect(screen.getByText('dashboard.mttr')).toBeInTheDocument();
  });

  it('the demo shows no tile and no figure, loaded or loading', () => {
    who.demo = true;
    const { container, rerender } = render(<MTTRCard data={DATA} loading={false} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<MTTRCard data={null} loading />);
    expect(container).toBeEmptyDOMElement();
  });
});
