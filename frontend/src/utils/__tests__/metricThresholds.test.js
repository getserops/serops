import { describe, it, expect } from 'vitest';
import {
    METRIC_THRESHOLDS,
    thresholdsFor,
    levelFor,
    colorFor,
    variantFor,
} from '../metricThresholds';

// These numbers are not styling. They are the thresholds
// integrations/metrics_processing.py passes to detect_anomalies, which decide
// what becomes an anomaly, what reaches the AI prompt, and what the analysis
// talks about. The chart used 70/90 — numbers that exist nowhere in the
// backend — so a service at 78% memory drew a calm amber line under a
// "Critical" cutoff it never crossed, while the backend had flagged it and the
// AI had written it up as the cause directly above.

describe('METRIC_THRESHOLDS mirrors the backend detector', () => {
    it('matches detect_anomalies(memory_usage, 75.0)', () => {
        expect(METRIC_THRESHOLDS.memory).toBe(75);
    });

    it('matches detect_anomalies(cpu_usage, 80.0)', () => {
        expect(METRIC_THRESHOLDS.cpu).toBe(80);
    });
});

describe('thresholdsFor', () => {
    it('derives the approaching band from the threshold, not a second guess', () => {
        expect(thresholdsFor('memory')).toEqual({ over: 75, approaching: 68 });
        expect(thresholdsFor('cpu')).toEqual({ over: 80, approaching: 72 });
    });

    it('falls back to memory for an unknown metric rather than undefined', () => {
        expect(thresholdsFor('disk').over).toBe(75);
    });
});

describe('levelFor', () => {
    it('flags above the threshold, matching what the backend would record', () => {
        // 78% memory is an anomaly to the backend. Under the old 90% cutoff
        // the page called it a warning.
        expect(levelFor(78, 'memory')).toBe('over');
        // The same reading is not yet an anomaly for CPU, whose line is 80.
        expect(levelFor(78, 'cpu')).toBe('approaching');
    });

    it('is exclusive at the boundary, as the backend comparison is', () => {
        // metrics_processing: `if value > threshold_percent`.
        expect(levelFor(75, 'memory')).toBe('approaching');
        expect(levelFor(75.1, 'memory')).toBe('over');
    });

    it('calls the run-up to the threshold out instead of plain green', () => {
        expect(levelFor(69, 'memory')).toBe('approaching');
        expect(levelFor(68, 'memory')).toBe('healthy');
    });

    it('treats a missing reading as healthy, not as an anomaly', () => {
        expect(levelFor(null, 'memory')).toBe('healthy');
        expect(levelFor(undefined, 'memory')).toBe('healthy');
    });
});

describe('colorFor / variantFor', () => {
    it('agree on the band', () => {
        expect(colorFor(99, 'memory')).toBe('#dc3545');
        expect(variantFor(99, 'memory')).toBe('danger');
        expect(variantFor(70, 'memory')).toBe('warning');
        expect(variantFor(10, 'memory')).toBe('success');
    });

    it('gives the same reading different bands per metric', () => {
        // The whole point of threading the metric through: 79% is flagged
        // memory and unflagged CPU.
        expect(variantFor(79, 'memory')).toBe('danger');
        expect(variantFor(79, 'cpu')).toBe('warning');
    });
});
