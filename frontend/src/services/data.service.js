import apiClient from "./api-client";
import JSON5 from "json5";
import { ProjectService } from "./project.service";

// URLs are now relative to baseURL in apiClient, or absolute overrides
// Since apiClient has baseURL set to AUTH_HOST, we can just use paths if we want, 
// but existing code uses absolute URLs. apiClient handles absolute URLs correctly (ignores baseURL if url is absolute).
// However, to be cleaner, let's keep using the constants but pass them to apiClient.

// apiClient has baseURL set to VITE_BASE_URL (/api by default). Passing a
// URL that ALSO starts with /api produced /api/api/data/batches → 404.
// Use path-only constants and let apiClient prepend the base.
const API_URL = "/data/batches";
const ISSUES_API_URL = "/data/issues/";
// Note: apiClient adds Authorization header automatically

// Composed deployment filter (Batch 54 completion / L1 fix, 2026-09-09).
// dash.service already forwards these via its own withEnv helper; here
// we do the same for batches / issues since Data.jsx + Issues.jsx read
// from data.service. Reads the persisted JSON blob DeploymentContext
// writes to localStorage — module stays React-free (no context import).
const _mergeDeploymentFilter = (params = {}) => {
  const out = { ...params };
  try {
    const raw = localStorage.getItem("serops.deployment.filter");
    if (raw) {
      const f = JSON.parse(raw);
      // Only merge dimensions the caller HASN'T explicitly set — a
      // page-level picker (e.g. env dropdown) always wins over the
      // header-level composed filter.
      if (f.region     && out.region     === undefined) out.region     = f.region;
      if (f.namespace  && out.namespace  === undefined) out.namespace  = f.namespace;
      if (f.deploymentId != null && out.deployment === undefined) out.deployment = f.deploymentId;
      // cluster is already forwarded by Data.jsx directly (via useCluster)
      // and by Issues.jsx — don't double-inject here.
    }
  } catch {
    // Bad JSON / no localStorage — silently skip.
  }
  return out;
};

const getBatches = async (params = {}) => {
  try {
    params = _mergeDeploymentFilter(params);
    const response = await apiClient.get(API_URL, {
      params,
    });

    // Handle the nested structure returned by your Django API
    if (response.data && response.data.results) {
      return {
        results: response.data.results,
        count: response.data.pagination?.total || response.data.results.length,
        pagination: response.data.pagination,
      };
    } else {
      // Fallback in case the structure is different
      console.warn("Unexpected API response structure:", response.data);
      return {
        results: Array.isArray(response.data) ? response.data : [],
        count: Array.isArray(response.data) ? response.data.length : 0,
      };
    }
  } catch (error) {
    console.error("Error fetching batches:", error);
    if (error.response) {
      console.error("Error response:", error.response.data);
    } else if (error.request) {
      console.error("No response received:", error.request);
    }
    // Return empty but consistent structure to prevent UI crashes
    return { results: [], count: 0, pagination: { total: 0, offset: 0, count: 0 } };
  }
};

