import React, { useState } from "react";
import { Offcanvas } from "react-bootstrap";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { FaCheck, FaVolumeMute, FaRedo, FaBell, FaComments, FaLink, FaSearch, FaFileAlt } from "react-icons/fa";
import { isDemoUser } from "../../utils/demo";

const MINUTE = 60 * 1000;

// Investigate the window around the issue: 30 minutes before it was first
// seen to 15 minutes after it was last seen (the page clamps to its limits).
export function investigateLink(issue) {
  const first = new Date(issue.created_at || Date.now());
  const last = new Date(issue.last_seen_at || issue.created_at || Date.now());
  const q = new URLSearchParams({
    start: new Date(first.getTime() - 30 * MINUTE).toISOString(),
    end: new Date(Math.min(Date.now(), last.getTime() + 15 * MINUTE)).toISOString(),
    hint: (issue.description || "").slice(0, 300),
  });
  if (issue.project) q.set("project_id", issue.project);
  if (issue.environment) q.set("environment", issue.environment);
  if (issue.component && /^[a-z0-9][a-z0-9-_.]*$/.test(issue.component)) q.set("services", issue.component);
  return `/dash/investigate?${q.toString()}`;
}

const when = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

export function StatusChip({ status, t }) {
  const s = (status || "").toUpperCase();
  // One status scale everywhere: open = warning, acknowledged = in
  // progress, resolved = healthy, muted = neutral, regressed = critical.
  const TONES = { OPEN: "ds-chip-warn", ACKNOWLEDGED: "ds-chip-info", RESOLVED: "ds-chip-ok", REGRESSED: "ds-chip-err" };
  const tone = TONES[s] || "ds-chip-neutral";
  return <span className={`ds-chip ds-dot ${tone}`}>{t(`issues.statusLabel.${s.toLowerCase() || "unknown"}`, { defaultValue: status || "—" })}</span>;
}

/**
 * Issue details, sliding in from the right so the list stays in view.
 * Everything comes from the list response; no extra request.
 */
