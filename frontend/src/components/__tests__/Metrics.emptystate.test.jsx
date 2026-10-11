import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// The Metrics page used to render a back button, a title and a filter label
// when a batch had no metric points — verified by rendering it, which produced
// exactly three words and no chart. A blank page reads as a broken page.
//
// Two causes worth telling apart: the retention task cleared the raw points
// (routine housekeeping, nothing to do) or nothing was ever collected (a metric
// provider is probably not connected). Showing the wrong one sends the operator
// hunting a fault that is not there.

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({ id: 'batch-1' }),
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key, vars) => (vars?.date ? `${key}:${vars.date}` : key),
  }),
}));

const svc = {
  getBatchMetrics: vi.fn(),
  getBatchDetails: vi.fn().mockResolvedValue({
    batch_id: 'batch-1', timestamp: '2026-10-04T00:00:00Z', environment: 'production',
  }),
  // Pure, so the real implementation is exercised in data.service's own
  // tests; here it just needs to answer 'this batch has no summary'.
  buildMetricSummary: vi.fn(() => null),
};
vi.mock('../../services/data.service', () => ({ default: svc }));

const { default: Metrics } = await import('../Metrics');

const EMPTY = { results: [], count: 0, average: 0, services: [], trimmedAt: null };
const POINTS = {
  results: [
    { timestamp: '2026-10-04T12:00:00Z', value: 95, service: 'cache' },
    { timestamp: '2026-10-04T12:00:30Z', value: 96, service: 'cache' },
  ],
  count: 2, average: '95.50', services: ['cache'], trimmedAt: null,
};

describe('Metrics empty state', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    svc.buildMetricSummary.mockReturnValue(null);
  });

  it('explains itself when nothing was collected', async () => {
    svc.getBatchMetrics.mockResolvedValue(EMPTY);
    render(<Metrics />);
    await waitFor(() => expect(screen.getByTestId('metrics-empty-state')).toBeTruthy());
    expect(screen.getByText('metrics.noMetricsTitle')).toBeTruthy();
    expect(screen.getByText('metrics.noMetricsCta')).toBeTruthy();
  });

  it('says "cleared" rather than "none" when retention trimmed the batch', async () => {
    svc.getBatchMetrics.mockResolvedValue({ ...EMPTY, trimmedAt: '2026-09-01T10:00:00Z' });
    render(<Metrics />);
    await waitFor(() => expect(screen.getByText('metrics.metricsTrimmedTitle')).toBeTruthy());
    // Must NOT suggest a misconfiguration — nothing is wrong.
    expect(screen.queryByText('metrics.noMetricsTitle')).toBeNull();
    expect(screen.queryByText('metrics.noMetricsCta')).toBeNull();
  });

  it('shows when it was cleared', async () => {
    svc.getBatchMetrics.mockResolvedValue({ ...EMPTY, trimmedAt: '2026-09-01T10:00:00Z' });
    render(<Metrics />);
    await waitFor(() =>
      expect(screen.getByText(/metrics\.metricsTrimmedWhen:/)).toBeTruthy());
  });

  it('stays out of the way when there are metrics', async () => {
    svc.getBatchMetrics.mockResolvedValue(POINTS);
    render(<Metrics />);
    await waitFor(() => expect(screen.getByText('metrics.memoryUsage')).toBeTruthy());
    expect(screen.queryByTestId('metrics-empty-state')).toBeNull();
  });

  it('does not flash the empty state before the fetch resolves', async () => {
    let release;
    svc.getBatchMetrics.mockReturnValue(new Promise(r => { release = () => r(POINTS); }));
    render(<Metrics />);
    expect(screen.queryByTestId('metrics-empty-state')).toBeNull();
    release();
    await waitFor(() => expect(screen.getByText('metrics.memoryUsage')).toBeTruthy());
  });
});