const getBatchLogs = async (batchId) => {
  if (!batchId) {
    console.error("No batch ID provided");
    return { results: [], count: 0 };
  }

  try {
    const response = await apiClient.get(`${API_URL}/${batchId}/`);

    const logs = response.data.data?.logs || [];
    const cicdLogs = response.data.data?.cicd_logs || [];

    // Adapter for CI/CD logs to match Detail.jsx expectation (Elasticsearch hit structure)
    const adaptedCicdLogs = cicdLogs.map((log, index) => {
      // Build status line
      const statusLine = `[CI/CD] Job "${log.job_name || 'unknown'}" ${log.status || 'finished'} on branch "${log.branch || 'unknown'}" (Pipeline #${log.pipeline_id || 'N/A'})`;

      // Combine message and trace for full visibility
      let fullMessage = log.message || statusLine;
      if (log.trace) {
        // Append trace content (truncated for display)
        const tracePreview = log.trace.length > 1000
          ? log.trace.substring(log.trace.length - 1000) // Show last 1000 chars (where errors usually are)
          : log.trace;
        fullMessage = `${statusLine}\n\n--- Job Output ---\n${tracePreview}`;
      }

      return {
        _id: log.job_id || `cicd-${index}`,
        _index: 'ci_cd-logs-project-generated', // Prefix required by Detail.jsx filter
        _source: {
          ...log, // Spread FIRST so defaults below take precedence
          '@timestamp': log.timestamp || new Date().toISOString(),
          message: fullMessage,
          level: log.status === 'failed' ? 'ERROR' : 'INFO',
          service_name: log.service_name || 'CI/CD', // Use actual service name if available
          trace: log.trace, // Keep original trace for expandable view
        }
      };
    });

    const allLogs = [...logs, ...adaptedCicdLogs];

    // Sort combined logs by timestamp descending
    allLogs.sort((a, b) => {
      const timeA = new Date(a._source?.['@timestamp'] || 0);
      const timeB = new Date(b._source?.['@timestamp'] || 0);
      return timeB - timeA;
    });

    return {
      results: allLogs,
      count: allLogs.length,
    };
  } catch (error) {
    console.error("Error fetching batch logs:", error);
    return { results: [], count: 0 };
  }
};
const getBatchMetrics = async (batchId, { type = "memory_usage" } = {}) => {
  if (!batchId) {
    console.error("No batch ID provided");
    return { results: [], count: 0, average: 0 };
  }

  try {
    const response = await apiClient.get(`${API_URL}/${batchId}/`);

    let metrics = [];
    if (type === "memory_usage") {
      metrics = response.data.data?.metrics?.memory_usage_percent || [];
    } else if (type === "cpu_usage") {
      metrics = response.data.data?.metrics?.cpu_usage_percent || [];
    }

    // Metrics are per-service: in Kubernetes the collectors aggregate by
    // service_name, so every service in the project reports at the same
    // instants. Plotting them as one flat list drew a line that jumped
    // between services at each timestamp.
    //
    // Collapse to one point per timestamp, keeping the HIGHEST value and the
    // service it belongs to. For an incident view that is the number worth
    // showing — one container saturating its limit is the thing to see, and it
    // used to be averaged into a healthy-looking project figure. The full
    // per-service breakdown rides along in `services` for callers that want it.
    const byTimestamp = new Map();
    const services = new Set();
    metrics.forEach((item) => {
      // metrics_processing names an unlabelled series 'default'. Carried
      // through it reads as a service called default, which does not exist —
      // the tooltip said "Memory Usage · default" and the caption listed it
      // among the project's services.
      const key = item.series_key;
      const service = key && key !== "default" ? key : null;
      if (service) services.add(service);
      const value = parseFloat(item.value) || 0;
      const existing = byTimestamp.get(item.time);
      if (!existing || value > existing.value) {
        byTimestamp.set(item.time, {
          timestamp: item.time,
          value: item.value,
          source: item.source_table,
          service,
        });
      }
    });

    const formattedMetrics = [...byTimestamp.values()];

    // Tri chronologique dès la récupération
    formattedMetrics.sort(
      (a, b) => new Date(a.timestamp) - new Date(b.timestamp)
    );

    // Calculate average
    const avg =
      formattedMetrics.length > 0
        ? (
          formattedMetrics.reduce(
            (sum, m) => sum + (parseFloat(m.value) || 0),
            0
          ) / formattedMetrics.length
        ).toFixed(2)
        : 0;

    return {
      results: formattedMetrics,
      count: formattedMetrics.length,
      average: avg,
      services: [...services].sort(),
      // Set when the retention task has cleared this batch's raw points. Lets
      // the UI say "cleared to save storage" rather than "no metrics" — one is
      // routine housekeeping, the other means something is misconfigured, and
      // showing the wrong one sends the operator looking for a fault that is
      // not there.
      trimmedAt: response.data.data?.metrics_trimmed_at || null,
    };
  } catch (error) {
    console.error("Error fetching batch metrics:", error);
    return { results: [], count: 0, average: 0, services: [], trimmedAt: null, failed: true };
  }
};

/**
 * The analysis SerOps already computed for a batch's metrics, normalised.
 *
 * batch.data.metrics_summary holds per-service statistics, trends, sustained
 * anomalies with correlation windows, peak single-pod utilisation and the
 * kubelet's container terminations. All of it is sent to the AI and, until
 * this function existed, none of it was shown to the operator — the metrics
 * page drew two charts off raw points and recomputed its own average. The
 * diagnosis lived in AI prose and the chart was decoration.
 *
 * It also survives retention trimming, which drops raw points but keeps the
 * summary — so a batch whose chart is empty can still explain what was found.
 *
 * Takes the batch detail response rather than a batch id, and does no I/O:
 * the summary arrives on that same response, so the one caller passes the
 * payload it already holds instead of paying for a second download of this
 * batch's whole log and metric payload.
 *
 * Returns null when the batch has no summary. Older batches predate parts of
 * it (`peak_pod` is absent before the per-pod query existed), so every branch
 * below has to tolerate a missing block rather than assume today's shape.
 */
