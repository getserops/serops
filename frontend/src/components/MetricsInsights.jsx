import React from "react";
import { useTranslation } from "react-i18next";
import { Card, Col, Row, Table, Badge } from "react-bootstrap";
import { FiAlertTriangle, FiActivity, FiZap } from "react-icons/fi";

/**
 * The analysis SerOps already computed for a batch's metrics.
 *
 * Everything here was being calculated, stored and sent to the AI while the UI
 * showed none of it: `metrics_summary` and `container_lifecycle` had zero
 * references anywhere in the frontend. The metrics page drew two charts from
 * raw points and recomputed its own average, so the diagnosis lived only in AI
 * prose and the chart was decoration.
 *
 * Three things are worth an operator's attention, in this order:
 *
 *  1. **Container terminations.** The kubelet's view, not the application's. A
 *     container killed for exceeding its memory limit writes no log line — its
 *     output simply stops — so this is the only place an OOMKill is visible as
 *     data rather than as a sentence in a narrative.
 *  2. **Sustained anomalies.** Detected per service, so "cache is saturating"
 *     survives instead of being averaged into a healthy-looking project.
 *  3. **Per-service figures, including the worst single pod.** A service
 *     average hides one replica at 95% while its siblings idle, which is how a
 *     pod reaches an OOMKill with nothing on the dashboard moving.
 *
 * Renders from `metrics_summary`, which survives retention trimming — so a
 * batch whose chart has been cleared can still say what was found.
 */

// metrics_processing.calculate_trend emits exactly these four. Rising memory
// is the one worth colouring red: it is the shape that ends in an OOMKill,
// whereas a high but flat figure is a service sized tight on purpose.
// UNKNOWN is not a failure — it means the window held fewer than two points.
const TREND_STYLE = {
    INCREASING: { bg: "danger", icon: "↑", key: "trendIncreasing" },
    DECREASING: { bg: "success", icon: "↓", key: "trendDecreasing" },
    STABLE: { bg: "secondary", icon: "→", key: "trendStable" },
    UNKNOWN: { bg: "light", icon: "·", key: "trendUnknown" },
};

const formatDuration = (seconds) => {
    const s = Math.round(Number(seconds) || 0);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    const rest = s % 60;
    // "5m", not "5m 0s" — the scrape interval makes exact minutes common.
    return rest ? `${m}m ${rest}s` : `${m}m`;
};

/**
 * Reshape a summary into what this panel draws, or null when it would draw
 * nothing. Exported so the metrics page can tell whether this panel will
 * appear: its "no metrics for this batch" empty state must not contradict a
 * panel full of findings sitting directly above it.
 */
export const deriveInsights = (summary) => {
    if (!summary) return null;

    const { terminated = [], restarts = {}, anomalies = [], perService = {}, peakPodMemory = {} } = summary;

    const busyRestarts = Object.entries(restarts).filter(([, n]) => n);

    // One row per service that reported memory, with CPU and worst-pod joined on.
    const serviceRows = Object.entries(perService.memory || {})
        .filter(([, stats]) => stats && stats.avg !== null && stats.avg !== undefined)
        .map(([name, mem]) => ({
            name,
            mem,
            cpu: (perService.cpu || {})[name] || null,
            worstPod: (peakPodMemory || {})[name]?.max ?? null,
        }))
        .sort((a, b) => (b.mem.max || 0) - (a.mem.max || 0));

    if (!terminated.length && !busyRestarts.length && !anomalies.length && !serviceRows.length) {
        return null;
    }

    return { terminated, busyRestarts, anomalies, serviceRows };
};

