import React from 'react';
import { FaShieldAlt, FaBell, FaVolumeMute, FaStar, FaEyeSlash, FaDollarSign } from 'react-icons/fa';
import './Dashboard.css';

const SentinelStatsCard = ({ data, loading }) => {
    if (loading) {
        return (
            <div className="chart-card sentinel-stats-card">
                <div className="loading-spinner-large"></div>
            </div>
        );
    }

    const {
        total_batches = 0,
        decisions = {},
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
                <h2><FaShieldAlt className="chart-icon" /> Sentinel Intelligence</h2>
                <span className="chart-subtitle">AI gating decisions &amp; savings</span>
            </div>

            {!hasData ? (
                <div className="no-data-message">No sentinel data available yet</div>
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
                            title="Estimated by multiplying tokens-saved by this org's actual cost-per-token over the same window."
                        >
                            <div className="d-flex align-items-center justify-content-between">
                                <div>
                                    <div className="small">
                                        <FaDollarSign className="me-1" />
                                        Saved this week by Sentinel
                                    </div>
                                    <div style={{ fontSize: '1.75rem', fontWeight: 700 }}>
                                        {formatUsd(estimated_cost_saved_usd)}
                                    </div>
                                </div>
                                <div className="text-end small">
                                    AI spend
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
                        <span className="rate-label">AI calls saved</span>
                    </div>

                    {/* Decision breakdown */}
                    <div className="correlation-stats">
                        <div className="corr-stat">
                            <div className="corr-stat-icon" style={{ color: '#991b1b' }}>
                                <FaBell />
                            </div>
                            <div className="corr-stat-info">
                                <span className="corr-stat-value">{decisions.alert || 0}</span>
                                <span className="corr-stat-label">Alert</span>
                            </div>
                        </div>

                        <div className="corr-stat">
                            <div className="corr-stat-icon" style={{ color: '#065f46' }}>
                                <FaVolumeMute />
                            </div>
                            <div className="corr-stat-info">
                                <span className="corr-stat-value">{decisions.quiet || 0}</span>
                                <span className="corr-stat-label">Quiet</span>
                            </div>
                        </div>

                        <div className="corr-stat">
                            <div className="corr-stat-icon" style={{ color: '#1e40af' }}>
                                <FaStar />
                            </div>
                            <div className="corr-stat-info">
                                <span className="corr-stat-value">{decisions.first || 0}</span>
                                <span className="corr-stat-label">First</span>
                            </div>
                        </div>
                    </div>

                    {/* Detail row — drilldown beneath the hero number */}
                    {ai_skipped > 0 && (
                        <div className="corr-components">
                            <span className="corr-components-title">Details</span>
                            <div className="corr-component-tags">
                                <span className="corr-tag">
                                    <FaEyeSlash style={{ marginRight: 4, fontSize: '0.7rem' }} />
                                    {ai_skipped} batches skipped
                                </span>
                                {estimated_tokens_saved > 0 && (
                                    <span className="corr-tag">
                                        ~{formatTokens(estimated_tokens_saved)} tokens saved
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
