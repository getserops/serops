import React from 'react';
import { FaCircle, FaExclamationTriangle, FaCheckCircle, FaTimesCircle, FaMapMarkedAlt } from 'react-icons/fa';
import { useTranslation } from 'react-i18next';
import './Dashboard.css';

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

    // Get status icon and styling
    const getStatusInfo = (status) => {
        switch (status) {
            case 'healthy':
                return {
                    icon: <FaCheckCircle />,
                    className: 'service-healthy',
                    bgColor: '#047a5c',
                    textColor: '#fff'
                };
            case 'degraded':
                return {
                    icon: <FaExclamationTriangle />,
                    className: 'service-degraded',
                    bgColor: '#ffd166',
                    textColor: '#333'
                };
            case 'critical':
                return {
                    icon: <FaTimesCircle />,
                    className: 'service-critical',
                    bgColor: '#d4123f',
                    textColor: '#fff'
                };
            default:
                return {
                    icon: <FaCircle />,
                    className: 'service-unknown',
                    bgColor: '#8b96a5',
                    textColor: '#fff'
                };
        }
    };

    if (total_services === 0) {
        return (
            <div className="chart-card service-heatmap">
                <div className="chart-header">
                    <h2><FaMapMarkedAlt className="chart-icon" aria-hidden="true" /> {t('dashboard.serviceHealthMap')}</h2>
                    <span className="chart-subtitle">{t('dashboard.realTimeStatus')}</span>
                </div>
                <div className="chart-container">
                    <p style={{ textAlign: 'center', color: '#8b96a5', padding: '40px' }}>
                        {t('dashboard.noServiceData')}
                    </p>
                </div>
            </div>
        );
    }

    return (
        <div className="chart-card service-heatmap">
            <div className="chart-header">
                <h2><FaMapMarkedAlt className="chart-icon" aria-hidden="true" /> {t('dashboard.serviceHealthMap')}</h2>
                <span className="chart-subtitle">{t('dashboard.servicesMonitored', { count: total_services })}</span>
            </div>
            <div className="heatmap-container">
                <div className="heatmap-grid">
                    {services.slice(0, 12).map((service, index) => {
                        const statusInfo = getStatusInfo(service.status);
                        return (
                            <div
                                key={index}
                                className={`heatmap-tile ${statusInfo.className}`}
                                style={{
                                    backgroundColor: statusInfo.bgColor,
                                    color: statusInfo.textColor
                                }}
                                title={`${service.name}\nHealth: ${service.health_score}%\nErrors: ${service.error_count}\nCritical: ${service.critical_issues}`}
                            >
                                <div className="tile-icon">{statusInfo.icon}</div>
                                <div className="tile-name">{service.name}</div>
                                <div className="tile-score">{service.health_score}%</div>
                            </div>
                        );
                    })}
                </div>

                <div className="heatmap-legend">
                    <div className="legend-item">
                        <FaCheckCircle style={{ color: '#06d6a0' }} />
                        <span>{t('dashboard.healthy')}</span>
                    </div>
                    <div className="legend-item">
                        <FaExclamationTriangle style={{ color: '#ffd166' }} />
                        <span>{t('dashboard.degraded')}</span>
                    </div>
                    <div className="legend-item">
                        <FaTimesCircle style={{ color: '#ef476f' }} />
                        <span>{t('dashboard.criticalStatus')}</span>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default ServiceHealthHeatmap;
