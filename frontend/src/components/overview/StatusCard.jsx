import React from "react";
import { useTranslation } from "react-i18next";
import { serviceGroups } from "./serviceGroups";
import "./Overview.css";

// Above this many services, one square each gets too small to read: the bar
// becomes three parts instead.
export const SQUARES_MAX = 60;

/**
 * The Overview's status (1.5.6): one sentence and a bar with one square per
 * service, open issue first, then affected, then healthy. It replaces the
 * open critical and open issue tiles and the health gauge. The sentence and
 * the legend carry the numbers, so the colours are never the only sign.
 */
const StatusCard = ({ data, loading }) => {
  const { t } = useTranslation();
  if (loading) return <section className="ds-card glance-status glance-loading" aria-busy="true" />;
  const g = serviceGroups(data);
  if (!g.total) return null;

  const tone = g.critical > 0 ? "critical" : g.open.length > 0 ? "warning" : "healthy";
  const title = g.critical > 0
    ? t("dashboard.glance.statusCritical", { count: g.critical, total: g.total })
    : g.open.length > 0
      ? t("dashboard.glance.statusOpen", { count: g.open.length, total: g.total })
      : t("dashboard.glance.statusNone", { total: g.total });
  const detail = g.open.length > 0 && [
    g.affected.length > 0 && t("dashboard.glance.statusAffected", { count: g.affected.length }),
    t("dashboard.glance.statusHealthy", { count: g.healthyCount }),
  ].filter(Boolean).join(" ");

  const parts = [
    ["open", g.open.length, "legendOpen"],
    ["affected", g.affected.length, "legendAffected"],
    ["healthy", g.healthyCount, "legendHealthy"],
  ];
  const squares = [
    ...g.open.map((s) => ["open", s.label]),
    ...g.affected.map((s) => ["affected", s.label]),
    ...g.healthy.map((s) => ["healthy", s.label]),
    ...Array.from({ length: g.unlisted }, () => ["healthy", null]),
  ];

  return (
    <section className={`ds-card glance-status glance-tone-${tone}`} aria-labelledby="glance-status-title">
      <div className="glance-status-text">
        <h2 id="glance-status-title" className="glance-status-title">{title}</h2>
        {detail && <p className="glance-status-detail">{detail}</p>}
      </div>
      <div className="glance-status-bar">
        {g.total <= SQUARES_MAX ? (
          <ul className="glance-squares">
            {squares.map(([group, name], i) => (
              // The label carries the project when two projects share a name.
              <li key={i} className={`glance-square glance-${group}`}>
                {name
                  ? <span role="img" aria-label={name} title={name} />
                  : <span aria-hidden="true" />}
              </li>
            ))}
          </ul>
        ) : (
          <div className="glance-parts" aria-hidden="true">
            {parts.filter(([, n]) => n > 0).map(([group, n]) => (
              <span key={group} className={`glance-${group}`} style={{ flexGrow: n }} />
            ))}
          </div>
        )}
        <ul className="glance-legend">
          {parts.map(([group, n, key]) => (
            <li key={group}>
              <span className={`glance-dot glance-${group}`} aria-hidden="true" />
              <strong>{n}</strong> {t(`dashboard.glance.${key}`, { count: n })}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
};

export default StatusCard;
