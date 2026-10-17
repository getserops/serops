import React from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { FaArrowRight, FaCheckCircle, FaFileAlt, FaSearch } from "react-icons/fa";
import dataService from "../services/data.service";
import { investigateLink } from "./issues/IssuePanel";
import { isDemoUser } from "../utils/demo";
import "./NeedsAttention.css";

const SEVERITY_CHIP = { CRITICAL: "ds-chip-err", HIGH: "ds-chip-err", WARNING: "ds-chip-warn", MEDIUM: "ds-chip-warn" };

// Only these get the full card; a warning gets one line so it doesn't
// dominate the page.
const URGENT = new Set(["CRITICAL", "HIGH"]);

/**
 * The Overview opens on what is broken now: the most severe open issue
 * with its root cause and recommended action, then the numbers below.
 */
const NeedsAttention = ({ environment, clusterId }) => {
  const { t } = useTranslation();
  const { data, isLoading } = useQuery({
    queryKey: ["needs-attention", environment, clusterId],
    queryFn: () => {
      const params = { status: "OPEN", sort_by: "severity", sort_dir: "desc", page_size: 3 };
      if (environment && environment !== "all") params.environment = environment;
      if (clusterId != null) params.cluster = clusterId;
      return dataService.getIssues(params);
    },
    staleTime: 30 * 1000,
    refetchInterval: 30 * 1000,
  });

  if (isLoading) return <section className="attention-card attention-loading" aria-busy="true" />;

  const issues = data?.results || [];
  const total = data?.pagination?.total_issues ?? issues.length;

  if (!issues.length) {
    return (
      <section className="attention-card attention-clear" aria-label={t("dashboard.attention.title")}>
        <FaCheckCircle className="attention-clear-icon" aria-hidden="true" />
        <div>
          <h2 className="attention-title">{t("dashboard.attention.allClear")}</h2>
          <p className="attention-sub">{t("dashboard.attention.allClearHint")}</p>
        </div>
      </section>
    );
  }

  const [top, ...rest] = issues;
  const severity = (top.severity || "").toUpperCase();

  if (!URGENT.has(severity)) {
    return (
      <section className={`attention-card attention-compact attention-${severity.toLowerCase()}`} aria-label={t("dashboard.attention.title")}>
        <span className={`ds-chip ${SEVERITY_CHIP[severity] || "ds-chip-info"}`}>{top.severity}</span>
        <Link to={`/dash/issues?id=${top.id}`} className="attention-compact-title">{top.description}</Link>
        {top.component && <span className="ds-mono attention-rest-svc">{top.component}</span>}
        <Link to="/dash/issues?status=OPEN" className="attention-all">
          {t("dashboard.attention.viewOpen", { count: total })} <FaArrowRight size={11} aria-hidden="true" />
        </Link>
      </section>
    );
  }

  return (
    <section className={`attention-card attention-${severity.toLowerCase()}`} aria-label={t("dashboard.attention.title")}>
      <div className="attention-head">
        <h2 className="attention-kicker">{t("dashboard.attention.title")}</h2>
        <Link to="/dash/issues?status=OPEN" className="attention-all">
          {t("dashboard.attention.viewOpen", { count: total })} <FaArrowRight size={11} aria-hidden="true" />
        </Link>
      </div>

      <div className="attention-top">
        <div className="attention-meta">
          <span className={`ds-chip ${SEVERITY_CHIP[severity] || "ds-chip-info"}`}>{top.severity}</span>
          {top.component && <span className="ds-mono">{top.component}</span>}
          {top.environment && <span>{top.environment}</span>}
          {top.project_name && <span>{top.project_name}</span>}
        </div>
        <Link to={`/dash/issues?id=${top.id}`} className="attention-issue-title">{top.description}</Link>

        <div className="attention-grid">
          <div>
            <h3 className="attention-label">{t("dashboard.attention.why")}</h3>
            <p>{top.root_cause || t("issues.panel.noRootCause")}</p>
          </div>
          {top.recommendation && (
            <div>
              <h3 className="attention-label">{t("dashboard.attention.whatToDo")}</h3>
              <p>{top.recommendation}</p>
            </div>
          )}
        </div>

        <div className="attention-actions">
          <Link to={`/dash/issues?id=${top.id}`} className="ds-btn ds-btn-primary ds-btn-sm">{t("dashboard.attention.openIssue")}</Link>
          {top.batch_id_str && (
            <Link to={`/dash/data/details/${top.batch_id_str}`} className="ds-btn ds-btn-secondary ds-btn-sm">
              <FaFileAlt size={11} aria-hidden="true" /> {t("issues.panel.openAnalysis")}
            </Link>
          )}
          {!isDemoUser() && (
            <Link to={investigateLink(top)} className="ds-btn ds-btn-secondary ds-btn-sm">
              <FaSearch size={11} aria-hidden="true" /> {t("issues.panel.investigate")}
            </Link>
          )}
        </div>
      </div>

      {rest.length > 0 && (
        <ul className="attention-rest">
          {rest.map((issue) => (
            <li key={issue.id}>
              <span className={`ds-chip ${SEVERITY_CHIP[(issue.severity || "").toUpperCase()] || "ds-chip-info"}`}>{issue.severity}</span>
              <Link to={`/dash/issues?id=${issue.id}`}>{issue.description}</Link>
              {issue.component && <span className="ds-mono attention-rest-svc">{issue.component}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
};

export default NeedsAttention;
