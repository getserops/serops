import axios from "axios";

const AUTH_HOST = import.meta.env.VITE_BASE_URL;
const API_BASE_URL = AUTH_HOST + "/data";

// Helper to get auth headers
const getAuthHeaders = () => {
  const token = localStorage.getItem("token");
  return token ? { Authorization: `Token ${token}` } : {};
};

// Build params object, injecting the composed deployment filter
// persisted by DeploymentContext (Batch 54). Reading localStorage
// here keeps this service module React-free — no context import
// needed. Bad / missing values fall through to "unfiltered".
//
// The composed filter has five dimensions (cluster, env, region,
// namespace, deployment) — only the non-empty ones are forwarded so
// the backend never receives an ambiguous "" filter that would over-
// narrow.
const _readDeploymentFilter = () => {
  try {
    const raw = localStorage.getItem('serops.deployment.filter');
    if (raw) return JSON.parse(raw);
    // Legacy fallback — pre-Batch-54 code only persisted cluster id.
    const legacy = localStorage.getItem('serops.cluster.selected');
    if (legacy && legacy !== 'null') {
      const n = parseInt(legacy, 10);
      if (Number.isFinite(n) && n > 0) return { clusterId: n };
    }
  } catch {
    // Bad JSON / no localStorage — treat as unfiltered.
  }
  return {};
};

// Explicit ``environment`` argument (from the per-page env picker on
// Dashboard, Batches, etc.) takes precedence over the persisted
// filter's env — the per-page picker is what the user just touched.
const withEnv = (params = {}, environment) => {
  const out = { ...params };
  const f = _readDeploymentFilter();

  if (environment && environment !== 'all') {
    out.environment = environment;
  } else if (f.environment) {
    out.environment = f.environment;
  }
  if (f.clusterId != null) out.cluster = f.clusterId;
  if (f.region) out.region = f.region;
  if (f.namespace) out.namespace = f.namespace;
  if (f.deploymentId != null) out.deployment = f.deploymentId;
  return out;
};

