/**
 * Distributed Traces Service
 *
 * Wraps /api/traces/ — split between two concerns:
 *
 *   Ingest keys  — org admin CRUD for OTLP bearer tokens
 *   Trace read   — list + detail + service list for the dashboard
 *
 * Multi-tenancy + auth are enforced server-side; this client just
 * shapes params.
 */

import apiClient from "./api-client";

const KEYS_BASE = "/traces/keys";
const TRACES_BASE = "/traces/traces";

// ── Ingest keys ──────────────────────────────────────────────────
const IngestKeys = {
    list: async () => {
        const { data } = await apiClient.get(`${KEYS_BASE}/`);
        return data;
    },

    // Returns { id, name, key_prefix, is_active, plaintext, message, ... }
    // — plaintext is ONLY present on this response, never on list/get.
    create: async (name) => {
        const { data } = await apiClient.post(`${KEYS_BASE}/`, { name });
        return data;
    },

    // Soft-delete (revoke). Backend flips is_active=false.
    revoke: async (id) => {
        await apiClient.delete(`${KEYS_BASE}/${id}/`);
    },
};

// ── Trace read ───────────────────────────────────────────────────
const Traces = {
    // Filters: { service, status, min_duration_ms, since, until, page, page_size }
    // — all optional; unknown keys are ignored server-side.
    list: async (filters = {}) => {
        const params = {};
        Object.entries(filters).forEach(([k, v]) => {
            if (v !== undefined && v !== null && v !== "") {
                params[k] = v;
            }
        });
        const { data } = await apiClient.get(`${TRACES_BASE}/`, { params });
        return data;   // { count, next, previous, results: [...] }
    },

    get: async (traceId) => {
        const { data } = await apiClient.get(`${TRACES_BASE}/${traceId}/`);
        return data;   // { trace_id, ..., spans: [...] }
    },

    // Distinct service names for the filter dropdown.
    services: async () => {
        const { data } = await apiClient.get(`${TRACES_BASE}/services/`);
        return data;   // ['api', 'checkout', ...]
    },
};

const TracesService = { IngestKeys, Traces };
export default TracesService;
