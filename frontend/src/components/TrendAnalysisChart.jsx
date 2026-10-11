import React, { memo } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from "recharts";
import { FaHistory } from "react-icons/fa";

import { useTranslation } from "react-i18next";

const TrendAnalysisChart = ({ data, loading }) => {
    const { t } = useTranslation();
    const CustomTooltip = ({ active, payload, label }) => {
        if (active && payload && payload.length) {
            return (
                <div className="chart-tooltip">
                    <p className="tooltip-label">{label}</p>
                    <p className="tooltip-value critical">{t('dashboard.statusLabels.critical')}: {payload[0].value}</p>
                    <p className="tooltip-value warning">{t('dashboard.statusLabels.warning')}: {payload[1].value}</p>
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

    // Handle empty or invalid data
    if (!data || !Array.isArray(data) || data.length === 0) {
        return (
            <div className="chart-card">
                <div className="chart-header">
                    <h2><FaHistory className="chart-icon" /> {t('dashboard.trendTitle')}</h2>
                    <span className="chart-subtitle">{t('dashboard.trendSubtitle')}</span>
                </div>
                <div className="no-data-message">{t('dashboard.noTrendData')}</div>
            </div>
        );
    }

    return (
        <div className="chart-card">
            <div className="chart-header">
                <h2><FaHistory className="chart-icon" /> {t('dashboard.trendTitle')}</h2>
                <span className="chart-subtitle">{t('dashboard.trendSubtitle')}</span>
            </div>

            <div className="chart-container">
                <ResponsiveContainer width="100%" height={320}>
                    <AreaChart
                        data={data}
                        margin={{ top: 10, right: 30, left: 0, bottom: 0 }}
                    >
                        <defs>
                            <linearGradient id="colorCritical" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor="#ef476f" stopOpacity={0.8} />
                                <stop offset="95%" stopColor="#ef476f" stopOpacity={0} />
                            </linearGradient>
                            <linearGradient id="colorWarning" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor="#ffd166" stopOpacity={0.8} />
                                <stop offset="95%" stopColor="#ffd166" stopOpacity={0} />
                            </linearGradient>
                        </defs>
                        <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                        <YAxis tick={{ fontSize: 12 }} />
                        <CartesianGrid strokeDasharray="3 3" vertical={false} opacity={0.3} />
                        <Tooltip content={<CustomTooltip />} />
                        <Legend wrapperStyle={{ paddingTop: "10px" }} />
                        <Area
                            type="monotone"
                            dataKey="critical"
                            name={t('dashboard.statusLabels.critical').toUpperCase()}
                            stroke="#ef476f"
                            fillOpacity={1}
                            fill="url(#colorCritical)"
                        />
                        <Area
                            type="monotone"
                            dataKey="warning"
                            name={t('dashboard.statusLabels.warning').toUpperCase()}
                            stroke="#ffd166"
                            fillOpacity={1}
                            fill="url(#colorWarning)"
                        />
                    </AreaChart>
                </ResponsiveContainer>
            </div>
        </div>
    );

};

export default memo(TrendAnalysisChart);
