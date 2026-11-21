import { describe, it, expect } from 'vitest';
import { tracePath, commitPath, logsTrimmed } from '../linkTargets';

describe('tracePath', () => {
  it('opens the trace when the payload does not say whether it was stored', () => {
    expect(tracePath({ trace_id: 'abc123' })).toBe('/dash/traces/abc123');
  });

  it('opens the trace when it was stored', () => {
    expect(tracePath({ trace_id: 'abc123', trace_stored: true })).toBe('/dash/traces/abc123');
  });

  it('has nowhere to go when the trace was not stored', () => {
    expect(tracePath({ trace_id: 'abc123', trace_stored: false })).toBeNull();
  });

  it('has nowhere to go without a trace id', () => {
    expect(tracePath(null)).toBeNull();
    expect(tracePath(undefined)).toBeNull();
    expect(tracePath({})).toBeNull();
    expect(tracePath({ trace_id: '', trace_stored: true })).toBeNull();
  });
});

describe('commitPath', () => {
  it('opens the code changes of the analysis for a linked commit', () => {
    expect(commitPath('shop-1', { sha: 'e7d3b201abc' })).toBe('/dash/code-changes/shop-1?sha=e7d3b201abc');
    expect(commitPath('shop-1', { sha: 'e7d3b201abc', in_batch: true })).toBe('/dash/code-changes/shop-1?sha=e7d3b201abc');
  });

  it('reads the sha of a correlation entry and of a bare string', () => {
    expect(commitPath('shop-1', { type: 'commit', value: 'e7d3b201' })).toBe('/dash/code-changes/shop-1?sha=e7d3b201');
    expect(commitPath('shop-1', 'e7d3b201')).toBe('/dash/code-changes/shop-1?sha=e7d3b201');
  });

  it('has nowhere to go when the analysis holds no code change for the sha', () => {
    expect(commitPath('shop-1', { sha: 'e7d3b201abc', in_batch: false })).toBeNull();
    expect(commitPath('shop-1', { type: 'commit', value: 'e7d3b201', in_batch: false })).toBeNull();
  });

  it('has nowhere to go without a sha or an analysis', () => {
    expect(commitPath('shop-1', null)).toBeNull();
    expect(commitPath('shop-1', {})).toBeNull();
    expect(commitPath('shop-1', '')).toBeNull();
    expect(commitPath(undefined, { sha: 'e7d3b201abc' })).toBeNull();
  });
});

describe('logsTrimmed', () => {
  it('gives both numbers when fewer lines are shown than were read', () => {
    expect(logsTrimmed({ logs_kept: 200, logs_total: 4812 })).toEqual({ kept: 200, total: 4812 });
  });

  it('is null when every line is shown', () => {
    expect(logsTrimmed({ logs_kept: 200, logs_total: 200 })).toBeNull();
  });

  it('is null when the payload does not say', () => {
    expect(logsTrimmed(undefined)).toBeNull();
    expect(logsTrimmed({})).toBeNull();
    expect(logsTrimmed({ logs_kept: 200 })).toBeNull();
    expect(logsTrimmed({ logs_kept: '200', logs_total: '4812' })).toBeNull();
  });
});
