import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock apiClient before importing the service
vi.mock('../api-client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('../project.service', () => ({
  ProjectService: {},
}));

import apiClient from '../api-client';
import dataService from '../data.service';

describe('dataService.bulkAction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls correct endpoint with resolve payload', async () => {
    apiClient.post.mockResolvedValue({ data: { updated: 3 } });

    const result = await dataService.bulkAction([1, 2, 3], 'resolve');

    expect(apiClient.post).toHaveBeenCalledTimes(1);
    const [url, payload] = apiClient.post.mock.calls[0];
    expect(url).toContain('/data/issues/bulk-action/');
    expect(payload).toEqual({ issue_ids: [1, 2, 3], action: 'resolve' });
    expect(result).toEqual({ updated: 3 });
  });

  it('includes days parameter for mute action', async () => {
    apiClient.post.mockResolvedValue({ data: { updated: 2 } });

    await dataService.bulkAction([1, 2], 'mute', 14);

    const [, payload] = apiClient.post.mock.calls[0];
    expect(payload).toEqual({ issue_ids: [1, 2], action: 'mute', days: 14 });
  });

  it('calls correct endpoint with reopen payload', async () => {
    apiClient.post.mockResolvedValue({ data: { updated: 1 } });

    await dataService.bulkAction([5], 'reopen');

    const [, payload] = apiClient.post.mock.calls[0];
    expect(payload).toEqual({ issue_ids: [5], action: 'reopen' });
  });

  it('throws on API error', async () => {
    apiClient.post.mockRejectedValue(new Error('Network error'));

    await expect(dataService.bulkAction([1], 'resolve')).rejects.toThrow('Network error');
  });
});

describe('dataService.getIssues', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('maps created_at from API response', async () => {
    const mockDate = '2024-01-15T10:30:00Z';
    apiClient.get.mockResolvedValue({
      data: {
        results: [{
          id: 1,
          severity: 'WARNING',
          description: 'test',
          created_at: mockDate,
          issue_type: 'OTHER',
          status: 'OPEN',
          occurrence_count: 1,
        }],
        pagination: { total_issues: 1 },
        summary: {},
      },
    });

    const result = await dataService.getIssues();
    expect(result.results[0].created_at).toBe(mockDate);
  });
});

// RCA audit finding #11 (2026-09-20): re-analysis mode + promote endpoint.
describe('dataService.reanalyzeBatches (mode)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('defaults to compare mode when caller omits mode', async () => {
    apiClient.post.mockResolvedValue({ data: { status: 'queued' } });
    await dataService.reanalyzeBatches(['b1'], 'gemini');
    const [url, payload] = apiClient.post.mock.calls[0];
    expect(url).toBe('/data/batches/reanalyze/');
    expect(payload).toEqual({ batch_ids: ['b1'], model: 'gemini', mode: 'compare' });
  });

  it('forwards primary mode to the backend', async () => {
    apiClient.post.mockResolvedValue({ data: { status: 'queued' } });
    await dataService.reanalyzeBatches(['b1', 'b2'], 'claude', 'primary');
    const [, payload] = apiClient.post.mock.calls[0];
    expect(payload.mode).toBe('primary');
    expect(payload.batch_ids).toEqual(['b1', 'b2']);
    expect(payload.model).toBe('claude');
  });
});

describe('dataService.promoteAnalysisEntry', () => {
  beforeEach(() => vi.clearAllMocks());

  it('POSTs analyzed_at to the batch-specific promote endpoint', async () => {
    apiClient.post.mockResolvedValue({ data: { status: 'promoted', issues_created: 2 } });
    const result = await dataService.promoteAnalysisEntry('b1', '2026-09-20T05:00:00Z');
    const [url, payload] = apiClient.post.mock.calls[0];
    expect(url).toBe('/data/batches/b1/promote-analysis/');
    expect(payload).toEqual({ analyzed_at: '2026-09-20T05:00:00Z' });
    expect(result.issues_created).toBe(2);
  });
});

