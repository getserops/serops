import React, { memo } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from "recharts";
import { FaHistory } from "react-icons/fa";

import { useTranslation } from "react-i18next";

// "2026-10-09" -> "Oct 9", read as a local date so it never shifts a day.
const shortDate = (value) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || '');
    if (!m) return value;
    return new Date(+m[1], +m[2] - 1, +m[3]).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
};

const TrendAnalysisChart = ({ data, loading }) => {
    const { t } = useTranslation();
    const CustomTooltip = ({ active, payload, label }) => {
        if (active && payload && payload.length) {
            return (
                <div className="chart-tooltip">
                    <p className="tooltip-label">{shortDate(label)}</p>
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

            {/* Daily counts are whole numbers: bars, not a smoothed area
                that drew hills between days. */}
            <div className="chart-container">
                <ResponsiveContainer width="100%" height={320}>
                    <BarChart
                        data={data}
                        margin={{ top: 10, right: 16, left: 0, bottom: 0 }}
                        barCategoryGap="25%"
                    >
                        <XAxis dataKey="date" tick={{ fontSize: 12 }} tickFormatter={shortDate}
                               interval="preserveStartEnd" minTickGap={12} />
                        <YAxis tick={{ fontSize: 12 }} allowDecimals={false} width={32}
                               domain={[0, (max) => Math.max(1, max)]} />
                        <CartesianGrid strokeDasharray="3 3" vertical={false} opacity={0.3} />
                        <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(0,0,0,0.04)' }} />
                        <Legend wrapperStyle={{ paddingTop: "10px" }} />
                        <Bar
                            dataKey="critical"
                            stackId="issues"
                            name={t('dashboard.statusLabels.critical').toUpperCase()}
                            fill="#ef476f"
                        />
                        <Bar
                            dataKey="warning"
                            stackId="issues"
                            name={t('dashboard.statusLabels.warning').toUpperCase()}
                            fill="#ffd166"
                            radius={[3, 3, 0, 0]}
                        />
                    </BarChart>
                </ResponsiveContainer>
            </div>
        </div>
    );

};

export default memo(TrendAnalysisChart);
