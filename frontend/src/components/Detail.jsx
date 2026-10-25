import React, { useState, useEffect } from "react";
import { Table, Pagination, Form, Button, Dropdown } from "react-bootstrap";
import { FaExclamationCircle, FaClock, FaBrain, FaBug, FaChartLine, FaCode, FaArrowRight, FaBell, FaLink, FaFileAlt } from "react-icons/fa";
import { toast } from "react-toastify";
import { useParams, useNavigate, useLocation, Link } from "react-router-dom";
import { StatusChip } from "./issues/IssuePanel";
import { useTranslation } from "react-i18next";
import DataService from "../services/data.service";
import { PostOnboardingUpsells } from "./onboarding";
import { isDemoUser } from "../utils/demo";
import notificationService from "../services/notification.service";
import PostmortemModal from "./PostmortemModal";
import PageHeader from "./PageHeader";
import BatchTimelineChart from "./BatchTimelineChart";
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

// Every signal for this batch (deploys, metric anomalies, errors, CI/CD,
// trace errors) on one time axis, with deploy-to-error arrows.
const IncidentTimeline = ({ batchId }) => {
  const { t } = useTranslation();
  const [payload, setPayload] = useState(null);
  useEffect(() => {
    let cancelled = false;
    DataService.getBatchTimeline(batchId).then((d) => { if (!cancelled) setPayload(d); });
    return () => { cancelled = true; };
  }, [batchId]);
  const events = payload?.events || [];
  return (
    <section className="ds-section incident-timeline" aria-labelledby="incident-tl">
      <div className="ds-section-head">
        <h2 className="ds-section-title" id="incident-tl">{t('detail.incident.timelineTitle')}</h2>
        <Link to={`/dash/timeline/${batchId}`} className="ds-section-link">{t('detail.incident.openTimeline')}</Link>
      </div>
      <div className="incident-timeline-body">
        {payload === null ? (
          <div className="incident-muted" aria-busy="true">{t('common.loading')}</div>
        ) : events.length === 0 ? (
          <div className="incident-muted">{t('detail.incident.noTimeline')}</div>
        ) : (
          <BatchTimelineChart events={events} causalPairs={payload?.causal_pairs || []} />
        )}
      </div>
    </section>
  );
};