const DashboardService = {
  async getRecommendationStats(environment) {
    try {
      const response = await axios.get(`${API_BASE_URL}/recommendation-stats/`, {
        params: withEnv({}, environment),
        headers: getAuthHeaders()
      });
      const apiData = response.data.statistics;

      return [
        {
          name: "IMMEDIATE",
          value: apiData.immediate.count,
          color: "#2B47D6",
          percentage: apiData.immediate.percentage,
        },
        {
          name: "LONG_TERM",
          value: apiData.long_term.count,
          color: "#73F3C2",
          percentage: apiData.long_term.percentage,
        },
      ];
    } catch (error) {
      console.error("Error fetching recommendation stats:", error);
      return [
        { name: "IMMEDIATE", value: 0, color: "#2B47D6", percentage: 0 },
        { name: "LONG_TERM", value: 0, color: "#73F3C2", percentage: 0 },
      ];
    }
  },

  async getRecommendationsList() {
    try {
      const response = await axios.get(`${API_BASE_URL}/recommendations/`, {
        headers: getAuthHeaders()
      });
      return response.data;
    } catch (error) {
      console.error("Error fetching recommendations list:", error);
      return [];
    }
  },

  async getIssueStats(environment) {
    try {
      const response = await axios.get(`${API_BASE_URL}/issue-stats/`, {
        params: withEnv({}, environment),
        headers: getAuthHeaders()
      });
      const apiData = response.data?.statistics;

      if (!apiData) {
        return [
          { name: "CRITICAL", value: 0, color: "#e53935", percentage: 0 },
          { name: "WARNING", value: 0, color: "#fb8c00", percentage: 0 }
        ];
      }

      return [
        {
          name: "CRITICAL",
          value: apiData.critical?.count || 0,
          color: "#e53935",
          percentage: apiData.critical?.percentage || 0
        },
        {
          name: "WARNING",
          value: apiData.warning?.count || 0,
          color: "#fb8c00",
          percentage: apiData.warning?.percentage || 0
        }
      ];
    } catch (error) {
      console.error("Error fetching issue stats:", error);
      return [
        { name: "CRITICAL", value: 0, color: "#e53935", percentage: 0 },
        { name: "WARNING", value: 0, color: "#fb8c00", percentage: 0 }
      ];
    }
  },

  async getIssuesSummary() {
    try {
      const response = await axios.get(`${API_BASE_URL}/issue-stats/`, {
        headers: getAuthHeaders()
      });
      return response.data.statistics.summary;
    } catch (error) {
      console.error("Error fetching issues summary:", error);
      return { total_batches: 0, batches_with_issues: 0, total_issues: 0 };
    }
  },

  async getSystemHealth(environment) {
    try {
      const response = await axios.get(`${API_BASE_URL}/analytics/health/`, {
        params: withEnv({}, environment),
        headers: getAuthHeaders()
      });
      return response.data;
    } catch (error) {
      console.error("Error fetching system health:", error);
      return { health_score: 100, status: "Unknown", metrics: {} };
    }
  },

  async getServiceReliability(environment) {
    try {
      const response = await axios.get(`${API_BASE_URL}/analytics/services/`, {
        params: withEnv({}, environment),
        headers: getAuthHeaders()
      });
      return response.data;
    } catch (error) {
      console.error("Error fetching service reliability:", error);
      return [];
    }
  },

  async getTrendAnalysis(environment) {
    try {
      const response = await axios.get(`${API_BASE_URL}/analytics/trends/`, {
        params: withEnv({}, environment),
        headers: getAuthHeaders()
      });
      return response.data;
    } catch (error) {
      console.error("Error fetching trend analysis:", error);
      return [];
    }
  },

  async getMTTRStats(days = 30, environment) {
    try {
      const response = await axios.get(`${API_BASE_URL}/analytics/mttr/`, {
        params: withEnv({ days }, environment),
        headers: getAuthHeaders()
      });
      return response.data;
    } catch (error) {
      console.error("Error fetching MTTR stats:", error);
      return { overall_mttr_hours: 0, by_severity: {}, trend: 'UNKNOWN', sample_size: 0 };
    }
  },

  async getServiceHealthMap(days = 7, environment) {
    try {
      const response = await axios.get(`${API_BASE_URL}/analytics/service-health/`, {
        params: withEnv({ days }, environment),
        headers: getAuthHeaders()
      });
      return response.data;
    } catch (error) {
      console.error("Error fetching service health map:", error);
      return { services: [], total_services: 0 };
    }
  },

  async getRootCauseStats(days = 30, environment) {
    try {
      const response = await axios.get(`${API_BASE_URL}/analytics/root-causes/`, {
        params: withEnv({ days }, environment),
        headers: getAuthHeaders()
      });
      return response.data;
    } catch (error) {
      console.error("Error fetching root cause stats:", error);
      return { breakdown: [], total_issues: 0 };
    }
  },

  async getRecentDeployments(environment) {
    try {
      const response = await axios.get(`${API_BASE_URL}/analytics/deployments/`, {
        params: withEnv({}, environment),
        headers: getAuthHeaders()
      });
      return response.data;
    } catch (error) {
      console.error("Error fetching recent deployments:", error);
      return { services: [], total_services: 0 };
    }
  },

  async getCorrelationInsights(days = 7, environment) {
    try {
      const response = await axios.get(`${API_BASE_URL}/analytics/correlations/`, {
        params: withEnv({ days }, environment),
        headers: getAuthHeaders()
      });
      return response.data;
    } catch (error) {
      console.error("Error fetching correlation insights:", error);
      return {
        total_issues: 0, commit_correlations: 0, metric_correlations: 0,
        metric_breakdown: { memory: 0, cpu: 0 }, correlation_rate: 0,
        top_correlated_components: [], period_days: days
      };
    }
  },

  async getAnalysisFeed(limit = 5, environment) {
    try {
      const response = await axios.get(`${API_BASE_URL}/analytics/feed/`, {
        params: withEnv({ limit }, environment),
        headers: getAuthHeaders()
      });
      return response.data;
    } catch (error) {
      console.error("Error fetching analysis feed:", error);
      return { feed: [], total_analyses: 0 };
    }
  },

  async getSentinelStats(days = 7, environment) {
    try {
      const response = await axios.get(`${API_BASE_URL}/analytics/sentinel/`, {
        params: withEnv({ days }, environment),
        headers: getAuthHeaders()
      });
      return response.data;
    } catch (error) {
      console.error("Error fetching sentinel stats:", error);
      return {
        total_batches: 0, decisions: {}, ai_analyzed: 0, ai_skipped: 0,
        skip_rate_percent: 0, estimated_tokens_saved: 0
      };
    }
  }
};

export default DashboardService;