describe('dataService.getBatchMetrics — per-service collapse', () => {
  beforeEach(() => vi.clearAllMocks());

  // In Kubernetes the collectors aggregate by service_name, so every service
  // reports at the same instants. Handed to the chart as a flat list, the line
  // jumped between services at each timestamp.
  const twoServicesOneSaturating = {
    data: {
      data: {
        metrics: {
          memory_usage_percent: [
            { time: '2026-09-28T10:00:00Z', value: 20, series_key: 'api', source_table: 'memory_usage_percent' },
            { time: '2026-09-28T10:00:00Z', value: 95, series_key: 'cache', source_table: 'memory_usage_percent' },
            { time: '2026-09-28T10:00:30Z', value: 21, series_key: 'api', source_table: 'memory_usage_percent' },
            { time: '2026-09-28T10:00:30Z', value: 97, series_key: 'cache', source_table: 'memory_usage_percent' },
          ],
        },
      },
    },
  };

  it('returns one point per timestamp, not one per service', async () => {
    apiClient.get.mockResolvedValue(twoServicesOneSaturating);
    const result = await dataService.getBatchMetrics('b1', { type: 'memory_usage' });
    expect(result.count).toBe(2);
    expect(result.results.map((r) => r.timestamp)).toEqual([
      '2026-09-28T10:00:00Z',
      '2026-09-28T10:00:30Z',
    ]);
  });

  it('keeps the saturating service rather than averaging it away', async () => {
    apiClient.get.mockResolvedValue(twoServicesOneSaturating);
    const result = await dataService.getBatchMetrics('b1', { type: 'memory_usage' });
    expect(result.results.map((r) => r.value)).toEqual([95, 97]);
    expect(result.results.map((r) => r.service)).toEqual(['cache', 'cache']);
  });

  it('reports which services were present', async () => {
    apiClient.get.mockResolvedValue(twoServicesOneSaturating);
    const result = await dataService.getBatchMetrics('b1', { type: 'memory_usage' });
    expect(result.services).toEqual(['api', 'cache']);
  });

  it('handles VM-mode points that carry no series_key', async () => {
    apiClient.get.mockResolvedValue({
      data: { data: { metrics: { memory_usage_percent: [
        { time: '2026-09-28T10:00:00Z', value: 42, source_table: 'memory_usage_percent' },
      ] } } },
    });
    const result = await dataService.getBatchMetrics('b1', { type: 'memory_usage' });
    expect(result.count).toBe(1);
    expect(result.results[0].service).toBeNull();
    expect(result.services).toEqual([]);
  });

  it('averages over the collapsed points, so one hot service is not diluted', async () => {
    apiClient.get.mockResolvedValue(twoServicesOneSaturating);
    const result = await dataService.getBatchMetrics('b1', { type: 'memory_usage' });
    expect(result.average).toBe('96.00');
  });

  it('returns an empty shape when the batch has no metrics', async () => {
    apiClient.get.mockResolvedValue({ data: { data: {} } });
    const result = await dataService.getBatchMetrics('b1', { type: 'cpu_usage' });
    // trimmedAt distinguishes 'retention cleared this' from 'nothing was ever
    // collected' — the empty state shows a different message for each.
    expect(result).toEqual({
      results: [], count: 0, average: 0, services: [], trimmedAt: null,
    });
  });
});

