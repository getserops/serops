/**
 * The utilisation thresholds SerOps actually judges metrics by.
 *
 * These are not UI preferences. They are the numbers
 * ``integrations/metrics_processing.py`` passes to ``detect_anomalies`` — 75%
 * for memory, 80% for CPU — which decide what gets recorded as an anomaly,
 * what reaches the AI prompt, and therefore what the analysis talks about.
 *
 * The metrics page had its own: amber above 70, red above 90, written inline
 * in five places. Neither number exists anywhere in the backend. The visible
 * consequence was a chart that disagreed with the analysis printed beside it —
 * a service sitting at 78% memory drew a calm amber line below a "Critical"
 * cutoff it never crossed, while the backend had already flagged it, told the
 * AI about it, and the AI had written it up as the cause. An operator
 * comparing the two could only conclude one of them was wrong.
 *
 * So the chart reads its lines from here, and here mirrors the backend. If the
 * backend thresholds change, this file changes with them — nothing else.
 *
 * There is deliberately no "critical" tier. The backend has exactly one
 * threshold per metric; its second axis is *duration*, not a higher number
 * (an anomaly is "sustained" when over 80% of the window's points are above
 * the line). Inventing a second cutoff here would put a severity on screen
 * that no part of the system computes.
 */

// Mirrors the detect_anomalies() calls in metrics_processing.build_summary.
export const METRIC_THRESHOLDS = {
    memory: 75,
    cpu: 80,
};

// How close to the threshold still deserves attention. Derived rather than
// chosen: a service at 90% of its detection threshold has not been flagged,
// but it is the one to watch, and showing it as plain healthy green hides the
// approach to a limit — which is the part an operator can still act on.
export const APPROACHING_FACTOR = 0.9;

const COLORS = {
    over: "#dc3545",
    approaching: "#ffc107",
    healthy: "#28a745",
};

/** The flagging threshold for a metric, and the band leading up to it. */
export const thresholdsFor = (metric) => {
    const over = METRIC_THRESHOLDS[metric] ?? METRIC_THRESHOLDS.memory;
    return { over, approaching: Math.round(over * APPROACHING_FACTOR) };
};

/**
 * Which band a reading falls in: 'over' is what the backend would flag,
 * 'approaching' is the run-up to it, 'healthy' is everything else.
 */
export const levelFor = (value, metric) => {
    const { over, approaching } = thresholdsFor(metric);
    const v = Number(value) || 0;
    if (v > over) return "over";
    if (v > approaching) return "approaching";
    return "healthy";
};

export const colorFor = (value, metric) => COLORS[levelFor(value, metric)];

/** Bootstrap contextual class for the same three bands. */
export const variantFor = (value, metric) =>
    ({ over: "danger", approaching: "warning", healthy: "success" }[
        levelFor(value, metric)
    ]);
