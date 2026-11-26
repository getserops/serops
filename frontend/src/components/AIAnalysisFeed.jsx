import React from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { FaArrowRight } from 'react-icons/fa';
import { SAMPLE_PATH } from '../sample/sampleIncident';
import './AIAnalysisFeed.css';
import { formatAbsolute, formatDayMonth, formatTime } from '../utils/dates';
import { severityChipClass } from '../utils/tones';
import { severityLabel } from '../utils/severityLabel';
import './overview/Overview.css';

// Five rows: when, the sentence (two lines), the severity (1.5.6).
const FEED_SIZE = 5;

const AIAnalysisFeed = ({ data, loading }) => {
    const { t } = useTranslation();
    const navigate = useNavigate();

    if (loading) {
        return (
            <div className="chart-card analysis-feed-card">
                <div className="chart-header">
                    <h2>{t('dashboard.glance.recentAnalyses')}</h2>
                    <span className="chart-subtitle">{t('dashboard.latestFindings', 'Latest findings from AI analysis')} · {t('dashboard.window.latestAnalyses', { count: FEED_SIZE })}</span>
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
                    <h2>{t('dashboard.glance.recentAnalyses')}</h2>
                    <span className="chart-subtitle">{t('dashboard.latestFindings', 'Latest findings from AI analysis')} · {t('dashboard.window.latestAnalyses', { count: FEED_SIZE })}</span>
                </div>
                <div className="no-data-message">
                    {t('dashboard.noAnalysisData', 'No AI analyses available yet. Analyses run automatically on log batches.')}
                    {' '}<Link to={SAMPLE_PATH}>{t('onboarding.viewSample', 'See a sample incident')}</Link>
                </div>
            </div>
        );
    }

    return (
        <div className="chart-card analysis-feed-card">
            <div className="chart-header">
                <h2>{t('dashboard.glance.recentAnalyses')}</h2>
                <span className="chart-subtitle">
                    {t('dashboard.totalAnalyses', '{{count}} total analyses', { count: total_analyses })} · {t('dashboard.window.latestAnalyses', { count: FEED_SIZE })}
                </span>
            </div>

            <div className="feed-list">
                {/* Five newest, no inner scroll box: the rest are a click away. */}
                {feed.slice(0, FEED_SIZE).map((item, index) => {
                    return (
                        <div
                            key={index}
                            className="feed-item"
                            onClick={() => navigate(`/dash/data/details/${item.batch_id}`)}
                            onKeyDown={(e) => { if (e.key === 'Enter') navigate(`/dash/data/details/${item.batch_id}`); }}
                            role="button"
                            tabIndex={0}
                        >
                            <span className="feed-when" title={formatAbsolute(item.analyzed_at, { fallback: '' })}>
                                <span>{formatDayMonth(item.analyzed_at, { fallback: '' })}</span>
                                <span>{formatTime(item.analyzed_at, { seconds: false, fallback: '' })}</span>
                            </span>
                            <p className="feed-summary glance-clamp-2">{item.summary || t('dashboard.noSummary', 'Analysis completed')}</p>
                            <span className="feed-severity">
                                {item.critical_count > 0
                                    ? <span className={severityChipClass('CRITICAL')}>{severityLabel(t, 'CRITICAL')}</span>
                                    : item.warning_count > 0 && <span className={severityChipClass('WARNING')}>{severityLabel(t, 'WARNING')}</span>}
                            </span>
                        </div>
                    );
                })}
            </div>
            {total_analyses > Math.min(feed.length, FEED_SIZE) && (
                <Link to="/dash/data" className="feed-view-all">
                    {t('dashboard.viewAllAnalyses', { count: total_analyses })} <FaArrowRight size={11} aria-hidden="true" />
                </Link>
            )}
        </div>
    );
};

export default AIAnalysisFeed;