const buildMetricSummary = (batchPayload) => {
  const summary = batchPayload?.data?.metrics_summary;
  if (!summary) return null;

  const lifecycle = summary.container_lifecycle || {};
  const peak = summary.peak_pod || {};

  // Anomalies arrive split by metric; the UI shows one ranked list, so the
  // kind travels with each entry rather than being implied by position.
  const anomalies = [
    ...(summary.memory?.anomalies || []).map((a) => ({ ...a, kind: 'memory' })),
    ...(summary.cpu?.anomalies || []).map((a) => ({ ...a, kind: 'cpu' })),
    ...(peak.memory_anomalies || []).map((a) => ({ ...a, kind: 'peak_pod_memory' })),
  ].sort((a, b) => (b.peak_value || 0) - (a.peak_value || 0));

  return {
    memory: summary.memory?.usage_percent || null,
    cpu: summary.cpu?.usage_percent || null,
    totalMemoryGb: summary.memory?.total_gb ?? null,
    perService: {
      memory: summary.per_service?.memory_usage_percent || {},
      cpu: summary.per_service?.cpu_usage_percent || {},
    },
    peakPodMemory: peak.memory_percent || {},
    anomalies,
    // `terminated` is what the kubelet reported, which is the only place an
    // OOMKill shows up at all — a killed container writes no log line.
    terminated: lifecycle.terminated || [],
    restarts: lifecycle.restarts || {},
    dataPoints: summary.data_points || {},
    timeRange: summary.time_range || {},
  };
};

const getBatchTimeline = async (batchId, maxEvents = 200) => {
  try {
    const response = await apiClient.get(
      `${API_URL}/${batchId}/timeline/`,
      { params: { max_events: maxEvents } },
    );
    return response.data;   // { batch_id, event_count, events: [...] }
  } catch (error) {
    console.error(`Error fetching batch timeline ${batchId}:`, error);
    return { batch_id: batchId, event_count: 0, events: [] };
  }
};

const getBatchDetails = async (batchId) => {
  try {
    const response = await apiClient.get(`${API_URL}/${batchId}/`);
    return response.data;
  } catch (error) {
    console.error(`Erreur lors de la récupération du batch ${batchId}:`, error);
    return null;
  }
};

const getIssues = async (params = {}) => {
  try {
    params = _mergeDeploymentFilter(params);
    const response = await apiClient.get(ISSUES_API_URL, {
      params,
    });

    // Check if the response has the expected structure
    const issues = response.data.results || [];

    // Map the new API response structure to the format expected by the app
    // Every API field passes through: the issue panel reads project,
    // batch_id_str, recommendation, reasoning and confidence, which the old
    // field list dropped. No placeholder root cause either: a missing one
    // stays empty instead of reading "Empty root cause".
    const mappedIssues = issues.map((issue) => ({
      ...issue,
      message: `[${issue.severity}] ${issue.description}`, // Keeping for compatibility but deprecated
      batch: issue.batch_id_str || issue.batch_id,
      solution: issue.recommendation || issue.solution || "",
      root_cause: issue.root_cause || "",
      timestamp: issue.timestamp,
      created_at: issue.created_at,
      count: issue.count,
      batchData: issue.batch_data,
      // v2 dedup fields
      issue_type: issue.issue_type || 'OTHER',
      scope: issue.scope || 'SERVICE',
      component: issue.component || '',
      environment: issue.environment || '',
      status: issue.status || 'OPEN',
      occurrence_count: issue.occurrence_count || 1,
      muted_until: issue.muted_until,
      last_seen_at: issue.last_seen_at,
      // v4 correlation fields
      has_commit_correlation: issue.has_commit_correlation || false,
      has_metric_correlation: issue.has_metric_correlation || false,
      linked_commits: issue.linked_commits || [],
      metric_correlation_type: issue.metric_correlation_type || '',
      correlation_summary: issue.correlation_summary || [],
    }));

    return {
      results: mappedIssues,
      count: response.data.pagination?.total_issues || mappedIssues.length,
      pagination: response.data.pagination,
      summary: response.data.summary,
    };
  } catch (error) {
    console.error("Error fetching issues:", error);
    throw error;
  }
};

