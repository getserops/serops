import React, { useState, useEffect, useCallback, useRef } from "react";
import { Table, Form, OverlayTrigger, Tooltip, Modal, Button, Badge, Dropdown, InputGroup } from "react-bootstrap";
import { FaExclamationCircle, FaEye, FaCheck, FaVolumeMute, FaRedo, FaLink, FaChartLine, FaColumns, FaEllipsisV, FaSearch, FaSortUp, FaSortDown, FaSort, FaCheckCircle, FaKeyboard, FaCog, FaProjectDiagram } from "react-icons/fa";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "react-toastify";
import { formatDistanceToNow } from "date-fns";
import dataService from "../services/data.service";
import notificationService from "../services/notification.service";
import InvestigationService from "../services/investigation.service";
import IssuePanel, { StatusChip } from "./issues/IssuePanel";
import { useCluster } from "../context/ClusterContext";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import "./Issues.css";

// --- Utility helpers (exported for testing) ---

export const formatAge = (dateStr) => {
  if (!dateStr) return "\u2014";
  try {
    const result = formatDistanceToNow(new Date(dateStr), { addSuffix: true });
    return result.replace(/^about /, '');
  } catch {
    return "\u2014";
  }
};

const toTitleCase = (str) => str.charAt(0).toUpperCase() + str.slice(1).toLowerCase();

export const abbreviateComponent = (name) => {
  if (!name) return "Infra";
  const map = {
    INFRASTRUCTURE: "Infra",
    AUTHENTICATION: "Auth",
    AUTHORIZATION: "Authz",
    DATABASE: "DB",
    CONFIGURATION: "Config",
    NOTIFICATION: "Notif",
  };
  const upper = name.toUpperCase();
  if (map[upper]) return map[upper];
  // Scope words arrive upper-case (e.g. NETWORK); service names are shown
  // exactly as they are named ("backend-api"), and CSS truncates long ones.
  return name === upper ? toTitleCase(name) : name;
};

export const getCountHeatLevel = (count) => {
  if (count > 20) return "red";
  if (count > 5) return "amber";
  return "normal";
};

export const getSeverityColor = (severity) => {
  switch (severity?.toLowerCase()) {
    case "critical":
      return "#e53935";
    case "high":
      return "#d81b60";
    case "medium":
      return "#ffb300";
    case "warning":
      return "#fb8c00";
    case "low":
      return "#43a047";
    default:
      return "#6c757d";
  }
};

export const getSeverityRowClass = (severity) => {
  switch (severity?.toUpperCase()) {
    case "CRITICAL":
      return "issue-row-critical";
    case "WARNING":
      return "issue-row-warning";
    case "INFO":
      return "issue-row-info";
    default:
      return "";
  }
};

export const getComponentChipClass = (scope) => {
  switch (scope?.toUpperCase()) {
    case 'SERVICE':
    case 'BACKEND':
    case 'API':
      return 'component-chip-service';
    case 'INFRASTRUCTURE':
    case 'INFRA':
      return 'component-chip-infra';
    case 'PIPELINE':
    case 'CICD':
      return 'component-chip-pipeline';
    default:
      return '';
  }
};

