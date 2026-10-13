import React from 'react';
import { useTranslation } from 'react-i18next';
import { FaCodeBranch, FaMemory, FaMicrochip, FaLink, FaCog } from 'react-icons/fa';
import './Dashboard.css';

const CorrelationInsightsCard = ({ data, loading }) => {
    const { t } = useTranslation();

    if (loading) {
        return (
            <div className="chart-card correlation-card">
                <div className="loading-spinner-large"></div>
            </div>
        );
    }

    const {
        total_issues = 0,
        commit_correlations = 0,
        metric_correlations = 0,
        metric_breakdown = {},
        correlation_rate = 0,
        top_correlated_components = [],
        anomaly_type_breakdown = {},
        high_confidence_count = 0,
        cicd_correlations = 0,
    } = data || {};

    const hasData = total_issues > 0;

    return (
        <div className="chart-card correlation-card">
            <div className="chart-header">
                <h2><FaLink className="chart-icon" /> {t('dashboard.correlationInsights', 'AI Correlation Insights')}</h2>
                <span className="chart-subtitle">
                    {t('dashboard.correlationSubtitle', 'Issues linked to deployments & metric spikes')}
                </span>
            </div>

            {!hasData ? (
                <div className="no-data-message">
                    {t('dashboard.noCorrelationData', 'No correlation data available yet')}
                </div>
            ) : (
                <div className="correlation-content">
                    {/* Correlation rate badge */}
                    <div className="correlation-rate-badge">
                        <span className="rate-value">{correlation_rate}%</span>
                        <span className="rate-label">
                            {t('dashboard.issuesCorrelated', 'of issues correlated')}
                        </span>
                    </div>

                    {/* Correlation breakdown */}
                    <div className="correlation-stats">
                        <div className="corr-stat">
                            <div className="corr-stat-icon" style={{ color: '#2B47D6' }}>
                                <FaCodeBranch />
                            </div>
                            <div className="corr-stat-info">
                                <span className="corr-stat-value">{commit_correlations}</span>
                                <span className="corr-stat-label">
                                    {t('dashboard.deploymentLinks', 'Deployment Links')}
                                </span>
                            </div>
                        </div>

                        <div className="corr-stat">
                            <div className="corr-stat-icon" style={{ color: '#ef476f' }}>
                                <FaMemory />
                            </div>
                            <div className="corr-stat-info">
                                <span className="corr-stat-value">{metric_breakdown.memory || 0}</span>
                                <span className="corr-stat-label">
                                    {t('dashboard.memorySpikes', 'Memory Spikes')}
                                </span>
                            </div>
                        </div>

                        <div className="corr-stat">
                            <div className="corr-stat-icon" style={{ color: '#ffd166' }}>
                                <FaMicrochip />
                            </div>
                            <div className="corr-stat-info">
                                <span className="corr-stat-value">{metric_breakdown.cpu || 0}</span>
                                <span className="corr-stat-label">
                                    {t('dashboard.cpuSpikes', 'CPU Spikes')}
                                </span>
                            </div>
                        </div>

                        <div className="corr-stat">
                            <div className="corr-stat-icon" style={{ color: '#6c757d' }}>
                                <FaCog />
                            </div>
                            <div className="corr-stat-info">
                                <span className="corr-stat-value">{cicd_correlations}</span>
                                <span className="corr-stat-label">
                                    {t('dashboard.pipelineFailures', 'Pipeline Failures')}
                                </span>
                            </div>
                        </div>
                    </div>

                    {/* Anomaly type breakdown (spike vs sustained) */}
                    {(anomaly_type_breakdown.spike > 0 || anomaly_type_breakdown.sustained_high > 0) && (
                        <div className="corr-components" style={{ marginBottom: '0.5rem' }}>
                            <span className="corr-components-title">Anomaly Types</span>
                            <div className="corr-component-tags">
                                {anomaly_type_breakdown.spike > 0 && (
                                    <span className="corr-tag" style={{ borderColor: '#17a2b8' }}>
                                        Spike
                                        <span className="corr-tag-count">{anomaly_type_breakdown.spike}</span>
                                    </span>
                                )}
                                {anomaly_type_breakdown.sustained_high > 0 && (
                                    <span className="corr-tag" style={{ borderColor: '#ffc107' }}>
                                        Sustained
                                        <span className="corr-tag-count">{anomaly_type_breakdown.sustained_high}</span>
                                    </span>
                                )}
                                {high_confidence_count > 0 && (
                                    <span className="corr-tag" style={{ borderColor: '#28a745' }}>
                                        High Confidence
                                        <span className="corr-tag-count">{high_confidence_count}</span>
                                    </span>
                                )}
                            </div>
                        </div>
                    )}

                    {/* Top correlated components */}
                    {top_correlated_components.length > 0 && (
                        <div className="corr-components">
                            <span className="corr-components-title">
                                {t('dashboard.topAffected', 'Top Affected')}
                            </span>
                            <div className="corr-component-tags">
                                {top_correlated_components.map((comp, i) => (
                                    <span key={i} className="corr-tag">
                                        {comp.component}
                                        <span className="corr-tag-count">{comp.count}</span>
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export default CorrelationInsightsCard;
