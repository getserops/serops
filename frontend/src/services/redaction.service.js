/**
 * Redaction Service — sensitive-data scanning + redaction reports.
 *
 * Migrated 2026-08-30 from raw ``fetch`` to the shared apiClient
 * so this service gets the same auto-Token header, same 401 →
 * login redirect, and same error shape as the rest of the app.
 */

import apiClient from './api-client';

/**
 * Scan a message for sensitive data. Used by chat to warn users
 * before sending potentially sensitive content.
 *
 * Failure mode: return a "safe" empty result rather than throwing
 * — a scan-service outage must not block the user from sending
 * their message (the backend redacts server-side too, this is
 * belt+braces UX).
 */
export const scanMessageForSensitiveData = async (message) => {
    try {
        const { data } = await apiClient.post('/utils/scan-message/', { message });
        return data;
    } catch (error) {
        console.error('[Redaction] scan failed:', error?.message || 'unknown');
        return {
            has_sensitive_data: false,
            findings: [],
            total_count: 0,
            critical_count: 0,
            high_count: 0,
            error: 'Scan failed',
        };
    }
};

/**
 * Get redaction report for a specific batch. Callers handle errors
 * — no fail-safe here because the caller usually wants to know if
 * the report is missing (report tabs render an error state).
 */
export const getRedactionReport = async (batchId) => {
    const { data } = await apiClient.get(`/data/batches/${batchId}/redaction/`);
    return data;
};

/** Get organisation-wide redaction statistics. */
export const getRedactionStats = async () => {
    const { data } = await apiClient.get('/data/redaction/stats/');
    return data;
};

export default {
    scanMessageForSensitiveData,
    getRedactionReport,
    getRedactionStats,
};
