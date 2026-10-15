/**
 * Recent Deployments Card Component
 * Shows latest CI/CD deployments per service with status indicators
 */

import React from 'react';
import { Spinner } from 'react-bootstrap';
import { FaRocket, FaCheckCircle, FaTimesCircle, FaSpinner, FaGitlab, FaGithub, FaMicrosoft, FaJenkins, FaBitbucket } from 'react-icons/fa';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { isDemoUser } from '../utils/demo';
import { deployWindow } from './investigate/window';
import './RecentDeploymentsCard.css';

// Investigate from five minutes before the deploy to thirty after.
const investigateLink = (service) => {
    const w = deployWindow(service.latest_pipeline.created_at);
    const q = new URLSearchParams({
        project_id: service.project_id,
        services: service.service_name,
        start: w.start.toISOString(),
        end: w.end.toISOString(),
    });
    if (service.latest_pipeline.environment) q.set('environment', service.latest_pipeline.environment);
    return `/dash/investigate?${q.toString()}`;
};

const RecentDeploymentsCard = ({ data, loading }) => {
    const { t } = useTranslation();

    if (loading) {
        return (
            <div className="chart-card deployments-card">
                <div className="chart-header">
                    <h2><FaRocket className="chart-icon" /> {t('dashboard.recentDeployments')}</h2>
                    <span className="chart-subtitle">{t('dashboard.cicdStatusPerService')}</span>
                </div>
                <div className="deployments-loading">
                    <Spinner animation="border" variant="primary" />
                    <p>{t('dashboard.loadingDeployments')}</p>
                </div>
            </div>
        );
    }

    const services = data?.services || [];

    if (services.length === 0) {
        return (
            <div className="chart-card deployments-card">
                <div className="chart-header">
                    <h2><FaRocket className="chart-icon" /> {t('dashboard.recentDeployments')}</h2>
                    <span className="chart-subtitle">{t('dashboard.cicdStatusPerService')}</span>
                </div>
                <div className="deployments-empty">
                    <FaRocket className="empty-icon" />
                    <p>{t('dashboard.noCicdServices')}</p>
                    <span>{t('dashboard.addCicdServices')}</span>
                </div>
            </div>
        );
    }

    const getStatusIcon = (status) => {
        if (!status) return <FaSpinner className="status-icon pending" />;
        const s = status.toLowerCase();
        if (['success', 'passed', 'completed'].includes(s)) {
            return <FaCheckCircle className="status-icon success" />;
        }
        if (['failed', 'error', 'canceled'].includes(s)) {
            return <FaTimesCircle className="status-icon failed" />;
        }
        return <FaSpinner className="status-icon running" />;
    };

    const getProviderIcon = (provider) => {
        switch (provider?.toLowerCase()) {
            case 'gitlab':
                return <FaGitlab className="provider-icon gitlab" />;
            case 'github':
            case 'github_actions':
                return <FaGithub className="provider-icon github" />;
            case 'jenkins':
                return <FaJenkins className="provider-icon jenkins" />;
            case 'bitbucket':
            case 'bitbucket_pipelines':
                return <FaBitbucket className="provider-icon bitbucket" />;
            case 'azure_devops':
                return <FaMicrosoft className="provider-icon azure" />;
            default:
                return <FaRocket className="provider-icon" />;
        }
    };

    const formatTimeAgo = (isoString) => {
        if (!isoString) return t('dashboard.noDeployments');
        const date = new Date(isoString);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);

        if (diffMins < 1) return t('dashboard.justNow');
        if (diffMins < 60) return t('dashboard.timeAgo.minutes', { count: diffMins });
        if (diffHours < 24) return t('dashboard.timeAgo.hours', { count: diffHours });
        if (diffDays < 7) return t('dashboard.timeAgo.days', { count: diffDays });
        return date.toLocaleDateString();
    };

    const getSuccessRateClass = (rate) => {
        if (rate === null || rate === undefined) return '';
        if (rate >= 80) return 'success-rate-good';
        if (rate >= 50) return 'success-rate-warning';
        return 'success-rate-poor';
    };

    return (
        <div className="chart-card deployments-card">
            <div className="chart-header">
                <h2><FaRocket className="chart-icon" /> {t('dashboard.recentDeployments')}</h2>
                <span className="chart-subtitle">{t('dashboard.servicesWithCicd', { count: services.length })}</span>
            </div>

            <div className="deployments-list" tabIndex={0} role="region" aria-label={t('dashboard.recentDeployments')}>
                {services.map((service, index) => (
                    <div key={service.service_id || index} className="deployment-item">
                        <div className="deployment-main">
                            <div className="deployment-provider">
                                {getProviderIcon(service.provider)}
                            </div>
                            <div className="deployment-info">
                                <div className="deployment-name">{service.service_name}</div>
                                <div className="deployment-project">{service.project_name}</div>
                            </div>
                            {service.latest_pipeline && (
                                <div className="deployment-status">
                                    {getStatusIcon(service.latest_pipeline.status)}
                                    <span className={`status-text ${service.latest_pipeline.status?.toLowerCase() || ''}`}>
                                        {service.latest_pipeline.status
                                            ? (t(`dashboard.statusValues.${service.latest_pipeline.status.toLowerCase()}`, { defaultValue: '' }) || service.latest_pipeline.status)
                                            : t('dashboard.statusValues.running')}
                                    </span>
                                </div>
                            )}
                        </div>

                        <div className="deployment-details">
                            {service.latest_pipeline ? (
                                <>
                                    <div className="deployment-meta">
                                        <span className="branch-name">
                                            {service.latest_pipeline.branch || 'main'}
                                        </span>
                                        <span className="deploy-time">
                                            {formatTimeAgo(service.latest_pipeline.created_at)}
                                        </span>
                                        {service.project_id && service.latest_pipeline.created_at && !isDemoUser() && (
                                            <Link className="deploy-investigate" to={investigateLink(service)}
                                                  title={t('investigate.analyzeDeployTitle')}>
                                                {t('investigate.analyzeDeploy')}
                                            </Link>
                                        )}
                                    </div>
                                    {service.success_rate !== null && (
                                        <div className={`success-rate ${getSuccessRateClass(service.success_rate)}`}>
                                            {service.success_rate}% {t('dashboard.success')}
                                        </div>
                                    )}
                                </>
                            ) : (
                                <div className="no-pipelines">
                                    <span>{t('dashboard.noPipelinesYet')}</span>
                                </div>
                            )}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default RecentDeploymentsCard;
