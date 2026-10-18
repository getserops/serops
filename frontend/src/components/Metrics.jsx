import React, { useState, useEffect, useRef } from "react";
import { Card, Dropdown, Container, Row, Col } from "react-bootstrap";
import { CircularProgressbar, buildStyles } from "react-circular-progressbar";
import "react-circular-progressbar/dist/styles.css";
import "./Data.css";
import { useNavigate, useParams } from "react-router-dom";
import { FiBarChart2 } from "react-icons/fi";
import PageHeader from "./PageHeader";
import { format, parse } from "date-fns";
import DataService from "../services/data.service";
import MetricsInsights, { deriveInsights } from "./MetricsInsights";
import {
  thresholdsFor,
  levelFor,
  colorFor,
  variantFor,
} from "../utils/metricThresholds";
import {
  LineChart,
  Line,
  Area,
  AreaChart,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { useTranslation } from "react-i18next";

const Metrics = () => {
  const { t } = useTranslation();
  const { batchId } = useParams();
  const navigate = useNavigate();
  const [memoryMetrics, setMemoryMetrics] = useState([]);
  const [cpuMetrics, setCpuMetrics] = useState([]);
  const [currentMemoryValue, setCurrentMemoryValue] = useState(0);
  // Distinguishes 'never collected' from 'cleared by retention' so the
  // empty state can say which. Null until the first fetch resolves.
  const [metricsTrimmedAt, setMetricsTrimmedAt] = useState(null);
  const [metricsLoaded, setMetricsLoaded] = useState(false);
  // Everything the backend already worked out about these metrics:
  // per-service figures, sustained anomalies, container terminations.
  // Stored on the batch alongside the raw points and sent to the AI, and
  // until now never shown to the operator who has to act on it.
  const [metricsSummary, setMetricsSummary] = useState(null);
  // Which services each chart's line was drawn from. getBatchMetrics
  // collapses the per-service series to one point per timestamp, keeping
  // the highest reading — so the line silently moves between services and
  // nothing on the page said so. It returned this list all along and no
  // caller read it.
  const [memoryServices, setMemoryServices] = useState([]);
  const [cpuServices, setCpuServices] = useState([]);
  const [currentCpuValue, setCurrentCpuValue] = useState(0);
  // No host state. A host filter was wired here and never rendered: only
  // filters.type reached the toolbar, filters.host was applied to nothing,
  // and getHosts() fired on every page load for a result nothing read.
  // Verified by rendering the component — exactly one dropdown in the DOM.
  const [batchMetadata, setBatchMetadata] = useState(null);
  const [filters, setFilters] = useState({
    environment: "All Environments",
    type: "Memory Usage",
    host: "All Hosts",
  });


  // Refs pour les sections
  const memorySectionRef = useRef(null);
  const cpuSectionRef = useRef(null);

  // The getHosts() effect that used to sit here is gone with the host filter:
  // it requested on every page load and nothing rendered the result.

  useEffect(() => {
    const fetchMetrics = async () => {
      try {
        // Fetch batch metadata
        const batchDetails = await DataService.getBatchDetails(batchId);
        if (batchDetails) {
          setBatchMetadata({
            batch_id: batchDetails.batch_id,
            timestamp: batchDetails.timestamp,
            environment: batchDetails.environment || 'production',
            project: batchDetails.project?.name || 'Unknown'
          });
          // metrics_summary lives on this same response, so it is read off
          // the payload already in hand. Fetching it separately would mean a
          // second download of this batch's whole log and metric payload for
          // data we are holding.
          setMetricsSummary(DataService.buildMetricSummary(batchDetails));
        }

        // Fetch Memory Usage metrics
        const memoryResponse = await DataService.getBatchMetrics(batchId, {
          type: "memory_usage",
        });
        if (memoryResponse?.results) {
          const sortedMemoryData = [...memoryResponse.results].sort(
            (a, b) => new Date(a.timestamp) - new Date(b.timestamp)
          );
          setMemoryMetrics(sortedMemoryData);
          setMemoryServices(memoryResponse.services || []);
          if (sortedMemoryData.length > 0) {
            setCurrentMemoryValue(
              sortedMemoryData[sortedMemoryData.length - 1].value
            );
          }
        }

        // Fetch CPU Usage metrics
        const cpuResponse = await DataService.getBatchMetrics(batchId, {
          type: "cpu_usage",
        });
        if (cpuResponse?.results) {
          const sortedCpuData = [...cpuResponse.results].sort(
            (a, b) => new Date(a.timestamp) - new Date(b.timestamp)
          );
          setCpuMetrics(sortedCpuData);
          setCpuServices(cpuResponse.services || []);
          if (sortedCpuData.length > 0) {
            setCurrentCpuValue(sortedCpuData[sortedCpuData.length - 1].value);
          }
        }

        // Why metrics are absent, for the empty state. getBatchMetrics sets
        // trimmedAt when the retention task has cleared this batch's raw
        // points, which is routine, as opposed to nothing having been
        // collected, which usually means a provider is not connected.
        setMetricsTrimmedAt(
          memoryResponse?.trimmedAt || cpuResponse?.trimmedAt || null
        );
      } catch (error) {
        console.error("Failed to fetch metrics:", error);
      } finally {
        setMetricsLoaded(true);
      }
    };

    fetchMetrics();
  }, [batchId]);

  useEffect(() => {
    // Scroll vers la section correspondante quand le type change
    if (filters.type === "Memory Usage" && memorySectionRef.current) {
      memorySectionRef.current.scrollIntoView({ behavior: "smooth" });
    } else if (filters.type === "CPU Usage" && cpuSectionRef.current) {
      cpuSectionRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [filters.type]);

  // Whether the insights panel will render anything. The empty state below
  // must not announce 'no metrics for this batch' while per-service figures
  // and an OOMKill sit on screen above it — which is exactly what a batch
  // past its raw-point retention looks like.
  const hasInsights = deriveInsights(metricsSummary) !== null;

  // Thresholds come from utils/metricThresholds, which mirrors the numbers
  // metrics_processing passes to detect_anomalies — 75% memory, 80% CPU. They
  // used to be 70/90 written inline here, and neither number exists anywhere
  // in the backend: the chart drew a calm amber line under a 'Critical' cutoff
  // a service at 78% never crossed, while the backend had already flagged it
  // and the AI had written it up as the cause directly above.
  const levelLabel = (value, metric) =>
    t(`metrics.level${levelFor(value, metric).replace(/^./, (c) => c.toUpperCase())}`);

  // "Peak across N services: a, b, c" — the line is a maximum, not an average,
  // and until now nothing said which services it ranged over.
  const peakCaption = (services) => {
    const named = services.filter((s) => s && s !== "default");
    if (named.length === 0) return null;
    return named.length === 1
      ? t("metrics.peakAcrossOne", { services: named[0] })
      : t("metrics.peakAcrossMany", {
          count: named.length,
          services: named.join(", "),
        });
  };

  const handleFilterChange = (key, value) => {
    if (key === "type") {
      if (value === "Logs") return;
      else if (value === "Issues") navigate(`/dash/issues/${batchId}`);
    }
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  const calculateAverage = (data) => {
    if (data.length === 0) return 0;
    const total = data.reduce(
      (sum, item) => sum + (parseFloat(item.value) || 0),
      0
    );
    return total / data.length;
  };

  // Metrics are batch-level, not per-host, so we don't filter by host
  const memoryAverageValue = calculateAverage(memoryMetrics);
  const cpuAverageValue = calculateAverage(cpuMetrics);

  const formatTimestamp = (timestamp, isTick = false) => {
    try {
      // Handle batch metadata timestamps (ISO format from backend)
      if (!isTick && typeof timestamp === 'string' && timestamp.includes('T')) {
        const date = new Date(timestamp);
        return format(date, "MMM dd, yyyy HH:mm");
      }

      // Handle chart timestamps (existing logic)
      const parsedDate = parse(timestamp, "dd/MM/yyyy HH:mm:ss", new Date());
      if (isNaN(parsedDate)) {
        return format(
          new Date(timestamp),
          isTick ? "HH:mm:ss" : "dd/MM/yyyy HH:mm:ss"
        );
      }
      return format(parsedDate, isTick ? "HH:mm:ss" : "dd/MM/yyyy HH:mm:ss");
    } catch (error) {
      console.error("Error formatting timestamp:", error);
      return timestamp;
    }
  };

  const sortedMemoryMetricsForChart = [...memoryMetrics].sort(
    (a, b) => new Date(a.timestamp) - new Date(b.timestamp)
  );

  const sortedCpuMetricsForChart = [...cpuMetrics].sort(
    (a, b) => new Date(a.timestamp) - new Date(b.timestamp)
  );

  return (
    <div className="data-page-container metrics-page">
      <PageHeader
        crumbs={[
          { label: t('nav.analyses'), to: '/dash/data' },
          ...(batchId ? [{ label: batchId.length <= 24 ? batchId : `${batchId.slice(0, 8)}…${batchId.slice(-6)}`, to: `/dash/data/details/${batchId}`, mono: true }] : []),
          { label: t('metrics.title') },
        ]}
        title={t('metrics.title')}
        actions={
          <Dropdown onSelect={(value) => handleFilterChange("type", value)} className="filter-dropdown">
            <Dropdown.Toggle variant="light" className="d-flex align-items-center justify-content-between gap-2">
              {filters.type}
            </Dropdown.Toggle>
            <Dropdown.Menu>
              <Dropdown.Item eventKey="Memory Usage">Memory Usage</Dropdown.Item>
              <Dropdown.Item eventKey="CPU Usage">CPU Usage</Dropdown.Item>
              <Dropdown.Item eventKey="Issues">Issues</Dropdown.Item>
            </Dropdown.Menu>
          </Dropdown>
        }
      />
      <div className="data-card mb-4">
        {/* What SerOps found, above the charts of the points it found it in.
          * Driven by metrics_summary, which survives the raw-point retention
          * trim — so the findings outlive the chart rather than disappearing
          * with it. Kept outside the two scroll-target sections so the
          * Memory/CPU dropdown still lands on the right chart. */}
        {hasInsights && (
          <div className="px-4 pt-4">
            <MetricsInsights summary={metricsSummary} />
          </div>
        )}

        <div className="p-4" ref={memorySectionRef}>
          {memoryMetrics.length > 0 && (
            <div>
              <h2 className="metrics-section-title">
                {t('metrics.memoryUsage')}
              </h2>
              <Row className="g-4 align-items-stretch mb-5">
                <Col md={8}>
                  <Card className="h-100 metrics-chart-card">
                    <Card.Body>
                      <h3 className="metrics-card-title">{t('metrics.memoryUsageOverTime')}</h3>
                      <div style={{ height: "300px" }}>
                        <ResponsiveContainer width="100%" height={250}>
                          <AreaChart
                            data={sortedMemoryMetricsForChart}
                            margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
                          >
                            <defs>
                              <linearGradient id="memoryGradient" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor="#4e73df" stopOpacity={0.8} />
                                <stop offset="95%" stopColor="#4e73df" stopOpacity={0.1} />
                              </linearGradient>
                            </defs>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e3e6f0" />
                            {/* The line the backend flags above, not a
                                number chosen for the chart. */}
                            <ReferenceLine
                              y={thresholdsFor("memory").over}
                              stroke="#dc3545"
                              strokeDasharray="3 3"
                              label={{
                                value: t('metrics.thresholdLine', { value: thresholdsFor("memory").over }),
                                position: 'insideTopRight', fill: '#dc3545', fontSize: 11, offset: 8,
                              }}
                            />
                            <ReferenceLine
                              y={thresholdsFor("memory").approaching}
                              stroke="#ffc107"
                              strokeDasharray="3 3"
                              label={{
                                value: t('metrics.approachingLine', { value: thresholdsFor("memory").approaching }),
                                position: 'insideTopRight', fill: '#b8860b', fontSize: 11, offset: 8,
                              }}
                            />
                            <XAxis
                              dataKey="timestamp"
                              tickFormatter={(timestamp) =>
                                formatTimestamp(timestamp, true)
                              }
                              // Recharts drops labels that would collide, so
                              // the axis stays readable at any width.
                              interval="preserveStartEnd"
                              minTickGap={16}
                              tick={{ fontSize: 12, fill: '#858796' }}
                              axisLine={false}
                              tickLine={false}
                            />
                            <YAxis
                              domain={[0, 100]}
                              tick={{ fontSize: 12, fill: '#858796' }}
                              axisLine={false}
                              tickLine={false}
                            />
                            <Tooltip
                              contentStyle={{ backgroundColor: '#fff', borderRadius: '8px', border: 'none', boxShadow: '0 0.15rem 1.75rem 0 rgba(58, 59, 69, 0.15)' }}
                              formatter={(value, _name, item) => [
                                `${value}%`,
                                // The plotted point is the highest reading
                                // across the project's services at that
                                // moment; naming the service is the whole
                                // value of it — "95% peak" with no service
                                // attached is an observation, not a diagnosis.
                                item?.payload?.service
                                  ? `Memory Usage · ${item.payload.service}`
                                  : 'Memory Usage',
                              ]}
                              labelFormatter={(timestamp) =>
                                formatTimestamp(timestamp, false)
                              }
                            />
                            <Area
                              type="monotone"
                              dataKey="value"
                              stroke="#4e73df"
                              strokeWidth={3}
                              fill="url(#memoryGradient)"
                              dot={false}
                              activeDot={{ r: 6, strokeWidth: 0 }}
                            />
                          </AreaChart>
                        </ResponsiveContainer>
                      </div>
                      {peakCaption(cpuServices) && (
                        <p className="small text-muted mb-0 mt-2" data-testid="cpu-peak-caption">
                          {peakCaption(cpuServices)}
                        </p>
                      )}
                      {/* What the line is: a maximum across services, not an
                          average of them. The services list came back on
                          every fetch and nothing read it, so a point at 98%
                          gave no clue whose 98% it was. */}
                      {peakCaption(memoryServices) && (
                        <p className="small text-muted mb-0 mt-2" data-testid="memory-peak-caption">
                          {peakCaption(memoryServices)}
                        </p>
                      )}
                    </Card.Body>
                  </Card>
                </Col>

                <Col md={4}>
                  <Card className="h-100 metrics-chart-card">
                    <Card.Body className="d-flex flex-column justify-content-center align-items-center">
                      <h3 className="metrics-card-title mb-3">{t('metrics.averageUsage')}</h3>
                      <div className="text-center">
                        <div
                          style={{
                            width: 180,
                            height: 180,
                            margin: "0 auto",
                            borderRadius: "50%",
                            padding: "8px",
                            border: `4px solid ${colorFor(memoryAverageValue, "memory")}`,
                            animation:
                              levelFor(memoryAverageValue, "memory") === "over"
                                ? 'pulse 2s infinite'
                                : 'none'
                          }}
                        >
                          <CircularProgressbar
                            value={memoryAverageValue}
                            text={`${Math.round(memoryAverageValue * 100) / 100}%`}
                            styles={buildStyles({
                              pathColor: colorFor(memoryAverageValue, "memory"),
                              textColor: colorFor(memoryAverageValue, "memory"),
                              trailColor: "#e3e6f0",
                              textSize: '16px',
                            })}
                          />
                        </div>
                        <div className="mt-2">
                          <span
                            className={`badge bg-${variantFor(memoryAverageValue, "memory")}`}
                            title={t('metrics.thresholdHint')}
                          >
                            {levelLabel(memoryAverageValue, "memory")}
                          </span>
                        </div>
                      </div>
                    </Card.Body>
                  </Card>
                </Col>
              </Row>
            </div>
          )}

          {cpuMetrics.length > 0 && (
            <div ref={cpuSectionRef} className="pt-4 border-top">
              <h2 className="metrics-section-title">
                {t('metrics.cpuUsage')}
              </h2>
              <Row className="g-4 align-items-stretch">
                <Col md={8}>
                  <Card className="h-100 metrics-chart-card">
                    <Card.Body>
                      <h3 className="metrics-card-title">{t('metrics.cpuUsageOverTime')}</h3>
                      <div style={{ height: "300px" }}>
                        <ResponsiveContainer width="100%" height={250}>
                          <AreaChart
                            data={sortedCpuMetricsForChart}
                            margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
                          >
                            <defs>
                              <linearGradient id="cpuGradient" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor="#1cc88a" stopOpacity={0.8} />
                                <stop offset="95%" stopColor="#1cc88a" stopOpacity={0.1} />
                              </linearGradient>
                            </defs>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e3e6f0" />
                            {/* The line the backend flags above, not a
                                number chosen for the chart. */}
                            <ReferenceLine
                              y={thresholdsFor("cpu").over}
                              stroke="#dc3545"
                              strokeDasharray="3 3"
                              label={{
                                value: t('metrics.thresholdLine', { value: thresholdsFor("cpu").over }),
                                position: 'insideTopRight', fill: '#dc3545', fontSize: 11, offset: 8,
                              }}
                            />
                            <ReferenceLine
                              y={thresholdsFor("cpu").approaching}
                              stroke="#ffc107"
                              strokeDasharray="3 3"
                              label={{
                                value: t('metrics.approachingLine', { value: thresholdsFor("cpu").approaching }),
                                position: 'insideTopRight', fill: '#b8860b', fontSize: 11, offset: 8,
                              }}
                            />
                            <XAxis
                              dataKey="timestamp"
                              tickFormatter={(timestamp) =>
                                formatTimestamp(timestamp, true)
                              }
                              // Recharts drops labels that would collide, so
                              // the axis stays readable at any width.
                              interval="preserveStartEnd"
                              minTickGap={16}
                              tick={{ fontSize: 12, fill: '#858796' }}
                              axisLine={false}
                              tickLine={false}
                            />
                            <YAxis
                              domain={[0, 100]}
                              tick={{ fontSize: 12, fill: '#858796' }}
                              axisLine={false}
                              tickLine={false}
                            />
                            <Tooltip
                              contentStyle={{ backgroundColor: '#fff', borderRadius: '8px', border: 'none', boxShadow: '0 0.15rem 1.75rem 0 rgba(58, 59, 69, 0.15)' }}
                              formatter={(value, _name, item) => [
                                `${value}%`,
                                // The plotted point is the highest reading
                                // across the project's services at that
                                // moment; naming the service is the whole
                                // value of it — "95% peak" with no service
                                // attached is an observation, not a diagnosis.
                                item?.payload?.service
                                  ? `CPU Usage · ${item.payload.service}`
                                  : 'CPU Usage',
                              ]}
                              labelFormatter={(timestamp) =>
                                formatTimestamp(timestamp, false)
                              }
                            />
                            <Area
                              type="monotone"
                              dataKey="value"
                              stroke="#1cc88a"
                              strokeWidth={3}
                              fill="url(#cpuGradient)"
                              dot={false}
                              activeDot={{
                                stroke: "#1cc88a",
                                strokeWidth: 2,
                                r: 6,
                                fill: "#fff",
                              }}
                            />
                          </AreaChart>
                        </ResponsiveContainer>
                      </div>
                    </Card.Body>
                  </Card>
                </Col>

                <Col md={4}>
                  <Card className="h-100 metrics-chart-card">
                    <Card.Body className="d-flex flex-column justify-content-center align-items-center">
                      <h3 className="metrics-card-title mb-3">{t('metrics.averageUsage')}</h3>
                      <div className="text-center">
                        <div
                          style={{
                            width: 180,
                            height: 180,
                            margin: "0 auto",
                            borderRadius: "50%",
                            padding: "8px",
                            border: `4px solid ${colorFor(cpuAverageValue, "cpu")}`,
                            animation:
                              levelFor(cpuAverageValue, "cpu") === "over"
                                ? 'pulse 2s infinite'
                                : 'none'
                          }}
                        >
                          <CircularProgressbar
                            value={cpuAverageValue}
                            text={`${Math.round(cpuAverageValue * 100) / 100}%`}
                            styles={buildStyles({
                              pathColor: colorFor(cpuAverageValue, "cpu"),
                              textColor: colorFor(cpuAverageValue, "cpu"),
                              trailColor: "#e3e6f0",
                              textSize: '16px',
                            })}
                          />
                        </div>
                        {/* The memory gauge carried a level badge and this one
                            did not, so the same reading read as judged on one
                            card and unjudged on the other. */}
                        <div className="mt-2">
                          <span
                            className={`badge bg-${variantFor(cpuAverageValue, "cpu")}`}
                            title={t('metrics.thresholdHint')}
                          >
                            {levelLabel(cpuAverageValue, "cpu")}
                          </span>
                        </div>
                      </div>
                    </Card.Body>
                  </Card>
                </Col>
              </Row>
            </div>
          )}

          {/* Empty state.
            * Without this the page rendered a back button, a title and a
            * filter label — verified by rendering the component with no data,
            * which produced exactly three words and no chart. A blank page
            * reads as a broken page, and it has two entirely different
            * causes worth telling apart: retention cleared the raw points
            * (routine, nothing to do) or nothing was ever collected (a
            * provider is probably not connected).
            * Gated on metricsLoaded so it does not flash during the fetch. */}
          {metricsLoaded &&
            memoryMetrics.length === 0 &&
            cpuMetrics.length === 0 &&
            (!hasInsights || metricsTrimmedAt) && (
            <div className="text-center py-5" data-testid="metrics-empty-state">
              <FiBarChart2 size={40} className="text-secondary mb-3" aria-hidden="true" />
              {metricsTrimmedAt ? (
                <>
                  <h5 className="fw-bold text-dark">{t('metrics.metricsTrimmedTitle')}</h5>
                  <p className="text-muted mx-auto" style={{ maxWidth: '38rem' }}>
                    {t('metrics.metricsTrimmedBody')}
                  </p>
                  <p className="small text-secondary mb-0">
                    {t('metrics.metricsTrimmedWhen', {
                      date: formatTimestamp(metricsTrimmedAt, false),
                    })}
                  </p>
                </>
              ) : (
                <>
                  <h5 className="fw-bold text-dark">{t('metrics.noMetricsTitle')}</h5>
                  <p className="text-muted mx-auto" style={{ maxWidth: '38rem' }}>
                    {t('metrics.noMetricsBody')}
                  </p>
                  <p className="small text-secondary mb-0">{t('metrics.noMetricsCta')}</p>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Metrics;
