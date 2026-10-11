import React from 'react';
import { Pie, PieChart, Cell, ResponsiveContainer, Legend, Tooltip } from 'recharts';
import { FaCode, FaServer, FaCog, FaCube, FaQuestionCircle } from 'react-icons/fa';
import { useTranslation } from 'react-i18next';
import './Dashboard.css';

const RootCausePie = ({ data, loading }) => {
    const { t } = useTranslation();

    if (loading) {
        return (
            <div className="chart-card">
                <div className="loading-spinner-large"></div>
            </div>
        );
    }

    const { breakdown = [], total_issues = 0 } = data || {};

    // Ensure breakdown is an array
    if (!Array.isArray(breakdown) || breakdown.length === 0) {
        return (
            <div className="chart-card">
                <div className="chart-header">
                    <h2><FaCode className="chart-icon" /> {t('dashboard.rootCauseAnalysis')}</h2>
                    <span className="chart-subtitle">{t('dashboard.issueCategoriesBreakdown')}</span>
                </div>
                <div className="no-data-message">{t('dashboard.noRootCauseData')}</div>
            </div>
        );
    }

    // Map categories to colors and icons
    const categoryConfig = {
        'Code': { color: '#118ab2', icon: <FaCode /> },
        'Infrastructure': { color: '#ef476f', icon: <FaServer /> },
        'Configuration': { color: '#ffd166', icon: <FaCog /> },
        'Dependency': { color: '#06d6a0', icon: <FaCube /> },
        'Unknown': { color: '#8b96a5', icon: <FaQuestionCircle /> }
    };

    // Format data for Recharts
    const chartData = breakdown.map(item => ({
        ...item,
        color: categoryConfig[item.category]?.color || '#8b96a5',
        icon: categoryConfig[item.category]?.icon || <FaQuestionCircle />
    }));

    const renderCustomizedLabel = ({ cx, cy, midAngle, innerRadius, outerRadius, percent }) => {
        const RADIAN = Math.PI / 180;
        const radius = innerRadius + (outerRadius - innerRadius) * 0.5;
        const x = cx + radius * Math.cos(-midAngle * RADIAN);
        const y = cy + radius * Math.sin(-midAngle * RADIAN);

        return percent === 0 ? null : (
            <text
                x={x}
                y={y}
                fill="white"
                textAnchor="middle"
                dominantBaseline="central"
                className="chart-label"
            >
                {`${(percent * 100).toFixed(0)}%`}
            </text>
        );
    };

    const CustomTooltip = ({ active, payload }) => {
        if (active && payload && payload.length) {
            const { category, count, percentage } = payload[0].payload;
            return (
                <div className="chart-tooltip">
                    <p className="tooltip-label" style={{ color: payload[0].payload.color }}>
                        {category}
                    </p>
                    <p className="tooltip-value">{count} {t('issues.title').toLowerCase()}</p>
                    <p className="tooltip-percentage">{percentage}% {t('dashboard.ofTotal')}</p>
                </div>
            );
        }
        return null;
    };

    if (total_issues === 0) {
        return (
            <div className="chart-card">
                <div className="chart-header">
                    <h2><FaQuestionCircle className="chart-icon" /> {t('dashboard.rootCauseBreakdown')}</h2>
                    <span className="chart-subtitle">{t('dashboard.issueCategorization')}</span>
                </div>
                <div className="chart-container">
                    <p style={{ textAlign: 'center', color: '#8b96a5', padding: '40px' }}>
                        {t('dashboard.noRootCauseData')}
                    </p>
                </div>
            </div>
        );
    }

    return (
        <div className="chart-card">
            <div className="chart-header">
                <h2><FaQuestionCircle className="chart-icon" /> {t('dashboard.rootCauseBreakdown')}</h2>
                <span className="chart-subtitle">{t('dashboard.issuesAnalyzed', { count: total_issues })}</span>
            </div>
            <div className="chart-container">
                <ResponsiveContainer width="100%" height={320}>
                    <PieChart>
                        <Pie
                            data={chartData}
                            cx="50%"
                            cy="50%"
                            labelLine={false}
                            label={renderCustomizedLabel}
                            outerRadius={120}
                            innerRadius={65}
                            dataKey="count"
                            strokeWidth={0}
                        >
                            {chartData.map((entry, index) => (
                                <Cell key={`cell-${index}`} fill={entry.color} />
                            ))}
                        </Pie>
                        <Tooltip content={<CustomTooltip />} />
                        <Legend
                            layout="horizontal"
                            verticalAlign="bottom"
                            align="center"
                            wrapperStyle={{ paddingTop: '20px' }}
                            formatter={(value, entry) => (
                                <span className="legend-label">
                                    {entry.payload.icon} {value}
                                </span>
                            )}
                        />
                    </PieChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
};

export default RootCausePie;