const MetricsInsights = ({ summary }) => {
    const { t } = useTranslation();

    const derived = deriveInsights(summary);
    if (!derived) return null;

    const { terminated, busyRestarts, anomalies, serviceRows } = derived;

    const label = (name) =>
        name === "default" ? t("metrics.unlabelledContainers") : name;

    const kindLabel = (kind) =>
        ({
            memory: t("metrics.kindMemory"),
            cpu: t("metrics.kindCpu"),
            peak_pod_memory: t("metrics.kindPeakPodMemory"),
        }[kind] || kind);

    return (
        <div className="mb-4" data-testid="metrics-insights">
            <h5 className="mb-1 text-secondary fw-bold">{t("metrics.insightsTitle")}</h5>
            <p className="text-muted small mb-3">{t("metrics.insightsSubtitle")}</p>

            <Row className="g-3">
                {/* Terminations first: a killed container is the most actionable
                    thing on this page, and the hardest to see anywhere else. */}
                {(terminated.length > 0 || busyRestarts.length > 0) && (
                    <Col lg={6}>
                        <Card className="h-100 border-0 shadow-sm">
                            <Card.Body>
                                <h6 className="fw-bold text-uppercase small text-muted d-flex align-items-center gap-2">
                                    <FiAlertTriangle className="text-danger" aria-hidden="true" />
                                    {t("metrics.terminationsTitle")}
                                </h6>
                                <p className="text-muted small">{t("metrics.terminationsHint")}</p>

                                {terminated.map((item) => (
                                    <div key={`${item.container}-${item.reason}`} className="mb-2">
                                        <span className="ds-mono fw-semibold">{label(item.container)}</span>{" "}
                                        <Badge bg="danger">{item.reason}</Badge>
                                    </div>
                                ))}

                                {busyRestarts.length > 0 && (
                                    <div className="small text-dark mt-3">
                                        {/* Counted under a heading rather than written per row
                                            as "1 restarts": the agreement would need plural
                                            forms in every locale to say nothing extra. */}
                                        <div className="text-muted text-uppercase fw-semibold mb-1"
                                             style={{ fontSize: "0.7rem", letterSpacing: "0.04em" }}>
                                            {t("metrics.restartsTitle")}
                                        </div>
                                        {busyRestarts.map(([name, n]) => (
                                            <div key={name}>
                                                <span className="ds-mono">{label(name)}</span>
                                                <span className="text-muted"> · </span>
                                                {n}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </Card.Body>
                        </Card>
                    </Col>
                )}

                <Col lg={terminated.length > 0 || busyRestarts.length > 0 ? 6 : 12}>
                    <Card className="h-100 border-0 shadow-sm">
                        <Card.Body>
                            <h6 className="fw-bold text-uppercase small text-muted d-flex align-items-center gap-2">
                                <FiZap className="text-warning" aria-hidden="true" />
                                {t("metrics.anomaliesTitle")}
                            </h6>

                            {anomalies.length === 0 ? (
                                <p className="text-muted small mb-0">{t("metrics.noAnomalies")}</p>
                            ) : (
                                anomalies.slice(0, 5).map((a, i) => (
                                    <div key={`${a.kind}-${a.service || "all"}-${i}`} className="mb-2 small">
                                        <Badge bg="warning" text="dark" className="me-2">
                                            {kindLabel(a.kind)}
                                        </Badge>
                                        {a.service && (
                                            <span className="ds-mono fw-semibold">{label(a.service)} </span>
                                        )}
                                        <span className="text-dark">
                                            {a.peak_value}% {t("metrics.anomalyPeak")}
                                        </span>
                                        {a.duration_seconds ? (
                                            <span className="text-muted">
                                                {" "}
                                                {t("metrics.anomalyFor")} {formatDuration(a.duration_seconds)}
                                            </span>
                                        ) : null}
                                    </div>
                                ))
                            )}
                        </Card.Body>
                    </Card>
                </Col>

                {serviceRows.length > 0 && (
                    <Col xs={12}>
                        <Card className="border-0 shadow-sm">
                            <Card.Body>
                                <h6 className="fw-bold text-uppercase small text-muted d-flex align-items-center gap-2">
                                    <FiActivity className="text-primary" aria-hidden="true" />
                                    {t("metrics.perServiceTitle")}
                                </h6>
                                {/* Tables are the one thing allowed to scroll sideways. */}
                                <div style={{ overflowX: "auto" }}>
                                    <Table size="sm" className="mb-0 align-middle">
                                        <thead>
                                            <tr className="text-muted small">
                                                <th>{t("metrics.colService")}</th>
                                                <th>{t("metrics.colAvg")}</th>
                                                <th>{t("metrics.colPeak")}</th>
                                                <th>{t("metrics.colCurrent")}</th>
                                                <th>{t("metrics.colTrend")}</th>
                                                <th title={t("metrics.worstPodHint")}>
                                                    {t("metrics.colWorstPod")}
                                                </th>
                                                <th>{t("metrics.kindCpu")}</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {serviceRows.map(({ name, mem, cpu, worstPod }) => {
                                                const trend = TREND_STYLE[mem.trend] || TREND_STYLE.UNKNOWN;
                                                // Flagged only when a single pod runs meaningfully
                                                // hotter than the service as a whole — that gap is
                                                // the thing the average cannot express.
                                                const podDiverges =
                                                    worstPod !== null && mem.max !== null && worstPod - mem.max >= 10;
                                                return (
                                                    <tr key={name}>
                                                        <td className="ds-mono">{label(name)}</td>
                                                        <td>{mem.avg}%</td>
                                                        <td className="fw-semibold">{mem.max}%</td>
                                                        <td>{mem.current}%</td>
                                                        <td>
                                                            {/* Falls back to the raw value rather
                                                                than blanking, so a trend the
                                                                backend adds later still reads. */}
                                                            <Badge bg={trend.bg}>
                                                                {trend.icon}{" "}
                                                                {TREND_STYLE[mem.trend]
                                                                    ? t(`metrics.${trend.key}`)
                                                                    : mem.trend}
                                                            </Badge>
                                                        </td>
                                                        <td className={podDiverges ? "text-danger fw-semibold" : ""}>
                                                            {worstPod === null ? "—" : `${worstPod}%`}
                                                        </td>
                                                        <td>{cpu ? `${cpu.max}%` : "—"}</td>
                                                    </tr>
                                                );
                                            })}
                                        </tbody>
                                    </Table>
                                </div>
                            </Card.Body>
                        </Card>
                    </Col>
                )}
            </Row>
        </div>
    );
};

export default MetricsInsights;
