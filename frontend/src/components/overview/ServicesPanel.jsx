import React, { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { serviceGroups } from "./serviceGroups";
import "./Overview.css";

// Healthy services shown before "and N more".
export const HEALTHY_SHOWN = 5;

// Each name opens the Issues page filtered on that service (the filter also
// finds the issues caused elsewhere that affect it).
const Name = ({ service, group }) => (
  <li>
    <Link className={`glance-tag glance-${group} ds-mono`} to={`/dash/issues?component=${encodeURIComponent(service.name)}`}>
      {service.label || service.name}
    </Link>
  </li>
);

/**
 * Every service by name, in the three groups of the status card, with the
 * count in each title. No percentage.
 */
const ServicesPanel = ({ data, loading }) => {
  const { t } = useTranslation();
  const restId = useId();
  const [open, setOpen] = useState(false);
  const healthyList = useRef(null);
  // "and N more" goes away once pressed: the focus moves to the first name
  // it showed, not to the top of the page.
  useEffect(() => {
    if (open) healthyList.current?.querySelectorAll("a")[HEALTHY_SHOWN]?.focus();
  }, [open]);
  if (loading) return <section className="ds-card glance-panel glance-loading" aria-busy="true" />;
  const g = serviceGroups(data);

  const shown = open ? g.healthy : g.healthy.slice(0, HEALTHY_SHOWN);
  const folded = g.healthy.length - shown.length;
  const groups = [
    ["open", "groupOpen", g.open, g.open.length],
    ["affected", "groupAffected", g.affected, g.affected.length],
    ["healthy", "groupHealthy", shown, g.healthyCount],
  ];

  return (
    <section className="ds-card glance-panel" aria-labelledby="glance-services-title">
      <h2 id="glance-services-title" className="glance-panel-title">{t("dashboard.glance.services")}</h2>
      <p className="glance-panel-sub">
        {t("dashboard.servicesMonitored", { count: g.total })} · {t("dashboard.window.openNow")}
      </p>
      {g.total === 0 && <p className="no-data-message">{t("dashboard.noServiceData")}</p>}
      {groups.filter(([, , , n]) => n > 0).map(([group, key, list, n]) => (
        <div key={group} className="glance-group">
          <h3 className="glance-label">{t(`dashboard.glance.${key}`, { count: n })}</h3>
          <ul className="glance-tags" id={group === "healthy" ? restId : undefined} ref={group === "healthy" ? healthyList : undefined}>
            {list.map((s, i) => <Name key={`${s.label}-${i}`} service={s} group={group} />)}
            {group === "healthy" && folded > 0 && (
              <li>
                <button type="button" className="glance-tag glance-more" aria-expanded={false} aria-controls={restId} onClick={() => setOpen(true)}>
                  {t("dashboard.glance.andMore", { count: folded + g.unlisted })}
                </button>
              </li>
            )}
            {group === "healthy" && folded === 0 && g.unlisted > 0 && (
              <li className="glance-tag glance-unlisted">{t("dashboard.glance.andMore", { count: g.unlisted })}</li>
            )}
          </ul>
        </div>
      ))}
    </section>
  );
};

export default ServicesPanel;