const getIssuesByBatch = async (batchId, params = {}) => {
  if (!batchId) {
    console.error("No batch ID provided");
    return { results: [], pagination: {}, summary: {} };
  }

  try {
    const response = await apiClient.get(`${ISSUES_API_URL}${batchId}/`, {
      params,
    });

    const issues = response.data.results || [];

    if (!Array.isArray(issues)) {
      console.error("Unexpected API response format:", response.data);
      return { results: [], pagination: {}, summary: {} };
    }

    const mappedIssues = issues.map((issue) => ({
      ...issue,
      message: `[${issue.severity}] ${issue.description}`, // Keeping for compatibility
      batch: issue.batch_id_str || issue.batch_id,
      solution: issue.recommendation || issue.solution || "",
      root_cause: issue.root_cause || "",
      timestamp: issue.timestamp,
      created_at: issue.created_at,
      count: issue.count,
      batchData: issue.batch_data,
      // v2 dedup fields
      issue_type: issue.issue_type || 'OTHER',
      scope: issue.scope || 'SERVICE',
      component: issue.component || '',
      environment: issue.environment || '',
      status: issue.status || 'OPEN',
      occurrence_count: issue.occurrence_count || 1,
      muted_until: issue.muted_until,
      last_seen_at: issue.last_seen_at,
      // v4 correlation fields
      has_commit_correlation: issue.has_commit_correlation || false,
      has_metric_correlation: issue.has_metric_correlation || false,
      linked_commits: issue.linked_commits || [],
      metric_correlation_type: issue.metric_correlation_type || '',
      correlation_summary: issue.correlation_summary || [],
    }));

    return {
      results: mappedIssues,
      count: response.data.pagination?.total_issues || mappedIssues.length,
      pagination: response.data.pagination,
      summary: response.data.summary,
    };
  } catch (error) {
    console.error(`Error fetching issues for batch ${batchId}:`, error);
    throw error;
  }
};

const triggerBatchAnalysis = async (batchId) => {
  try {
    const response = await apiClient.post(
      "/chat/analyze-batch/",
      { batch_id: batchId }, // Only batch_id
    );

    return {
      success: true,
      data: response.data,
      analysisResult: response.data.analysis_result,
    };
  } catch (error) {
    console.error("Error triggering batch analysis:", error);
    throw error;
  }
};

const formatAnalysisResult = (analysisResult) => {
  try {
    if (typeof analysisResult === "string") {
      let jsonStr = analysisResult.trim();
      if (jsonStr.startsWith("```json")) {
        jsonStr = jsonStr.replace(/^```json\s*/, "").replace(/\n```$/, "");
      } else if (jsonStr.startsWith("```")) {
        jsonStr = jsonStr.replace(/^```\s*/, "").replace(/\n```$/, "");
      }
      return JSON5.stringify(JSON5.parse(jsonStr), null, 2);
    }
    return JSON5.stringify(analysisResult, null, 2);
  } catch (error) {
    console.error("Error formatting analysis result JSON:", error);
    return "Invalid JSON format.";
  }
};

const getNextBatchPage = async (pagination, additionalParams = {}) => {
  // If there's no next offset, return empty results
  if (pagination?.next_offset === null) {
    return {
      results: [],
      count: 0,
      pagination: pagination,
      hasMorePages: false,
    };
  }

  // Call getBatches with the next offset
  try {
    return await getBatches({
      ...additionalParams,
      offset: pagination.next_offset,
    });
  } catch (error) {
    console.error("Error fetching next page:", error);
    return {
      results: [],
      count: 0,
      pagination: pagination,
      hasMorePages: false,
    };
  }
};

