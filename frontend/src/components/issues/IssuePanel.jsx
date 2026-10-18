import React from "react";
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
  if (!issue) return null;
  const commits = Array.isArray(issue.linked_commits) ? issue.linked_commits : [];
  const reasoning = Array.isArray(issue.reasoning) ? issue.reasoning : (issue.reasoning ? [issue.reasoning] : []);
  const open = issue.status === "OPEN";

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
          <h3>{t("issues.panel.rootCause")}</h3>
          <p>{issue.root_cause || <span className="text-muted">{t("issues.panel.noRootCause")}</span>}</p>
        </section>
        {issue.recommendation && (
          <section className="issue-panel-section">
            <h3>{t("issues.panel.recommendation")}</h3>
            <p>{issue.recommendation}</p>
          </section>
        )}
        {reasoning.length > 0 && (
          <section className="issue-panel-section">
            <h3>{t("issues.panel.reasoning")}</h3>
            <ul>{reasoning.map((r, i) => <li key={i}>{typeof r === "string" ? r : JSON.stringify(r)}</li>)}</ul>
          </section>
        )}
        {(commits.length > 0 || issue.metric_anomaly_type) && (
          <section className="issue-panel-section">
            <h3>{t("issues.panel.correlations")}</h3>
            <ul>
              {commits.slice(0, 5).map((c, i) => {
                const sha = typeof c === "object" ? c.sha : String(c);
                const msg = typeof c === "object" ? c.message : "";
                return <li key={i}><code>{(sha || "").slice(0, 8)}</code>{msg ? ` — ${msg}` : ""}</li>;
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
      <div className="issue-panel-footer">
        {open && (
          <>
            <button type="button" className="ds-btn ds-btn-primary ds-btn-sm" onClick={() => onResolve(issue)}>
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
    </Offcanvas>
  );
};

export default IssuePanel;
