import React, { memo } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, CartesianGrid } from "recharts";
import { FaServer } from "react-icons/fa";
import { useTranslation } from "react-i18next";

const ServiceRankingChart = ({ data, loading }) => {
    const { t } = useTranslation();
    const COLORS = ["#ef476f", "#fb8c00", "#ffd166", "#06d6a0", "#118ab2"];

    const CustomTooltip = ({ active, payload, label }) => {
        if (active && payload && payload.length) {
            return (
                <div className="chart-tooltip">
                    <p className="tooltip-label">{payload[0].payload.name || t('dashboard.unknownService')}</p>
                    <p className="tooltip-value">{payload[0].value} {t('issues.title').toLowerCase()}</p>
                </div>
            );
        }
        return null;
    };

    if (loading) {
        return (
            <div className="chart-card loading">
                <div className="loading-spinner"></div>
            </div>
        );
    }

    // Handle empty data
    if (!data || !Array.isArray(data) || data.length === 0) {
        return (
            <div className="chart-card">
                <div className="chart-header">
                    <h2><FaServer className="chart-icon" /> {t('dashboard.topFailingServices')}</h2>
                    <span className="chart-subtitle">{t('dashboard.byIssueCount', 'By issue count')}</span>
                </div>
                <div className="no-data-message">
                    {t('dashboard.noFailureData')}
                </div>
            </div>
        );
    }

    return (
        <div className="chart-card">
            <div className="chart-header">
                <h2><FaServer className="chart-icon" /> {t('dashboard.topFailingServices')}</h2>
                <span className="chart-subtitle">{t('dashboard.byIssueCount', 'By issue count')}</span>
            </div>

            <div className="chart-container">
                <ResponsiveContainer width="100%" height={320}>
                    <BarChart
                        layout="vertical"
                        data={data}
                        margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
                    >
                        <CartesianGrid strokeDasharray="3 3" horizontal={false} opacity={0.3} />
                        <XAxis type="number" hide />
                        <YAxis
                            type="category"
                            dataKey="name"
                            width={150}
                            tick={{ fontSize: 12 }}
                            tickFormatter={(value) => value && value.length > 20 ? `${value.substring(0, 20)}...` : (value || '')}
                        />
                        <Tooltip content={<CustomTooltip />} cursor={{ fill: 'transparent' }} />
                        <Bar dataKey="count" radius={[0, 4, 4, 0]} barSize={20}>
                            {data.map((entry, index) => (
                                <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                            ))}
                        </Bar>
                    </BarChart>
                </ResponsiveContainer>
            </div>
        </div>
    );

};

export default memo(ServiceRankingChart);
