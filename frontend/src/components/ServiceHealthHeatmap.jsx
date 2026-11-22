import React from 'react';
import { FaCircle, FaExclamationTriangle, FaCheckCircle, FaTimesCircle, FaMapMarkedAlt } from 'react-icons/fa';
import { useTranslation } from 'react-i18next';
import './Dashboard.css';

const STATUS = {
    healthy: { Icon: FaCheckCircle, className: 'service-healthy' },
    degraded: { Icon: FaExclamationTriangle, className: 'service-degraded' },
    critical: { Icon: FaTimesCircle, className: 'service-critical' },
};
const UNKNOWN = { Icon: FaCircle, className: 'service-unknown' };

// Worst first: lowest health, then most open issues, then the name.
export const worstFirst = (services) => [...services].sort((a, b) =>
    (a.health_score ?? 100) - (b.health_score ?? 100)
    || (b.open_issues || 0) - (a.open_issues || 0)
    || String(a.name).localeCompare(String(b.name)));

/**
 * Service health: one panel for "which service is worst". Each tile is a
 * neutral card with a status accent on the left and shows the name, the
 * health and the open issues. (It replaces the health map of coloured
 * tiles and the "Top Failing Services" chart.)
 */
const ServiceHealthHeatmap = ({ data, loading }) => {
    const { t } = useTranslation();

    if (loading) {
        return (
            <div className="chart-card service-heatmap">
                <div className="loading-spinner-large"></div>
            </div>
        );
    }

    const { services = [], total_services = 0 } = data || {};

    if (total_services === 0) {
        return (
            <div className="chart-card service-heatmap">
                <div className="chart-header">
                    <h2><FaMapMarkedAlt className="chart-icon" aria-hidden="true" /> {t('dashboard.serviceHealthMap')}</h2>
                    <span className="chart-subtitle">{t('dashboard.window.openNow')}</span>
                </div>
                <div className="chart-container">
                    <p className="no-data-message">{t('dashboard.noServiceData')}</p>
                </div>
            </div>
        );
    }

    return (
        <div className="chart-card service-heatmap">
            <div className="chart-header">
                <h2><FaMapMarkedAlt className="chart-icon" aria-hidden="true" /> {t('dashboard.serviceHealthMap')}</h2>
                <span className="chart-subtitle">
                    {t('dashboard.servicesMonitored', { count: total_services })} · {t('dashboard.window.openNow')} · {t('dashboard.worstHealthFirst')}
                </span>
            </div>
            <div className="heatmap-container">
                <ul className="heatmap-grid">
                    {worstFirst(services).slice(0, 12).map((service) => {
                        const { Icon, className } = STATUS[service.status] || UNKNOWN;
                        return (
                            <li key={service.name} className={`heatmap-tile ${className}`}>
                                <span className="tile-name" title={service.name}>{service.name}</span>
                                <span className="tile-score"><Icon aria-hidden="true" /> {service.health_score}%</span>
                                <span className="tile-issues">{t('dashboard.openIssues', { count: service.open_issues || 0 })}</span>
                            </li>
                        );
                    })}
                </ul>

                <div className="heatmap-legend">
                    <div className="legend-item service-healthy">
                        <FaCheckCircle aria-hidden="true" />
                        <span>{t('dashboard.healthy')}</span>
                    </div>
                    <div className="legend-item service-degraded">
                        <FaExclamationTriangle aria-hidden="true" />
                        <span>{t('dashboard.degraded')}</span>
                    </div>
                    <div className="legend-item service-critical">
                        <FaTimesCircle aria-hidden="true" />
                        <span>{t('dashboard.criticalStatus')}</span>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default ServiceHealthHeatmap;
