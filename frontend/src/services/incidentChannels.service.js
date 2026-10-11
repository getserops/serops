/**
 * Incident Notification Channels — outbound destinations for post-RCA
 * notifications (Items #22 + #23).
 *
 * Shape:
 *   { id, name, kind, kind_display, has_webhook_url, has_api_key,
 *     extra_config, trigger_events, min_severity, is_active,
 *     last_sent_at, last_error, created_at, updated_at }
 *
 * Writes accept plaintext `webhook_url_input` / `api_key_input`
 * — the backend encrypts before storage, never returns them on reads.
 */

import apiClient from "./api-client";

const BASE = "/notification/incident-channels";

const IncidentChannelsService = {
    list: async () => {
        const { data } = await apiClient.get(`${BASE}/`);
        return Array.isArray(data) ? data : (data?.results || []);
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

    // Sends a synthetic test message so users can verify the URL/key
    // before real incidents happen. Returns { ok, message }.
    testSend: async (id) => {
        const { data } = await apiClient.post(`${BASE}/${id}/test-send/`, {});
        return data;
    },
};

export default IncidentChannelsService;
