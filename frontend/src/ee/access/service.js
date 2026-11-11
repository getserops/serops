// Enterprise access management API (backend ee/access, /api/ee/...).
import apiClient from '../../services/api-client';

export const AccessService = {
    createRole: async (role) => (await apiClient.post('/ee/roles/', role)).data,
    updateRole: async (id, role) => (await apiClient.put(`/ee/roles/${id}/`, role)).data,
    deleteRole: async (id) => { await apiClient.delete(`/ee/roles/${id}/`); },
    getProjectAccess: async (projectId) => (await apiClient.get(`/ee/projects/${projectId}/access/`)).data,
    updateProjectAccess: async (projectId, access) => (await apiClient.put(`/ee/projects/${projectId}/access/`, access)).data,
};
