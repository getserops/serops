import React, { memo } from "react";
import { FaHeartbeat, FaCheckCircle, FaExclamationTriangle, FaTimesCircle } from "react-icons/fa";
import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import { useTranslation } from "react-i18next";

// Text on white needs darker shades of the gauge colours (WCAG AA).
const TEXT = { '#06d6a0': '#047857', '#ef476f': '#c4123c', '#ffd166': '#8a6100' };

const HealthScoreCard = ({ score, status, loading }) => {
    const { t } = useTranslation();
    // Determine color based on score
    let color = "#06d6a0"; // Green
    let Icon = FaCheckCircle;

    if (score < 60) {
        color = "#ef476f"; // Red
        Icon = FaTimesCircle;
    } else if (score < 85) {
        color = "#ffd166"; // Yellow
        Icon = FaExclamationTriangle;
    }

    // Speedometer data
    // We want a semi-circle (180 deg)
    // Value is score, Remainder is 100 - score
    const data = [
        { name: "Score", value: score, color: color },
        { name: "Remainder", value: 100 - score, color: "#e9ecef" }
    ];

    if (loading) {
        return (
            <div className="metric-card health-card loading">
                <div className="loading-spinner"></div>
            </div>
        );
    }

    return (
        <div className="metric-card health-card">
            <div className="health-header">
                <div className="health-icon" style={{ backgroundColor: `${color}20`, color: color }}>
                    <FaHeartbeat />
                </div>
                <div className="health-title">{t('dashboard.healthTitle')}</div>
            </div>

            <div className="health-content">
                <div className="health-chart">
                    {/* Decorative gauge: the score is written out beside it. */}
                    <div aria-hidden="true" inert>
                    <ResponsiveContainer width={120} height={80}>
                        <PieChart>
                            <Pie
                                data={data}
                                cx="50%"
                                cy="100%"
                                startAngle={180}
                                endAngle={0}
                                innerRadius={35}
                                outerRadius={50}
                                paddingAngle={0}
                                dataKey="value"
                                stroke="none"
                            >
                                {data.map((entry, index) => (
                                    <Cell key={`cell-${index}`} fill={entry.color} />
                                ))}
                            </Pie>
                        </PieChart>
                    </ResponsiveContainer>
                    </div>
                    <div className="health-score-overlay">
                        <span className="score-value" style={{ color: TEXT[color] }}>{score}%</span>
                    </div>
                </div>

                <div className="health-details">
                    <div className="health-status" style={{ color: TEXT[color] }}>
                        <Icon className="status-icon" />
                        {t(`dashboard.statusLabels.${status?.toLowerCase()}`) || status}
                    </div>
                    <div className="health-subtitle">{t('dashboard.basedOnLast24h')}</div>
                </div>
            </div>
        </div>
    );

};

export default memo(HealthScoreCard);
