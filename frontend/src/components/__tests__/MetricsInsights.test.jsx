import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

// The panel's job is to make visible what was already being computed: the
// per-service figures, the sustained anomalies and — the one that made memory
// exhaustion diagnosable at all — the kubelet's container terminations. A
// container killed for exceeding its memory limit writes no log line, so an
// OOMKill that is not shown here is not shown anywhere.

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key) => key }),
}));

const { default: MetricsInsights, deriveInsights } = await import('../MetricsInsights');

const base = {
  perService: { memory: {}, cpu: {} },
  peakPodMemory: {},
  anomalies: [],
  terminated: [],
  restarts: {},
};

describe('deriveInsights', () => {
  it('returns null when there is nothing to show', () => {
    expect(deriveInsights(null)).toBeNull();
    expect(deriveInsights(undefined)).toBeNull();
    expect(deriveInsights({})).toBeNull();
    expect(deriveInsights(base)).toBeNull();
  });

  it('ignores a restart count of zero', () => {
    // kube-state-metrics reports every container, restarted or not. A panel
    // listing "api: 0 restarts" is noise that pushes the real one off screen.
    expect(deriveInsights({ ...base, restarts: { api: 0, web: 0 } })).toBeNull();
    expect(deriveInsights({ ...base, restarts: { api: 0, cache: 2 } }).busyRestarts)
      .toEqual([['cache', 2]]);
  });

  it('drops services whose stats never resolved', () => {
    const out = deriveInsights({
      ...base,
      perService: { memory: { api: { avg: null, max: null }, cache: { avg: 70, max: 98 } }, cpu: {} },
    });
    expect(out.serviceRows.map((r) => r.name)).toEqual(['cache']);
  });

  it('ranks services by peak, not by name', () => {
    const out = deriveInsights({
      ...base,
      perService: {
        memory: {
          api: { avg: 10, max: 22 },
          cache: { avg: 70, max: 98 },
          web: { avg: 30, max: 55 },
        },
        cpu: {},
      },
    });
    expect(out.serviceRows.map((r) => r.name)).toEqual(['cache', 'web', 'api']);
  });

  it('joins the worst single pod onto its service, and tolerates it missing', () => {
    const out = deriveInsights({
      ...base,
      perService: { memory: { cache: { avg: 70, max: 80 }, api: { avg: 5, max: 9 } }, cpu: {} },
      peakPodMemory: { cache: { max: 99 } },
    });
    const byName = Object.fromEntries(out.serviceRows.map((r) => [r.name, r.worstPod]));
    expect(byName.cache).toBe(99);
    expect(byName.api).toBeNull();
  });
});

describe('MetricsInsights', () => {
  it('renders nothing rather than an empty shell', () => {
    const { container } = render(<MetricsInsights summary={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('names the termination reason, which no log line carries', () => {
    render(<MetricsInsights summary={{
      ...base,
      terminated: [{ container: 'cache', reason: 'OOMKilled' }],
      restarts: { cache: 1 },
    }} />);
    // Named twice — once for the kill, once for the restart it caused.
    expect(screen.getAllByText('cache').length).toBe(2);
    expect(screen.getByText('OOMKilled')).toBeTruthy();
    expect(screen.getByText('metrics.restartsTitle')).toBeTruthy();
  });

  it('labels each anomaly with the metric it came from', () => {
    render(<MetricsInsights summary={{
      ...base,
      anomalies: [
        { kind: 'peak_pod_memory', service: 'cache', peak_value: 99, duration_seconds: 240 },
        { kind: 'cpu', service: 'api', peak_value: 88, duration_seconds: 30 },
      ],
    }} />);
    // Without the kind, "cache 99%" and "api 88%" are indistinguishable:
    // one is a single pod's memory, the other a service's CPU.
    expect(screen.getByText('metrics.kindPeakPodMemory')).toBeTruthy();
    expect(screen.getAllByText('metrics.kindCpu').length).toBeGreaterThan(0);
    expect(screen.getByText(/4m/)).toBeTruthy();
    expect(screen.getByText(/30s/)).toBeTruthy();
  });

  it('says so when a window held no sustained anomaly', () => {
    render(<MetricsInsights summary={{
      ...base,
      perService: { memory: { api: { avg: 10, max: 22, current: 11, trend: 'STABLE' } }, cpu: {} },
    }} />);
    expect(screen.getByText('metrics.noAnomalies')).toBeTruthy();
  });

  it('flags a pod running far hotter than its service average', () => {
    // This gap is the whole reason the per-pod query exists: a service at 40%
    // with one replica at 99% is one OOMKill away, and the average says
    // nothing is wrong.
    render(<MetricsInsights summary={{
      ...base,
      perService: { memory: { cache: { avg: 35, max: 40, current: 38, trend: 'STABLE' } }, cpu: {} },
      peakPodMemory: { cache: { max: 99 } },
    }} />);
    const cell = screen.getByText('99%');
    expect(cell.className).toContain('text-danger');
  });

  it('does not flag a pod in line with its service', () => {
    render(<MetricsInsights summary={{
      ...base,
      perService: { memory: { cache: { avg: 90, max: 95, current: 94, trend: 'STABLE' } }, cpu: {} },
      peakPodMemory: { cache: { max: 96 } },
    }} />);
    expect(screen.getByText('96%').className).not.toContain('text-danger');
  });

  it("names the 'default' series for what it is", () => {
    // metrics_processing names an unlabelled series 'default'. Printed raw it
    // reads as a service called default, which does not exist.
    render(<MetricsInsights summary={{
      ...base,
      terminated: [{ container: 'default', reason: 'Error' }],
    }} />);
    expect(screen.getByText('metrics.unlabelledContainers')).toBeTruthy();
    expect(screen.queryByText('default')).toBeNull();
  });

  it('translates the four trends the backend emits', () => {
    render(<MetricsInsights summary={{
      ...base,
      perService: { memory: { api: { avg: 10, max: 22, current: 11, trend: 'INCREASING' } }, cpu: {} },
    }} />);
    expect(screen.getByText(/metrics\.trendIncreasing/)).toBeTruthy();
  });

  it('falls back to the raw value for a trend it does not know', () => {
    // A trend added to metrics_processing later must read as itself rather
    // than as a missing translation key or a blank cell.
    render(<MetricsInsights summary={{
      ...base,
      perService: { memory: { api: { avg: 10, max: 22, current: 11, trend: 'WOBBLY' } }, cpu: {} },
    }} />);
    expect(screen.getByText(/WOBBLY/)).toBeTruthy();
  });
});
