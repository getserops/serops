import React, { useState, useEffect, useRef } from "react";
import { useCluster } from "../context/ClusterContext";
import PostmortemModal from "./PostmortemModal";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Table,
  Pagination,
  Form,
  Dropdown,
  Spinner,
} from "react-bootstrap";
import { FaEye, FaSearch, FaBolt } from "react-icons/fa";
import { useTranslation } from "react-i18next";
import DataService from "../services/data.service";
import "./Data.css";

import { useQuery } from "@tanstack/react-query";

const Data = () => {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const isDetailRoute = location.pathname.includes("/details/");
  const searchInputRef = useRef(null);
  // Read the composed filter via useCluster (aliased to useDeployment).
  // Prefer ``currentCluster?.id`` over raw ``clusterId`` so we never
  // forward an ID that doesn't match a loaded cluster — that's what
  // used to silently return zero batches when a user visited the
  // demo with a stale filter from a different org (Batch 54 fix).
  const { currentCluster, loading: clustersLoading } = useCluster();
  const clusterId = clustersLoading ? null : (currentCluster?.id ?? null);

  const [currentPage, setCurrentPage] = useState(1);
  const [searchTerm, setSearchTerm] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const pageSize = 5;
  const [selectedDeepseek, setSelectedDeepseek] = useState("Gemini"); // DEPRECATED - keeping for potential future use
  const [selectedProject, setSelectedProject] = useState("all");
  const [selectedEnvironment, setSelectedEnvironment] = useState("all");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  // Item #28: which batch id (if any) has the post-mortem modal open.
  const [postmortemBatchId, setPostmortemBatchId] = useState(null);
  const [notification, setNotification] = useState(null); // { type: 'success'|'error'|'warning', message: string }

  // Debounce search term to avoid excessive API calls
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchTerm);
      if (searchTerm !== debouncedSearch) {
        setCurrentPage(1);
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [searchTerm]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch available AI models for re-analysis (dynamic based on org's API keys)
  const { data: availableModels = [] } = useQuery({
    queryKey: ['available-models'],
    queryFn: () => DataService.getAvailableModels(),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  // Fetch all projects for the dropdown
  const { data: projectsData = ["all"] } = useQuery({
    queryKey: ["projects"],
    queryFn: async () => {
      const response = await DataService.getBatches({ limit: 1000 });
      const uniqueProjects = new Set();
      response.results.forEach((item) => {
        // Use project_name from API if available, fallback to extracting from batch_id
        const projectName = item.project_name || extractProjectNameFromBatch(item.batch_id);
        if (projectName) uniqueProjects.add(projectName);
      });
      return ["all", ...Array.from(uniqueProjects).sort()];
    },
    staleTime: 10 * 60 * 1000, // 10 minutes
  });

  const projects = projectsData;

  // Read project filter from URL query parameter
  useEffect(() => {
    const searchParams = new URLSearchParams(location.search);
    const projectFromUrl = searchParams.get('project');
    if (projectFromUrl) {
      // Try to match with projects in dropdown (case-insensitive)
      if (projects.length > 1) {
        const normalizedUrl = projectFromUrl.toLowerCase().replace(/[-_]/g, ' ').trim();
        const matchedProject = projects.find(p =>
          p.toLowerCase().replace(/[-_]/g, ' ').trim() === normalizedUrl ||
          p.toLowerCase() === projectFromUrl.toLowerCase()
        );
        if (matchedProject && matchedProject !== selectedProject) {
          setSelectedProject(matchedProject);
          return;
        }
      }
      // If not found in dropdown but URL has a project, use URL value directly
      // This handles cases where the project exists but has no batches yet
      if (projectFromUrl !== selectedProject) {
        setSelectedProject(projectFromUrl);
      }
    }
  }, [location.search, projects]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch batches with query management
  const {
    data: batchesResponse,
    isLoading,
    isPlaceholderData,
  } = useQuery({
    queryKey: ["batches", currentPage, selectedProject, selectedEnvironment, debouncedSearch, clusterId],
    queryFn: async () => {
      // Send both project and environment filters to API for server-side filtering
      const params = {
        limit: pageSize,
        offset: (currentPage - 1) * pageSize,
        order_by: "-timestamp",
        environment: selectedEnvironment,  // Send environment filter to API
        project: selectedProject,  // Send project filter to API
        ...(debouncedSearch && { search: debouncedSearch }),  // Send search to API
        ...(clusterId != null && { cluster: clusterId }),  // Cluster picker (Item #19)
      };

      const response = await DataService.getBatches(params);

      const today = new Date();
      today.setHours(0, 0, 0, 0);

      let todayCount = 0;
      const processedData = response.results.map((item) => {
        const itemDate = new Date(item.timestamp);
        const isToday = itemDate >= today;
        if (isToday) todayCount++;

        let modelDisplayName = "Not found";
        if (item.model_name) {
          modelDisplayName =
            item.model_name.toLowerCase() === "gemini"
              ? "Gemini"
              : item.model_name.toLowerCase() === "deepseek"
                ? "Deepseek"
                : item.model_name;
        }
        // Use project_name from API if available, fallback to extracting from batch_id
        const projectName = item.project_name || extractProjectNameFromBatch(item.batch_id) || "Unknown Project";

        return {
          id: item.batch_id,
          timestamp: itemDate.toLocaleString(),
          batch: item.batch_id,
          issue_count: item.issue_count || 0,
          issues: item.issue_count || 0,
          selected: false,
          rawTimestamp: itemDate,
          isToday: isToday,
          model: modelDisplayName,
          model_name: item.model_name || null,
          analyzed_at: item.analyzed_at || null,
          rawModel: item.model_name || null,
          project_id: item.project_id || "not found",
          project_name: projectName,
          environment: item.environment || "production",
          sentinel_decision: item.sentinel_decision || "shadow",
          sentinel_triggers: item.sentinel_triggers || [],
          ai_skipped: item.ai_skipped || false,
        };
      });

      return {
        results: processedData,
        todayCount,
        pagination: response.pagination || {
          total: processedData.length,
          count: processedData.length,
          next_offset: null,
          previous_offset: null
        },
      };
    },
    placeholderData: (prev) => prev,
  });

  // Local state for batch selection (needs to be kept local as it's UI state per render)
  const [selectedBatches, setSelectedBatches] = useState({});

  const data = batchesResponse?.results || [];
  const todayBatchesCount = batchesResponse?.todayCount || 0;
  const pagination = batchesResponse?.pagination || null;
  const totalCount = pagination?.total || 0;

  function extractProjectNameFromBatch(batchName) {
    if (!batchName) return null;

    const parts = batchName.toLowerCase().split("-batch-");
    if (parts.length > 0) {
      const projectPart = parts[0];

      return projectPart
        .split("-")
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(" ");
    }
    return null;
  }

  const goToPage = (pageNumber) => {
    if (pageNumber < 1 || pageNumber > totalPages) return;
    setCurrentPage(pageNumber);
  };

  const nextPage = () => {
    if (currentPage < totalPages) {
      goToPage(currentPage + 1);
    }
  };

  const prevPage = () => {
    if (currentPage > 1) {
      goToPage(currentPage - 1);
    }
  };

  // Use server pagination total since filtering is done server-side
  const totalPages = pagination?.total
    ? Math.ceil(pagination.total / pageSize)
    : 0;

  const highlightSearchTerm = (text) => {
    if (!searchTerm) return text;

    const parts = text.split(new RegExp(`(${searchTerm})`, "gi"));
    return parts.map((part, i) =>
      part.toLowerCase() === searchTerm.toLowerCase() ? (
        <strong key={i} style={{ backgroundColor: "var(--highlight-bg, #fff3cd)" }}>
          {part}
        </strong>
      ) : (
        part
      )
    );
  };

  const handlePageChange = (pageNumber) => {
    setCurrentPage(pageNumber);
  };

  // DEPRECATED: Model filter removed - model info shown in each row
  // const handleDeepseekChange = (Deepseek) => {
  //   setSelectedDeepseek(Deepseek);
  // };

  const handleProjectChange = (project) => {
    setSelectedProject(project);
    setCurrentPage(1);
  };

  const handleEnvironmentChange = (environment) => {
    setSelectedEnvironment(environment);
    setCurrentPage(1);
  };

  const handleSearchChange = (e) => {
    setSearchTerm(e.target.value);
  };

  // Re-analyze selected batches. Two modes (RCA audit finding #11):
  //   'primary' — rewrites the batch's primary analysis + refreshes
  //     Issues via fingerprint dedup. This is what a non-expert user
  //     expects "re-analyze" to do.
  //   'compare' — appends to analysis_history so the Compare view can
  //     put multiple models side-by-side.
  // On completion the toast upgrades to a CTA the user can click to
  // see the result: Issues (primary mode) or Compare (compare mode).
  const handleReanalyze = async (model, mode = 'compare') => {
    if (selectedBatchIds.length === 0) return;

    setIsAnalyzing(true);
    setNotification(null);
    // Snapshot the history size on the FIRST selected batch — we poll
    // this endpoint to know when the celery worker has appended its
    // new entry. Single-batch is the common case; for multi-batch
    // primary re-runs we just keep the initial "queued" toast.
    const firstBatchId = selectedBatchIds[0];
    const isSingleBatch = selectedBatchIds.length === 1;
    let startingHistorySize = 0;
    if (isSingleBatch) {
      try {
        const before = await DataService.getAnalysisHistory(firstBatchId);
        startingHistorySize = before?.analysis_count || 0;
      } catch (_e) { /* non-fatal — polling will just no-op */ }
    }

    try {
      const result = await DataService.reanalyzeBatches(selectedBatchIds, model, mode);
      const verb = mode === 'primary' ? 'Re-running primary analysis' : 'Comparing';
      setNotification({
        type: 'info',
        message: `${verb} with ${model} on ${selectedBatchIds.length} batch(es)…`,
      });
      setSelectedBatches({});

      // Poll for completion (single-batch only). Give the AI ~2 min.
      if (isSingleBatch) {
        const started = Date.now();
        const poll = async () => {
          if (Date.now() - started > 120_000) {
            setNotification({
              type: 'warning',
              message: `Still running with ${model}. Refresh the batch to check on it manually.`,
            });
            return;
          }
          try {
            const after = await DataService.getAnalysisHistory(firstBatchId);
            if ((after?.analysis_count || 0) > startingHistorySize) {
              const latest = (after.analysis_history || []).slice(-1)[0];
              const issueCount = latest?.issue_count ?? 0;
              if (mode === 'primary') {
                setNotification({
                  type: 'success',
                  message: (
                    `${model} finished — primary analysis updated with ${issueCount} issue(s). `
                    + `View them in the Issues tab or on the batch detail page.`
                  ),
                  cta: { label: 'View batch', href: `/dash/data/details/${firstBatchId}` },
                });
              } else {
                setNotification({
                  type: 'success',
                  message: `${model} finished — ${issueCount} issue(s) added to comparison.`,
                  cta: { label: 'Open comparison', href: `/dash/data/details/${firstBatchId}?compare=true` },
                });
              }
              return;
            }
          } catch (_e) { /* keep polling */ }
          setTimeout(poll, 4000);
        };
        setTimeout(poll, 4000);
      }
    } catch (error) {
      console.error('Error reanalyzing batches:', error);
      setNotification({
        type: 'error',
        message: `Error: ${error.response?.data?.error || error.message}`,
      });
    } finally {
      setIsAnalyzing(false);
    }
  };

  // View comparison of model results for a single batch
  const handleViewComparison = async () => {
    const batchId = selectedBatchIds[0];
    if (!batchId) return;

    try {
      const history = await DataService.getAnalysisHistory(batchId);

      if (history.analysis_count < 2) {
        setNotification({
          type: 'warning',
          message: 'This batch has only one analysis result. Use "Re-Analyze with Model" to generate a second analysis with a different model, then compare.'
        });
        return;
      }

      // Navigate to detail page with comparison mode
      navigate(`/dash/data/details/${batchId}?compare=true`);
    } catch (error) {
      console.error('Error viewing comparison:', error);
      setNotification({
        type: 'error',
        message: `Error: ${error.message}`
      });
    }
  };

  const handleSendToIA = async () => {
    const selectedBatchId = Object.keys(selectedBatches).find(key => selectedBatches[key]);
    const selectedBatch = data.find((item) => item.id === selectedBatchId);
    if (!selectedBatch) return;

    setIsAnalyzing(true);

    try {
      // Only send batch_id, not model
      const response = await DataService.triggerBatchAnalysis(selectedBatch.id);

      let formattedAnalysis = "Batch Analysis Results:\n\n";

      if (response.analysisResult) {
        if (typeof response.analysisResult === "string") {
          try {
            const parsed = JSON.parse(
              response.analysisResult.replace(/'/g, '"')
            );
            if (parsed.analysis_text) {
              formattedAnalysis += formatAnalysisText(
                JSON.parse(parsed.analysis_text)
              );
            } else if (parsed.correlated_issues) {
              formattedAnalysis += formatAnalysisText(parsed);
            } else {
              formattedAnalysis += response.analysisResult;
            }
          } catch (e) {
            formattedAnalysis += response.analysisResult;
          }
        } else if (response.analysisResult.correlated_issues) {
          formattedAnalysis += formatAnalysisText(response.analysisResult);
        } else {
          formattedAnalysis += JSON.stringify(response.analysisResult, null, 2);
        }
      } else {
        formattedAnalysis += "No analysis available for this batch";
      }

      // Pass chat_id if returned by backend
      navigate(`/dash/chat`, {
        state: {
          batchId: selectedBatch.id,
          model: selectedDeepseek,
          analysisResult: response.analysisResult || null,
          initialMessage: formattedAnalysis,
          sessionId: response.data?.chat_id || null, // <-- Add this line
        },
      });
    } catch (error) {
      console.error("Analysis error:", error);
      navigate(`/dash/chat`, {
        state: {
          initialMessage: `Error analyzing batch: ${error.message}`,
        },
      });
    } finally {
      setIsAnalyzing(false);
    }
  };

  const formatAnalysisText = (analysis) => {
    if (!analysis) return "No analysis available";

    let formatted = "";

    if (analysis.correlated_issues) {
      analysis.correlated_issues.forEach((issue, index) => {
        formatted += `=== Issue ${index + 1} ===\n`;
        formatted += `Root Cause: ${issue.root_cause || "Not specified"}\n`;
        formatted += `Solution: ${issue.solution || "Not specified"}\n`;

        if (issue.related_errors && issue.related_errors.length > 0) {
          formatted += `Related Errors:\n`;
          issue.related_errors.forEach((error, i) => {
            formatted += `- ${error}\n`;
          });
        }

        formatted += "\n";
      });
    } else {
      formatted = JSON.stringify(analysis, null, 2);
    }

    return formatted;
  };

  const handleIssueClick = (id) => {
    navigate(`/dash/issues/${id}`, { state: { from: location.pathname } });
  };

  const handleSelectBatch = (id, event) => {
    // Multi-select: toggle individual batch, keep others selected
    setSelectedBatches((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  };

  const handleSelectAllBatches = () => {
    const allSelected = paginatedData.every((item) => selectedBatches[item.id]);
    if (allSelected) {
      // Deselect all
      setSelectedBatches({});
    } else {
      // Select all visible batches
      const newSelection = {};
      paginatedData.forEach((item) => {
        newSelection[item.id] = true;
      });
      setSelectedBatches(newSelection);
    }
  };

  const selectedBatchIds = Object.keys(selectedBatches).filter((id) => selectedBatches[id]);
  const selectedBatchCount = selectedBatchIds.length;
  const isAnyBatchSelected = selectedBatchCount > 0;
  // Server handles search and pagination
  const paginatedData = data;

  return (
    <div className="data-page-container">
      <div className="data-card">
        {notification && (
          <div className={`data-notification data-notification-${notification.type}`}>
            <span>{notification.message}</span>
            {notification.cta && (
              <Link
                to={notification.cta.href}
                className="data-notification-cta"
                style={{ marginLeft: 12, fontWeight: 600 }}
              >
                {notification.cta.label} →
              </Link>
            )}
            <button onClick={() => setNotification(null)} className="data-notification-close">&times;</button>
          </div>
        )}
        {!isDetailRoute && (
          <>
            <div className="data-toolbar">
              <div className="search-wrapper">
                <FaSearch className="search-icon" aria-hidden="true" />
                <input
                  ref={searchInputRef}
                  type="search"
                  placeholder={t('data.searchPlaceholder')}
                  aria-label={t('data.searchPlaceholder')}
                  className="search-input"
                  value={searchTerm}
                  onChange={handleSearchChange}
                />
              </div>

              <Dropdown className="filter-dropdown">
                <Dropdown.Toggle variant="light">
                  {selectedProject === 'all' ? t('projects.title') : selectedProject}
                </Dropdown.Toggle>
                <Dropdown.Menu style={{ maxHeight: "300px", overflowY: "auto" }}>
                  {projects.map((project) => (
                    <Dropdown.Item
                      key={project}
                      onClick={() => handleProjectChange(project)}
                    >
                      {project === 'all' ? t('common.all') : project}
                    </Dropdown.Item>
                  ))}
                </Dropdown.Menu>
              </Dropdown>

              <Dropdown className="filter-dropdown">
                <Dropdown.Toggle variant="light">
                  {t('data.environment')}: {selectedEnvironment === 'all' ? t('common.all') : t(`data.${selectedEnvironment}`)}
                </Dropdown.Toggle>
                <Dropdown.Menu>
                  <Dropdown.Item onClick={() => handleEnvironmentChange("all")}>
                    {t('data.allEnvironments')}
                  </Dropdown.Item>
                  <Dropdown.Item onClick={() => handleEnvironmentChange("development")}>
                    {t('data.development')}
                  </Dropdown.Item>
                  <Dropdown.Item onClick={() => handleEnvironmentChange("staging")}>
                    {t('data.staging')}
                  </Dropdown.Item>
                  <Dropdown.Item onClick={() => handleEnvironmentChange("production")}>
                    {t('data.production')}
                  </Dropdown.Item>
                </Dropdown.Menu>
              </Dropdown>

              <Dropdown className="filter-dropdown">
                <Dropdown.Toggle
                  variant={isAnyBatchSelected ? "primary" : "light"}
                  disabled={!isAnyBatchSelected || isAnalyzing}
                  className={isAnyBatchSelected ? "action-btn" : ""}
                >
                  {isAnalyzing ? (
                    <>
                      <Spinner animation="border" size="sm" className="me-1" />
                      {t('chat.thinking')}
                    </>
                  ) : (
                    <>
                      <FaBolt className="me-1" />
                      {selectedBatchCount > 0
                        ? `${t('data.analyzeWithAI')} (${selectedBatchCount})`
                        : t('data.analyzeWithAI')}
                    </>
                  )}
                </Dropdown.Toggle>
                <Dropdown.Menu>
                  <Dropdown.Header>Re-run primary analysis (updates Issues)</Dropdown.Header>
                  {availableModels.length > 0 ? (
                    availableModels.map((model) => (
                      <Dropdown.Item
                        key={`primary-${model.id}`}
                        onClick={() => handleReanalyze(model.id, 'primary')}
                      >
                        Re-run with {model.name}
                      </Dropdown.Item>
                    ))
                  ) : (
                    <Dropdown.Item disabled className="text-muted small">
                      No AI provider configured
                    </Dropdown.Item>
                  )}
                  <Dropdown.Divider />
                  <Dropdown.Header>Compare against another model (keeps primary)</Dropdown.Header>
                  {availableModels.length > 0 && availableModels.map((model) => (
                    <Dropdown.Item
                      key={`compare-${model.id}`}
                      onClick={() => handleReanalyze(model.id, 'compare')}
                    >
                      Compare with {model.name}
                    </Dropdown.Item>
                  ))}
                  <Dropdown.Divider />
                  <Dropdown.Item onClick={handleSendToIA}>
                    Chat about Batch
                  </Dropdown.Item>
                  {selectedBatchCount === 1 && (
                    <>
                      <Dropdown.Divider />
                      <Dropdown.Item onClick={handleViewComparison}>
                        Open comparison view
                      </Dropdown.Item>
                      <Dropdown.Item onClick={() => setPostmortemBatchId(selectedBatchIds[0])}>
                        Generate post-mortem draft
                      </Dropdown.Item>
                    </>
                  )}
                </Dropdown.Menu>
              </Dropdown>
            </div>

            <div className="table-responsive">
              <table className="modern-table">
                <thead>
                  <tr>
                    <th style={{ width: "60px" }}></th>
                    <th>{t('data.timestamp')}</th>
                    <th>Batch ID</th>
                    <th>{t('projects.title')}</th>
                    <th>{t('data.environment')}</th>
                    <th>Sentinel</th>
                    <th>{t('issues.title')}</th>
                    <th>{t('data.status')}</th>
                    <th style={{ width: "80px" }}>{t('data.actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {isLoading && data.length === 0 ? (
                    <tr>
                      <td colSpan="9" className="table-loading">
                        <Spinner animation="border" variant="primary" />
                        <p className="mt-2">{t('data.loading')}</p>
                      </td>
                    </tr>
                  ) : data.length === 0 ? (
                    <tr>
                      <td colSpan="9" className="table-loading">
                        <p>{t('data.noBatches')}</p>
                      </td>
                    </tr>
                  ) : (
                    paginatedData.map((item) => {
                      const getStatusBadge = () => {
                        if (item.model_name && item.model_name.startsWith("FAILED")) {
                          const reasonMatch = item.model_name.match(/\(([^)]+)\)/);
                          const reasonCode = reasonMatch ? reasonMatch[1] : null;
                          const tooltipMap = {
                            'TRUNCATED': 'AI response was truncated (hit output token limit)',
                            'QUOTA_EXCEEDED': 'AI quota exceeded',
                            'AUTH_ERROR': 'API authentication failed',
                            'NETWORK_ERROR': 'Connection to AI service failed',
                            'TIMEOUT': 'AI request timed out',
                            'PARSE ERROR': 'AI response could not be parsed as JSON',
                          };
                          const tooltip = reasonCode ? (tooltipMap[reasonCode] || reasonCode) : 'AI analysis failed';
                          return <span className="status-badge failed" title={tooltip}>Failed</span>;
                        }
                        if (item.issue_count > 0 || item.analyzed_at) {
                          return <span className="status-badge analyzed">Analyzed</span>;
                        }
                        if (item.ai_skipped) {
                          return <span className="status-badge skipped">Skipped</span>;
                        }
                        // Sentinel put the batch in shadow/quiet mode
                        // and the AI pipeline deliberately did not run.
                        // Prior to this, we labelled these as "Pending"
                        // which read as "waiting for a worker" — users
                        // opened them expecting an in-flight analysis.
                        if (item.sentinel_decision === 'shadow') {
                          return <span className="status-badge skipped" title="Sentinel is in shadow (observe-only) mode — AI analysis was not dispatched">Sentinel: Shadow</span>;
                        }
                        if (item.sentinel_decision === 'quiet') {
                          return <span className="status-badge skipped" title="Sentinel classified this batch as Quiet — AI analysis was skipped to save cost">Sentinel: Quiet</span>;
                        }
                        return <span className="status-badge pending">Pending</span>;
                      };

                      return (
                        <tr key={item.id}>
                          <td>
                            <input
                              type="checkbox"
                              className="custom-checkbox"
                              aria-label={`Select batch ${item.batch}`}
                              checked={!!selectedBatches[item.id]}
                              onChange={() => handleSelectBatch(item.id)}
                            />
                          </td>
                          <td>{highlightSearchTerm(item.timestamp)}</td>
                          <td className="ds-mono" style={{ whiteSpace: 'nowrap', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis' }} title={item.batch}>
                            {highlightSearchTerm(item.batch)}
                          </td>
                          <td style={{ fontWeight: "500" }}>
                            {highlightSearchTerm(item.project_name)}
                          </td>
                          <td>
                            <span style={{ textTransform: 'capitalize' }}>
                              {item.environment || 'production'}
                            </span>
                          </td>
                          <td>
                            {(() => {
                              const isRoutine = item.sentinel_decision === 'alert'
                                && item.sentinel_triggers?.length === 1
                                && item.sentinel_triggers[0] === 'forced_periodic';
                              const badgeClass = isRoutine ? 'sentinel-routine' : `sentinel-${item.sentinel_decision}`;
                              const label = isRoutine ? 'routine' : item.sentinel_decision;
                              const triggerLabels = {
                                forced_periodic: 'Periodic health check',
                                deployment_detected: 'New deployment',
                                new_error_pattern: 'New error pattern',
                                error_rate_spike: 'Error rate spike',
                                memory_anomaly: 'Memory anomaly',
                                cpu_anomaly: 'CPU anomaly',
                                error_rate_escalating: 'Error rate escalating',
                                issue_regression: 'Issue regression',
                                first_batch: 'First batch',
                              };
                              const tooltip = (item.sentinel_triggers || [])
                                .map(t => triggerLabels[t] || t)
                                .join(', ') || item.sentinel_decision;
                              return (
                                <span className={`sentinel-badge ${badgeClass}`} title={tooltip}>
                                  {label}
                                </span>
                              );
                            })()}
                          </td>
                          <td>
                            {item.issue_count > 0 ? (
                              <span
                                className="fw-bold text-danger clickable-issue"
                                style={{ cursor: "pointer" }}
                                onClick={() => handleIssueClick(item.id)}
                              >
                                {item.issue_count}
                              </span>
                            ) : (
                              <span className="text-secondary">None</span>
                            )}
                          </td>
                          <td>
                            <div className="d-flex align-items-center gap-2">
                              {getStatusBadge()}
                              {item.model && item.model !== "Not found" && (
                                <span className="text-muted small">({item.model})</span>
                              )}
                            </div>
                          </td>
                          <td>
                            <Link to={`/dash/data/details/${item.id}`} className="view-btn">
                              <FaEye size={18} />
                            </Link>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            <div className="pagination-footer">
              <div className="pagination-info">
                {pagination && typeof pagination.offset !== 'undefined' ? (
                  <>
                    Showing <strong>{pagination.offset + 1}-{Math.min(pagination.offset + data.length, pagination.total)}</strong> of <strong>{pagination.total}</strong>
                  </>
                ) : (
                  <>Page {currentPage}</>
                )}
              </div>

              <div className="modern-pagination">
                <button
                  className="page-btn"
                  onClick={prevPage}
                  disabled={currentPage === 1}
                >
                  &lt;
                </button>

                {/* Dynamic Pagination Buttons */}
                {(() => {
                  const pages = [];
                  const maxVisible = 5;

                  if (totalPages <= 7) {
                    for (let i = 1; i <= totalPages; i++) pages.push(i);
                  } else {
                    pages.push(1);

                    if (currentPage > 3) pages.push("...");

                    let start = Math.max(2, currentPage - 1);
                    let end = Math.min(totalPages - 1, currentPage + 1);

                    if (currentPage <= 3) {
                      end = 4;
                    } else if (currentPage >= totalPages - 2) {
                      start = totalPages - 3;
                    }

                    for (let i = start; i <= end; i++) pages.push(i);

                    if (currentPage < totalPages - 2) pages.push("...");

                    pages.push(totalPages);
                  }

                  return pages.map((page, index) => (
                    <button
                      key={index}
                      className={`page-btn ${page === currentPage ? "active" : ""} ${page === "..." ? "dots" : ""}`}
                      onClick={() => typeof page === "number" && goToPage(page)}
                      disabled={page === "..."}
                    >
                      {page}
                    </button>
                  ));
                })()}
                <button
                  className="page-btn"
                  onClick={nextPage}
                  disabled={currentPage === totalPages}
                >
                  &gt;
                </button>
              </div>
            </div>
          </>
        )}
        <Outlet />
      </div>
      {/* Item #28 — post-mortem draft modal, controlled by dropdown item above. */}
      <PostmortemModal
        show={!!postmortemBatchId}
        batchId={postmortemBatchId}
        onHide={() => setPostmortemBatchId(null)}
      />
    </div >
  );
};

export default Data;
