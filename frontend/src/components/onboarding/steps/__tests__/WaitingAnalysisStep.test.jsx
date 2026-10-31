import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key) => key }) }));
vi.mock('../../../../services/project.service', () => ({
  ProjectService: {
    GetProjects: vi.fn().mockResolvedValue([{ id: 7, name: 'shop', created_at: '2026-10-28T10:00:00Z' }]),
    GetProjectDetails: vi.fn().mockResolvedValue({ environments: [{ id: 1, name: 'production' }] }),
    GetDataRuns: vi.fn().mockResolvedValue({ runs: [
      { environment: 1, outcome: 'empty', reason: 'no_matching_logs', detail: 'd' },
    ] }),
  },
}));

import WaitingAnalysisStep from '../WaitingAnalysisStep';

describe('WaitingAnalysisStep', () => {
  it('when a run found nothing, says why and links to Check my data instead of embedding it', async () => {
    render(<MemoryRouter><WaitingAnalysisStep status={{}} /></MemoryRouter>);
    expect(await screen.findByText('dataCheck.reason.no_matching_logs')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'dataCheck.run' })).toHaveAttribute('href', '/dash/projects/7?tab=data');
    expect(screen.queryByRole('region', { name: 'dataCheck.title' })).not.toBeInTheDocument();
  });
});
