/**
 * DeploymentService — CRUD + suggest for ProjectDeployment (Batch 52).
 *
 * ProjectDeployment is the new unit of "where a project runs"
 * (env × cluster × region × namespace). This service wraps the
 * REST viewset at /api/project-deployments/.
 *
 * Uses apiClient (not raw axios) so 401 → login redirect flows through
 * the shared interceptor.
 */

import apiClient from './api-client';

// apiClient prepends baseURL (VITE_BASE_URL) automatically. Path-only
// constant here — a leading /api would double-prefix to /api/api/...
// Mounted under Projects.urls (see backend/Projects/urls.py) which is
// itself mounted at /api/projects/ — matching the sibling scm-bindings
// and cicd-bindings viewsets.
const BASE = "/projects/deployments";

const DeploymentService = {
    /**
     * List deployments — optionally filtered by project.
     * ``project`` argument = numeric project id.
     */
    list: async (project = null) => {
        const params = project != null ? { project } : {};
        const { data } = await apiClient.get(`${BASE}/`, { params });
        // DRF ModelViewSet returns paginated ({results, count, ...}) OR
        // a raw list depending on the pagination class. Handle both.
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

    /**
     * Suggestions for a newly-registered cluster.
     *
     * Returns:
     *   { cluster_id, suggestions: [{project_id, project_name,
     *     environment_id, environment_name, reason}, ...] }
     *
     * Per the "suggest, don't auto-create" design decision — the caller
     * shows these as a modal + user accepts individual rows.
     */
    suggest: async (clusterId) => {
        const { data } = await apiClient.get(`${BASE}/suggest/`, {
            params: { cluster: clusterId },
        });
        return data;
    },
};

export default DeploymentService;
