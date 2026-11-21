import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

// The analysis page: references it cannot open are plain text, and it says
// when the log lines it lists are only part of what the analysis read.

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key, opts) => (opts && typeof opts === 'object' ? `${key} ${JSON.stringify(opts)}` : key) }),
}));
vi.mock('../BatchTimelineChart', () => ({ default: () => <div>timeline chart</div> }));
vi.mock('../onboarding', () => ({ PostOnboardingUpsells: () => null }));
vi.mock('../../services/notification.service', () => ({ default: { acknowledgeIssue: vi.fn() } }));

const svc = {
  getBatchLogs: vi.fn(),
  getBatchDetailsResult: vi.fn(),
  getBatchDetails: vi.fn(),
  getBatchTimeline: vi.fn(),
  getAnalysisHistory: vi.fn(),
};
vi.mock('../../services/data.service', () => ({ default: svc }));

const { default: Detail } = await import('../Detail');

const TRACE = '4bf92f3577b34da6a3ce929d0e0e4736';

const batch = ({ data = {}, issue = {} } = {}) => ({
  batch_id: 'shop-1',
  analyzed_at: '2026-11-01T10:00:00Z',
  analysis_text: 'The pool shrank',
  data,
  issues: [{
    id: 1, severity: 'CRITICAL', status: 'OPEN', description: 'payment-worker cannot reach Redis',
    component: 'payment-worker', ...issue,
  }],
});

const renderBatch = async (b) => {
  svc.getBatchDetailsResult.mockResolvedValue({ batch: b, notFound: false });
  render(
    <MemoryRouter initialEntries={['/dash/data/details/shop-1']}>
      <Routes><Route path="/dash/data/details/:batchId" element={<Detail />} /></Routes>
    </MemoryRouter>,
  );
  await screen.findByText('detail.incident.rootCause');
};

const chip = (label) => screen.getByText((text) => text.startsWith(label));

describe('Detail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.getItem.mockReset();
    svc.getBatchLogs.mockResolvedValue({ results: [] });
    svc.getBatchTimeline.mockResolvedValue({ events: [] });
    svc.getAnalysisHistory.mockResolvedValue({ analysis_history: [] });
  });

  describe('log lines shown', () => {
    const shown = () => screen.queryByText(/^detail\.logsShown/);

    it('says how many of the log lines are shown when some were left out', async () => {
      await renderBatch(batch({ data: { logs_kept: 200, logs_total: 4812 } }));
      expect(shown().textContent).toBe(
        `detail.logsShown ${JSON.stringify({ kept: (200).toLocaleString(), total: (4812).toLocaleString() })}`,
      );
    });

    it('says nothing when every line is shown', async () => {
      await renderBatch(batch({ data: { logs_kept: 200, logs_total: 200 } }));
      expect(shown()).toBeNull();
    });

    it('says nothing when the payload has no counts', async () => {
      await renderBatch(batch());
      expect(shown()).toBeNull();
    });
  });

  describe('token figure', () => {
    const tokens = () => screen.queryByText(/^detail\.incident\.tokens/);
    const withTokens = () => batch({ data: { token_count: 189843 } });

    it('is shown to a normal organisation', async () => {
      await renderBatch({ ...withTokens(), token_count: 189843 });
      expect(tokens()).not.toBeNull();
    });

    it('is not shown in the demo, where no token count was recorded', async () => {
      window.localStorage.getItem.mockImplementation((key) => (key === 'user' ? JSON.stringify({ is_demo: true }) : null));
      await renderBatch({ ...withTokens(), token_count: 189843 });
      expect(tokens()).toBeNull();
    });
  });

  describe('evidence chips', () => {
    it('link a commit and a trace the app can open', async () => {
      await renderBatch(batch({ issue: {
        correlation_summary: [{ type: 'commit', value: 'e7d3b201' }],
        related_traces: { top_errors: [{ trace_id: TRACE }] },
      } }));
      expect(chip('detail.incident.corrCommit').closest('a')).toHaveAttribute('href', '/dash/code-changes/shop-1?sha=e7d3b201');
      expect(chip('detail.incident.corrTrace').closest('a')).toHaveAttribute('href', `/dash/traces/${TRACE}`);
    });

    it('show a commit the analysis has no code change for as plain text', async () => {
      await renderBatch(batch({ issue: {
        correlation_summary: [{ type: 'commit', value: 'e7d3b201', in_batch: false }],
      } }));
      const commit = chip('detail.incident.corrCommit');
      expect(commit.tagName).toBe('SPAN');
      expect(commit.closest('a')).toBeNull();
      expect(document.querySelector('a[href*="sha=e7d3b201"]')).toBeNull();
    });

    it('show a trace that was not stored as plain text', async () => {
      await renderBatch(batch({ issue: {
        related_traces: { top_errors: [{ trace_id: TRACE, trace_stored: false }] },
      } }));
      const trace = chip('detail.incident.corrTrace');
      expect(trace.tagName).toBe('SPAN');
      expect(trace.closest('a')).toBeNull();
      expect(document.querySelector(`a[href*="${TRACE}"]`)).toBeNull();
    });
  });
});
