import React, { useState, useEffect } from "react";
import { Table, Pagination, Form, Button, Dropdown } from "react-bootstrap";
import { FaExclamationCircle, FaClock, FaBrain, FaBug, FaChartLine, FaCode, FaArrowRight, FaBell, FaLink, FaFileAlt } from "react-icons/fa";
import { toast } from "react-toastify";
import { useParams, useNavigate, useLocation, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import DataService from "../services/data.service";
import useCapabilities from "../hooks/useCapabilities";
import { PostOnboardingUpsells } from "./onboarding";
import { isDemoUser } from "../utils/demo";
import notificationService from "../services/notification.service";
import PostmortemModal from "./PostmortemModal";
import "./Detail.css";

// Investigate prefilled with this batch's scope and window.
const rerunLink = (batch) => {
  const q = new URLSearchParams();
  if (batch.project) q.set("project_id", batch.project);
  if (batch.deployment) q.set("deployment_id", batch.deployment);
  const env = batch.data?.environment || batch.data?.statistics?.environment;
  if (env) q.set("environment", env);
  const range = batch.data?.statistics?.time_range || {};
  if (range.start) q.set("start", range.start);
  if (range.end) q.set("end", range.end);
  return `/dash/investigate?${q.toString()}`;
};

// Small helpers used by the RCA hero
const relTime = (isoLike) => {
  if (!isoLike) return null;
  const then = new Date(isoLike);
  if (Number.isNaN(then.getTime())) return null;
  const diff = Math.max(1, Math.floor((Date.now() - then.getTime()) / 1000));
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

// Sentinel decision → chip tone
const sentinelChip = (decision) => {
  switch ((decision || '').toLowerCase()) {
    case 'alert':   return { klass: 'ds-chip-err',  label: 'ALERT' };
    case 'shadow':  return { klass: 'ds-chip-info', label: 'SHADOW' };
    case 'quiet':   return { klass: 'ds-chip-ok',   label: 'QUIET' };
    default:        return { klass: 'ds-chip-neutral', label: (decision || 'PENDING').toUpperCase() };
  }
};

// Issue severity → chip tone
const severityChip = (severity) => {
  switch ((severity || '').toUpperCase()) {
    case 'CRITICAL': return 'ds-chip-err';
    case 'WARNING':  return 'ds-chip-warn';
    case 'INFO':     return 'ds-chip-info';
    default:         return 'ds-chip-neutral';
  }
};

const Detail = () => {
  const { t } = useTranslation();
  const { batchId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { has } = useCapabilities();

  const [data, setData] = useState([]);
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedLogType, setSelectedLogType] = useState("All");
  const [searchTerm, setSearchTerm] = useState("");
  const [availableServices, setAvailableServices] = useState([]);
  const pageSize = 9;

  const [selectedService, setSelectedService] = useState("All");
  const [selectedData, setSelectedData] = useState("Logs");
  // PR-D: also carry the batch header (analysis / issues / metadata)
  // so this page renders the RCA hero, not just a log dump.
  const [batchMeta, setBatchMeta] = useState(null);
  const [acking, setAcking] = useState(false);
  const [showPostmortem, setShowPostmortem] = useState(false);

  // RCA audit finding #11 (2026-09-20): render the Compare panel when
  // the URL says ?compare=true, or when the batch has more than one
  // analysis on file (auto-surface it so users discover the feature).
  const [analysisHistory, setAnalysisHistory] = useState(null);
  const [historyExpanded, setHistoryExpanded] = useState(false);
  const [promoteInFlight, setPromoteInFlight] = useState(null); // analyzed_at of the entry being promoted
  const compareRequested = new URLSearchParams(location.search).get('compare') === 'true';

  useEffect(() => {
    let cancelled = false;
    if (!batchId) return () => {};
    DataService.getAnalysisHistory(batchId)
      .then((h) => { if (!cancelled) setAnalysisHistory(h); })
      .catch(() => { /* non-fatal */ });
    return () => { cancelled = true; };
  }, [batchId]);

  const historyEntries = Array.isArray(analysisHistory?.analysis_history)
    ? analysisHistory.analysis_history
    : [];
  const hasMultipleAnalyses = historyEntries.length > 1;
  const showComparePanel = compareRequested || hasMultipleAnalyses;

  useEffect(() => {
    // Expand automatically the first time the panel is worth showing.
    if (compareRequested && !historyExpanded) setHistoryExpanded(true);
  }, [compareRequested, historyExpanded]);

  const handlePromote = async (analyzedAt) => {
    if (!analyzedAt || promoteInFlight) return;
    setPromoteInFlight(analyzedAt);
    try {
      await DataService.promoteAnalysisEntry(batchId, analyzedAt);
      // Refresh both the hero and the compare list from source.
      const [freshMeta, freshHist] = await Promise.all([
        DataService.getBatchDetails(batchId),
        DataService.getAnalysisHistory(batchId),
      ]);
      setBatchMeta(freshMeta || null);
      setAnalysisHistory(freshHist || null);
    } catch (e) {
      console.error('Promote failed:', e);
    } finally {
      setPromoteInFlight(null);
    }
  };

  useEffect(() => {
    const fetchBatch = async () => {
      try {
        if (!batchId) return;

        // Fetch the two pieces in parallel: the log adapter output
        // (already merges cicd + logs, sorts by timestamp) and the
        // raw batch envelope (analysis_text, issues, model, etc).
        const [logsResponse, meta] = await Promise.all([
          DataService.getBatchLogs(batchId),
          DataService.getBatchDetails(batchId),
        ]);
        setBatchMeta(meta || null);

        if (logsResponse?.results) {
          const formattedData = logsResponse.results.map((log) => ({
            id: log._id,
            timestamp: new Date(log._source?.["@timestamp"]).toLocaleString(),
            logDetails: log._source?.message || "No message available",
            type: log._source?.level?.toLowerCase() || "other",
            index: log._index || "unknown",
            serviceName: log._source?.service_name || null,
            projectName: log._source?.project_name || null,
          }));
          setData(formattedData);
          extractAvailableServices(formattedData);
        }
      } catch (error) {
        console.error("Failed to fetch batch:", error);
        setData([]);
      }
    };

    fetchBatch();
  }, [batchId]);

  const extractAvailableServices = (logsData) => {
    const services = new Set();

    logsData.forEach((log) => {
      if (log.serviceName) {
        services.add(log.serviceName);
      }
      if (log.index.startsWith("system-") && !log.serviceName) {
        services.add("system");
      }
    });

    const servicesList = Array.from(services).sort();
    setAvailableServices(servicesList);
  };

  const errorKeywords = new Set([
    "ERROR", "FAIL", "FAILED LOGIN", "FAILURE", "TIMEOUT",
    "EXCEEDED", "UNAUTHORIZED", "PERMISSION DENIED", "ACCESS DENIED", "CONNECTION REFUSED",
  ]);

  const warningKeywords = new Set([
    "WARNING", "DENIED", "REFUSED", "VIOLATION",
  ]);

  const getLogCategory = (logDetails, type) => {
    const lowerDetails = logDetails.toLowerCase();

    for (const keyword of errorKeywords) {
      if (lowerDetails.includes(keyword.toLowerCase())) {
        return "error";
      }
    }
    for (const keyword of warningKeywords) {
      if (lowerDetails.includes(keyword.toLowerCase())) {
        return "warning";
      }
    }
    return "other";
  };

  const highlightSearchTerm = (text) => {
    if (!searchTerm) return text;
    const parts = text.split(new RegExp(`(${searchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, "gi"));
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

  const filteredData = data.filter((item) => {
    if (selectedService !== "All") {
      if (selectedService === "system" && item.index.startsWith("ci_cd-logs-project-")) {
        return false;
      }
      if (selectedService !== "system" && item.serviceName !== selectedService) {
        return false;
      }
    }

    if (selectedData === "CI/CD Logs" && !item.index.startsWith("ci_cd-logs-project-")) {
      return false;
    }
    if (selectedData === "Logs" && item.index.startsWith("ci_cd-logs-project-")) {
      return false;
    }

    const matchesLogType =
      selectedLogType === "All" ||
      (selectedLogType === "Error" && getLogCategory(item.logDetails, item.type) === "error") ||
      (selectedLogType === "Warning" && getLogCategory(item.logDetails, item.type) === "warning");

    const matchesSearch =
      !searchTerm || item.logDetails.toLowerCase().includes(searchTerm.toLowerCase());

    return matchesLogType && matchesSearch;
  });

  const paginatedData = filteredData.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize
  );

  const getLogIcon = (logDetails, type) => {
    const category = getLogCategory(logDetails, type);
    if (category === "error")
      return <FaExclamationCircle className="text-danger" />;
    if (category === "warning")
      return <FaExclamationCircle className="text-warning" />;
  };

  const handleServiceChange = (service) => setSelectedService(service);
  const handleDataChange = (data) => {
    setSelectedData(data);
    if (data === "Metrics") navigate(`/dash/metrics/${batchId}`);
    else if (data === "Issues") navigate(`/dash/issues/${batchId}`);
    else if (data === "Code Changes") navigate(`/dash/code-changes/${batchId}`);
    else if (data === "Traces") navigate(`/dash/traces/batch/${batchId}`);
    else if (data === "Timeline") navigate(`/dash/timeline/${batchId}`);
  };
  const handleLogTypeChange = (type) => setSelectedLogType(type);
  const handleSearchChange = (e) => setSearchTerm(e.target.value);

  const getTotalPages = () => Math.ceil(filteredData.length / pageSize);

  const renderPaginationItems = () => {
    const totalPages = getTotalPages();
    const items = [];
    const maxVisiblePages = 5;

    items.push(
      <Pagination.Item
        key={1}
        active={currentPage === 1}
        onClick={() => setCurrentPage(1)}
        style={{ fontSize: "14px" }}
      >
        1
      </Pagination.Item>
    );

    if (totalPages <= maxVisiblePages) {
      for (let i = 2; i <= totalPages; i++) {
        items.push(
          <Pagination.Item
            key={i}
            active={currentPage === i}
            onClick={() => setCurrentPage(i)}
            style={{ fontSize: "14px" }}
          >
            {i}
          </Pagination.Item>
        );
      }
    } else {
      if (currentPage > 3) items.push(<Pagination.Ellipsis key="ellipsis1" />);

      for (
        let i = Math.max(2, currentPage - 1);
        i <= Math.min(currentPage + 1, totalPages - 1);
        i++
      ) {
        items.push(
          <Pagination.Item
            key={i}
            active={currentPage === i}
            onClick={() => setCurrentPage(i)}
            style={{ fontSize: "14px" }}
          >
            {i}
          </Pagination.Item>
        );
      }

      if (currentPage < totalPages - 2)
        items.push(<Pagination.Ellipsis key="ellipsis2" />);

      if (totalPages > 1) {
        items.push(
          <Pagination.Item
            key={totalPages}
            active={currentPage === totalPages}
            onClick={() => setCurrentPage(totalPages)}
            style={{ fontSize: "14px" }}
          >
            {totalPages}
          </Pagination.Item>
        );
      }
    }

    return items;
  };

  const sentinel = sentinelChip(batchMeta?.sentinel_decision);
  const issues = Array.isArray(batchMeta?.issues) ? batchMeta.issues : [];
  // Incident actions: acknowledge stops escalation for every open issue
  // this batch found; the link and post-mortem make it shareable.
  const unacknowledged = issues.filter((i) => i.id && (i.status || 'OPEN') === 'OPEN' && !i.acknowledged_at);
  const handleAcknowledgeAll = async () => {
    setAcking(true);
    try {
      await Promise.all(unacknowledged.map((i) => notificationService.acknowledgeIssue(i.id)));
      setBatchMeta((m) => m && {
        ...m,
        issues: m.issues.map((i) => (unacknowledged.some((u) => u.id === i.id) ? { ...i, acknowledged_at: new Date().toISOString() } : i)),
      });
      toast.success(t('detail.incident.acknowledged', { count: unacknowledged.length }));
    } catch {
      toast.error(t('issues.panel.acknowledgeFailed'));
    } finally {
      setAcking(false);
    }
  };
  const handleCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      toast.success(t('detail.incident.linkCopied'));
    } catch {
      toast.error(t('detail.incident.copyFailed'));
    }
  };
  const previewIssues = issues.slice(0, 3);
  // Prefer the first issue's ``root_cause`` — that's a proper
  // human-readable narrative. Fall back to ``analysis_text`` only when
  // it looks like plain prose (not a stringified Python dict left over
  // from the pre-2026-09-20 bug). Cap length so the hero card doesn't
  // eat the viewport.
  const _rawAnalysisText = batchMeta?.analysis_text || null;
  const _looksLikeDictRepr = typeof _rawAnalysisText === 'string'
    && /^\s*\{['"]/.test(_rawAnalysisText.trim());
  const _issuePrimary = Array.isArray(batchMeta?.issues) && batchMeta.issues[0]
    ? batchMeta.issues[0]
    : null;
  const _hypothesisFromIssue = _issuePrimary?.root_cause
    || _issuePrimary?.description
    || null;
  const _analysisSummary = typeof batchMeta?.analysis?.summary === 'string'
    ? batchMeta.analysis.summary
    : null;
  const _cap = (s, n) => (typeof s === 'string' && s.length > n
    ? `${s.slice(0, n).trimEnd()}…`
    : s);
  const analysisText = _cap(
    _hypothesisFromIssue
      || _analysisSummary
      || (_looksLikeDictRepr ? null : _rawAnalysisText),
    600,
  );

  return (
    <div className="p-3 detail-page" style={{ maxWidth: '100%', overflowX: 'hidden' }}>
      {/* PR-D3 (2026-09-20): breadcrumb replaces the bottom-of-page
          "Back to Data" button. Standard nav pattern; keeps the
          bottom of the page for real content. */}
      <nav aria-label="breadcrumb" className="mb-2" style={{ fontSize: 12 }}>
        <ol className="breadcrumb mb-0" style={{ background: 'transparent', padding: 0 }}>
          <li className="breadcrumb-item">
            <Link to="/dash/data" style={{ textDecoration: 'none' }}>
              {t('nav.data', 'Data')}
            </Link>
          </li>
          <li
            className="breadcrumb-item active ds-mono"
            aria-current="page"
            style={{ color: 'var(--text-tertiary)' }}
          >
            {batchId}
          </li>
        </ol>
      </nav>

      {/* Contextual "connect SCM / CI-CD" nudges — surfaced here
          rather than in the wizard because the aha-moment (after
          seeing a first insight) is when users are most receptive
          to expanding the integration surface. */}
      <PostOnboardingUpsells />

      {/* ============ PR-D · RCA hero ============
          Renders the AI hypothesis + confidence + metadata + a
          short issues panel above the logs table. Data comes from
          the same /api/data/batches/<id>/ endpoint that already
          feeds the logs — one extra parallel call, no new backend
          work. Gracefully hidden when batchMeta hasn't loaded or
          when the batch genuinely has no analysis (Sentinel QUIET
          decision, etc). */}
      {batchMeta && (
        <div className="ds-card ds-card-elevated" style={{ marginBottom: '1rem' }}>
          <div className="ds-card-body detail-hero" style={{ display: 'flex', gap: '1.25rem', alignItems: 'flex-start' }}>
            <div className="detail-hero-icon" style={{
              width: 44, height: 44, borderRadius: 8,
              background: 'hsl(230, 100%, 96%)',
              color: 'var(--primary-600)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0, fontSize: 20,
            }}>
              <FaBrain />
            </div>
            <div style={{ flexGrow: 1, minWidth: 0 }}>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
                fontSize: 11, textTransform: 'uppercase',
                letterSpacing: '0.12em', color: 'var(--text-tertiary)',
                marginBottom: 6,
              }}>
                <span>AI hypothesis</span>
                {batchMeta.trigger === 'manual' || batchMeta.trigger === 'alert' ? (
                  <span className={`ds-chip ${batchMeta.trigger === 'alert' ? 'ds-chip-err' : 'ds-chip-brand'}`}>
                    {t(`investigate.trigger.${batchMeta.trigger}`)}
                  </span>
                ) : (
                  <span className={`ds-chip ${sentinel.klass}`}>{sentinel.label}</span>
                )}
                {batchMeta.model_name && <span className="ds-mono" style={{ textTransform: 'none', letterSpacing: 0, color: 'var(--text-secondary)' }}>{batchMeta.model_name}</span>}
                {batchMeta.analyzed_at && <span style={{ textTransform: 'none', letterSpacing: 0, marginLeft: 'auto' }}>{relTime(batchMeta.analyzed_at)}</span>}
              </div>
              {/* The incident is titled by the AI's hypothesis. */}
              <h1 className="detail-hypothesis" style={{
                fontSize: 18, fontWeight: 500, lineHeight: 1.5,
                color: 'var(--text-primary)', marginBottom: 12,
              }}>
                {analysisText || (
                  <span style={{ color: 'var(--text-tertiary)', fontStyle: 'italic', fontSize: 16 }}>
                    Sentinel skipped AI analysis for this batch — signal was quiet.
                  </span>
                )}
              </h1>
              <div style={{
                display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center',
                fontSize: 12, color: 'var(--text-tertiary)',
              }}>
                {batchMeta.batch_id && (
                  <span className="ds-mono" style={{ color: 'var(--text-secondary)' }}>{batchMeta.batch_id}</span>
                )}
                {typeof batchMeta.logs_analyzed === 'number' && (
                  <span>{batchMeta.logs_analyzed} logs analysed</span>
                )}
                {typeof batchMeta.token_count === 'number' && batchMeta.token_count > 0 && (
                  <span>{batchMeta.token_count.toLocaleString()} tokens</span>
                )}
                {batchMeta.data?.environment && (
                  <span className="ds-chip ds-chip-neutral">{batchMeta.data.environment}</span>
                )}
                {(batchMeta.sentinel_triggers || []).slice(0, 3).map((tr) => (
                  <span key={tr} className="ds-chip ds-chip-warn">{tr}</span>
                ))}
              </div>
              <div className="detail-incident-actions">
                {unacknowledged.length > 0 && !isDemoUser() && (
                  <button type="button" className="ds-btn ds-btn-primary ds-btn-sm" onClick={handleAcknowledgeAll} disabled={acking}
                          title={t('detail.incident.acknowledgeTitle')}>
                    <FaBell size={11} aria-hidden="true" /> {t('detail.incident.acknowledge', { count: unacknowledged.length })}
                  </button>
                )}
                <button type="button" className="ds-btn ds-btn-secondary ds-btn-sm" onClick={handleCopyLink}>
                  <FaLink size={11} aria-hidden="true" /> {t('detail.incident.copyLink')}
                </button>
                {analysisText && !isDemoUser() && (
                  <button type="button" className="ds-btn ds-btn-secondary ds-btn-sm" onClick={() => setShowPostmortem(true)}>
                    <FaFileAlt size={11} aria-hidden="true" /> {t('detail.incident.postmortem')}
                  </button>
                )}
                {batchMeta.project && !isDemoUser() && (
                  <Link to={rerunLink(batchMeta)} className="ds-btn ds-btn-secondary ds-btn-sm" title={t('investigate.rerunTitle')}>
                    {t('investigate.rerun')}
                  </Link>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ============ Compare panel (RCA audit #11, 2026-09-20) ============
          Surfaces analysis_history entries as a horizontally-scrollable
          set of cards so an operator can see two or three models' RCAs
          side-by-side and promote the best one to primary. Auto-expands
          when the URL has ?compare=true or when there's more than one
          analysis on file; otherwise it renders as a one-line collapse
          the user opts into. */}
      {showComparePanel && historyEntries.length > 0 && (
        <div className="ds-card" style={{ marginBottom: '1rem' }}>
          <div
            className="ds-card-header"
            style={{ background: 'var(--bg-sunken)', cursor: 'pointer' }}
            onClick={() => setHistoryExpanded(!historyExpanded)}
          >
            <FaBrain style={{ color: 'var(--text-tertiary)' }} />
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <div style={{ fontSize: 14, fontWeight: 600 }}>
                {historyEntries.length} analysis result{historyEntries.length === 1 ? '' : 's'}
                {' '}on file
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
                Compare model outputs, promote the best to primary
              </div>
            </div>
            <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-tertiary)' }}>
              {historyExpanded ? 'Collapse ▲' : 'Expand ▼'}
            </span>
          </div>
          {historyExpanded && (
            <div style={{
              display: 'flex', gap: 12, padding: 12,
              overflowX: 'auto', flexWrap: 'nowrap',
            }}>
              {historyEntries.slice().reverse().map((entry, _idx) => {
                const isPrimary = !!entry.is_primary;
                const entryNarrative = (() => {
                  const r = entry.analysis_result;
                  if (!r || typeof r !== 'object') return null;
                  const first = Array.isArray(r.correlated_issues) && r.correlated_issues[0];
                  if (!first) return null;
                  const rc = first.root_cause;
                  return typeof rc === 'string' ? rc : (rc?.description || null);
                })();
                const issueCount = typeof entry.issue_count === 'number'
                  ? entry.issue_count
                  : (Array.isArray(entry.analysis_result?.correlated_issues)
                     ? entry.analysis_result.correlated_issues.length
                     : 0);
                const tokensTotal = (entry.tokens_input || 0) + (entry.tokens_output || 0);
                return (
                  <div
                    key={entry.analyzed_at || `history-${_idx}`}
                    style={{
                      flex: '0 0 320px', border: '1px solid var(--border-default)',
                      borderRadius: 8, padding: 12, background: 'var(--bg-elevated)',
                      display: 'flex', flexDirection: 'column', gap: 8,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span className={`ds-chip ${isPrimary ? 'ds-chip-ok' : 'ds-chip-neutral'}`}>
                        {isPrimary ? 'PRIMARY' : (entry.mode || 'compare').toUpperCase()}
                      </span>
                      <span className="ds-mono" style={{ fontSize: 12 }}>
                        {entry.model_name || 'unknown'}
                      </span>
                      <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-tertiary)' }}>
                        {relTime(entry.analyzed_at)}
                      </span>
                    </div>
                    <div style={{
                      fontSize: 13, lineHeight: 1.5, color: 'var(--text-primary)',
                      display: '-webkit-box', WebkitBoxOrient: 'vertical',
                      WebkitLineClamp: 6, overflow: 'hidden',
                    }}>
                      {entryNarrative || <em style={{ color: 'var(--text-tertiary)' }}>No narrative recorded.</em>}
                    </div>
                    <div style={{
                      display: 'flex', gap: 10, alignItems: 'center',
                      fontSize: 11, color: 'var(--text-tertiary)', marginTop: 'auto',
                    }}>
                      <span>{issueCount} issue{issueCount === 1 ? '' : 's'}</span>
                      {tokensTotal > 0 && <span>{tokensTotal.toLocaleString()} tokens</span>}
                    </div>
                    {!isPrimary && (
                      <button
                        type="button"
                        className="ds-btn ds-btn-secondary ds-btn-sm"
                        disabled={promoteInFlight === entry.analyzed_at}
                        onClick={() => handlePromote(entry.analyzed_at)}
                      >
                        {promoteInFlight === entry.analyzed_at
                          ? 'Promoting…'
                          : 'Promote to primary'}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ============ Detected issues preview ============ */}
      {issues.length > 0 && (
        <div className="ds-card" style={{ marginBottom: '1rem' }}>
          <div className="ds-card-header" style={{ background: 'var(--bg-sunken)' }}>
            <FaBug style={{ color: 'var(--text-tertiary)' }} />
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <div style={{ fontSize: 14, fontWeight: 600 }}>
                {issues.length} issue{issues.length === 1 ? '' : 's'} detected
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
                Ranked by severity and evidence strength
              </div>
            </div>
            <Link
              to={`/dash/issues/${batchId}`}
              className="ds-btn ds-btn-secondary ds-btn-sm"
              style={{ marginLeft: 'auto', textDecoration: 'none' }}
            >
              View all
              <FaArrowRight size={11} />
            </Link>
          </div>
          <div>
            {previewIssues.map((issue) => (
              <div
                key={issue.id}
                className="detail-issue-row"
                style={{
                  display: 'flex',
                  gap: '0.75rem',
                  alignItems: 'flex-start',
                  padding: '0.875rem 1.25rem',
                  borderTop: '1px solid var(--border-default)',
                }}
              >
                <span className={`ds-chip ${severityChip(issue.severity)}`} style={{ marginTop: 2 }}>
                  {issue.severity}
                </span>
                <div className="detail-issue-text" style={{ flexGrow: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--text-primary)' }}>
                    {issue.description || issue.error_target || 'Untitled issue'}
                  </div>
                  {issue.recommendation && (
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4, lineHeight: 1.5 }}>
                      → {issue.recommendation}
                    </div>
                  )}
                  {issue.component && (
                    <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 4 }}>
                      <span className="ds-mono">{issue.component}</span>
                      {issue.environment && <span> · {issue.environment}</span>}
                    </div>
                  )}
                </div>
                <Link
                  to={`/dash/issues/${batchId}`}
                  className="ds-btn ds-btn-ghost ds-btn-sm"
                  style={{ flexShrink: 0, textDecoration: 'none' }}
                >
                  Open
                </Link>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* PR-D3 #6 (2026-09-21): true tab strip. "Logs" is the current
          view (we're on Detail); the others are sibling pages with the
          same batch context. Active tab gets a 2 px primary underline
          overlapping the strip's bottom border. */}
      {batchMeta && (
        <div
          role="tablist"
          aria-label="Batch data source"
          className="detail-tabs"
          style={{
            display: 'flex', gap: 2, flexWrap: 'wrap',
            borderBottom: '1px solid var(--border-default)',
            marginBottom: '1rem',
          }}
        >
          {(() => {
            const tabStyle = (active) => ({
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '10px 16px', fontSize: 13, fontWeight: 500,
              textDecoration: 'none',
              color: active ? 'var(--primary-600)' : 'var(--text-secondary)',
              borderBottom: `2px solid ${active ? 'var(--primary-600)' : 'transparent'}`,
              marginBottom: -1,
              background: 'transparent',
            });
            const traceCount = batchMeta.data?.traces?.trace_count || 0;
            const codeCount = batchMeta.data?.code_changes?.length || 0;
            return (
              <>
                <span role="tab" aria-selected="true" style={tabStyle(true)}>
                  <FaBug size={12} aria-hidden="true" /> Logs
                </span>
                <Link role="tab" to={`/dash/metrics/${batchId}`} style={tabStyle(false)}>
                  <FaChartLine size={12} aria-hidden="true" /> Metrics
                </Link>
                <Link role="tab" to={`/dash/traces/batch/${batchId}`} style={tabStyle(false)}>
                  Traces
                  {traceCount > 0 && (
                    <span className="ds-chip ds-chip-neutral" style={{ marginLeft: 4 }}>
                      {traceCount}
                    </span>
                  )}
                </Link>
                <Link role="tab" to={`/dash/code-changes/${batchId}`} style={tabStyle(false)}>
                  <FaCode size={12} aria-hidden="true" /> Code changes
                  {codeCount > 0 && (
                    <span className="ds-chip ds-chip-neutral" style={{ marginLeft: 4 }}>
                      {codeCount}
                    </span>
                  )}
                </Link>
                <Link role="tab" to={`/dash/timeline/${batchId}`} style={tabStyle(false)}>
                  <FaClock size={12} aria-hidden="true" /> Timeline
                </Link>
              </>
            );
          })()}
        </div>
      )}

      {/* PR-D3 (2026-09-20 follow-up): use ``.ds-card`` here so the
          log-wrapper's outer edges line up with the hero + issues
          cards above. The prior ``p-3 rounded-3`` div rendered 16 px
          inset both sides — a visual mismatch that read as
          "different section, different app" during the UI review. */}
      <div
        className="ds-card ds-card-elevated"
        style={{ color: 'var(--text-primary)', padding: 'var(--space-5)' }}
      >
        <div className="d-flex flex-wrap justify-content-between align-items-center mb-2 gap-1">
          <div
            className="d-flex flex-wrap align-items-center gap-1"
            style={{ flex: 1, minWidth: 0 }}
          >
            <Form.Group
              className="position-relative me-1"
              style={{ minWidth: 0, flex: 1, flexBasis: 200 }}
            >
              <Form.Control
                type="text"
                placeholder={t('detail.searchLogs')}
                className="rounded-3"
                style={{
                  paddingLeft: "10px",
                  fontSize: "14px",
                  height: "36px",
                  boxShadow: "0 1px 2px rgba(0,0,0,0.1)",
                  cursor: "default",
                }}
                value={searchTerm}
                onChange={handleSearchChange}
              />
            </Form.Group>

            <div className="d-flex flex-wrap gap-1 ms-2" style={{ flex: 2 }}>
              <Dropdown>
                <Dropdown.Toggle
                  variant="outline-secondary"
                  className="rounded-3 d-flex align-items-center"
                  style={{
                    fontSize: "14px",
                    height: "36px",
                    minWidth: "100px",
                    padding: "0.5rem 0.4rem",
                  }}
                >
                  <span className="text-nowrap">
                    {t('detail.service')}: {selectedService === "All" ? t('common.all') : selectedService}
                  </span>
                </Dropdown.Toggle>
                <Dropdown.Menu>
                  <Dropdown.Item
                    onClick={() => handleServiceChange("All")}
                    style={{ fontSize: "14px" }}
                  >
                    {t('detail.allServices')}
                  </Dropdown.Item>
                  {availableServices.map((service) => (
                    <Dropdown.Item
                      key={service}
                      onClick={() => handleServiceChange(service)}
                      style={{ fontSize: "14px" }}
                    >
                      {service}
                    </Dropdown.Item>
                  ))}
                </Dropdown.Menu>
              </Dropdown>

              {/* PR-D3 (2026-09-20): the Data-type dropdown used to
                  offer 5 options where 4 just navigated away (Metrics,
                  Code Changes, Traces, Timeline all have their own tab
                  in the action bar above). Reduced to the actual
                  in-page choice: raw logs vs CI/CD logs. Kept only if
                  the org has CI/CD capability — otherwise there's
                  nothing to toggle. */}
              {has('cicd') && (
                <Dropdown>
                  <Dropdown.Toggle
                    variant="outline-secondary"
                    className="rounded-3 d-flex align-items-center"
                    style={{
                      fontSize: "14px",
                      height: "36px",
                      minWidth: "100px",
                      padding: "0.25rem 0.5rem",
                    }}
                  >
                    <span className="text-nowrap">
                      {t('detail.logSource', 'Source')}: {selectedData === "CI/CD Logs" ? t('detail.cicdLogs') : t('detail.logs')}
                    </span>
                  </Dropdown.Toggle>
                  <Dropdown.Menu>
                    <Dropdown.Item
                      onClick={() => handleDataChange("Logs")}
                      style={{ fontSize: "14px" }}
                    >
                      {t('detail.logs')}
                    </Dropdown.Item>
                    <Dropdown.Item
                      onClick={() => handleDataChange("CI/CD Logs")}
                      style={{ fontSize: "14px" }}
                    >
                      {t('detail.cicdLogs')}
                    </Dropdown.Item>
                  </Dropdown.Menu>
                </Dropdown>
              )}

              <Dropdown>
                <Dropdown.Toggle
                  variant="outline-secondary"
                  className="rounded-3 d-flex align-items-center"
                  style={{
                    fontSize: "14px",
                    height: "36px",
                    minWidth: "90px",
                    padding: "0.25rem 0.5rem",
                  }}
                >
                  <span className="text-nowrap">
                    {t('detail.level', 'Level')}: {selectedLogType === "All" ? t('common.all') : t(`issues.${selectedLogType.toLowerCase()}`)}
                  </span>
                </Dropdown.Toggle>
                <Dropdown.Menu>
                  <Dropdown.Item
                    onClick={() => handleLogTypeChange("All")}
                    style={{ fontSize: "14px" }}
                  >
                    {t('common.all')}
                  </Dropdown.Item>
                  <Dropdown.Item
                    onClick={() => handleLogTypeChange("Error")}
                    style={{ fontSize: "14px", color: "#dc3545" }}
                  >
                    {t('issues.error')}
                  </Dropdown.Item>
                  <Dropdown.Item
                    onClick={() => handleLogTypeChange("Warning")}
                    style={{ fontSize: "14px", color: "#ffc107" }}
                  >
                    {t('issues.warning')}
                  </Dropdown.Item>
                </Dropdown.Menu>
              </Dropdown>
            </div>
          </div>
        </div>

        {/* PR-D3 (2026-09-20): full column layout — was single blob
            per row (only ``logDetails`` message + icon). Real prod
            logs need at least timestamp, level, service, message to
            triage. */}
        <Table
          bordered
          hover
          responsive
          className="rounded-4 overflow-hidden mt-2 table-stack detail-logs-table"
        >
          <thead className="table-primary">
            <tr>
              <th style={{ fontSize: "13px", width: "180px" }}>
                {t('detail.colTimestamp', 'Timestamp')}
              </th>
              <th style={{ fontSize: "13px", width: "72px" }}>
                {t('detail.colLevel', 'Level')}
              </th>
              <th style={{ fontSize: "13px", width: "140px" }}>
                {t('detail.colService', 'Service')}
              </th>
              <th style={{ fontSize: "13px" }}>
                {t('detail.colMessage', 'Message')}
              </th>
            </tr>
          </thead>
          <tbody>
            {paginatedData.map((item) => (
              <tr key={item.id}>
                <td data-label={t('detail.colTimestamp', 'Timestamp')} style={{ padding: "0.5rem", fontSize: "13px", whiteSpace: "nowrap", color: "var(--text-secondary)" }}>
                  {item.timestamp}
                </td>
                <td data-label={t('detail.colLevel', 'Level')} style={{ padding: "0.5rem", fontSize: "13px" }}>
                  <span className={`ds-chip ${
                    (item.type || '').toLowerCase() === 'error' ? 'ds-chip-err'
                      : (item.type || '').toLowerCase() === 'warning' ? 'ds-chip-warn'
                      : 'ds-chip-neutral'
                  }`}>
                    {(item.type || 'info').toUpperCase()}
                  </span>
                </td>
                <td data-label={t('detail.colService', 'Service')} style={{ padding: "0.5rem", fontSize: "13px", color: "var(--text-secondary)" }}>
                  {item.serviceName || '—'}
                </td>
                <td
                  style={{ padding: "0.5rem", fontSize: "13px", textAlign: "left" }}
                  className="align-middle"
                >
                  {/* Icon retired 2026-09-21: LEVEL column now owns
                      severity signal via chips. Message stays pure text. */}
                  <span>{highlightSearchTerm(item.logDetails)}</span>
                </td>
              </tr>
            ))}
            {paginatedData.length === 0 && (
              <tr>
                <td colSpan="4" className="text-center text-muted py-4" style={{ fontSize: "14px" }}>
                  {data.length === 0 ? t('detail.noLogs') : t('detail.noLogsMatch')}
                </td>
              </tr>
            )}
          </tbody>
        </Table>

        {/* PR-D3: pagination hidden when a single page fits. Prior
            code rendered "1" for a batch with only 2 log lines. */}
        {getTotalPages() > 1 && (
          <div className="d-flex justify-content-end align-items-center mt-2">
            <Pagination className="mb-0">
              <Pagination.Prev
                onClick={() => setCurrentPage(currentPage - 1)}
                disabled={currentPage === 1}
                style={{ fontSize: "14px" }}
              />
              {renderPaginationItems()}
              <Pagination.Next
                onClick={() => setCurrentPage(currentPage + 1)}
                disabled={currentPage === getTotalPages()}
                style={{ fontSize: "14px" }}
              />
            </Pagination>
          </div>
        )}
      </div>
      <PostmortemModal show={showPostmortem} onHide={() => setShowPostmortem(false)} batchId={batchId} />
    </div>
  );
};

export default Detail;
