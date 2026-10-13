/**
 * Enterprise Settings Service
 * API calls for Security, Audit Log, Data Usage, and Retention Policy
 */

import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_BASE_URL || "/api";

const getAuthHeaders = () => {
    const token = localStorage.getItem("token");
    if (!token) {
        window.location.href = "/login";
        return {};
    }
    return {
        Authorization: `Token ${token}`,
    };
};

const enterpriseSettingsService = {
    // ============ SECURITY SETTINGS ============

    async getSecuritySettings() {
        try {
            const response = await axios.get(`${API_BASE_URL}/data/settings/security/`, {
                headers: getAuthHeaders()
            });
            return response.data;
        } catch (error) {
            console.error("Error fetching security settings:", error);
            throw error;
        }
    },

    async updateSecuritySettings(settings) {
        try {
            const response = await axios.put(`${API_BASE_URL}/data/settings/security/`, settings, {
                headers: getAuthHeaders()
            });
            return response.data;
        } catch (error) {
            console.error("Error updating security settings:", error);
            throw error;
        }
    },

    // ============ AUDIT LOG ============

    async getAuditLogs(params = {}) {
        try {
            const response = await axios.get(`${API_BASE_URL}/data/settings/audit-log/`, {
                headers: getAuthHeaders(),
                params
            });
            return response.data;
        } catch (error) {
            console.error("Error fetching audit logs:", error);
            throw error;
        }
    },

    async exportAuditLogs(params = {}) {
        try {
            const response = await axios.get(`${API_BASE_URL}/data/settings/audit-log/export/`, {
                headers: getAuthHeaders(),
                params,
                responseType: 'blob'
            });

            // Create download link
            const url = window.URL.createObjectURL(new Blob([response.data]));
            const link = document.createElement('a');
            link.href = url;
            link.setAttribute('download', `audit_log_${new Date().toISOString().split('T')[0]}.csv`);
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.URL.revokeObjectURL(url);

            return true;
        } catch (error) {
            console.error("Error exporting audit logs:", error);
            throw error;
        }
    },

    // ============ DATA USAGE ============

    async getDataUsage() {
        try {
            const response = await axios.get(`${API_BASE_URL}/data/settings/data-usage/`, {
                headers: getAuthHeaders()
            });
            return response.data;
        } catch (error) {
            console.error("Error fetching data usage:", error);
            throw error;
        }
    },

    // ============ RETENTION POLICY ============

    async getRetentionPolicy() {
        try {
            const response = await axios.get(`${API_BASE_URL}/data/settings/retention-policy/`, {
                headers: getAuthHeaders()
            });
            return response.data;
        } catch (error) {
            console.error("Error fetching retention policy:", error);
            throw error;
        }
    },

    async updateRetentionPolicy(policy) {
        try {
            const response = await axios.put(`${API_BASE_URL}/data/settings/retention-policy/`, policy, {
                headers: getAuthHeaders()
            });
            return response.data;
        } catch (error) {
            console.error("Error updating retention policy:", error);
            throw error;
        }
    },

    // ============ SSO CONFIGURATION ============

    async getSSOConfig() {
        try {
            const response = await axios.get(`${API_BASE_URL}/auth/sso/config`, {
                headers: getAuthHeaders()
            });
            return response.data;
        } catch (error) {
            console.error("Error fetching SSO config:", error);
            throw error;
        }
    },

    async updateSSOConfig(config) {
        try {
            const response = await axios.put(`${API_BASE_URL}/auth/sso/config`, config, {
                headers: getAuthHeaders()
            });
            return response.data;
        } catch (error) {
            console.error("Error updating SSO config:", error);
            throw error;
        }
    },

    async initSSO(email) {
        try {
            const response = await axios.post(`${API_BASE_URL}/auth/sso/init`, { email });
            return response.data;
        } catch (error) {
            console.error("Error initializing SSO:", error);
            throw error;
        }
    },

    // ============ ISSUE DEDUPLICATION SETTINGS ============

    async getIssueSettings() {
        try {
            const response = await axios.get(`${API_BASE_URL}/settings/issues/`, {
                headers: getAuthHeaders()
            });
            return response.data;
        } catch (error) {
            console.error("Error fetching issue settings:", error);
            throw error;
        }
    },

    async updateIssueSettings(settings) {
        try {
            const response = await axios.put(`${API_BASE_URL}/settings/issues/`, settings, {
                headers: getAuthHeaders()
            });
            return response.data;
        } catch (error) {
            console.error("Error updating issue settings:", error);
            throw error;
        }
    }
};

export default enterpriseSettingsService;