const Detail = () => {
  const { t } = useTranslation();
  const { batchId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();

  const [data, setData] = useState([]);
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedLogType, setSelectedLogType] = useState("All");
  const [searchTerm, setSearchTerm] = useState("");
  const [availableServices, setAvailableServices] = useState([]);
  const pageSize = 9;

  const [selectedService, setSelectedService] = useState("All");
  // Logs and CI/CD runs together by default: a failed build that is part of
  // the analysis was hidden behind the Source menu (journey suite, B25).
  const [selectedData, setSelectedData] = useState("All");
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

  // ---- Incident view model -------------------------------------------
  const primary = _issuePrimary;
  const _primaryTitle = primary?.description || primary?.error_target || null;
  const incidentTitle = _cap(
    _primaryTitle || _analysisSummary || (_looksLikeDictRepr ? null : _rawAnalysisText),
    180,
  );
  // The narrative only adds something when it differs from the title.
  const narrative = analysisText && analysisText !== incidentTitle ? analysisText : null;
  const evidence = typeof primary?.reasoning === 'string'
    ? primary.reasoning.split('\n').map((l) => l.replace(/^\s*\d+[.)]\s*/, '').trim()).filter(Boolean)
    : (Array.isArray(primary?.reasoning) ? primary.reasoning.map(String) : []);
  const confidence = (primary?.confidence || '').toUpperCase();
  const CONFIDENCE_FILL = { HIGH: 88, MEDIUM: 60, LOW: 30 };
  const CONFIDENCE_TONE = { HIGH: 'var(--tone-green-text)', MEDIUM: 'var(--tone-amber-text)', LOW: 'var(--text-tertiary)' };
  const correlations = Array.isArray(primary?.correlation_summary) ? primary.correlation_summary : [];
  const primarySeverity = (primary?.severity || '').toUpperCase();
  const criticalCount = issues.filter((i) => (i.severity || '').toUpperCase() === 'CRITICAL').length;
  const services = [...new Set(issues.flatMap((i) => [i.component, ...(i.affected_services || [])]).filter(Boolean))];
  const environment = batchMeta?.data?.environment || primary?.environment || null;
  const traceCount = batchMeta?.data?.traces?.trace_count || 0;
  const codeCount = batchMeta?.data?.code_changes?.length || 0;
  const status = issues.length === 0
    ? { klass: 'ds-chip-ok', label: t('detail.incident.statusNoIssues') }
    : unacknowledged.length > 0
      ? { klass: primarySeverity === 'CRITICAL' ? 'ds-chip-err' : 'ds-chip-warn', label: t('detail.incident.statusOpen') }
      : { klass: 'ds-chip-info', label: t('detail.incident.statusAcknowledged') };
  const triggerLabel = batchMeta?.trigger === 'manual' || batchMeta?.trigger === 'alert'
    ? t(`investigate.trigger.${batchMeta.trigger}`)
    : sentinel.label;
  const correlationLabel = (c) => {
    if (c.type === 'commit') return t('detail.incident.corrCommit', { value: c.value });
    if (c.type === 'metric') return t('detail.incident.corrMetric', { value: c.value });
    if (c.type === 'cicd') return t('detail.incident.corrCicd', { value: c.value });
    if (c.type === 'trace') return t('detail.incident.corrTrace', { value: String(c.value).slice(0, 8) });
    return String(c.value || c.type);
  };
  // Each piece of evidence opens the page that shows it in context.
  const correlationLink = (c) => {
    if (c.type === 'commit') return `/dash/code-changes/${batchId}?sha=${encodeURIComponent(c.value)}`;
    if (c.type === 'metric') return `/dash/metrics/${batchId}`;
    if (c.type === 'cicd') return `/dash/timeline/${batchId}`;
    if (c.type === 'trace') return `/dash/traces/${encodeURIComponent(c.value)}`;
    return null;
  };
  // The failing span closest to this issue, when the batch has traces.
  const failingTrace = primary?.related_traces?.top_errors?.[0]?.trace_id;
  const evidenceChips = failingTrace ? [...correlations, { type: 'trace', value: failingTrace }] : correlations;

  return (
    <div className="detail-page incident-page">
      <PageHeader
        crumbs={[
          { label: t('nav.analyses'), to: '/dash/data' },
          { label: batchId, mono: true },
        ]}
        title={batchMeta ? (incidentTitle || t('detail.incident.quietTitle')) : batchId}
        badges={batchMeta && (
          <>
            <span className={`ds-chip ds-dot ${status.klass}`}>{status.label}</span>
            {primary?.severity && <span className={`ds-chip ${severityChip(primary.severity)}`}>{primary.severity}</span>}
          </>
        )}
        subtitle={batchMeta && (
          <span className="incident-meta">
            {services.length > 0 && <span className="ds-mono">{services.slice(0, 3).join(', ')}</span>}
            {environment && <span>{environment}</span>}
            <span>{triggerLabel}</span>
            {batchMeta.analyzed_at && <span>{t('detail.incident.analysedAgo', { when: relTime(batchMeta.analyzed_at) })}</span>}
          </span>
        )}
        actions={batchMeta && (
          <>
            <button type="button" className="ds-btn ds-btn-ghost" onClick={handleCopyLink}>
              <FaLink size={12} aria-hidden="true" /> {t('detail.incident.copyLink')}
            </button>
            {batchMeta.project && !isDemoUser() && (
              <Link to={rerunLink(batchMeta)} className="ds-btn ds-btn-secondary" title={t('investigate.rerunTitle')}>
                {t('investigate.rerun')}
              </Link>
            )}
            {unacknowledged.length > 0 && !isDemoUser() && (
              <button type="button" className={`ds-btn ${analysisText ? 'ds-btn-secondary' : 'ds-btn-primary'}`} onClick={handleAcknowledgeAll} disabled={acking}
                      title={t('detail.incident.acknowledgeTitle')}>
                <FaBell size={12} aria-hidden="true" /> {t('detail.incident.acknowledge', { count: unacknowledged.length })}
              </button>
            )}
            {analysisText && !isDemoUser() && (
              <button type="button" className="ds-btn ds-btn-primary" onClick={() => setShowPostmortem(true)}>
                <FaFileAlt size={12} aria-hidden="true" /> {t('detail.incident.postmortem')}
              </button>
            )}
          </>
        )}
      />

      {/* Contextual "connect SCM / CI-CD" nudges — surfaced here
          rather than in the wizard because the aha-moment (after
          seeing a first insight) is when users are most receptive
          to expanding the integration surface. */}
      <PostOnboardingUpsells />

      {batchMeta && (
        <div className="incident-grid">
          <div className="incident-main">
            {/* Root cause: the AI's narrative, how sure it is, and the
                evidence chain it followed. */}
            <section className="ds-section incident-rootcause" aria-labelledby="incident-rc">
              <div className="ds-section-head">
                <h2 className="ds-section-title" id="incident-rc">
                  <FaBrain aria-hidden="true" style={{ color: 'var(--tone-brand-text)' }} /> {t('detail.incident.rootCause')}
                </h2>
                {confidence && CONFIDENCE_FILL[confidence] && (
                  <div className="incident-confidence">
                    {t('detail.incident.confidence')}
                    <div className="incident-confidence-bar" role="img"
                         aria-label={`${t('detail.incident.confidence')}: ${primary.confidence_display || confidence}`}>
                      <div style={{ width: `${CONFIDENCE_FILL[confidence]}%`, background: CONFIDENCE_TONE[confidence] }} />
                    </div>
                    <strong>{primary.confidence_display || confidence}</strong>
                  </div>
                )}
              </div>
              <div className="incident-rootcause-body">
                {narrative ? (
                  <p className="incident-narrative">{narrative}</p>
                ) : !analysisText && (
                  <p className="incident-narrative incident-muted">{t('detail.incident.quietBody')}</p>
                )}
                {evidence.length > 0 && (
                  <>
                    <h3 className="incident-label">{t('detail.incident.evidence')}</h3>
                    <ol className="incident-steps">
                      {evidence.map((step, i) => (
                        <li key={i}><span className="incident-step-n" aria-hidden="true">{i + 1}</span><span>{step}</span></li>
                      ))}
                    </ol>
                  </>
                )}
                {evidenceChips.length > 0 && (
                  <div className="incident-correlations">
                    {evidenceChips.map((c, i) => {
                      const to = correlationLink(c);
                      return to
                        ? <Link key={i} to={to} className="ds-chip ds-chip-neutral incident-evidence-link">{correlationLabel(c)}</Link>
                        : <span key={i} className="ds-chip ds-chip-neutral">{correlationLabel(c)}</span>;
                    })}
                  </div>
                )}
                <div className="incident-model">
                  {batchMeta.model_name && <span className="ds-mono">{batchMeta.model_name}</span>}
                  {typeof batchMeta.logs_analyzed === 'number' && <span>{t('detail.incident.logsAnalysed', { count: batchMeta.logs_analyzed })}</span>}
                  {typeof batchMeta.token_count === 'number' && batchMeta.token_count > 0 && (
                    <span>{t('detail.incident.tokens', { count: batchMeta.token_count, formatted: batchMeta.token_count.toLocaleString() })}</span>
                  )}
                  {(batchMeta.sentinel_triggers || []).slice(0, 3).map((tr) => (
                    <span key={tr} className="ds-chip ds-chip-warn">{tr}</span>
                  ))}
                </div>
              </div>
            </section>

            <IncidentTimeline batchId={batchId} />

            {primary?.recommendation && (
              <section className="ds-section" aria-labelledby="incident-fix">
                <div className="ds-section-head">
                  <h2 className="ds-section-title" id="incident-fix">{t('detail.incident.suggestedFix')}</h2>
                  {batchMeta.project && !isDemoUser() && (
                    <Link to={rerunLink(batchMeta)} className="ds-btn ds-btn-secondary ds-btn-sm">{t('investigate.rerun')}</Link>
                  )}
                </div>
                <p className="incident-fix">{primary.recommendation}</p>
                {Array.isArray(primary.linked_commits) && primary.linked_commits.length > 0 && (
                  <ul className="incident-commits">
                    {primary.linked_commits.slice(0, 3).map((c, i) => (
                      <li key={i}>
                        <span className="ds-mono">{String(c?.sha || c).slice(0, 8)}</span>
                        {c?.message && <span>{c.message}</span>}
                        {c?.author && <span className="incident-muted">{c.author}</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
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
                {issue.status && <span style={{ marginTop: 2 }}><StatusChip status={issue.status} t={t} /></span>}
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
                      {issue.affected_services?.length > 0 && (
                        <span> · {t('issues.panel.alsoAffects', { services: issue.affected_services.join(', ') })}</span>
                      )}
                      {issue.environment && <span> · {issue.environment}</span>}
                    </div>
                  )}
                </div>
                <Link
                  to={`/dash/issues/${batchId}`}
                  className="ds-btn ds-btn-ghost ds-btn-sm"
                  style={{ flexShrink: 0, textDecoration: 'none' }}
                >
                  {t('detail.incident.viewIssue')} <FaArrowRight aria-hidden="true" />
                </Link>
              </div>
            ))}
          </div>
        </div>
      )}

          </div>

          <aside className="incident-rail" aria-label={t('detail.incident.details')}>
            <section className="ds-section incident-rail-card">
              <h2 className="incident-rail-title">{t('detail.incident.impact')}</h2>
              <div className="incident-stats">
                <div><strong>{issues.length}</strong><span>{t('detail.incident.issuesFound', { count: issues.length })}</span></div>
                <div><strong>{criticalCount}</strong><span>{t('detail.incident.critical')}</span></div>
              </div>
              {services.length > 0 && <div className="ds-kv"><span>{t('detail.incident.services')}</span><span className="ds-mono">{services.join(', ')}</span></div>}
              {environment && <div className="ds-kv"><span>{t('detail.incident.environment')}</span><span>{environment}</span></div>}
              {typeof batchMeta.logs_analyzed === 'number' && <div className="ds-kv"><span>{t('detail.incident.logs')}</span><span>{batchMeta.logs_analyzed.toLocaleString()}</span></div>}
            </section>
            <section className="ds-section incident-rail-card">
              <h2 className="incident-rail-title">{t('detail.incident.response')}</h2>
              <div className="ds-kv"><span>{t('detail.incident.status')}</span><span><span className={`ds-chip ds-dot ${status.klass}`}>{status.label}</span></span></div>
              <div className="ds-kv"><span>{t('detail.incident.trigger')}</span><span>{triggerLabel}</span></div>
              {batchMeta.model_name && <div className="ds-kv"><span>{t('detail.incident.model')}</span><span className="ds-mono">{batchMeta.model_name}</span></div>}
              {batchMeta.analyzed_at && <div className="ds-kv"><span>{t('detail.incident.analysed')}</span><span>{relTime(batchMeta.analyzed_at)}</span></div>}
            </section>
            <section className="ds-section incident-rail-card">
              <h2 className="incident-rail-title">{t('detail.incident.related')}</h2>
              <div className="ds-kv"><Link to={`/dash/issues/${batchId}`}>{t('detail.incident.allIssues')}</Link><span>{issues.length}</span></div>
              <div className="ds-kv"><Link to={`/dash/metrics/${batchId}`}>{t('detail.metrics')}</Link><span /></div>
              <div className="ds-kv"><Link to={`/dash/traces/batch/${batchId}`}>{t('detail.traces')}</Link><span>{traceCount || ''}</span></div>
              <div className="ds-kv"><Link to={`/dash/code-changes/${batchId}`}>{t('detail.codeChanges')}</Link><span>{codeCount || ''}</span></div>
              <div className="ds-kv"><Link to={`/dash/timeline/${batchId}`}>{t('detail.timeline')}</Link><span /></div>
            </section>
          </aside>
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
                  in-page choice: raw logs vs CI/CD logs. Shown when the
                  batch has CI/CD runs — otherwise there's nothing to
                  toggle. */}
              {data.some((item) => item.index.startsWith("ci_cd-logs-project-")) && (
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
                      {t('detail.logSource', 'Source')}: {{ "CI/CD Logs": t('detail.cicdLogs'), Logs: t('detail.logs') }[selectedData] || t('detail.allSources', 'All')}
                    </span>
                  </Dropdown.Toggle>
                  <Dropdown.Menu>
                    <Dropdown.Item
                      onClick={() => handleDataChange("All")}
                      style={{ fontSize: "14px" }}
                    >
                      {t('detail.allSources', 'All')}
                    </Dropdown.Item>
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
                <td data-label={t('detail.colTimestamp', 'Timestamp')} style={{ fontSize: "13px", whiteSpace: "nowrap", color: "var(--text-secondary)" }}>
                  {item.timestamp}
                </td>
                <td data-label={t('detail.colLevel', 'Level')} style={{ fontSize: "13px" }}>
                  <span className={`ds-chip ${
                    (item.type || '').toLowerCase() === 'error' ? 'ds-chip-err'
                      : (item.type || '').toLowerCase() === 'warning' ? 'ds-chip-warn'
                      : 'ds-chip-neutral'
                  }`}>
                    {(item.type || 'info').toUpperCase()}
                  </span>
                </td>
                <td data-label={t('detail.colService', 'Service')} style={{ fontSize: "13px", color: "var(--text-secondary)" }}>
                  {item.serviceName || '—'}
                </td>
                <td
                  style={{ fontSize: "13px", textAlign: "left" }}
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
