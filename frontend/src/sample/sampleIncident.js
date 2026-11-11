/**
 * The sample incident shown to a new install before anything is connected.
 *
 * It is a fixture, not rows in the organisation: rows would tick onboarding
 * steps the user has not done and appear in their dashboards. incident.json
 * has the exact shape of the batch API, captured from the demo incident, so
 * the real incident page renders it. Nothing here calls an AI provider.
 */
export const SAMPLE_BATCH_ID = 'sample';
export const SAMPLE_PATH = `/dash/data/details/${SAMPLE_BATCH_ID}`;

export const isSampleBatch = (batchId) => batchId === SAMPLE_BATCH_ID;

const ISO_DATE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/;
const ANALYSED_AGO_MS = 2 * 60 * 60 * 1000;

/** A copy of ``value`` with every ISO timestamp moved by ``shiftMs``. */
export function shiftDates(value, shiftMs) {
    if (typeof value === 'string') {
        return ISO_DATE.test(value)
            ? new Date(new Date(value).getTime() + shiftMs).toISOString()
            : value;
    }
    if (Array.isArray(value)) return value.map((v) => shiftDates(v, shiftMs));
    if (value && typeof value === 'object') {
        return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, shiftDates(v, shiftMs)]));
    }
    return value;
}

/** The fixture, dated as if the analysis finished two hours ago. */
export async function loadSampleIncident(now = Date.now()) {
    const { default: incident } = await import('./incident.json');
    const analysedAt = new Date(incident.details.analyzed_at).getTime();
    return shiftDates(incident, now - ANALYSED_AGO_MS - analysedAt);
}
