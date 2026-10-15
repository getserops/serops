import React from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { FaRobot, FaExclamationCircle, FaExclamationTriangle } from 'react-icons/fa';
import './AIAnalysisFeed.css';

// Badge text: darker shades of the environment colours, readable on their
// own 12% tint (the base colours measured under 3:1).
const ENV_TEXT = { production: '#c4123c', staging: '#8a6100', dev: '#047857', development: '#047857' };

const AIAnalysisFeed = ({ data, loading }) => {
    const { t } = useTranslation();
    const navigate = useNavigate();

    if (loading) {
        return (
            <div className="chart-card analysis-feed-card">
                <div className="chart-header">
                    <h2><FaRobot className="chart-icon" /> {t('dashboard.aiAnalysisFeed', 'Recent AI Analyses')}</h2>
                    <span className="chart-subtitle">{t('dashboard.latestFindings', 'Latest findings from AI analysis')}</span>
                </div>
                <div className="feed-skeleton">
                    {[1, 2, 3].map(i => (
                        <div key={i} className="feed-skeleton-item">
                            <div className="skeleton-line" style={{ width: '30%', height: 12 }} />
                            <div className="skeleton-line" style={{ width: '90%', height: 16 }} />
                            <div className="skeleton-line" style={{ width: '50%', height: 12 }} />
                        </div>
                    ))}
                </div>
            </div>
        );
    }

    const { feed = [], total_analyses = 0 } = data || {};

    if (feed.length === 0) {
        return (
            <div className="chart-card analysis-feed-card">
                <div className="chart-header">
                    <h2><FaRobot className="chart-icon" /> {t('dashboard.aiAnalysisFeed', 'Recent AI Analyses')}</h2>
                    <span className="chart-subtitle">{t('dashboard.latestFindings', 'Latest findings from AI analysis')}</span>
                </div>
                <div className="no-data-message">
                    {t('dashboard.noAnalysisData', 'No AI analyses available yet. Analyses run automatically on log batches.')}
                </div>
            </div>
        );
    }

    const formatTime = (isoString) => {
        if (!isoString) return '';
        const date = new Date(isoString);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);

        if (diffMins < 1) return t('dashboard.justNow', 'just now');
        if (diffMins < 60) return t('dashboard.minutesAgo', '{{count}}m ago', { count: diffMins });
        const diffHours = Math.floor(diffMins / 60);
        if (diffHours < 24) return t('dashboard.hoursAgo', '{{count}}h ago', { count: diffHours });
        const diffDays = Math.floor(diffHours / 24);
        return t('dashboard.daysAgo', '{{count}}d ago', { count: diffDays });
    };

    const envColors = {
        production: '#ef476f',
        staging: '#ffd166',
        dev: '#06d6a0',
        development: '#06d6a0',
        unknown: '#8b96a5',
    };

    return (
        <div className="chart-card analysis-feed-card">
            <div className="chart-header">
                <h2><FaRobot className="chart-icon" /> {t('dashboard.aiAnalysisFeed', 'Recent AI Analyses')}</h2>
                <span className="chart-subtitle">
                    {t('dashboard.totalAnalyses', '{{count}} total analyses', { count: total_analyses })}
                </span>
            </div>

            <div className="feed-list">
                {feed.map((item, index) => {
                    const envKey = (item.environment || 'unknown').toLowerCase();
                    const envColor = envColors[envKey] || envColors.unknown;

                    return (
                        <div
                            key={index}
                            className="feed-item"
                            onClick={() => navigate(`/dash/data/details/${item.batch_id}`)}
                            role="button"
                            tabIndex={0}
                        >
                            <div className="feed-item-header">
                                <span
                                    className="feed-env-badge"
                                    style={{ backgroundColor: `${envColor}20`, color: ENV_TEXT[envKey] || '#4b5163', borderColor: envColor }}
                                >
                                    {item.environment || 'unknown'}
                                </span>
                                <span className="feed-time">{formatTime(item.analyzed_at)}</span>
                            </div>

                            <p className="feed-summary">{item.summary || t('dashboard.noSummary', 'Analysis completed')}</p>

                            <div className="feed-item-footer">
                                {item.critical_count > 0 && (
                                    <span className="feed-badge feed-badge-critical">
                                        <FaExclamationCircle /> {item.critical_count} {t('issues.critical')}
                                    </span>
                                )}
                                {item.warning_count > 0 && (
                                    <span className="feed-badge feed-badge-warning">
                                        <FaExclamationTriangle /> {item.warning_count} {t('issues.warning', 'Warning')}
                                    </span>
                                )}
                                {item.model_name && (
                                    <span className="feed-model">{item.model_name}</span>
                                )}
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

export default AIAnalysisFeed;