const IssuePanel = ({ issue, onClose, onResolve, onMute, onReopen, onAcknowledge, onAskAI, onCopyLink }) => {
  const { t } = useTranslation();
  const demo = isDemoUser();
  // Resolve form: the AI's root cause and fix, to confirm or correct.
  const [resolving, setResolving] = useState(false);
  const [rootCause, setRootCause] = useState("");
  const [fix, setFix] = useState("");
  if (!issue) return null;
  const startResolve = () => {
    setRootCause(issue.root_cause || "");
    setFix(issue.recommendation || "");
    setResolving(true);
  };
  const submitResolve = (e) => {
    e.preventDefault();
    setResolving(false);
    onResolve(issue, { root_cause: rootCause.trim(), fix: fix.trim() });
  };
  const teamCause = (issue.resolution_root_cause || "").trim();
  const corrected = teamCause && teamCause !== (issue.root_cause || "").trim();
  const commits = Array.isArray(issue.linked_commits) ? issue.linked_commits : [];
  // The AI writes its reasoning as numbered lines ("1. …\n2. …"): one step
  // per line, numbering dropped since the list numbers them.
  const reasoning = (Array.isArray(issue.reasoning) ? issue.reasoning : String(issue.reasoning || "").split("\n"))
    .map((r) => (typeof r === "string" ? r.replace(/^\s*\d+[.)]\s*/, "").trim() : JSON.stringify(r)))
    .filter(Boolean);
  const open = issue.status === "OPEN";
  const affected = Array.isArray(issue.affected_services) ? issue.affected_services : [];

  return (
    <Offcanvas show placement="end" onHide={onClose} className="issue-panel" aria-labelledby="issue-panel-title">
      <Offcanvas.Header closeButton closeLabel={t("common.close")}>
        <div className="issue-panel-head">
          <div className="issue-panel-chips">
            <span className={`severity-badge severity-badge-${(issue.severity || "unknown").toLowerCase()}`}>{(issue.severity || "N/A").toUpperCase()}</span>
            <StatusChip status={issue.status} t={t} />
            {issue.acknowledged_at && <span className="ds-chip ds-chip-info">{t("issues.panel.acknowledged")}</span>}
            <span className="ds-mono issue-panel-id">#{issue.id}</span>
          </div>
          <Offcanvas.Title as="h2" id="issue-panel-title" className="issue-panel-title">{issue.description}</Offcanvas.Title>
          <div className="issue-panel-meta">
            {issue.component && <span className="ds-mono">{issue.component}</span>}
            {affected.length > 0 && <span>{t("issues.panel.alsoAffects", { services: affected.join(", ") })}</span>}
            {issue.project_name && <span>{issue.project_name}</span>}
            {issue.environment && <span>{issue.environment}</span>}
          </div>
        </div>
      </Offcanvas.Header>
      <Offcanvas.Body>
        <dl className="issue-panel-facts">
          <div><dt>{t("issues.panel.firstSeen")}</dt><dd>{when(issue.created_at)}</dd></div>
          <div><dt>{t("issues.panel.lastSeen")}</dt><dd>{when(issue.last_seen_at)}</dd></div>
          <div><dt>{t("issues.panel.occurrences")}</dt><dd>{issue.occurrence_count ?? 1}×</dd></div>
          {issue.confidence && <div><dt>{t("issues.panel.confidence")}</dt><dd>{issue.confidence_display || issue.confidence}</dd></div>}
        </dl>

        <section className="issue-panel-section">
          {teamCause ? (
            <>
              <h3>{issue.resolved_by_name
                ? t("issues.panel.confirmedRootCause", { name: issue.resolved_by_name })
                : t("issues.panel.confirmedRootCauseTeam")}</h3>
              <p>{teamCause}</p>
              {corrected && issue.root_cause && (
                <p className="issue-panel-ai-said">{t("issues.panel.aiSaid", { text: issue.root_cause })}</p>
              )}
            </>
          ) : (
            <>
              <h3>{t("issues.panel.rootCause")}</h3>
              <p>{issue.root_cause || <span className="text-muted">{t("issues.panel.noRootCause")}</span>}</p>
            </>
          )}
        </section>
        {issue.resolution_fix && (
          <section className="issue-panel-section">
            <h3>{t("issues.panel.whatFixedIt")}</h3>
            <p>{issue.resolution_fix}</p>
          </section>
        )}
        {issue.recommendation && (
          <section className="issue-panel-section">
            <h3>{t("issues.panel.recommendation")}</h3>
            <p>{issue.recommendation}</p>
          </section>
        )}
        {reasoning.length > 0 && (
          <section className="issue-panel-section">
            <h3>{t("issues.panel.reasoning")}</h3>
            <ol>{reasoning.map((r, i) => <li key={i}>{r}</li>)}</ol>
          </section>
        )}
        {(commits.length > 0 || issue.metric_anomaly_type) && (
          <section className="issue-panel-section">
            <h3>{t("issues.panel.correlations")}</h3>
            <ul>
              {commits.slice(0, 5).map((c, i) => {
                const sha = typeof c === "object" ? c.sha : String(c);
                const msg = typeof c === "object" ? c.message : "";
                const code = <code>{(sha || "").slice(0, 8)}</code>;
                return (
                  <li key={i}>
                    {sha && issue.batch_id_str
                      ? <Link to={`/dash/code-changes/${issue.batch_id_str}?sha=${encodeURIComponent(sha)}`}>{code}</Link>
                      : code}
                    {msg ? ` — ${msg}` : ""}
                  </li>
                );
              })}
              {issue.metric_anomaly_type && <li>{t("issues.panel.metricAnomaly", { type: issue.metric_anomaly_type.replace(/_/g, " ") })}</li>}
            </ul>
          </section>
        )}

        <div className="issue-panel-links">
          {issue.batch_id_str && (
            <Link className="ds-btn ds-btn-secondary ds-btn-sm" to={`/dash/data/details/${issue.batch_id_str}`}>
              <FaFileAlt aria-hidden="true" /> {t("issues.panel.openAnalysis")}
            </Link>
          )}
          {!demo && (
            <Link className="ds-btn ds-btn-secondary ds-btn-sm" to={investigateLink(issue)}>
              <FaSearch aria-hidden="true" /> {t("issues.panel.investigate")}
            </Link>
          )}
          <button type="button" className="ds-btn ds-btn-secondary ds-btn-sm" onClick={() => onAskAI(issue)}>
            <FaComments aria-hidden="true" /> {t("issues.panel.askAI")}
          </button>
          <button type="button" className="ds-btn ds-btn-ghost ds-btn-sm" onClick={() => onCopyLink(issue)}>
            <FaLink aria-hidden="true" /> {t("issues.panel.copyLink")}
          </button>
        </div>
      </Offcanvas.Body>
      {resolving ? (
        <form className="issue-panel-footer issue-resolve-form" onSubmit={submitResolve}>
          <label htmlFor="resolve-root-cause">{t("issues.panel.resolveRootCause")}</label>
          <textarea id="resolve-root-cause" className="form-control" rows={3} value={rootCause}
            onChange={(e) => setRootCause(e.target.value)} autoFocus />
          <small className="issue-resolve-hint">{t("issues.panel.resolveRootCauseHint")}</small>
          <label htmlFor="resolve-fix">{t("issues.panel.resolveFix")}</label>
          <textarea id="resolve-fix" className="form-control" rows={2} value={fix}
            onChange={(e) => setFix(e.target.value)} />
          <div className="issue-resolve-actions">
            <button type="submit" className="ds-btn ds-btn-primary ds-btn-sm">
              <FaCheck aria-hidden="true" /> {t("issues.panel.resolveConfirm")}
            </button>
            <button type="button" className="ds-btn ds-btn-ghost ds-btn-sm" onClick={() => setResolving(false)}>
              {t("common.cancel")}
            </button>
          </div>
        </form>
      ) : (
      <div className="issue-panel-footer">
        {open && (
          <>
            <button type="button" className="ds-btn ds-btn-primary ds-btn-sm" onClick={startResolve}>
              <FaCheck aria-hidden="true" /> {t("issues.panel.resolve")}
            </button>
            <button type="button" className="ds-btn ds-btn-secondary ds-btn-sm" onClick={() => onMute(issue.id)}>
              <FaVolumeMute aria-hidden="true" /> {t("issues.panel.mute")}
            </button>
            {!issue.acknowledged_at && (
              <button type="button" className="ds-btn ds-btn-secondary ds-btn-sm" onClick={() => onAcknowledge(issue)}>
                <FaBell aria-hidden="true" /> {t("issues.panel.acknowledge")}
              </button>
            )}
          </>
        )}
        {!open && (
          <button type="button" className="ds-btn ds-btn-secondary ds-btn-sm" onClick={() => onReopen(issue.id)}>
            <FaRedo aria-hidden="true" /> {t("issues.panel.reopen")}
          </button>
        )}
      </div>
      )}
    </Offcanvas>
  );
};

export default IssuePanel;
