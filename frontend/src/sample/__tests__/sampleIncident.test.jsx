import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import apiClient from '../../services/api-client';
import DataService from '../../services/data.service';
import Detail from '../../components/Detail';
import { loadSampleIncident, shiftDates } from '../sampleIncident';
import AIAnalysisFeed from '../../components/AIAnalysisFeed';
import OnboardingWizard from '../../components/onboarding/OnboardingWizard';
import en from '../../locales/en.json';
import fr from '../../locales/fr.json';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key, fallback) => (typeof fallback === 'string' ? fallback : key) }),
}));
vi.mock('../../services/api-client', () => ({
  default: { get: vi.fn(), post: vi.fn(), interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } } },
}));
vi.mock('../../components/BatchTimelineChart', () => ({ default: () => <div>timeline chart</div> }));
vi.mock('../../components/onboarding/hooks/useOnboardingStatus', () => {
  const useOnboardingStatus = () => ({
    status: { current_step: 'connect_ai_provider', completed_steps: [], skipped_steps: [], progress_percentage: 0 },
    loading: false, error: null, refresh: vi.fn(), skipStep: vi.fn(), storeData: vi.fn(), dismiss: vi.fn(),
  });
  return { default: useOnboardingStatus, useOnboardingStatus };
});

const NOW = Date.parse('2030-01-15T12:00:00Z');

const renderSample = () => render(
  <MemoryRouter initialEntries={['/dash/data/details/sample']}>
    <Routes><Route path="/dash/data/details/:batchId" element={<Detail />} /></Routes>
  </MemoryRouter>,
);

describe('sample incident', () => {
  beforeEach(() => apiClient.get.mockClear());

  it('moves dates and leaves other text alone', () => {
    expect(shiftDates({ at: '2026-01-01T00:00:00Z', n: 3, text: 'v2.3.3', list: ['2026-01-01T00:00:00+00:00'] }, 1000)).toEqual({
      at: '2026-01-01T00:00:01.000Z', n: 3, text: 'v2.3.3', list: ['2026-01-01T00:00:01.000Z'],
    });
  });

  it('reads as a recent incident', async () => {
    const { details } = await loadSampleIncident(NOW);
    expect(Date.parse(details.analyzed_at)).toBe(NOW - 2 * 60 * 60 * 1000);
  });

  it('claims no AI run and belongs to no project', async () => {
    const { details, history } = await loadSampleIncident(NOW);
    expect(details.model_name).toBeNull();
    expect(details.token_count).toBe(0);
    expect(details.project).toBeNull();
    expect(history.current_model).toBeNull();
    expect(details.batch_id).toBe('sample');
  });

  it('is served without calling the API', async () => {
    const logs = await DataService.getBatchLogs('sample');
    expect(logs.results.length).toBeGreaterThan(0);
    expect((await DataService.getBatchTimeline('sample')).events.length).toBeGreaterThan(0);
    expect(await DataService.getBatchDetails('sample')).toBeTruthy();
    expect((await DataService.getAnalysisHistory('sample')).analysis_count).toBe(0);
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it('shows the analysis, says it is an example, and offers nothing to act on', async () => {
    const { container } = renderSample();
    expect(await screen.findByRole('note')).toHaveTextContent('detail.incident.sampleBody');
    expect(await screen.findByText(/reduced the Redis connection pool/)).toBeInTheDocument();
    expect(screen.queryByText(/detail.incident.postmortem/)).toBeNull();
    expect(screen.queryByText(/detail.incident.copyLink/)).toBeNull();
    expect(screen.queryByText(/detail.incident.acknowledge/)).toBeNull();
    const links = [...container.querySelectorAll('a')].map((a) => a.getAttribute('href'));
    expect(links.filter((h) => h && h.includes('sample'))).toEqual([]);
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it('is offered on the step a new admin really lands on, and moves the wizard aside', () => {
    render(<MemoryRouter><OnboardingWizard /></MemoryRouter>);
    const link = screen.getByRole('link', { name: 'onboarding.viewSample' });
    expect(link).toHaveAttribute('href', '/dash/data/details/sample');
    fireEvent.click(link);
    expect(document.querySelector('.onboarding-wizard.minimized')).not.toBeNull();
  });

  it('is offered when there are no analyses yet', () => {
    render(<MemoryRouter><AIAnalysisFeed data={[]} /></MemoryRouter>);
    expect(screen.getByRole('link', { name: 'See a sample incident' })).toHaveAttribute('href', '/dash/data/details/sample');
  });

  it('has its text in every language', () => {
    for (const locale of [en, fr]) {
      expect(locale.detail.incident.sampleBody).toBeTruthy();
      expect(locale.onboarding.viewSample).toBeTruthy();
    }
  });
});
