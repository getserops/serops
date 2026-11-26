import React, { useId } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { FaArrowRight, FaCheckCircle } from "react-icons/fa";
import dataService from "../services/data.service";
import { headline as cutHeadline, firstSentence, splitSteps } from "../utils/sentences";
import { severityChipClass } from "../utils/tones";
import { severityLabel } from "../utils/severityLabel";
import "./NeedsAttention.css";
import "./overview/Overview.css";


// Headline and rows show the first sentence of the description, cut at a
// word boundary when it is very long; the full text is on the issue and in
// the tooltip.
const headline = (issue) => cutHeadline(issue.description) || issue.description;

// One open issue, in the same shape for each (1.5.6): who, what is broken
// (two lines), why (the first sentence of the root cause, three lines), the
// first step of the action and how many more the issue holds. The cuts are
// at sentence ends; the whole text is on the issue.
const IssueRow = ({ issue, first, t }) => {
  const severity = (issue.severity || "").toUpperCase();
  const affected = Array.isArray(issue.affected_services) ? issue.affected_services : [];
  const why = firstSentence(issue.root_cause);
  const steps = splitSteps(issue.recommendation);
  const place = [issue.project_name, issue.environment].filter(Boolean).join(" · ");
  const to = `/dash/issues?id=${issue.id}`;
  const titleId = useId();
  return (
    <article className={`ds-card glance-issue glance-issue-${severity.toLowerCase() || "unknown"}`}>
      <div className="glance-issue-who">
        <span className={severityChipClass(issue.severity)}>{severityLabel(t, issue.severity)}</span>
        {issue.component && <span className="ds-mono glance-issue-service">{issue.component}</span>}
        {affected.length > 0 && <span className="glance-issue-place">{t("issues.panel.alsoAffects", { services: affected.join(", ") })}</span>}
        {place && <span className="glance-issue-place">{place}</span>}
      </div>
      <div className="glance-issue-what">
        <h3 className="glance-label">{t("dashboard.glance.whatIsBroken")}</h3>
        <Link to={to} id={titleId} className="glance-issue-title glance-clamp-2" title={issue.description}>{headline(issue)}</Link>
        {why && (
          <>
            <h3 className="glance-label glance-label-why">{t("dashboard.attention.why")}</h3>
            <p className="glance-issue-why glance-clamp-3">{why}</p>
          </>
        )}
      </div>
      {steps.length > 0 && (
        <div className="glance-issue-step">
          <h3 className="glance-label">{t("dashboard.glance.firstStep")}</h3>
          <p className="glance-step">{steps[0]}</p>
          {steps.length > 1 && <p className="glance-more-steps">{t("dashboard.glance.moreSteps", { count: steps.length - 1 })}</p>}
        </div>
      )}
      <div className="glance-issue-action">
        <Link to={to} className={`ds-btn ds-btn-sm ${first ? "ds-btn-primary" : "ds-btn-secondary"}`}
          aria-describedby={titleId}>
          {t("dashboard.attention.openIssue")}
        </Link>
      </div>
    </article>
  );
};

/**
 * The Overview opens on what is broken now: the three worst open issues,
 * each with what is broken, why and the first step.
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

  return (
    <section className="glance-attention" aria-labelledby="glance-attention-title">
      <div className="glance-section-head">
        <h2 id="glance-attention-title" className="glance-section-title">{t("dashboard.attention.title")}</h2>
        <Link to="/dash/issues?status=OPEN" className="attention-all">
          {t("dashboard.attention.viewOpen", { count: total })} <FaArrowRight size={11} aria-hidden="true" />
        </Link>
      </div>
      {issues.map((issue, i) => <IssueRow key={issue.id} issue={issue} first={i === 0} t={t} />)}
    </section>
  );
};

export default NeedsAttention;