const getAllIssues = async () => {
  try {
    let allIssues = [];
    let currentPagination = { next_offset: 0 }; // Start with offset 0

    // Keep fetching batches until there are no more pages
    while (currentPagination.next_offset !== null) {
      const response = await getBatches({
        offset: currentPagination.next_offset || 0,
        limit: 50, // Fetch more batches per request to reduce number of API calls
      });

      // Process batches from this page
      const batches = response.results || [];

      // Extract issues from each batch
      for (const batch of batches) {
        const batchId = batch.batch_id;
        let analysisData = {};

        let jsonStr = batch.analysis_text || "";
        if (jsonStr.startsWith("```json")) {
          jsonStr = jsonStr.replace(/^```json\s*/, "").replace(/\n```$/, "");
        }

        jsonStr = jsonStr.trim();

        try {
          if (jsonStr) {
            analysisData = JSON5.parse(jsonStr);
          }
        } catch (parseError) {
          console.error(
            `Could not parse analysis_text for batch ${batchId}:`,
            parseError
          );
          allIssues.push({
            id: `${batchId}-error`,
            message: "[CRITICAL] JSON parsing error in batch analysis",
            batch: batchId,
            solution: "Review and fix the JSON format in the analysis_text",
          });
          continue;
        }

        const correlatedIssues = Array.isArray(analysisData.correlated_issues)
          ? analysisData.correlated_issues
          : [];

        const batchIssues = correlatedIssues.map((issue) => ({
          id: `${batchId}-${issue.issue_id}`,
          message: `[${issue.severity}] ${issue.description}`,
          batch: batchId,
          solution: issue.recommended_action || "No action specified ",
        }));

        allIssues = [...allIssues, ...batchIssues];
      }

      // Update pagination for next iteration
      currentPagination = response.pagination;

      // If there are no more pages, exit the loop
      if (!currentPagination || currentPagination.next_offset === null) {
        break;
      }
    }

    return allIssues;
  } catch (error) {
    console.error("Error fetching all issues:", error);
    return [];
  }
};

const getBatchCodeChanges = async (batchId) => {
  if (!batchId) {
    console.error("No batch ID provided");
    return { results: [], count: 0 };
  }

  try {
    const response = await apiClient.get(`${API_URL}/${batchId}/`);


    const codeChanges = response.data.data?.code_changes || [];

    // Format code changes for display
    const formattedChanges = codeChanges.map((change, index) => ({
      id: change.sha || index,
      sha: change.sha || 'N/A',
      message: change.message || 'No message',
      author: change.author || 'Unknown',
      timestamp: change.timestamp || null,
      branch: change.branch || 'unknown',
      service_name: change.service_name || null,  // NEW: Which service this commit belongs to
      stats: change.stats || { files: 0, additions: 0, deletions: 0 },
      files: change.files || [],
    }));


    return {
      results: formattedChanges,
      count: formattedChanges.length,
    };
  } catch (error) {
    console.error("Error fetching batch code changes:", error);
    return { results: [], count: 0 };
  }
};

const deleteOldBatches = async (days = 30) => {
  try {
    const response = await apiClient.delete(
      "/data/delete-old-batches/",
      {
        params: { days },
      }
    );
    return response.data;
  } catch (error) {
    console.error("Error deleting old batches:", error);
    throw error;
  }
};
/**
 * Get discovered hosts from Promscale labels
 * @param {Object} params - Filter parameters
 * @param {string} params.project - Project slug
 * @param {string} params.environment - Environment filter (optional)
 * @returns {Promise<Array>} List of hosts with instance, environment, hostname
 */
const getHosts = async (params = {}) => {
  try {
    const response = await apiClient.get("/data/hosts/", {
      params,
    });
    return response.data?.hosts || [];
  } catch (error) {
    console.error("Error fetching hosts:", error);
    return [];
  }
};

/**
 * Get metric-issue correlations for a batch
 * @param {string} batchId - Batch identifier
 * @param {string} metricType - 'memory' or 'cpu'
 * @param {number} threshold - Spike threshold (default 80)
 * @returns {Promise<Array>} List of correlations with spike info and related issues
 */
const getMetricCorrelations = async (batchId, metricType = 'memory', threshold = 80) => {
  try {
    const response = await apiClient.get(`/data/batches/${batchId}/correlations/`, {
      params: { metric_type: metricType, threshold },
    });
    return response.data?.correlations || [];
  } catch (error) {
    console.error("Error fetching metric correlations:", error);
    return [];
  }
};

/**
 * Re-analyze one or more batches with a specific AI model.
 *
 * @param {Array<string>} batchIds - List of batch IDs to re-analyze
 * @param {string} model - AI model to use (e.g. 'gemini', 'claude')
 * @param {'compare'|'primary'} mode - 'compare' (default) appends the
 *   result to ``analysis_history`` for the side-by-side view;
 *   'primary' promotes the new result to the batch's primary
 *   analysis and refreshes Issues via fingerprint dedup.
 * @returns {Promise<Object>} Result with status, queued batch IDs, mode
 */
const reanalyzeBatches = async (batchIds, model = 'gemini', mode = 'compare') => {
  try {
    const response = await apiClient.post(
      "/data/batches/reanalyze/",
      { batch_ids: batchIds, model, mode },
    );
    return response.data;
  } catch (error) {
    console.error("Error reanalyzing batches:", error);
    throw error;
  }
};

