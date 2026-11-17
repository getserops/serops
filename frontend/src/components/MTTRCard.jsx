import React from 'react';
import { useTranslation } from 'react-i18next';
import { FaClock, FaArrowTrendDown, FaArrowTrendUp, FaMinus } from 'react-icons/fa6';
import './Dashboard.css';

const MTTRCard = ({ data, loading }) => {
    const { t } = useTranslation();
    if (loading) {
        return (
            <div className="metric-card">
                <div className="loading-spinner-large"></div>
            </div>
        );
    }

    const {
        overall_mttr_hours = null,
        by_severity = {},
        trend = 'INSUFFICIENT_DATA',
        sample_size = 0,
        period_days = 30,
    } = data || {};

    // Convert hours to human-readable format
    const formatTime = (hours) => {
        if (hours == null) return '—';
        if (hours < 1) {
            return `${Math.round(hours * 60)}min`;
        } else if (hours < 24) {
            return `${hours.toFixed(1)}h`;
        } else {
            return `${(hours / 24).toFixed(1)}d`;
        }
    };

    // Trend icon and color. Below the backend's minimum sample there is
    // no trend to show, only "not enough data".
    const getTrendInfo = () => {
        switch (trend) {
            case 'IMPROVING':
                return { icon: <FaArrowTrendDown />, color: 'var(--tone-green-text)', text: t('dashboard.trend.improving') };
            case 'DEGRADING':
                return { icon: <FaArrowTrendUp />, color: 'var(--tone-red-text)', text: t('dashboard.trend.degrading') };
            case 'STABLE':
                return { icon: <FaMinus />, color: 'var(--tone-amber-text)', text: t('dashboard.trend.stable') };
            default:
                return { icon: null, color: 'var(--text-tertiary)', text: t('dashboard.trend.insufficient') };
        }
    };

    const trendInfo = getTrendInfo();

    const SEVERITY_ROWS = [
        ['CRITICAL', 'issues.critical', 'var(--tone-red-text)'],
        ['WARNING', 'issues.warning', 'var(--tone-amber-text)'],
        ['INFO', 'issues.info', 'var(--text-secondary)'],
    ];

    return (
        <div className="metric-card metric-primary">
            <div className="metric-icon"><FaClock /></div>
            <div className="metric-content">
                <span className="metric-label">{t('dashboard.mttr')}</span>
                <span className="metric-value">
                    {sample_size > 0 ? formatTime(overall_mttr_hours) : t('dashboard.notEnoughData')}
                </span>
                <span className="panel-window">
                    {t('dashboard.window.lastDays', { count: period_days })} · {t('dashboard.mttrSample', { count: sample_size })}
                </span>
            </div>
            <div className="metric-trend" style={{ color: trendInfo.color }}>
                {trendInfo.icon} {trendInfo.text}
            </div>

            {Object.keys(by_severity).length > 0 && (
                <div className="mttr-breakdown">
                    {SEVERITY_ROWS.filter(([sev]) => by_severity[sev]).map(([sev, label, color]) => (
                        <div className="mttr-severity" key={sev}>
                            <span className="severity-label" style={{ color }}>{t(label)}:</span>
                            <span className="severity-value">
                                {formatTime(by_severity[sev].avg_hours)} · {t('dashboard.mttrSample', { count: by_severity[sev].count })}
                            </span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default MTTRCard;