const Issues = () => {
  const { t } = useTranslation();
  const { batchId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const { clusterId } = useCluster();
  const [currentPage, setCurrentPage] = useState(
    parseInt(searchParams.get("page") || "1")
  );
  const [severityFilter, setSeverityFilter] = useState(
    searchParams.get("severity") || "All"
  );
  const [statusFilter, setStatusFilter] = useState(
    searchParams.get("status") || "All"
  );
  const [sortBy, setSortBy] = useState(
    searchParams.get("sort_by") || "severity"
  );
  const [sortDir, setSortDir] = useState(
    searchParams.get("sort_dir") || "desc"
  );
  const [searchTerm, setSearchTerm] = useState(
    searchParams.get("search") || ""
  );
  const [debouncedSearch, setDebouncedSearch] = useState(searchTerm);
  const [projectFilter, setProjectFilter] = useState(searchParams.get("project") || "");
  const [environmentFilter, setEnvironmentFilter] = useState(searchParams.get("environment") || "");
  const [componentFilter, setComponentFilter] = useState(searchParams.get("component") || "");
  const [scopeOptions, setScopeOptions] = useState({ projects: [] });
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // Deep linking: ?id=17 opens that issue's panel.
  const [panelIssueId, setPanelIssueId] = useState(searchParams.get("id") ? parseInt(searchParams.get("id")) : null);

  // Mute modal state
  const [showMuteModal, setShowMuteModal] = useState(false);
  const [muteIssueId, setMuteIssueId] = useState(null);
  const [muteDays, setMuteDays] = useState(7);
  // Track if mute is for bulk or single
  const [isBulkMute, setIsBulkMute] = useState(false);

  // Bulk selection state
  const [selectedIds, setSelectedIds] = useState(new Set());

  // Keyboard navigation state
  const [focusedIndex, setFocusedIndex] = useState(-1);
  const [showShortcutHelp, setShowShortcutHelp] = useState(false);
  const tableRef = useRef(null);

  // Column visibility state — merge saved with defaults so new columns get their default value
  const [visibleColumns, setVisibleColumns] = useState(() => {
    const defaults = {
      id: false,
      type: false,
      component: true,
      description: true,
      age: true,
      correlations: false,
      count: true,
      severity: true,
      status: true,
      actions: true,
    };
    const saved = localStorage.getItem('issueColumnVisibility');
    if (saved) {
      try { return { ...defaults, ...JSON.parse(saved) }; } catch { /* fall through */ }
    }
    return defaults;
  });

  const columnLabels = {
    id: 'ID',
    type: 'Type',
    component: 'Component',
    description: 'Description',
    age: 'Age',
    correlations: 'Correlations',
    count: 'Occurrences',
    severity: 'Severity',
    status: 'Status',
    actions: 'Actions',
  };

  const sortableColumns = {
    id: null,
    type: 'type',
    component: 'component',
    description: 'description',
    age: 'created_at',
    correlations: null,
    count: 'count',
    severity: 'severity',
    status: 'status',
    actions: null,
  };

  const toggleColumn = (column) => {
    if (column === 'actions') return;
    setVisibleColumns(prev => {
      const updated = { ...prev, [column]: !prev[column] };
      localStorage.setItem('issueColumnVisibility', JSON.stringify(updated));
      return updated;
    });
  };

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchTerm);
      setCurrentPage(1);
    }, 400);
    return () => clearTimeout(timer);
  }, [searchTerm]);

  const buildQueryParams = useCallback(() => {
    const params = {
      page: currentPage,
      page_size: 10,
      sort_by: sortBy,
      sort_dir: sortDir,
    };
    if (severityFilter !== "All") params.severity = severityFilter.toUpperCase();
    if (statusFilter !== "All") params.status = statusFilter.toUpperCase();
    if (debouncedSearch) params.search = debouncedSearch;
    if (projectFilter) params.project = projectFilter;
    if (environmentFilter) params.environment = environmentFilter;
    if (componentFilter) params.component = componentFilter;
    // Cluster picker (Item #19) — only applied when set + not viewing a
    // single batch's issues (that batch already implies its cluster).
    if (clusterId != null && !batchId) params.cluster = clusterId;
    return params;
  }, [currentPage, severityFilter, statusFilter, sortBy, sortDir, debouncedSearch, projectFilter, environmentFilter, componentFilter, clusterId, batchId]);

  // Fetch issues with auto-refresh (30s)
  const {
    data,
    isLoading: loading,
    error: queryError,
    isPlaceholderData,
  } = useQuery({
    queryKey: ["issues", batchId, currentPage, severityFilter, statusFilter, sortBy, sortDir, debouncedSearch, projectFilter, environmentFilter, componentFilter, clusterId],
    queryFn: async () => {
      const params = buildQueryParams();
      if (batchId) {
        return await dataService.getIssuesByBatch(batchId, params);
      } else {
        return await dataService.getIssues(params);
      }
    },
    placeholderData: (previousData) => previousData,
    refetchInterval: 30000,
  });

  const issuesData = data?.results || [];
  const pagination = data?.pagination || null;
  const summary = data?.summary || null;
  const error = queryError
    ? (queryError.response?.data?.error || queryError.message || "Failed to load issues. Please try again later.")
    : null;

  // Sync URL params
  useEffect(() => {
    const params = {};
    if (currentPage !== 1) params.page = currentPage;
    if (severityFilter !== "All") params.severity = severityFilter;
    if (statusFilter !== "All") params.status = statusFilter;
    if (sortBy !== "severity") params.sort_by = sortBy;
    if (sortDir !== "desc") params.sort_dir = sortDir;
    if (debouncedSearch) params.search = debouncedSearch;
    if (projectFilter) params.project = projectFilter;
    if (environmentFilter) params.environment = environmentFilter;
    if (componentFilter) params.component = componentFilter;
    if (panelIssueId) params.id = panelIssueId;
    setSearchParams(params);
  }, [currentPage, severityFilter, statusFilter, sortBy, sortDir, debouncedSearch, projectFilter, environmentFilter, componentFilter, panelIssueId, setSearchParams]);

  // Project / environment / service choices for the filters.
  useEffect(() => {
    InvestigationService.options().then(setScopeOptions).catch(() => {});
  }, []);

  // Clear selection when data changes
  useEffect(() => {
    setSelectedIds(new Set());
  }, [currentPage, severityFilter, statusFilter, sortBy, sortDir, debouncedSearch, projectFilter, environmentFilter, componentFilter]);

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Don't intercept if user is typing in an input
      if (
        e.target.tagName === 'INPUT' ||
        e.target.tagName === 'SELECT' ||
        e.target.tagName === 'TEXTAREA' ||
        e.target.isContentEditable
      ) return;

      const len = issuesData.length;
      if (len === 0) return;

      switch (e.key) {
        case 'j': {
          e.preventDefault();
          setFocusedIndex(prev => Math.min(prev + 1, len - 1));
          break;
        }
        case 'k': {
          e.preventDefault();
          setFocusedIndex(prev => Math.max(prev - 1, 0));
          break;
        }
        case 'v':
        case 'Enter': {
          if (focusedIndex >= 0 && focusedIndex < len && !e.target.closest?.('button, a, .dropdown')) {
            e.preventDefault();
            setPanelIssueId(issuesData[focusedIndex].id);
          }
          break;
        }
        case 'r': {
          if (focusedIndex >= 0 && focusedIndex < len) {
            e.preventDefault();
            const issue = issuesData[focusedIndex];
            if (issue.status === 'OPEN') handleResolve(issue);
          }
          break;
        }
        case 'm': {
          if (focusedIndex >= 0 && focusedIndex < len) {
            e.preventDefault();
            const issue = issuesData[focusedIndex];
            if (issue.status === 'OPEN') handleMuteClick(issue.id);
          }
          break;
        }
        case 'x': {
          if (focusedIndex >= 0 && focusedIndex < len) {
            e.preventDefault();
            const issueId = issuesData[focusedIndex].id;
            toggleSelection(issueId);
          }
          break;
        }
        case '?': {
          e.preventDefault();
          setShowShortcutHelp(prev => !prev);
          break;
        }
        case 'Escape': {
          setShowShortcutHelp(false);
          break;
        }
        default:
          break;
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [focusedIndex, issuesData]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- Selection helpers ---
  const toggleSelection = (issueId) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(issueId)) next.delete(issueId);
      else next.add(issueId);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === issuesData.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(issuesData.map(i => i.id)));
    }
  };

  // Status as a label: a coloured dot alone failed WCAG 1.4.1 and left
  // open / muted / resolved to guesswork.
  const getStatusBadge = (issueStatus) => <StatusChip status={issueStatus} t={t} />;

  // Correlation badges
  const renderCorrelationBadges = (issue) => {
    const badges = [];
    const linkedCommits = Array.isArray(issue.linked_commits) ? issue.linked_commits : [];
    const confidence = issue.correlation_confidence || '';
    const anomalyType = issue.metric_anomaly_type || '';
    const metricDetail = (issue.correlation_details || {}).metric_anomaly || {};

    if (issue.has_commit_correlation && linkedCommits.length > 0) {
      const firstCommit = linkedCommits[0];
      const commitSha = typeof firstCommit === 'object' ? firstCommit.sha : String(firstCommit);
      const displaySha = commitSha ? commitSha.substring(0, 8) : 'unknown';
      const tooltipText = `Linked to commit ${displaySha}${confidence ? ` (${confidence})` : ''}`;
      badges.push(
        <OverlayTrigger key="commit" overlay={<Tooltip>{tooltipText}</Tooltip>}>
          <Badge bg="purple" className="me-1 d-inline-flex align-items-center" style={{ backgroundColor: '#7c3aed', cursor: 'pointer' }}>
            <FaLink size={10} className="me-1" />{displaySha}
          </Badge>
        </OverlayTrigger>
      );
    }
    if (issue.has_metric_correlation) {
      const metricType = issue.metric_correlation_type || 'resource';
      const label = anomalyType === 'sustained_high' ? 'sustained' : metricType;
      const badgeBg = anomalyType === 'sustained_high' ? 'warning' : 'info';
      const peakStr = metricDetail.peak_value != null ? ` peak ${metricDetail.peak_value}%` : '';
      const durationStr = metricDetail.duration_seconds > 0 ? ` (${Math.round(metricDetail.duration_seconds / 60)}m)` : '';
      const tooltipText = `${metricType.charAt(0).toUpperCase() + metricType.slice(1)} ${anomalyType === 'sustained_high' ? 'sustained high' : 'spike'}${peakStr}${durationStr}`;
      badges.push(
        <OverlayTrigger key="metric" overlay={<Tooltip>{tooltipText}</Tooltip>}>
          <Badge bg={badgeBg} className="d-inline-flex align-items-center" style={{ cursor: 'pointer' }}>
            <FaChartLine size={10} className="me-1" />{label}
          </Badge>
        </OverlayTrigger>
      );
    }
    // Trace correlation — appears when the issue's originating batch
    // snapshotted spans (see backend #10.5). Links straight into the
    // trace waterfall for the most-relevant error span (or top-slow
    // if no errors).
    const traces = issue.related_traces || {};
    const traceLink = (traces.top_errors && traces.top_errors[0])
      || (traces.top_slow && traces.top_slow[0])
      || null;
    if (traces.span_count > 0 && traceLink && traceLink.trace_id) {
      const svc = traceLink.service_name || '';
      const op = traceLink.operation_name || '';
      const errCount = traces.error_span_count || 0;
      const tooltipText = `${traces.span_count} spans (${errCount} errors)`
        + (svc ? ` — ${svc}` : '') + (op ? ` :: ${op}` : '');
      badges.push(
        <OverlayTrigger key="trace" overlay={<Tooltip>{tooltipText}</Tooltip>}>
          <Badge
            bg={errCount > 0 ? 'danger' : 'info'}
            className="d-inline-flex align-items-center"
            style={{ cursor: 'pointer' }}
            onClick={(e) => {
              e.stopPropagation();
              navigate(`/dash/traces/${traceLink.trace_id}`);
            }}
          >
            <FaProjectDiagram size={10} className="me-1" />
            {errCount > 0 ? `${errCount} err` : `${traces.span_count} spans`}
          </Badge>
        </OverlayTrigger>
      );
    }
    if (issue.has_cicd_correlation) {
      const cicdDetail = (issue.correlation_details || {}).cicd_correlation || {};
      const jobName = cicdDetail.job_name || 'pipeline';
      const pipelineId = cicdDetail.pipeline_id || '';
      const tooltipText = `Pipeline failure: ${jobName}${pipelineId ? ` (#${pipelineId})` : ''}`;
      badges.push(
        <OverlayTrigger key="cicd" overlay={<Tooltip>{tooltipText}</Tooltip>}>
          <Badge bg="secondary" className="d-inline-flex align-items-center" style={{ cursor: 'pointer' }}>
            <FaCog size={10} className="me-1" />Pipeline
          </Badge>
        </OverlayTrigger>
      );
    }
    if (badges.length === 0) return <span className="text-muted">&mdash;</span>;
    return <div className="d-flex flex-wrap gap-1">{badges}</div>;
  };

  const handleCopyId = (issueId) => {
    const url = `${window.location.origin}/dash/issues?id=${issueId}`;
    navigator.clipboard.writeText(url);
    toast.success("Issue link copied!");
  };

  const handleSort = (columnKey) => {
    const apiField = sortableColumns[columnKey];
    if (!apiField) return;
    if (sortBy === apiField) {
      setSortDir(prev => prev === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(apiField);
      setSortDir('desc');
    }
    setCurrentPage(1);
  };

  const renderSortIcon = (columnKey) => {
    const apiField = sortableColumns[columnKey];
    if (!apiField) return null;
    if (sortBy === apiField) {
      return sortDir === 'asc'
        ? <FaSortUp className="ms-1 text-primary" size={12} />
        : <FaSortDown className="ms-1 text-primary" size={12} />;
    }
    return <FaSort className="ms-1 text-muted opacity-50" size={10} />;
  };

  const handleSeverityFilterChange = (event) => {
    setSeverityFilter(event.target.value);
    setCurrentPage(1);
  };

  const handleStatusFilterChange = (event) => {
    setStatusFilter(event.target.value);
    setCurrentPage(1);
  };

  const handleSolutionClick = (issue) => {
    navigate("/dash/chat", {
      state: {
        issueContext: {
          issueId: issue.id,
          batchId: issue.batch,
          message: issue.description,
          solution: issue.solution,
          root_cause: issue.root_cause,
          recommendation: issue.recommendation,
          // AI evidence chain + how confident the AI is in this root cause
          reasoning: issue.reasoning || '',
          confidence: issue.confidence || '',
          confidence_display: issue.confidence_display || '',
          // "Informed by N past resolutions" digest from the backend
          informed_by: issue.informed_by || { count: 0, items: [] },
          // Trace snapshot from the issue's originating batch
          related_traces: issue.related_traces || null,
          has_commit_correlation: issue.has_commit_correlation,
          has_metric_correlation: issue.has_metric_correlation,
          has_cicd_correlation: issue.has_cicd_correlation,
          linked_commits: issue.linked_commits || [],
          metric_correlation_type: issue.metric_correlation_type || '',
          correlation_confidence: issue.correlation_confidence || '',
          metric_anomaly_type: issue.metric_anomaly_type || '',
          correlation_details: issue.correlation_details || {},
        },
      },
    });
  };

  // Mirrors MIN_ROOT_CAUSE_LENGTH in backend/Data/memory.py — resolutions
  // shorter than this are dropped from past-incident memory.
  const MEMORY_ROOT_CAUSE_MIN_LENGTH = 30;

  // Single action handlers
  const handleResolve = async (issue) => {
    // Accept either an Issue object (preferred) or a raw id for backward compat.
    const issueId = typeof issue === 'object' ? issue.id : issue;
    const rootCause = typeof issue === 'object' ? (issue.root_cause || '').trim() : '';

    try {
      await dataService.resolveIssue(issueId);
      queryClient.invalidateQueries({ queryKey: ["issues"] });

      if (rootCause.length >= MEMORY_ROOT_CAUSE_MIN_LENGTH) {
        // Positive reinforcement — this resolution will feed future analyses.
        toast.success(
          "Issue resolved. The root cause will be used as context in future AI analyses for this project.",
          { autoClose: 4000 }
        );
      } else {
        toast.success("Issue resolved successfully");
        // Soft nudge — heads-up that this won't contribute as context.
        toast.info(
          "Tip: a more descriptive root cause becomes useful context for future AI analyses on this project.",
          { autoClose: 6000 }
        );
      }
    } catch {
      toast.error("Failed to resolve issue");
    }
  };

  const handleMuteClick = (issueId) => {
    setMuteIssueId(issueId);
    setIsBulkMute(false);
    setShowMuteModal(true);
  };

  const handleMuteConfirm = async () => {
    try {
      if (isBulkMute) {
        await dataService.bulkAction([...selectedIds], 'mute', muteDays);
        toast.success(`${selectedIds.size} issue(s) muted`);
        setSelectedIds(new Set());
      } else {
        await dataService.muteIssue(muteIssueId, muteDays);
        toast.success(`Issue muted for ${muteDays === 0 ? 'forever' : `${muteDays} days`}`);
      }
      setShowMuteModal(false);
      queryClient.invalidateQueries({ queryKey: ["issues"] });
    } catch {
      toast.error("Failed to mute issue");
    }
  };

  const handleReopen = async (issueId) => {
    try {
      await dataService.reopenIssue(issueId);
      toast.success("Issue reopened");
      queryClient.invalidateQueries({ queryKey: ["issues"] });
    } catch {
      toast.error("Failed to reopen issue");
    }
  };

  const handleAcknowledge = async (issue) => {
    try {
      await notificationService.acknowledgeIssue(issue.id);
      toast.success(t('issues.panel.acknowledgedToast'));
      queryClient.invalidateQueries({ queryKey: ["issues"] });
    } catch {
      toast.error(t('issues.panel.acknowledgeFailed'));
    }
  };

  // Count tiles double as filters; clicking the active one clears it.
  const toggleTileFilter = (kind, value) => {
    if (kind === 'severity') setSeverityFilter(severityFilter === value ? 'All' : value);
    else setStatusFilter(statusFilter === value ? 'All' : value);
    setCurrentPage(1);
  };
  const scopeProject = scopeOptions.projects.find((p) => String(p.id) === String(projectFilter));
  const environmentChoices = [...new Set((scopeProject ? [scopeProject] : scopeOptions.projects)
    .flatMap((p) => p.environments.map((e) => e.name)))].sort();
  const serviceChoices = [...new Set((scopeProject ? [scopeProject] : scopeOptions.projects)
    .flatMap((p) => p.services))].sort();
  const selectedIssues = issuesData.filter((i) => selectedIds.has(i.id));
  const canResolveSelection = selectedIssues.some((i) => i.status === 'OPEN');
  const canReopenSelection = selectedIssues.some((i) => i.status !== 'OPEN');
  const panelIssue = issuesData.find((i) => i.id === panelIssueId) || null;

  // Bulk action handlers
  const handleBulkResolve = async () => {
    try {
      const result = await dataService.bulkAction([...selectedIds], 'resolve');
      toast.success(`${result.updated} issue(s) resolved`);
      setSelectedIds(new Set());
      queryClient.invalidateQueries({ queryKey: ["issues"] });
    } catch {
      toast.error("Failed to bulk resolve");
    }
  };

  const handleBulkMuteClick = () => {
    setIsBulkMute(true);
    setShowMuteModal(true);
  };

  const handleBulkReopen = async () => {
    try {
      const result = await dataService.bulkAction([...selectedIds], 'reopen');
      toast.success(`${result.updated} issue(s) reopened`);
      setSelectedIds(new Set());
      queryClient.invalidateQueries({ queryKey: ["issues"] });
    } catch {
      toast.error("Failed to bulk reopen");
    }
  };

  // Summary stats
  const summaryStats = summary ? {
    critical: summary.severity_distribution?.CRITICAL || 0,
    warning: summary.severity_distribution?.WARNING || 0,
    open: summary.status_distribution?.OPEN || 0,
    muted: summary.status_distribution?.MUTED || 0,
    resolved: summary.status_distribution?.RESOLVED || 0,
  } : null;

  // Empty state celebration logic
  const showCelebration = issuesData.length === 0 && !debouncedSearch && (
    (statusFilter === "RESOLVED" && summaryStats?.resolved > 0) ||
    (statusFilter === "All" && summaryStats && summaryStats.open === 0 && summaryStats.resolved > 0)
  );

  if (loading && !isPlaceholderData) {
    return <div className="text-center">{t('common.loading')}</div>;
  }

  if (error) {
    return (
      <div className="p-3 d-flex justify-content-center">
        <div className="bg-white p-3 rounded-3" style={{ maxWidth: "1400px", width: "100%" }}>
          <div className="alert alert-danger" role="alert">{error}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="fade-in">
      <IssuePanel
        issue={panelIssue}
        onClose={() => setPanelIssueId(null)}
        onResolve={handleResolve}
        onMute={handleMuteClick}
        onReopen={handleReopen}
        onAcknowledge={handleAcknowledge}
        onAskAI={handleSolutionClick}
        onCopyLink={(issue) => handleCopyId(issue.id)}
      />
      <div className="bg-white p-4 rounded-4 shadow-sm issues-page-card">
        {/* Breadcrumb (batch view) */}
        {batchId && (
          <nav className="issues-breadcrumb">
            <Link to="/dash/issues">Issues</Link>
            <span className="issues-breadcrumb-sep">&rsaquo;</span>
            <span className="ds-mono" title={batchId}>{batchId.length <= 24 ? batchId : batchId.slice(0, 8) + '…' + batchId.slice(-6)}</span>
          </nav>
        )}

        {/* Page header */}
        <div className="mb-3">
          <div className="d-flex align-items-center gap-2 mb-1">
            <h4 className="mb-0 fw-bold text-dark">
              {batchId
                ? `${pagination?.total_issues ?? issuesData.length} Issues Detected`
                : t('issues.systemIssues')}
            </h4>
            <span className="auto-refresh-indicator">
              <span className="auto-refresh-dot" />
              auto-refresh
            </span>
          </div>
          <p className="text-muted mb-0 small">
            {batchId
              ? <>From batch analysis &middot; <span className="ds-mono" title={batchId}>{batchId.length <= 24 ? batchId : batchId.slice(0, 8) + '…' + batchId.slice(-6)}</span></>
              : t('issues.trackAnomalies')}
          </p>
        </div>

        {/* Summary stat cards */}
        {summaryStats && (
          <div className="issue-stat-grid">
            {[
              ['critical', 'severity', 'Critical', summaryStats.critical],
              ['warning', 'severity', 'Warning', summaryStats.warning],
              ['open', 'status', 'OPEN', summaryStats.open],
              ['resolved', 'status', 'RESOLVED', summaryStats.resolved],
            ].map(([key, kind, value, count]) => {
              const active = (kind === 'severity' ? severityFilter : statusFilter) === value;
              return (
                <button
                  key={key}
                  type="button"
                  className={`issue-stat-card issue-stat-${key}${active ? ' is-active' : ''}`}
                  aria-pressed={active}
                  onClick={() => toggleTileFilter(kind, value)}
                >
                  <span className="issue-stat-value">{count}</span>
                  <span className="issue-stat-label">{t(`issues.tiles.${key}`)}</span>
                </button>
              );
            })}
          </div>
        )}

        {/* Filter toolbar */}
        <div className="issues-toolbar">
          <InputGroup className="issues-search">
            <InputGroup.Text className="bg-light border-0">
              <FaSearch size={12} className="text-muted" />
            </InputGroup.Text>
            <Form.Control
              type="text"
              placeholder={t('issues.searchPlaceholder')}
              aria-label={t('issues.searchPlaceholder')}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="bg-light border-0"
              size="sm"
            />
          </InputGroup>

          <Form.Select
            value={severityFilter}
            onChange={handleSeverityFilterChange}
            style={{ width: "140px" }}
            className="bg-light border-0"
            size="sm"
            aria-label="Filter by severity"
          >
            <option value="All">{t('common.all')} Severity</option>
            <option value="Critical">{t('issues.critical')}</option>
            <option value="Warning">{t('issues.warning')}</option>
          </Form.Select>

          <Form.Select
            value={statusFilter}
            onChange={handleStatusFilterChange}
            style={{ width: "140px" }}
            className="bg-light border-0"
            size="sm"
            aria-label="Filter by status"
          >
            <option value="All">{t('common.all')} Status</option>
            <option value="OPEN">Open</option>
            <option value="MUTED">Muted</option>
            <option value="RESOLVED">Resolved</option>
          </Form.Select>

          {!batchId && scopeOptions.projects.length > 0 && (
            <>
              <Form.Select value={projectFilter} size="sm" className="bg-light border-0 issues-scope-select"
                           aria-label={t('issues.filters.project')}
                           onChange={(e) => { setProjectFilter(e.target.value); setEnvironmentFilter(''); setComponentFilter(''); setCurrentPage(1); }}>
                <option value="">{t('issues.filters.allProjects')}</option>
                {scopeOptions.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </Form.Select>
              <Form.Select value={environmentFilter} size="sm" className="bg-light border-0 issues-scope-select"
                           aria-label={t('issues.filters.environment')}
                           onChange={(e) => { setEnvironmentFilter(e.target.value); setCurrentPage(1); }}>
                <option value="">{t('issues.filters.allEnvironments')}</option>
                {environmentChoices.map((n) => <option key={n} value={n}>{n}</option>)}
              </Form.Select>
              <Form.Select value={componentFilter} size="sm" className="bg-light border-0 issues-scope-select"
                           aria-label={t('issues.filters.service')}
                           onChange={(e) => { setComponentFilter(e.target.value); setCurrentPage(1); }}>
                <option value="">{t('issues.filters.allServices')}</option>
                {serviceChoices.map((n) => <option key={n} value={n}>{n}</option>)}
              </Form.Select>
            </>
          )}

          <Dropdown>
            <Dropdown.Toggle variant="outline-secondary" size="sm" id="columns-dropdown">
              <FaColumns className="me-1" /> Columns
            </Dropdown.Toggle>
            <Dropdown.Menu>
              {Object.entries(columnLabels).map(([key, label]) => (
                <Dropdown.Item
                  key={key}
                  onClick={() => toggleColumn(key)}
                  className="d-flex align-items-center justify-content-between"
                  disabled={key === 'id' || key === 'actions'}
                >
                  <span>{label}</span>
                  {visibleColumns[key] && <FaCheck className="text-success ms-2" size={12} />}
                </Dropdown.Item>
              ))}
            </Dropdown.Menu>
          </Dropdown>

          <OverlayTrigger overlay={<Tooltip>Keyboard shortcuts (?)</Tooltip>}>
            <button
              className="btn btn-link btn-sm p-1 text-muted"
              onClick={() => setShowShortcutHelp(true)}
              aria-label="Show keyboard shortcuts"
            >
              <FaKeyboard size={16} aria-hidden="true" />
            </button>
          </OverlayTrigger>

          {pagination && (
            <span className="issues-result-count" aria-live="polite">
              {t('issues.resultCount', { count: pagination.total_issues ?? issuesData.length })}
            </span>
          )}
        </div>

        {/* Empty state */}
        {issuesData.length === 0 ? (
          showCelebration ? (
            <div className="empty-state-celebration">
              <div className="checkmark-icon">
                <FaCheckCircle />
              </div>
              <h4>All clear!</h4>
              <p>No open issues remaining. Great work keeping the system healthy.</p>
            </div>
          ) : (
            <div className="text-center py-5">
              <p className="text-muted">
                {debouncedSearch
                  ? `No issues matching "${debouncedSearch}"`
                  : t('issues.noIssues')}
              </p>
            </div>
          )
        ) : (
          <div className="table-responsive issues-table-wrap" ref={tableRef}>
            <Table hover className="align-middle mb-0" style={{ tableLayout: 'fixed', width: '100%' }}>
              <thead className="bg-light">
                <tr>
                  {/* Checkbox column */}
                  <th className="py-3 ps-3 border-bottom" style={{ width: '40px' }}>
                    <input
                      type="checkbox"
                      className="select-all-checkbox"
                      aria-label="Select all issues"
                      checked={issuesData.length > 0 && selectedIds.size === issuesData.length}
                      onChange={toggleSelectAll}
                    />
                  </th>
                  {visibleColumns.id && <th className="py-3 border-bottom" style={{ width: '56px' }}>ID</th>}
                  {visibleColumns.type && (
                    <th className="py-3 border-bottom" style={{ cursor: 'pointer', userSelect: 'none' }} onClick={() => handleSort('type')}>
                      Type{renderSortIcon('type')}
                    </th>
                  )}
                  {visibleColumns.component && (
                    <th className="py-3 border-bottom" style={{ width: '130px', cursor: 'pointer', userSelect: 'none' }} onClick={() => handleSort('component')}>
                      Component{renderSortIcon('component')}
                    </th>
                  )}
                  {visibleColumns.description && (
                    <th className="py-3 border-bottom" style={{ cursor: 'pointer', userSelect: 'none' }} onClick={() => handleSort('description')}>
                      Description{renderSortIcon('description')}
                    </th>
                  )}
                  {visibleColumns.age && (
                    <th className="py-3 border-bottom" style={{ width: '100px', cursor: 'pointer', userSelect: 'none' }} onClick={() => handleSort('age')}>
                      Age{renderSortIcon('age')}
                    </th>
                  )}
                  {visibleColumns.correlations && <th className="py-3 border-bottom">Correlations</th>}
                  {visibleColumns.count && (
                    <th className="py-3 border-bottom text-center" style={{ width: '100px', cursor: 'pointer', userSelect: 'none' }} onClick={() => handleSort('count')}>
                      Occurrences{renderSortIcon('count')}
                    </th>
                  )}
                  {visibleColumns.severity && (
                    <th className="py-3 border-bottom" style={{ width: '100px', cursor: 'pointer', userSelect: 'none' }} onClick={() => handleSort('severity')}>
                      Severity{renderSortIcon('severity')}
                    </th>
                  )}
                  {visibleColumns.status && (
                    <th className="py-3 border-bottom text-center" style={{ width: '104px', cursor: 'pointer', userSelect: 'none' }} onClick={() => handleSort('status')}>
                      Status{renderSortIcon('status')}
                    </th>
                  )}
                  <th className="py-3 pe-3 border-bottom text-end" style={{ width: '60px' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {issuesData.map((issue, index) => {
                  const heatLevel = getCountHeatLevel(issue.occurrence_count);
                  return (
                    <tr
                      key={issue.id}
                      className={`issue-row ${getSeverityRowClass(issue.severity)} ${panelIssueId === issue.id ? 'issue-row-open' : ''} ${focusedIndex === index ? 'issue-row-focused' : ''}`}
                      // The severity stripe is an inset shadow on the first cell: a
                      // border on the <tr> widened rows past the header and shifted
                      // every column out of line.
                      style={{ '--severity-color': getSeverityColor(issue.severity) }}
                      tabIndex={0}
                      aria-label={t('issues.openIssue', { id: issue.id, description: issue.description })}
                      onClick={(e) => { if (!e.target.closest('input, button, a, .dropdown')) setPanelIssueId(issue.id); }}
                      onKeyDown={(e) => { if (e.key === 'Enter' && e.target === e.currentTarget) setPanelIssueId(issue.id); }}
                      onFocus={() => setFocusedIndex(index)}
                    >
                      {/* Checkbox */}
                      <td className="ps-3 py-3">
                        <input
                          type="checkbox"
                          className="row-checkbox"
                          aria-label={`Select issue ${issue.id}`}
                          checked={selectedIds.has(issue.id)}
                          onChange={() => toggleSelection(issue.id)}
                        />
                      </td>
                      {visibleColumns.id && <td className="py-3 text-muted small issue-cell-meta">#{issue.id}</td>}
                      {visibleColumns.type && (
                        <td className="py-3 issue-cell-meta">
                          <code className="bg-light px-2 py-1 rounded small">{issue.issue_type || 'OTHER'}</code>
                        </td>
                      )}
                      {visibleColumns.component && (
                        <td className="py-3 issue-cell-meta issue-cell-first-meta" style={{ maxWidth: '130px' }}>
                          <span
                            className={`issue-component-chip ${getComponentChipClass(issue.scope)}`}
                            title={issue.component || 'INFRASTRUCTURE'}
                          >
                            {abbreviateComponent(issue.component)}
                          </span>
                        </td>
                      )}
                      {visibleColumns.description && (
                        <td className="py-3 issue-cell-description">
                          <div className="d-flex align-items-start">
                            <FaExclamationCircle
                              className="me-2 mt-1 flex-shrink-0"
                              style={{ color: getSeverityColor(issue.severity), fontSize: "1rem" }}
                            />
                            <span className="issue-description-cell">
                              <span className="text-dark issue-description-clamp" title={issue.description}>
                                {issue.description}
                              </span>
                              {issue.root_cause && (
                                <span className="issue-root-cause-line" title={issue.root_cause}>{issue.root_cause}</span>
                              )}
                            </span>
                          </div>
                        </td>
                      )}
                      {visibleColumns.age && (
                        <td className="py-3 issue-cell-meta">
                          <OverlayTrigger overlay={<Tooltip>{issue.created_at ? new Date(issue.created_at).toLocaleString() : 'Unknown'}</Tooltip>}>
                            <span className="text-muted small">{formatAge(issue.created_at)}</span>
                          </OverlayTrigger>
                        </td>
                      )}
                      {visibleColumns.correlations && (
                        <td className="py-3 issue-cell-meta">{renderCorrelationBadges(issue)}</td>
                      )}
                      {visibleColumns.count && (
                        <td className="text-center issue-cell-meta">
                          <span className={`px-2 py-1 rounded count-heat-${heatLevel}`}>
                            {issue.occurrence_count}&times;
                          </span>
                        </td>
                      )}
                      {visibleColumns.severity && (
                        <td className="issue-cell-meta">
                          <span className={`severity-badge severity-badge-${(issue.severity || 'unknown').toLowerCase()}`}>
                            {(issue.severity || 'N/A').toUpperCase()}
                          </span>
                        </td>
                      )}
                      {visibleColumns.status && <td className="text-center issue-cell-meta">{getStatusBadge(issue.status)}</td>}
                      {/* Actions — ... menu */}
                      <td className="text-end pe-3">
                        <Dropdown className="issue-actions-dropdown" align="end">
                          <Dropdown.Toggle
                            variant="link" size="sm" className="text-muted p-1"
                            aria-label={`Actions for issue ${issue.id}`}
                          >
                            <FaEllipsisV size={14} aria-hidden="true" />
                          </Dropdown.Toggle>
                          <Dropdown.Menu>
                            <Dropdown.Item onClick={() => setPanelIssueId(issue.id)}>
                              <FaEye className="me-2" size={12} />{t('issues.menu.viewDetails')}
                            </Dropdown.Item>
                            {issue.batch_id_str && (
                              <Dropdown.Item as={Link} to={`/dash/data/details/${issue.batch_id_str}`}>
                                <FaChartLine className="me-2" size={12} />{t('issues.panel.openAnalysis')}
                              </Dropdown.Item>
                            )}
                            <Dropdown.Item onClick={() => handleSolutionClick(issue)}>
                              <FaCog className="me-2" size={12} />{t('issues.panel.askAI')}
                            </Dropdown.Item>
                            <Dropdown.Item onClick={() => handleCopyId(issue.id)}>
                              <FaLink className="me-2" size={12} />{t('issues.panel.copyLink')}
                            </Dropdown.Item>
                            {issue.status === 'OPEN' && (
                              <>
                                <Dropdown.Item onClick={() => handleResolve(issue)}>
                                  <FaCheck className="me-2 text-success" size={12} />Resolve
                                </Dropdown.Item>
                                <Dropdown.Item onClick={() => handleMuteClick(issue.id)}>
                                  <FaVolumeMute className="me-2 text-secondary" size={12} />Mute
                                </Dropdown.Item>
                              </>
                            )}
                            {(issue.status === 'MUTED' || issue.status === 'RESOLVED') && (
                              <Dropdown.Item onClick={() => handleReopen(issue.id)}>
                                <FaRedo className="me-2 text-warning" size={12} />Reopen
                              </Dropdown.Item>
                            )}
                          </Dropdown.Menu>
                        </Dropdown>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          </div>
        )}

        {/* Bulk action toolbar */}
        {selectedIds.size > 0 && (
          <div className="bulk-toolbar">
            <span className="bulk-count">{selectedIds.size} selected</span>
            {canResolveSelection && (
              <>
                <Button size="sm" variant="success" onClick={handleBulkResolve}>
                  <FaCheck className="me-1" size={12} />Resolve {selectedIds.size}
                </Button>
                <Button size="sm" variant="secondary" onClick={handleBulkMuteClick}>
                  <FaVolumeMute className="me-1" size={12} />Mute {selectedIds.size}
                </Button>
              </>
            )}
            {canReopenSelection && (
              <Button size="sm" variant="outline-warning" onClick={handleBulkReopen}>
                <FaRedo className="me-1" size={12} />Reopen {selectedIds.size}
              </Button>
            )}
            <Button size="sm" variant="outline-secondary" onClick={() => setSelectedIds(new Set())}>
              Clear
            </Button>
          </div>
        )}

        {pagination && pagination.total_pages > 1 && (
          <div className="pagination-footer">
            <div className="pagination-info">
              Showing <strong>
                {(pagination.page - 1) * (pagination.page_size || 10) + 1}-
                {Math.min(pagination.page * (pagination.page_size || 10), pagination.total_issues)}
              </strong> of <strong>{pagination.total_issues}</strong>
            </div>

            <div className="modern-pagination">
              <button
                className="page-btn"
                onClick={() => setCurrentPage(currentPage - 1)}
                disabled={pagination.previous_page === null}
              >
                &lt;
              </button>

              {(() => {
                const pages = [];
                const totalPages = pagination.total_pages;

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
                    onClick={() => typeof page === "number" && setCurrentPage(page)}
                    disabled={page === "..."}
                  >
                    {page}
                  </button>
                ));
              })()}

              <button
                className="page-btn"
                onClick={() => setCurrentPage(currentPage + 1)}
                disabled={pagination.next_page === null}
              >
                &gt;
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Mute Modal */}
      <Modal show={showMuteModal} onHide={() => setShowMuteModal(false)} centered>
        <Modal.Header closeButton>
          <Modal.Title>{isBulkMute ? `Mute ${selectedIds.size} Issue(s)` : 'Mute Issue'}</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <p>How long would you like to mute {isBulkMute ? 'these issues' : 'this issue'}?</p>
          <Form.Select value={muteDays} onChange={(e) => setMuteDays(parseInt(e.target.value))}>
            <option value={1}>1 day</option>
            <option value={7}>7 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
            <option value={0}>Forever</option>
          </Form.Select>
          <p className="text-muted mt-3 small">
            Muted issues will still be tracked but won't create duplicate alerts.
          </p>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="outline-secondary" onClick={() => setShowMuteModal(false)}>Cancel</Button>
          <Button variant="secondary" onClick={handleMuteConfirm}>
            {isBulkMute ? `Mute ${selectedIds.size} Issue(s)` : 'Mute Issue'}
          </Button>
        </Modal.Footer>
      </Modal>

      {/* Keyboard shortcut help overlay */}
      {showShortcutHelp && (
        <div className="shortcut-help-overlay" onClick={() => setShowShortcutHelp(false)}>
          <div className="shortcut-help-card" onClick={(e) => e.stopPropagation()}>
            <h5>Keyboard Shortcuts</h5>
            <div className="shortcut-row">
              <span>Move down</span>
              <span className="shortcut-key">j</span>
            </div>
            <div className="shortcut-row">
              <span>Move up</span>
              <span className="shortcut-key">k</span>
            </div>
            <div className="shortcut-row">
              <span>View details</span>
              <span className="shortcut-key">v</span>
            </div>
            <div className="shortcut-row">
              <span>Resolve</span>
              <span className="shortcut-key">r</span>
            </div>
            <div className="shortcut-row">
              <span>Mute</span>
              <span className="shortcut-key">m</span>
            </div>
            <div className="shortcut-row">
              <span>Toggle select</span>
              <span className="shortcut-key">x</span>
            </div>
            <div className="shortcut-row">
              <span>Show/hide help</span>
              <span className="shortcut-key">?</span>
            </div>
            <div className="mt-3 text-center">
              <Button size="sm" variant="outline-secondary" onClick={() => setShowShortcutHelp(false)}>Close</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Issues;