/**
 * Promote one analysis_history entry to the batch's primary analysis.
 * Fast, synchronous on the server (no AI call). Runs the same
 * fingerprint-dedup Issue flow as a primary re-analysis.
 *
 * @param {string} batchId - Batch identifier
 * @param {string} analyzedAt - ISO timestamp of the history entry to promote
 * @returns {Promise<Object>} Summary { issues_created, issue_count, ... }
 */
const promoteAnalysisEntry = async (batchId, analyzedAt) => {
  const response = await apiClient.post(
    `/data/batches/${batchId}/promote-analysis/`,
    { analyzed_at: analyzedAt },
  );
  return response.data;
};

/**
 * Get analysis history for a batch (for comparing different model results)
 * @param {string} batchId - Batch identifier
 * @returns {Promise<Object>} Analysis history with all model results
 */
const getAnalysisHistory = async (batchId) => {
  try {
    const response = await apiClient.get(`/data/batches/${batchId}/history/`);
    return response.data;
  } catch (error) {
    console.error("Error fetching analysis history:", error);
    return { analysis_history: [], analysis_count: 0 };
  }
};

/**
 * Get available AI models for re-analysis
 * Returns models based on org's configured API keys
 * @returns {Promise<Array>} List of available models with id and name
 */
const getAvailableModels = async () => {
  try {
    const response = await apiClient.get("/settings/ai/available-models/");
    return response.data?.models || [];
  } catch (error) {
    console.error("Error fetching available models:", error);
    return [];
  }
};

/**
 * Resolve an issue (set status to RESOLVED)
 * @param {number} issueId - Issue ID
 * @returns {Promise<Object>} Updated issue data
 */
// `resolution` (optional): { root_cause, fix } as confirmed or corrected
// by the person resolving.
const resolveIssue = async (issueId, resolution = {}) => {
  try {
    const response = await apiClient.post(
      `${ISSUES_API_URL}${issueId}/resolve/`,
      resolution,
    );
    return response.data;
  } catch (error) {
    console.error("Error resolving issue:", error);
    throw error;
  }
};

/**
 * Mute an issue for a specified number of days
 * @param {number} issueId - Issue ID
 * @param {number} days - Number of days to mute (0 = forever)
 * @returns {Promise<Object>} Updated issue data
 */
const muteIssue = async (issueId, days = 7) => {
  try {
    const response = await apiClient.post(
      `${ISSUES_API_URL}${issueId}/mute/`,
      { days },
    );
    return response.data;
  } catch (error) {
    console.error("Error muting issue:", error);
    throw error;
  }
};

/**
 * Perform a bulk action on multiple issues
 * @param {Array<number>} issueIds - List of issue IDs
 * @param {string} action - Action: 'resolve', 'mute', or 'reopen'
 * @param {number} days - Days to mute (only for 'mute' action, default 7)
 * @returns {Promise<Object>} { updated: N }
 */
const bulkAction = async (issueIds, action, days = 7) => {
  try {
    const payload = { issue_ids: issueIds, action };
    if (action === 'mute') {
      payload.days = days;
    }
    const response = await apiClient.post(
      `${ISSUES_API_URL}bulk-action/`,
      payload,
    );
    return response.data;
  } catch (error) {
    console.error("Error performing bulk action:", error);
    throw error;
  }
};

/**
 * Reopen a resolved or muted issue
 * @param {number} issueId - Issue ID
 * @returns {Promise<Object>} Updated issue data
 */
const reopenIssue = async (issueId) => {
  try {
    const response = await apiClient.post(
      `${ISSUES_API_URL}${issueId}/reopen/`,
      {},
    );
    return response.data;
  } catch (error) {
    console.error("Error reopening issue:", error);
    throw error;
  }
};

export default {
  getBatchLogs,
  getBatchDetails,
  getBatchTimeline,
  getIssues,
  getIssuesByBatch,
  getBatches,
  getBatchMetrics,
  buildMetricSummary,
  getBatchCodeChanges,
  triggerBatchAnalysis,
  getNextBatchPage,
  getAllIssues,
  deleteOldBatches,
  getHosts,
  getMetricCorrelations,
  reanalyzeBatches,
  promoteAnalysisEntry,
  getAnalysisHistory,
  getAvailableModels,
  // Issue actions
  resolveIssue,
  muteIssue,
  reopenIssue,
  bulkAction,
};

export { formatAnalysisResult };


