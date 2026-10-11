/**
 * Cluster Service — Item #17.
 *
 * CRUD wrapper for /api/integrations/clusters/. Used by the Cluster
 * Settings page (admins) + any future cluster picker (Item #19).
 *
 * Cluster shape:
 *   { id, name, description, provider, provider_display, region,
 *     kubernetes_context, is_active, integration_count,
 *     created_at, updated_at }
 */

import apiClient from "./api-client";

const BASE = "/integrations/clusters";

const ClusterService = {
    list: async () => {
        const { data } = await apiClient.get(`${BASE}/`);
        // DRF ViewSet: raw list (no pagination wrapper on this endpoint).
        return Array.isArray(data) ? data : (data?.results || []);
    },

    get: async (id) => {
        const { data } = await apiClient.get(`${BASE}/${id}/`);
        return data;
    },

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

    // Workload view (Item #19) — projects + services in this cluster.
    workloads: async (id) => {
        const { data } = await apiClient.get(`${BASE}/${id}/workloads/`);
        return data;   // { cluster: {...}, projects: [{id, name, services: [...]}] }
    },
};

export default ClusterService;
