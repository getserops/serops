import React from "react";
import { useTranslation } from "react-i18next";
import "./Overview.css";

// The causes of the last 30 days as one stacked bar, the counts in the
// legend (1.5.6, in place of the donut). Shades of one colour, most first;
// the legend names each part, so the shade is never the only sign.
const SHADES = 4;

const CausesBar = ({ data, loading }) => {
  const { t } = useTranslation();
  if (loading) return <section className="ds-card glance-panel glance-loading" aria-busy="true" />;
  const { breakdown = [], total_issues = 0, period_days = 30 } = data || {};
  const parts = (Array.isArray(breakdown) ? breakdown : [])
    .filter((b) => (b.count || 0) > 0)
    .sort((a, b) => b.count - a.count || String(a.category).localeCompare(String(b.category)));
  // The category as the server sends it, as the donut showed it.
  const name = (c) => c || "Unknown";
  const shade = (c, i) => (String(c).toLowerCase() === "unknown" ? "glance-cause-unknown" : `glance-cause-${Math.min(i, SHADES - 1)}`);

  return (
    <section className="ds-card glance-panel" aria-labelledby="glance-causes-title">
      <h2 id="glance-causes-title" className="glance-panel-title">{t("dashboard.glance.weekCauses")}</h2>
      <p className="glance-panel-sub">
        {t("dashboard.issuesAnalyzed", { count: total_issues })} · {t("dashboard.window.lastDays", { count: period_days })}
      </p>
      {parts.length === 0 ? (
        <p className="no-data-message">{t("dashboard.noRootCauseData")}</p>
      ) : (
        <>
          <div className="glance-stack" aria-hidden="true">
            {parts.map((p, i) => (
              <span key={p.category} className={shade(p.category, i)} style={{ flexGrow: p.count }} title={`${name(p.category)}: ${p.count}`} />
            ))}
          </div>
          <ul className="glance-legend">
            {parts.map((p, i) => (
              <li key={p.category}>
                <span className={`glance-dot ${shade(p.category, i)}`} aria-hidden="true" />
                <strong>{p.count}</strong> {name(p.category)}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
};

export default CausesBar;