describe('Metrics host filter is gone', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    svc.buildMetricSummary.mockReturnValue(null);
  });

  it('does not request hosts on load', async () => {
    svc.getBatchMetrics.mockResolvedValue(EMPTY);
    render(<Metrics />);
    await waitFor(() => expect(screen.getByTestId('metrics-empty-state')).toBeTruthy());
    // getHosts is not even on the mocked service; referencing it would throw.
    expect(svc.getHosts).toBeUndefined();
  });

  it('renders exactly one dropdown — the type filter', async () => {
    svc.getBatchMetrics.mockResolvedValue(POINTS);
    render(<Metrics />);
    await waitFor(() => expect(screen.getByText('metrics.memoryUsage')).toBeTruthy());
    expect(document.querySelectorAll('.filter-dropdown').length).toBe(1);
  });
});

// F2/F3 · metrics_summary and container_lifecycle had zero references in the
// frontend: per-service figures, sustained anomalies and OOMKill reasons were
// computed, stored and sent to the AI while the page showed two charts of raw
// points and nothing else. The panel that fixes that has to survive the case
// the charts cannot cover — a batch past its raw-point retention, where the
// summary is all that is left.

const SUMMARY = {
  memory: { avg: 71, max: 98, current: 98, trend: 'INCREASING' },
  cpu: null,
  totalMemoryGb: 1.5,
  perService: {
    memory: { cache: { avg: 71, max: 98, current: 98, trend: 'INCREASING' } },
    cpu: {},
  },
  peakPodMemory: { cache: { max: 99 } },
  anomalies: [{ kind: 'memory', service: 'cache', peak_value: 98, duration_seconds: 240 }],
  terminated: [{ container: 'cache', reason: 'OOMKilled' }],
  restarts: { cache: 1 },
  dataPoints: {},
  timeRange: {},
};

describe('Metrics insights panel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    svc.buildMetricSummary.mockReturnValue(SUMMARY);
  });

  it('renders what the backend found alongside the charts', async () => {
    svc.getBatchMetrics.mockResolvedValue(POINTS);
    render(<Metrics />);
    await waitFor(() => expect(screen.getByTestId('metrics-insights')).toBeTruthy());
    expect(screen.getByText('OOMKilled')).toBeTruthy();
    expect(screen.getByText('metrics.terminationsTitle')).toBeTruthy();
    expect(screen.getByText('metrics.perServiceTitle')).toBeTruthy();
  });

  it('still renders after retention cleared the raw points', async () => {
    svc.getBatchMetrics.mockResolvedValue({ ...EMPTY, trimmedAt: '2026-09-01T10:00:00Z' });
    render(<Metrics />);
    await waitFor(() => expect(screen.getByTestId('metrics-insights')).toBeTruthy());
    // The chart is gone and says so; the findings are not.
    expect(screen.getByText('metrics.metricsTrimmedTitle')).toBeTruthy();
    expect(screen.getByText('OOMKilled')).toBeTruthy();
  });

  it('does not claim "no metrics" while findings are on screen', async () => {
    svc.getBatchMetrics.mockResolvedValue(EMPTY);
    render(<Metrics />);
    await waitFor(() => expect(screen.getByTestId('metrics-insights')).toBeTruthy());
    // No raw points and no retention trim, but a summary exists: telling the
    // operator to go connect a provider would send them after a fault that
    // is not there.
    expect(screen.queryByText('metrics.noMetricsTitle')).toBeNull();
    expect(screen.queryByTestId('metrics-empty-state')).toBeNull();
  });

  it('derives nothing from an empty summary, so the empty state still shows', async () => {
    svc.buildMetricSummary.mockReturnValue({
      memory: null, cpu: null, perService: { memory: {}, cpu: {} },
      peakPodMemory: {}, anomalies: [], terminated: [], restarts: {},
    });
    svc.getBatchMetrics.mockResolvedValue(EMPTY);
    render(<Metrics />);
    await waitFor(() => expect(screen.getByTestId('metrics-empty-state')).toBeTruthy());
    expect(screen.queryByTestId('metrics-insights')).toBeNull();
  });
});

