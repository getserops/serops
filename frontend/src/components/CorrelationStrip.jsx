import React from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { FaLink } from 'react-icons/fa';
import DashboardService from '../services/dash.service';
import './Dashboard.css';

/**
 * AI correlation insights as one compact line above the Analyses list
 * (they were a card on the Overview). Same data as the card; nothing is
 * shown until there is something to count.
 */
const CorrelationStrip = ({ environment, clusterId }) => {
    const { t } = useTranslation();
    const { data } = useQuery({
        queryKey: ['correlation-insights', environment, clusterId],
        queryFn: () => DashboardService.getCorrelationInsights(7, environment),
        staleTime: 2 * 60 * 1000,
        refetchInterval: 2 * 60 * 1000,
    });

    const {
        total_issues = 0,
        commit_correlations = 0,
        metric_breakdown = {},
        correlation_rate = 0,
        cicd_correlations = 0,
        period_days = 7,
    } = data || {};

    if (!total_issues) return null;

    const facts = [
        [commit_correlations, t('dashboard.commitLinks')],
        [metric_breakdown.memory || 0, t('dashboard.memorySpikes')],
        [metric_breakdown.cpu || 0, t('dashboard.cpuSpikes')],
        [cicd_correlations, t('dashboard.pipelineFailures')],
    ];

    return (
        <section className="correlation-strip" aria-label={t('dashboard.correlationInsights')}>
            <span className="correlation-strip-title">
                <FaLink aria-hidden="true" /> {t('dashboard.correlationInsights')}
            </span>
            <span className="correlation-strip-rate">
                <strong>{correlation_rate}%</strong> {t('dashboard.issuesCorrelated')}
            </span>
            <ul className="correlation-strip-facts">
                {facts.map(([value, label]) => (
                    <li key={label}><strong>{value}</strong> {label}</li>
                ))}
            </ul>
            <span className="correlation-strip-window">{t('dashboard.window.lastDays', { count: period_days })}</span>
        </section>
    );
};

export default CorrelationStrip;
