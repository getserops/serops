/**
 * Observability Integration Service
 *
 * CRUD operations for ObservabilityIntegration (unified log + metric providers).
 * Endpoint: /integrations/observability/
 */

import apiClient from "./api-client";

const BASE = "/integrations/observability";

const ObservabilityService = {
    // ── LIST / DETAIL ────────────────────────────────────────────────
    getAll: async () => {
        const { data } = await apiClient.get(`${BASE}/`);
        return data;
    },

    get: async (id) => {
        const { data } = await apiClient.get(`${BASE}/${id}/`);
        return data;
    },

    // ── CREATE / UPDATE / DELETE ─────────────────────────────────────
    create: async (payload) => {
        const { data } = await apiClient.post(`${BASE}/`, payload);
        return data;
    },

    update: async (id, payload) => {
        const { data } = await apiClient.patch(`${BASE}/${id}/`, payload);
        return data;
    },

    delete: async (id) => {
        await apiClient.delete(`${BASE}/${id}/`);
    },

    // ── ACTIONS ──────────────────────────────────────────────────────
    healthCheck: async (id) => {
        const { data } = await apiClient.post(`${BASE}/${id}/health-check/`);
        return data;
    },

    getProviders: async () => {
        const { data } = await apiClient.get(`${BASE}/providers/`);
        return data;
    },
};

export default ObservabilityService;