// F3 · `metrics_summary` is the only part of a batch's metrics that survives
// the raw-point retention trim, and it is the shape the AI reasons over. It
// has also grown over time: `peak_pod` did not exist until the per-pod query
// was added, so every batch written before then has it as null. A normaliser
// that assumes today's shape would crash the metrics page on last month's
// batches.
describe('dataService.buildMetricSummary', () => {
  const full = {
    data: {
      metrics_summary: {
        memory: {
          usage_percent: { avg: 71, max: 98, current: 98, trend: 'INCREASING' },
          total_gb: 1.5,
          anomalies: [{ service: 'cache', peak_value: 98, duration_seconds: 240 }],
        },
        cpu: {
          usage_percent: { avg: 12, max: 20, current: 11, trend: 'STABLE' },
          anomalies: [{ service: 'api', peak_value: 99, duration_seconds: 60 }],
        },
        per_service: {
          memory_usage_percent: { cache: { avg: 71, max: 98 } },
          cpu_usage_percent: { api: { avg: 12, max: 20 } },
        },
        peak_pod: {
          memory_percent: { cache: { max: 99 } },
          memory_anomalies: [{ service: 'cache', peak_value: 99 }],
        },
        container_lifecycle: {
          terminated: [{ container: 'cache', reason: 'OOMKilled' }],
          restarts: { cache: 1 },
        },
        data_points: { memory_usage: 40 },
        time_range: { start: '2026-10-04T12:00:00Z' },
      },
    },
  };

  it('returns null when the batch has no summary', () => {
    expect(dataService.buildMetricSummary(null)).toBeNull();
    expect(dataService.buildMetricSummary({})).toBeNull();
    expect(dataService.buildMetricSummary({ data: {} })).toBeNull();
  });

  it('surfaces container terminations and restarts', () => {
    const out = dataService.buildMetricSummary(full);
    expect(out.terminated).toEqual([{ container: 'cache', reason: 'OOMKilled' }]);
    expect(out.restarts).toEqual({ cache: 1 });
  });

  it('merges anomalies into one list, tagged by kind and ranked by peak', () => {
    const out = dataService.buildMetricSummary(full);
    expect(out.anomalies.map((a) => a.kind)).toEqual(['cpu', 'peak_pod_memory', 'memory']);
    expect(out.anomalies[0].peak_value).toBe(99);
  });

  it('tolerates a batch written before peak_pod existed', () => {
    const legacy = {
      data: {
        metrics_summary: {
          ...full.data.metrics_summary,
          peak_pod: null,
          per_service: undefined,
        },
      },
    };
    const out = dataService.buildMetricSummary(legacy);
    expect(out.peakPodMemory).toEqual({});
    expect(out.perService).toEqual({ memory: {}, cpu: {} });
    // The anomalies that do exist still come through.
    expect(out.anomalies.map((a) => a.kind)).toEqual(['cpu', 'memory']);
  });

  it('keeps total_gb of zero rather than nulling it', () => {
    const zero = {
      data: { metrics_summary: { memory: { total_gb: 0 } } },
    };
    expect(dataService.buildMetricSummary(zero).totalMemoryGb).toBe(0);
  });
});

// F5 · getBatchMetrics collapses the per-service series to one point per
// timestamp, keeping the highest reading. That is the right number for an
// incident view — one container saturating its limit used to be averaged into
// a healthy-looking project figure — but it means the line moves between
// services, so which service each point belongs to has to travel with it.
describe('dataService.getBatchMetrics — per-service collapse', () => {
  beforeEach(() => vi.clearAllMocks());

  const points = (rows) => ({
    data: { data: { metrics: { memory_usage_percent: rows } } },
  });

  it('keeps the highest reading at each timestamp, with its service', async () => {
    apiClient.get.mockResolvedValue(points([
      { time: 't1', value: 20, series_key: 'api' },
      { time: 't1', value: 98, series_key: 'cache' },
      { time: 't1', value: 35, series_key: 'checkout' },
    ]));

    const out = await dataService.getBatchMetrics('b1', { type: 'memory_usage' });

    expect(out.results).toHaveLength(1);
    expect(out.results[0].value).toBe(98);
    expect(out.results[0].service).toBe('cache');
  });

  it('reports every service the line ranged over, sorted', async () => {
    apiClient.get.mockResolvedValue(points([
      { time: 't1', value: 20, series_key: 'checkout' },
      { time: 't1', value: 98, series_key: 'cache' },
      { time: 't2', value: 30, series_key: 'api' },
    ]));

    const out = await dataService.getBatchMetrics('b1', { type: 'memory_usage' });

    // Every service, not just the ones that won a timestamp — the caption has
    // to say what the chart covers, not what happened to peak.
    expect(out.services).toEqual(['api', 'cache', 'checkout']);
  });

  it("does not pass 'default' off as a service name", async () => {
    // metrics_processing names an unlabelled series 'default'. Carried
    // through, the tooltip read "Memory Usage · default" and the caption
    // listed a service that does not exist.
    apiClient.get.mockResolvedValue(points([
      { time: 't1', value: 55, series_key: 'default' },
    ]));

    const out = await dataService.getBatchMetrics('b1', { type: 'memory_usage' });

    expect(out.services).toEqual([]);
    expect(out.results[0].service).toBeNull();
    // The reading itself is still plotted.
    expect(out.results[0].value).toBe(55);
  });
});