// F5 · getBatchMetrics collapses the per-service series to one point per
// timestamp, keeping the highest reading, and returned the list of services it
// ranged over. Nothing read it, so a point at 98% gave no clue whose 98% it
// was — or that the line moves between services at all.

describe('Metrics peak-across-services caption', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    svc.buildMetricSummary.mockReturnValue(null);
  });

  it('names the services the peak line was drawn from', async () => {
    svc.getBatchMetrics.mockResolvedValue({ ...POINTS, services: ['api', 'cache', 'checkout'] });
    render(<Metrics />);
    const caption = await waitFor(() => screen.getByTestId('memory-peak-caption'));
    expect(caption.textContent).toContain('metrics.peakAcrossMany');
  });

  it('uses the singular phrasing for a single service', async () => {
    svc.getBatchMetrics.mockResolvedValue({ ...POINTS, services: ['cache'] });
    render(<Metrics />);
    const caption = await waitFor(() => screen.getByTestId('memory-peak-caption'));
    expect(caption.textContent).toContain('metrics.peakAcrossOne');
  });

  it("says nothing when the series carried no service label", async () => {
    // metrics_processing names an unlabelled series 'default'. A caption
    // reading "peak across 1 service: default" is worse than no caption.
    svc.getBatchMetrics.mockResolvedValue({ ...POINTS, services: ['default'] });
    render(<Metrics />);
    await waitFor(() => expect(screen.getByText('metrics.memoryUsage')).toBeTruthy());
    expect(screen.queryByTestId('memory-peak-caption')).toBeNull();
  });

  it('says nothing when the backend sent no services at all', async () => {
    svc.getBatchMetrics.mockResolvedValue({ ...POINTS, services: [] });
    render(<Metrics />);
    await waitFor(() => expect(screen.getByText('metrics.memoryUsage')).toBeTruthy());
    expect(screen.queryByTestId('memory-peak-caption')).toBeNull();
  });
});

// F6 · the page judged readings by its own numbers — amber above 70, red
// above 90 — written inline in five places. The backend flags memory above 75
// and CPU above 80, and those are the thresholds that decide what reaches the
// AI. A service at 78% memory therefore drew a calm amber line under a
// "Critical" cutoff it never crossed, directly below an analysis naming it as
// the cause.

const atValue = (v) => ({
  results: [
    { timestamp: '2026-10-04T12:00:00Z', value: v, service: 'cache' },
    { timestamp: '2026-10-04T12:00:30Z', value: v, service: 'cache' },
  ],
  count: 2, average: String(v), services: ['cache'], trimmedAt: null,
});

describe('Metrics threshold bands follow the backend detector', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    svc.buildMetricSummary.mockReturnValue(null);
  });

  const renderAt = async (memory, cpu) => {
    svc.getBatchMetrics.mockImplementation((_id, { type }) =>
      Promise.resolve(atValue(type === 'cpu_usage' ? cpu : memory)));
    render(<Metrics />);
    await waitFor(() => expect(screen.getByText('metrics.memoryUsage')).toBeTruthy());
  };

  it('calls 78% memory flagged, as the backend does', async () => {
    await renderAt(78, 10);
    // Memory is over its 75 line; CPU at 10 is not.
    expect(screen.getByText('metrics.levelOver')).toBeTruthy();
    expect(screen.getByText('metrics.levelHealthy')).toBeTruthy();
  });

  it('calls the same 78% unflagged for CPU, whose line is 80', async () => {
    await renderAt(10, 78);
    expect(screen.getByText('metrics.levelApproaching')).toBeTruthy();
    expect(screen.getByText('metrics.levelHealthy')).toBeTruthy();
    expect(screen.queryByText('metrics.levelOver')).toBeNull();
  });

  it('gives the CPU gauge a level badge too', async () => {
    // The memory gauge carried one and this one did not, so the same reading
    // read as judged on one card and unjudged on the other.
    await renderAt(90, 90);
    expect(screen.getAllByText('metrics.levelOver')).toHaveLength(2);
  });
});
