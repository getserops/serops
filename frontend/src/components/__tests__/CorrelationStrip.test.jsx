import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

let result;
vi.mock('@tanstack/react-query', () => ({ useQuery: () => result }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k, o) => (o && o.count != null ? `${k}:${o.count}` : k) }) }));
vi.mock('../../services/dash.service', () => ({ default: {} }));

import CorrelationStrip from '../CorrelationStrip';

describe('Correlation insights above the Analyses list', () => {
  beforeEach(() => { result = { data: undefined, isLoading: false }; });

  it('shows the rate and the four counts on one strip', () => {
    result.data = { total_issues: 10, correlation_rate: 60, commit_correlations: 4, metric_breakdown: { memory: 2, cpu: 1 }, cicd_correlations: 3, period_days: 7 };
    render(<CorrelationStrip environment="all" clusterId={null} />);
    const strip = screen.getByRole('region', { name: 'dashboard.correlationInsights' });
    expect(strip.textContent).toContain('60%');
    expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      '4 dashboard.commitLinks', '2 dashboard.memorySpikes', '1 dashboard.cpuSpikes', '3 dashboard.pipelineFailures',
    ]);
    expect(strip.textContent).toContain('dashboard.window.lastDays:7');
  });

  it('shows nothing when there is nothing to count', () => {
    result.data = { total_issues: 0 };
    const { container } = render(<CorrelationStrip environment="all" clusterId={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
