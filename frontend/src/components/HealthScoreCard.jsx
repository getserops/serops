import React, { memo } from "react";
import { FaHeartbeat, FaCheckCircle, FaExclamationTriangle, FaTimesCircle } from "react-icons/fa";
import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import { useTranslation } from "react-i18next";

// Text on white needs darker shades of the gauge colours (WCAG AA).
const TEXT = { '#06d6a0': 'var(--tone-green-text)', '#ef476f': 'var(--tone-red-text)', '#ffd166': 'var(--tone-amber-text)' };

// The half-circle is drawn inside its own box: centre on the bottom edge
// minus a small gap, so the whole arc stays inside the card. The unfilled
// track uses the hairline-border token, visible on the card in both themes.
export const GAUGE = { width: 120, height: 60, outerRadius: 50, innerRadius: 35, gap: 4 };
export const GAUGE_TRACK = "var(--border-hover)";

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
        { name: "Remainder", value: 100 - score, color: GAUGE_TRACK }
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
                    <ResponsiveContainer width={GAUGE.width} height={GAUGE.height}>
                        <PieChart margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
                            <Pie
                                data={data}
                                cx={GAUGE.width / 2}
                                cy={GAUGE.height - GAUGE.gap}
                                startAngle={180}
                                endAngle={0}
                                innerRadius={GAUGE.innerRadius}
                                outerRadius={GAUGE.outerRadius}
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
                        {t(`dashboard.statusLabels.${status?.toLowerCase()}`, { defaultValue: status })}
                    </div>
                    <div className="health-subtitle">{t('dashboard.healthWindow')}</div>
                </div>
            </div>
        </div>
    );

};

export default memo(HealthScoreCard);
