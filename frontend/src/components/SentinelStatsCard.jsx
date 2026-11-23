import React from 'react';
import { useTranslation } from 'react-i18next';
import { FaShieldAlt, FaBell, FaVolumeMute, FaStar, FaEyeSlash, FaDollarSign, FaUser, FaFlask } from 'react-icons/fa';
import { isDemoUser } from '../utils/demo';
import './Dashboard.css';

const SentinelStatsCard = ({ data, loading }) => {
    const { t } = useTranslation();
    if (loading) {
        return (
            <div className="chart-card sentinel-stats-card">
                <div className="loading-spinner-large"></div>
            </div>
        );
    }

    const {
        period_days = 7,
        total_batches = 0,
        decisions = {},
        ai_analyzed = 0,
        ai_skipped = 0,
        skip_rate_percent = 0,
        estimated_tokens_saved = 0,
        // Hero numbers — derived from this org's own per-token AI spend.
        // Falls back to 0 cleanly when there's no usage data yet.
        estimated_cost_saved_usd = 0,
        ai_spend_usd = 0,
    } = data || {};

    const hasData = total_batches > 0;

    const formatTokens = (tokens) => {
        if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
        if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}K`;
        return tokens.toString();
    };

    const formatUsd = (amount) => {
        if (!amount) return '$0.00';
        if (amount < 0.01) return '<$0.01';
        if (amount >= 1000) return `$${(amount / 1000).toFixed(1)}K`;
        return `$${amount.toFixed(2)}`;
    };

    return (
        <div className="chart-card sentinel-stats-card">
            <div className="chart-header">
                <h2><FaShieldAlt className="chart-icon" /> {t('dashboard.sentinel.title')}</h2>
                <span className="chart-subtitle">{t('dashboard.sentinel.subtitle')} · {t('dashboard.window.lastDays', { count: period_days })}</span>
            </div>

            {!hasData ? (
                <div className="no-data-message">{t('dashboard.sentinel.noData')}</div>
            ) : (
                <div className="sentinel-content">
                    {/* Hero stat: dollars saved by Sentinel gating.
                        Derived from the org's own per-token spend rate so
                        the figure is defensible, not a marketing estimate. */}
                    {estimated_cost_saved_usd > 0 && (
                        <div
                            className="sentinel-hero-stat mb-3 p-3 rounded"
                            style={{
                                background: 'var(--tone-green-soft)',
                                color: 'var(--tone-green-text)',
                            }}
                            title={t('dashboard.sentinel.savedHint')}
                        >
                            <div className="d-flex align-items-center justify-content-between">
                                <div>
                                    <div className="small">
                                        <FaDollarSign className="me-1" />
                                        {t('dashboard.sentinel.savedBy')}
                                    </div>
                                    <div style={{ fontSize: '1.75rem', fontWeight: 700 }}>
                                        {formatUsd(estimated_cost_saved_usd)}
                                    </div>
                                </div>
                                <div className="text-end small">
                                    {t('dashboard.sentinel.aiSpend')}
                                    <div style={{ fontWeight: 600 }}>
                                        {formatUsd(ai_spend_usd)}
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Skip rate badge */}
                    <div className="correlation-rate-badge">
                        <span className="rate-value">{skip_rate_percent}%</span>
                        <span className="rate-label">{t('dashboard.sentinel.callsSaved')}</span>
                    </div>

                    {/* Decision breakdown */}
                    <div className="correlation-stats">
                        <div className="corr-stat">
                            <div className="corr-stat-icon" style={{ color: '#991b1b' }}>
                                <FaBell />
                            </div>
                            <div className="corr-stat-info">
                                <span className="corr-stat-value">{decisions.alert || 0}</span>
                                <span className="corr-stat-label">{t('dashboard.sentinel.alert')}</span>
                            </div>
                        </div>

                        <div className="corr-stat">
                            <div className="corr-stat-icon" style={{ color: '#065f46' }}>
                                <FaVolumeMute />
                            </div>
                            <div className="corr-stat-info">
                                <span className="corr-stat-value">{decisions.quiet || 0}</span>
                                <span className="corr-stat-label">{t('dashboard.sentinel.quiet')}</span>
                            </div>
                        </div>

                        <div className="corr-stat">
                            <div className="corr-stat-icon" style={{ color: '#1e40af' }}>
                                <FaStar />
                            </div>
                            <div className="corr-stat-info">
                                <span className="corr-stat-value">{decisions.first || 0}</span>
                                <span className="corr-stat-label">{t('dashboard.sentinel.first')}</span>
                            </div>
                        </div>

                        {/* Shadow and manual batches too, so the buckets add up to the total. */}
                        {decisions.shadow > 0 && (
                            <div className="corr-stat">
                                <div className="corr-stat-icon"><FaFlask /></div>
                                <div className="corr-stat-info">
                                    <span className="corr-stat-value">{decisions.shadow}</span>
                                    <span className="corr-stat-label">{t('dashboard.sentinel.shadow')}</span>
                                </div>
                            </div>
                        )}
                        {decisions.manual > 0 && (
                            <div className="corr-stat">
                                <div className="corr-stat-icon"><FaUser /></div>
                                <div className="corr-stat-info">
                                    <span className="corr-stat-value">{decisions.manual}</span>
                                    <span className="corr-stat-label">{t('dashboard.sentinel.manual')}</span>
                                </div>
                            </div>
                        )}
                    </div>
                    <p className="panel-window" title={t('dashboard.sentinel.decisionsHint', { count: total_batches })}>
                        {t('dashboard.sentinel.analysed', { analysed: ai_analyzed, total: total_batches })}
                    </p>

                    {/* Detail row — drilldown beneath the hero number */}
                    {ai_skipped > 0 && (
                        <div className="corr-components">
                            <span className="corr-components-title">{t('dashboard.sentinel.details')}</span>
                            <div className="corr-component-tags">
                                <span className="corr-tag">
                                    <FaEyeSlash style={{ marginRight: 4, fontSize: '0.7rem' }} />
                                    {t('dashboard.sentinel.batchesSkipped', { n: ai_skipped })}
                                </span>
                                {/* Tokens saved is the average tokens of an analysis times
                                    the batches skipped. In the demo that average is only a
                                    size estimate, so the figure is not shown there. */}
                                {estimated_tokens_saved > 0 && !isDemoUser() && (
                                    <span className="corr-tag">
                                        {t('dashboard.sentinel.tokensSaved', { tokens: formatTokens(estimated_tokens_saved) })}
                                    </span>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export default SentinelStatsCard;
