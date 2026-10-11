/**
 * Data-source capabilities service.
 *
 * Wraps GET /api/organisation/capabilities/. Response shape:
 *
 *   { capabilities: ["logs", "traces"], all_known: [...] }
 *
 * ``capabilities`` is the subset the caller's org has at least one
 * configured integration for. Used to gate sidebar entries, dashboard
 * cards, and batch-detail dropdown options so a logs-only user never
 * sees dead UI for unconnected sources.
 */

import apiClient from "./api-client";

const CapabilityService = {
    get: async () => {
        const { data } = await apiClient.get("/organisation/capabilities/");
        return data;   // { capabilities: [...], all_known: [...] }
    },
};

export default CapabilityService;
