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

    const { overall_mttr_hours = 0, by_severity = {}, trend = 'STABLE' } = data || {};

    // Convert hours to human-readable format
    const formatTime = (hours) => {
        if (hours < 1) {
            return `${Math.round(hours * 60)}min`;
        } else if (hours < 24) {
            return `${hours.toFixed(1)}h`;
        } else {
            return `${(hours / 24).toFixed(1)}d`;
        }
    };

    // Trend icon and color
    const getTrendInfo = () => {
        switch (trend) {
            case 'IMPROVING':
                return { icon: <FaArrowTrendDown />, color: 'var(--tone-green-text)', text: t('dashboard.trend.improving') };
            case 'DEGRADING':
                return { icon: <FaArrowTrendUp />, color: 'var(--tone-red-text)', text: t('dashboard.trend.degrading') };
            default:
                return { icon: <FaMinus />, color: 'var(--tone-amber-text)', text: t('dashboard.trend.stable') };
        }
    };

    const trendInfo = getTrendInfo();

    return (
        <div className="metric-card metric-primary">
            <div className="metric-icon"><FaClock /></div>
            <div className="metric-content">
                <span className="metric-label">{t('dashboard.mttr')}</span>
                <span className="metric-value">{formatTime(overall_mttr_hours)}</span>
            </div>
            <div className="metric-trend" style={{ color: trendInfo.color }}>
                {trendInfo.icon} {trendInfo.text}
            </div>

            {Object.keys(by_severity).length > 0 && (
                <div className="mttr-breakdown">
                    {by_severity.CRITICAL && (
                        <div className="mttr-severity">
                            <span className="severity-label" style={{ color: 'var(--tone-red-text)' }}>{t('issues.critical')}:</span>
                            <span className="severity-value">{formatTime(by_severity.CRITICAL.avg_hours)}</span>
                        </div>
                    )}
                    {by_severity.WARNING && (
                        <div className="mttr-severity">
                            <span className="severity-label" style={{ color: 'var(--tone-amber-text)' }}>{t('issues.warning')}:</span>
                            <span className="severity-value">{formatTime(by_severity.WARNING.avg_hours)}</span>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export default MTTRCard;
