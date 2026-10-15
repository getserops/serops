import apiClient from "./api-client";

const BASE = "/data/investigations/";

const InvestigationService = {
  options: () => apiClient.get(`${BASE}options/`).then((r) => r.data),
  list: (params = {}) => apiClient.get(BASE, { params }).then((r) => r.data),
  get: (id) => apiClient.get(`${BASE}${id}/`).then((r) => r.data),
  create: (body) => apiClient.post(BASE, body).then((r) => r.data),
};

export default InvestigationService;
