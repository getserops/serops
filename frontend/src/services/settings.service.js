/**
 * Settings Service
 * Handles API calls for organisation settings (notifications, AI, etc.)
 */

import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_BASE_URL + "/settings";
const NOTIF_API = import.meta.env.VITE_BASE_URL + "/notification";
const ORG_API = import.meta.env.VITE_BASE_URL + "/organisation";

// Helper to get auth headers
const getAuthHeaders = () => {
    const token = localStorage.getItem("token");
    return {
        headers: {
            Authorization: `Token ${token}`,
        },
    };
};

export const SettingsService = {
    // ==================== DELIVERY CHANNELS (PR-N phase 2) ====================
    // Matches the Grafana / Alertmanager "Contact Points" pattern.
    // Backed by notifications.IncidentNotificationChannel.

    listDeliveryChannels: async () => {
        const r = await axios.get(`${NOTIF_API}/incident-channels/`, getAuthHeaders());
        return r.data;
    },

    createDeliveryChannel: async (payload) => {
        const r = await axios.post(`${NOTIF_API}/incident-channels/`, payload, getAuthHeaders());
        return r.data;
    },

    updateDeliveryChannel: async (id, payload) => {
        const r = await axios.patch(`${NOTIF_API}/incident-channels/${id}/`, payload, getAuthHeaders());
        return r.data;
    },

    deleteDeliveryChannel: async (id) => {
        await axios.delete(`${NOTIF_API}/incident-channels/${id}/`, getAuthHeaders());
        return true;
    },

    // ==================== ROUTING RULES (PR-N phase 2) ====================
    // Matches the Alertmanager "route tree" pattern (flat table for now).
    // Backed by notifications.NotificationRoutingRule.

    listRoutingRules: async () => {
        const r = await axios.get(`${NOTIF_API}/routing-rules/`, getAuthHeaders());
        return r.data;
    },

    createRoutingRule: async (payload) => {
        const r = await axios.post(`${NOTIF_API}/routing-rules/`, payload, getAuthHeaders());
        return r.data;
    },

    updateRoutingRule: async (id, payload) => {
        const r = await axios.patch(`${NOTIF_API}/routing-rules/${id}/`, payload, getAuthHeaders());
        return r.data;
    },

    deleteRoutingRule: async (id) => {
        await axios.delete(`${NOTIF_API}/routing-rules/${id}/`, getAuthHeaders());
        return true;
    },

    // ==================== ALERT-INGEST SECRET (Q5-5) ====================

    getAlertIngestSecret: async () => {
        const r = await axios.get(`${ORG_API}/alert-secret/`, getAuthHeaders());
        return r.data;
    },

    rotateAlertIngestSecret: async () => {
        const r = await axios.post(`${ORG_API}/alert-secret/rotate/`, {}, getAuthHeaders());
        return r.data;
    },

    /**
     * Test a webhook (Slack or Teams) — retained from phase 1 for the
     * per-channel test button on Delivery Channels.
     */
    testWebhook: async (webhookType, webhookUrl) => {
        try {
            const response = await axios.post(
                `${API_BASE_URL}/notifications/test/`,
                { webhook_type: webhookType, webhook_url: webhookUrl },
                getAuthHeaders()
            );
            return response.data;
        } catch (error) {
            console.error("Error testing webhook:", error);
            throw error;
        }
    },

    // ==================== AI SETTINGS ====================

    /**
     * Get available AI providers
     */
    getAIProviders: async () => {
        try {
            const response = await axios.get(
                `${API_BASE_URL}/ai/providers/`,
                getAuthHeaders()
            );
            return response.data;
        } catch (error) {
            console.error("Error fetching AI providers:", error);
            throw error;
        }
    },

    /**
     * Create a new AI provider
     */
    createAIProvider: async (providerData) => {
        try {
            const response = await axios.post(
                `${API_BASE_URL}/ai/providers/`,
                providerData,
                getAuthHeaders()
            );
            return response.data;
        } catch (error) {
            console.error("Error creating AI provider:", error);
            throw error;
        }
    },

    /**
     * Update an AI provider
     */
    updateAIProvider: async (id, providerData) => {
        try {
            const response = await axios.put(
                `${API_BASE_URL}/ai/providers/${id}/`,
                providerData,
                getAuthHeaders()
            );
            return response.data;
        } catch (error) {
            console.error("Error updating AI provider:", error);
            throw error;
        }
    },

    /**
     * Delete an AI provider
     */
    deleteAIProvider: async (id) => {
        try {
            await axios.delete(
                `${API_BASE_URL}/ai/providers/${id}/`,
                getAuthHeaders()
            );
        } catch (error) {
            console.error("Error deleting AI provider:", error);
            throw error;
        }
    },

    /**
     * Get current AI settings
     */
    getAISettings: async () => {
        try {
            const response = await axios.get(
                `${API_BASE_URL}/ai/`,
                getAuthHeaders()
            );
            return response.data;
        } catch (error) {
            console.error("Error fetching AI settings:", error);
            throw error;
        }
    },

    /**
     * Update AI settings
     */
    updateAISettings: async (settings) => {
        try {
            const response = await axios.put(
                `${API_BASE_URL}/ai/`,
                settings,
                getAuthHeaders()
            );
            return response.data;
        } catch (error) {
            console.error("Error updating AI settings:", error);
            throw error;
        }
    },

    /**
     * Get current AI cost budget snapshot (Batch 26 endpoint).
     * Returns:
     *   {
     *     monthly_budget_usd:   "100.00" | null,   // null = unlimited
     *     current_spend_usd:    "234.57",          // Decimal serialised as string
     *     remaining_usd:        "-134.57" | null,
     *     warn_threshold_pct:   80,
     *     is_warning:           bool,
     *     is_exceeded:          bool,
     *     month_start_utc:      "2026-09-01T00:00:00+00:00"
     *   }
     * Cheap for unlimited orgs (short-circuits before DB scan). Fail-
     * open on backend errors — caller should assume budget may be
     * misconfigured, not that AI is paused.
     */
    getAIBudgetStatus: async () => {
        try {
            const response = await axios.get(
                `${API_BASE_URL}/ai/budget/`,
                getAuthHeaders()
            );
            return response.data;
        } catch (error) {
            console.error("Error fetching AI budget status:", error);
            throw error;
        }
    },

    /**
     * Test AI connection
     */
    testAIConnection: async (providerName, apiKey = null) => {
        try {
            const payload = { provider_name: providerName };
            if (apiKey) {
                payload.api_key = apiKey;
            }
            const response = await axios.post(
                `${API_BASE_URL}/ai/test/`,
                payload,
                getAuthHeaders()
            );
            return response.data;
        } catch (error) {
            console.error("Error testing AI connection:", error);
            throw error;
        }
    },

    /**
     * Get available models for re-analysis and chat.
     *
     * Returns providers where the org has an API key configured (or
     * a provider-side env var). Empty ``models`` list means "no AI
     * provider set up yet" — UI must show an empty state pointing to
     * Settings → AI, not a hardcoded fallback list that would 500 on
     * first use.
     *
     * Bug-fix history: URL was previously ``/ai/available-models/``
     * — 404 on every call, so ``useChatIssues`` always fell into its
     * catch block and rendered a stale [Gemini, DeepSeek] hardcoded
     * fallback in the model dropdown. Correct route is
     * ``/settings/ai/available-models/`` (see backend org_settings/urls.py).
     */
    getAvailableModels: async () => {
        try {
            // API_BASE_URL already ends in /settings — do NOT add
            // another /settings/ here. The doubled path silently 404'd
            // for months; the catch below then set availableModels to
            // [] and the chat top-bar rendered 'No AI provider' even
            // when the org had Claude + Gemini keys configured.
            const response = await axios.get(
                `${API_BASE_URL}/ai/available-models/`,
                getAuthHeaders()
            );
            return response.data;
        } catch (error) {
            console.error("Error fetching available models:", error);
            throw error;
        }
    },

    // ==================== SENTINEL CONFIG ====================

    /**
     * Get current sentinel configuration
     */
    getSentinelConfig: async () => {
        try {
            const response = await axios.get(
                `${API_BASE_URL}/sentinel/`,
                getAuthHeaders()
            );
            return response.data;
        } catch (error) {
            console.error("Error fetching sentinel config:", error);
            throw error;
        }
    },

    /**
     * Update sentinel configuration
     */
    updateSentinelConfig: async (config) => {
        try {
            const response = await axios.put(
                `${API_BASE_URL}/sentinel/`,
                config,
                getAuthHeaders()
            );
            return response.data;
        } catch (error) {
            console.error("Error updating sentinel config:", error);
            throw error;
        }
    },

    // ==================== API KEYS ====================

    /**
     * Get all API keys (masked)
     */
    getAPIKeys: async () => {
        try {
            const response = await axios.get(
                `${API_BASE_URL}/api-keys/`,
                getAuthHeaders()
            );
            return response.data;
        } catch (error) {
            console.error("Error fetching API keys:", error);
            throw error;
        }
    },

    /**
     * Add or update an API key
     */
    saveAPIKey: async (providerId, apiKey, baseUrl = null) => {
        try {
            const payload = { provider_id: providerId, api_key: apiKey };
            if (baseUrl) {
                payload.base_url = baseUrl;
            }
            const response = await axios.post(
                `${API_BASE_URL}/api-keys/`,
                payload,
                getAuthHeaders()
            );
            return response.data;
        } catch (error) {
            console.error("Error saving API key:", error);
            throw error;
        }
    },

    /**
     * Delete an API key
     */
    deleteAPIKey: async (providerId) => {
        try {
            await axios.delete(
                `${API_BASE_URL}/api-keys/${providerId}/`,
                getAuthHeaders()
            );
        } catch (error) {
            console.error("Error deleting API key:", error);
            throw error;
        }
    },
};

export default SettingsService;
