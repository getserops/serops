/**
 * BatchTimelineChart — SVG time-axis visualisation for a batch's
 * unified event stream (Item #12, upgraded in Batches 40 + 42).
 *
 * Renders every event on a horizontal time axis with five vertical
 * lanes (one per event kind). Zoom via mouse wheel; pan by dragging
 * with plain click; brush-select a time range by shift-dragging so
 * the event list below the chart narrows to that window.
 *
 * Causal-arrow overlay is engine-backed (Batch 42) — it reads the
 * pre-computed ``causal_pairs`` prop rather than heuristically
 * inferring pairs on the frontend. Confidence label determines
 * stroke width + colour so HIGH-confidence causal chains stand out.
 * Hovering an arrow surfaces its type + note.
 *
 * Lane visibility toggles + severity floor filter let the user hide
 * noise (e.g. "just show me infra events") without leaving the
 * page. Filters affect the chart, the arrows (an arrow whose
 * endpoint is hidden is skipped), and the parent's event list via
 * the ``onFilteredIndexesChange`` callback.
 *
 * Pure SVG + React state. No d3 / vis-library dependency — keeps
 * the bundle lean and lets the whole thing stay auditable.
 * Accessibility: parent BatchTimeline keeps the plain event list
 * beneath the chart. Screen readers hit that list; sighted users
 * scan the chart.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Form } from 'react-bootstrap';
import { FaSearchPlus, FaSearchMinus, FaExpand } from 'react-icons/fa';

// Fixed order — determines lane stacking top-to-bottom.
const LANE_ORDER = ['deploy', 'cicd', 'metric_anomaly', 'span_error', 'log'];

const LANE_META = {
    deploy:         { label: 'Deploy',   colour: '#0d6efd' },  // primary blue
    cicd:           { label: 'CI/CD',    colour: '#fd7e14' },  // orange
    metric_anomaly: { label: 'Metric',   colour: '#ffc107' },  // warning yellow
    span_error:     { label: 'Trace',    colour: '#dc3545' },  // danger red
    log:            { label: 'Log',      colour: '#6c757d' },  // secondary grey
};

const SEVERITY_COLOUR = {
    CRITICAL: '#dc3545', FATAL: '#dc3545', ERROR: '#dc3545',
    WARN: '#fd7e14', WARNING: '#fd7e14',
    INFO: '#0dcaf0',
};

// Numeric rank for the "severity floor" filter dropdown.
const SEVERITY_RANK = {
    CRITICAL: 4, FATAL: 4,
    ERROR: 3,
    WARN: 2, WARNING: 2,
    INFO: 1,
};

// HIGH / MEDIUM / LOW → arrow visual treatment.
const CONF_STYLE = {
    HIGH:   { stroke: '#dc3545', width: 2.2, dash: '',        opacity: 1.0 },
    MEDIUM: { stroke: '#fd7e14', width: 1.6, dash: '5 3',     opacity: 0.85 },
    LOW:    { stroke: '#adb5bd', width: 1.2, dash: '3 3',     opacity: 0.65 },
};

const CHART_HEIGHT = 260;   // total svg height
const LANE_HEIGHT = 36;     // per-lane row height
const AXIS_HEIGHT = 28;     // bottom time-axis room
const MARGIN_LEFT = 96;     // room for lane labels
const MARGIN_RIGHT = 16;

// Parse ISO string → epoch ms. Returns null on failure so callers can
// skip malformed events rather than blowing up the whole chart.
const toEpoch = (iso) => {
    if (!iso) return null;
    const t = Date.parse(iso);
    return Number.isFinite(t) ? t : null;
};

const formatTick = (epoch, spanMs) => {
    const d = new Date(epoch);
    // Choose granularity by zoom span — no seconds when zoomed out.
    if (spanMs > 24 * 3600 * 1000) {
        return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:00`;
    }
    if (spanMs > 3600 * 1000) {
        return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
    }
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')}`;
};

const BatchTimelineChart = ({
    events,
    causalPairs = [],
    onFilteredIndexesChange,
}) => {
    const navigate = useNavigate();
    const containerRef = useRef(null);
    const [width, setWidth] = useState(1000);
    const [hover, setHover] = useState(null);             // {event | pair, x, y, kind}
    const [viewStart, setViewStart] = useState(null);     // epoch ms — visible window start
    const [viewEnd, setViewEnd] = useState(null);         // epoch ms — visible window end
    const [dragging, setDragging] = useState(null);       // {startPx, startEpoch}
    const [brushing, setBrushing] = useState(null);       // {startEpoch, endEpoch} — being drawn
    const [brushSelection, setBrushSelection] = useState(null); // {startEpoch, endEpoch} — locked
    // Lane visibility + severity floor filters. Lanes default to all-on.
    const [hiddenLanes, setHiddenLanes] = useState(() => new Set());
    const [severityFloor, setSeverityFloor] = useState('INFO'); // INFO | WARN | ERROR

    // Track container width so the chart is responsive without ResizeObserver churn.
    useEffect(() => {
        const el = containerRef.current;
        if (!el) return;
        const update = () => setWidth(Math.max(400, el.clientWidth));
        update();
        const ro = new ResizeObserver(update);
        ro.observe(el);
        return () => ro.disconnect();
    }, []);

    // Pre-compute normalised events + full time range.
    // ``_origIndex`` preserves the position in the original events[] so
    // parent components (which own the un-normalised list) can map
    // visibility state back correctly. Prior code used the normalised
    // array's own index which shifted when we dropped null-time events
    // — the parent then narrowed the wrong rows.
    const { normalised, dataStart, dataEnd } = useMemo(() => {
        const rows = (events || [])
            .map((e, i) => ({ ...e, _epoch: toEpoch(e.time), _origIndex: i }))
            .filter((e) => e._epoch !== null);
        if (rows.length === 0) {
            return { normalised: [], dataStart: null, dataEnd: null };
        }
        const min = Math.min(...rows.map((r) => r._epoch));
        const max = Math.max(...rows.map((r) => r._epoch));
        // Pad the range by 3% on each side so edge markers aren't clipped.
        const pad = Math.max(1000, Math.round((max - min) * 0.03));
        return { normalised: rows, dataStart: min - pad, dataEnd: max + pad };
    }, [events]);

    // Reset the view window whenever the data changes.
    useEffect(() => {
        setViewStart(dataStart);
        setViewEnd(dataEnd);
    }, [dataStart, dataEnd]);

    const plotWidth = Math.max(100, width - MARGIN_LEFT - MARGIN_RIGHT);
    const spanMs = viewStart != null && viewEnd != null ? viewEnd - viewStart : 0;

    // Time → px converter for the current zoom window.
    const timeToPx = useCallback(
        (epoch) => {
            if (!spanMs) return MARGIN_LEFT;
            return MARGIN_LEFT + ((epoch - viewStart) / spanMs) * plotWidth;
        },
        [viewStart, spanMs, plotWidth],
    );

    // Per-event filter mask. Hidden-lane and severity-floor state
    // determine whether each event is visible. Downstream: arrows
    // whose endpoint is filtered out get skipped, and the parent's
    // list narrows via onFilteredIndexesChange.
    const floorRank = SEVERITY_RANK[severityFloor] || 0;
    const eventVisible = useCallback(
        (ev) => {
            if (hiddenLanes.has(ev.kind)) return false;
            if (floorRank > 1) {
                const sev = String(ev.severity || 'INFO').toUpperCase();
                if ((SEVERITY_RANK[sev] || 0) < floorRank) return false;
            }
            if (brushSelection) {
                if (ev._epoch < brushSelection.startEpoch) return false;
                if (ev._epoch > brushSelection.endEpoch) return false;
            }
            return true;
        },
        [hiddenLanes, floorRank, brushSelection],
    );

    // Push filtered indexes to parent so the event list mirrors the chart.
    // Uses ``_origIndex`` (position in the un-normalised events array)
    // so the parent's mapping is correct even when normalised dropped
    // events with unparseable timestamps.
    //
    // Events dropped by normalisation (bad/missing timestamps) remain
    // visible in the parent's list — that's the honest behaviour, and
    // the backend now backfills to batch.timestamp so this should be
    // rare in practice.
    useEffect(() => {
        if (!onFilteredIndexesChange) return;
        // Start with every original index visible.
        const visible = new Set();
        (events || []).forEach((_, i) => visible.add(i));
        // Remove indexes that the chart's user-driven filters excluded.
        normalised.forEach((ev) => {
            if (!eventVisible(ev)) visible.delete(ev._origIndex);
        });
        onFilteredIndexesChange(visible);
    }, [events, normalised, eventVisible, onFilteredIndexesChange]);

    // Lanes present in the data (skip empty lanes so the chart stays compact).
    const activeLanes = useMemo(() => {
        const kinds = new Set(normalised.map((e) => e.kind));
        return LANE_ORDER.filter((k) => kinds.has(k));
    }, [normalised]);

    const laneY = (kind) => {
        const idx = activeLanes.indexOf(kind);
        return 12 + idx * LANE_HEIGHT + LANE_HEIGHT / 2;
    };

    const chartHeight = Math.max(
        CHART_HEIGHT,
        activeLanes.length * LANE_HEIGHT + AXIS_HEIGHT + 24,
    );

    // Time-axis ticks — 5 evenly spaced.
    const ticks = useMemo(() => {
        if (viewStart == null || viewEnd == null) return [];
        const N = 5;
        const step = spanMs / (N - 1);
        return Array.from({ length: N }, (_, i) => viewStart + step * i);
    }, [viewStart, viewEnd, spanMs]);

    // Zoom logic — scroll wheel zooms around the cursor's time position.
    const handleWheel = (e) => {
        if (!spanMs) return;
        e.preventDefault();
        const rect = e.currentTarget.getBoundingClientRect();
        const px = e.clientX - rect.left;
        const anchorFrac = Math.max(0, Math.min(1, (px - MARGIN_LEFT) / plotWidth));
        const anchorEpoch = viewStart + anchorFrac * spanMs;
        // deltaY > 0 = scroll down = zoom out.
        const factor = e.deltaY > 0 ? 1.25 : 0.8;
        let newSpan = Math.round(spanMs * factor);
        // Clamp so we don't zoom below 5s or beyond 2x the data range.
        const maxSpan = (dataEnd - dataStart) * 2;
        newSpan = Math.max(5000, Math.min(maxSpan, newSpan));
        const newStart = anchorEpoch - anchorFrac * newSpan;
        setViewStart(newStart);
        setViewEnd(newStart + newSpan);
    };

    const resetZoom = () => {
        setViewStart(dataStart);
        setViewEnd(dataEnd);
    };

    const zoomBy = (factor) => {
        if (!spanMs) return;
        const centre = (viewStart + viewEnd) / 2;
        const newSpan = Math.max(5000, Math.min((dataEnd - dataStart) * 2, spanMs * factor));
        setViewStart(centre - newSpan / 2);
        setViewEnd(centre + newSpan / 2);
    };

    // Convert an SVG-local x coordinate to an epoch ms in the current view.
    const pxToEpoch = (px) => viewStart + ((px - MARGIN_LEFT) / plotWidth) * spanMs;

    // Mouse down: shift-drag = brush, plain drag = pan.
    const handleMouseDown = (e) => {
        if (e.button !== 0) return;
        const rect = e.currentTarget.getBoundingClientRect();
        const px = e.clientX - rect.left;
        if (px < MARGIN_LEFT) return; // clicks on lane labels don't drag
        if (e.shiftKey) {
            const epoch = pxToEpoch(px);
            setBrushing({ startEpoch: epoch, endEpoch: epoch });
        } else {
            setDragging({ startPx: e.clientX, startEpoch: viewStart });
        }
    };

    const handleMouseMove = (e) => {
        if (brushing) {
            const rect = e.currentTarget.getBoundingClientRect();
            const px = Math.max(MARGIN_LEFT, Math.min(MARGIN_LEFT + plotWidth, e.clientX - rect.left));
            const epoch = pxToEpoch(px);
            setBrushing({ ...brushing, endEpoch: epoch });
            return;
        }
        if (!dragging || !spanMs) return;
        const dx = e.clientX - dragging.startPx;
        const dEpoch = -(dx / plotWidth) * spanMs;
        const newStart = dragging.startEpoch + dEpoch;
        setViewStart(newStart);
        setViewEnd(newStart + spanMs);
    };

    const handleMouseUp = () => {
        if (brushing) {
            // Commit the brush selection. If the drag was too short,
            // treat it as a click that clears any prior selection.
            const start = Math.min(brushing.startEpoch, brushing.endEpoch);
            const end = Math.max(brushing.startEpoch, brushing.endEpoch);
            if (end - start > 500) {
                setBrushSelection({ startEpoch: start, endEpoch: end });
            } else {
                setBrushSelection(null);
            }
            setBrushing(null);
        }
        setDragging(null);
    };

    const clearBrush = () => setBrushSelection(null);
    const toggleLane = (kind) => {
        setHiddenLanes((prev) => {
            const next = new Set(prev);
            if (next.has(kind)) next.delete(kind);
            else next.add(kind);
            return next;
        });
    };

    // Click handler for markers — jumps to the relevant detail page
    // (trace detail for span/log with trace_id).
    const handleMarkerClick = (event) => {
        const traceId = event?.detail?.trace_id;
        if (traceId) {
            navigate(`/dash/traces/${traceId}`);
        }
    };

    if (normalised.length === 0) {
        return (
            <div ref={containerRef} className="text-muted small text-center py-4">
                No events with parseable timestamps to plot.
            </div>
        );
    }

    return (
        <div ref={containerRef} className="batch-timeline-chart-wrap">
            {/* Toolbar row 1: interaction hint + zoom controls */}
            <div className="d-flex justify-content-between align-items-center mb-2 flex-wrap gap-2">
                <small className="text-muted">
                    Drag to pan · scroll to zoom · shift-drag to filter a window · click a trace marker to open it
                </small>
                <div className="btn-group btn-group-sm" role="group" aria-label="Timeline zoom">
                    <button type="button" className="btn btn-outline-secondary" onClick={() => zoomBy(0.7)} aria-label="Zoom in">
                        <FaSearchPlus />
                    </button>
                    <button type="button" className="btn btn-outline-secondary" onClick={() => zoomBy(1.4)} aria-label="Zoom out">
                        <FaSearchMinus />
                    </button>
                    <button type="button" className="btn btn-outline-secondary" onClick={resetZoom} aria-label="Fit to data">
                        <FaExpand />
                    </button>
                </div>
            </div>

            {/* Toolbar row 2: lane visibility + severity floor + brush reset */}
            <div className="d-flex justify-content-between align-items-center mb-2 flex-wrap gap-2 batch-timeline-filters">
                <div className="d-flex align-items-center gap-2 flex-wrap">
                    <span className="text-muted small me-1">Lanes:</span>
                    {activeLanes.map((k) => {
                        const on = !hiddenLanes.has(k);
                        return (
                            <button
                                key={k}
                                type="button"
                                onClick={() => toggleLane(k)}
                                className={`btn btn-sm ${on ? 'btn-outline-secondary active' : 'btn-outline-secondary text-muted'}`}
                                style={{
                                    borderColor: on ? LANE_META[k]?.colour : '#dee2e6',
                                    color: on ? LANE_META[k]?.colour : '#adb5bd',
                                    fontWeight: on ? 600 : 400,
                                    padding: '2px 10px',
                                }}
                                aria-pressed={on}
                                aria-label={`${on ? 'Hide' : 'Show'} ${LANE_META[k]?.label || k} lane`}
                            >
                                {LANE_META[k]?.label || k}
                            </button>
                        );
                    })}
                </div>
                <div className="d-flex align-items-center gap-2">
                    <Form.Select
                        size="sm"
                        style={{ width: 'auto' }}
                        value={severityFloor}
                        onChange={(e) => setSeverityFloor(e.target.value)}
                        aria-label="Severity floor"
                    >
                        <option value="INFO">All severities</option>
                        <option value="WARN">Warn & above</option>
                        <option value="ERROR">Errors only</option>
                    </Form.Select>
                    {brushSelection && (
                        <button
                            type="button"
                            className="btn btn-sm btn-outline-secondary"
                            onClick={clearBrush}
                            aria-label="Clear time-window filter"
                        >
                            Clear window
                        </button>
                    )}
                </div>
            </div>

            <svg
                width={width}
                height={chartHeight}
                onWheel={handleWheel}
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseUp={handleMouseUp}
                onMouseLeave={handleMouseUp}
                style={{
                    display: 'block',
                    background: 'var(--bs-body-bg, #fff)',
                    border: '1px solid var(--bs-border-color, #dee2e6)',
                    borderRadius: 6,
                    cursor: dragging ? 'grabbing' : 'grab',
                    userSelect: 'none',
                }}
                aria-label="Batch event timeline"
                role="img"
            >
                {/* Lane bands + labels */}
                {activeLanes.map((kind) => (
                    <g key={kind}>
                        <rect
                            x={MARGIN_LEFT}
                            y={laneY(kind) - LANE_HEIGHT / 2}
                            width={plotWidth}
                            height={LANE_HEIGHT}
                            fill={activeLanes.indexOf(kind) % 2 ? '#f8f9fa' : '#ffffff'}
                        />
                        <line
                            x1={MARGIN_LEFT}
                            x2={MARGIN_LEFT + plotWidth}
                            y1={laneY(kind) + LANE_HEIGHT / 2}
                            y2={laneY(kind) + LANE_HEIGHT / 2}
                            stroke="#e9ecef"
                        />
                        <text
                            x={MARGIN_LEFT - 8}
                            y={laneY(kind) + 4}
                            textAnchor="end"
                            fontSize="12"
                            fill={LANE_META[kind]?.colour || '#6c757d'}
                            fontWeight="600"
                        >
                            {LANE_META[kind]?.label || kind}
                        </text>
                    </g>
                ))}

                {/* Brush overlay — drawn behind arrows so they stay on top */}
                {(brushing || brushSelection) && spanMs > 0 && (() => {
                    const sel = brushing || brushSelection;
                    const start = Math.min(sel.startEpoch, sel.endEpoch);
                    const end = Math.max(sel.startEpoch, sel.endEpoch);
                    const x1 = Math.max(MARGIN_LEFT, timeToPx(start));
                    const x2 = Math.min(MARGIN_LEFT + plotWidth, timeToPx(end));
                    if (x2 <= x1) return null;
                    return (
                        <g key="brush">
                            <rect
                                x={x1}
                                y={4}
                                width={x2 - x1}
                                height={chartHeight - AXIS_HEIGHT - 4}
                                fill="#0d6efd"
                                opacity="0.10"
                                stroke="#0d6efd"
                                strokeWidth="1"
                                strokeDasharray="3 3"
                                pointerEvents="none"
                            />
                        </g>
                    );
                })()}

                {/* Causal arrows — engine-backed (from batch.data.
                    correlation_results) rather than a naive time-window
                    heuristic. Confidence label picks stroke width +
                    colour: HIGH=red solid, MEDIUM=orange dashed,
                    LOW=grey dotted. Skipped when either endpoint is
                    filtered out or outside the viewport. */}
                {causalPairs.map((pair, i) => {
                    const from = normalised[pair.from_index];
                    const to = normalised[pair.to_index];
                    if (!from || !to) return null;
                    if (!eventVisible(from) || !eventVisible(to)) return null;
                    if (hiddenLanes.has(from.kind) || hiddenLanes.has(to.kind)) return null;
                    const x1 = timeToPx(from._epoch);
                    const y1 = laneY(from.kind);
                    const x2 = timeToPx(to._epoch);
                    const y2 = laneY(to.kind);
                    if (x1 < MARGIN_LEFT - 40 && x2 < MARGIN_LEFT - 40) return null;
                    if (x1 > MARGIN_LEFT + plotWidth + 40 && x2 > MARGIN_LEFT + plotWidth + 40) return null;
                    const style = CONF_STYLE[pair.confidence] || CONF_STYLE.MEDIUM;
                    const dx = x2 - x1;
                    const path = `M ${x1} ${y1} C ${x1 + dx / 3} ${y1 - 24}, ${x2 - dx / 3} ${y2 - 24}, ${x2} ${y2}`;
                    return (
                        <g key={`arrow-${i}`}>
                            <path
                                d={path}
                                fill="none"
                                stroke={style.stroke}
                                strokeWidth={style.width}
                                strokeDasharray={style.dash}
                                opacity={style.opacity}
                                markerEnd={`url(#tl-arrow-${pair.confidence || 'MEDIUM'})`}
                                onMouseEnter={() => setHover({
                                    _pair: pair,
                                    x: (x1 + x2) / 2,
                                    y: Math.min(y1, y2) - 20,
                                })}
                                onMouseLeave={() => setHover(null)}
                                style={{ cursor: 'help' }}
                            >
                                <title>{`${pair.confidence || ''} · ${pair.type} — ${pair.note || ''}`}</title>
                            </path>
                        </g>
                    );
                })}

                <defs>
                    {Object.entries(CONF_STYLE).map(([conf, style]) => (
                        <marker
                            key={conf}
                            id={`tl-arrow-${conf}`}
                            viewBox="0 0 10 10"
                            refX="9"
                            refY="5"
                            markerWidth="6"
                            markerHeight="6"
                            orient="auto-start-reverse"
                        >
                            <path d="M 0 0 L 10 5 L 0 10 z" fill={style.stroke} />
                        </marker>
                    ))}
                </defs>

                {/* Event markers — hidden lanes + below-floor severities are dimmed
                    instead of removed so the chart's density doesn't jump when
                    the user toggles filters. Dimmed markers stay non-interactive. */}
                {normalised.map((event, i) => {
                    const x = timeToPx(event._epoch);
                    if (x < MARGIN_LEFT - 6 || x > MARGIN_LEFT + plotWidth + 6) return null;
                    if (hiddenLanes.has(event.kind)) return null;
                    const visible = eventVisible(event);
                    const y = laneY(event.kind);
                    const isRoot = event.kind === 'deploy' || event.kind === 'span_error';
                    const r = isRoot ? 7 : 5;
                    const fill = SEVERITY_COLOUR[event.severity] || LANE_META[event.kind]?.colour || '#6c757d';
                    return (
                        <circle
                            key={`m-${i}`}
                            cx={x}
                            cy={y}
                            r={r}
                            fill={fill}
                            stroke="#fff"
                            strokeWidth="1.5"
                            opacity={visible ? 1 : 0.18}
                            onMouseEnter={visible ? () => setHover({ event, x, y }) : undefined}
                            onMouseLeave={visible ? () => setHover(null) : undefined}
                            onClick={visible ? () => handleMarkerClick(event) : undefined}
                            style={{ cursor: (visible && event?.detail?.trace_id) ? 'pointer' : 'default' }}
                        >
                            <title>{`${event.kind} · ${event.summary || ''}`}</title>
                        </circle>
                    );
                })}

                {/* Time axis */}
                <g>
                    <line
                        x1={MARGIN_LEFT}
                        x2={MARGIN_LEFT + plotWidth}
                        y1={chartHeight - AXIS_HEIGHT}
                        y2={chartHeight - AXIS_HEIGHT}
                        stroke="#adb5bd"
                    />
                    {ticks.map((t, i) => {
                        const x = timeToPx(t);
                        return (
                            <g key={`tick-${i}`}>
                                <line
                                    x1={x} x2={x}
                                    y1={chartHeight - AXIS_HEIGHT}
                                    y2={chartHeight - AXIS_HEIGHT + 5}
                                    stroke="#6c757d"
                                />
                                <text
                                    x={x}
                                    y={chartHeight - AXIS_HEIGHT + 18}
                                    textAnchor="middle"
                                    fontSize="11"
                                    fill="#6c757d"
                                >
                                    {formatTick(t, spanMs)}
                                </text>
                            </g>
                        );
                    })}
                </g>
            </svg>

            {/* Tooltip — handles both event-marker hover and causal-arrow hover */}
            {hover && (
                <div
                    className="batch-timeline-tooltip"
                    style={{
                        position: 'absolute',
                        left: Math.min(hover.x + 12, (containerRef.current?.clientWidth || width) - 260),
                        top: hover.y + 12,
                        pointerEvents: 'none',
                    }}
                >
                    {hover._pair ? (
                        // Arrow hover
                        <>
                            <div className="fw-semibold small">
                                <span
                                    className="badge me-2"
                                    style={{ background: (CONF_STYLE[hover._pair.confidence] || CONF_STYLE.MEDIUM).stroke }}
                                >
                                    {hover._pair.confidence} confidence
                                </span>
                                <span className="text-muted small">{hover._pair.type}</span>
                            </div>
                            <div className="small mt-1">{hover._pair.note || '—'}</div>
                        </>
                    ) : (
                        // Event marker hover
                        <>
                            <div className="fw-semibold small">
                                <span
                                    className="badge me-2"
                                    style={{ background: LANE_META[hover.event.kind]?.colour || '#6c757d' }}
                                >
                                    {LANE_META[hover.event.kind]?.label || hover.event.kind}
                                </span>
                                {hover.event.severity && <span className="badge bg-light text-dark me-2">{hover.event.severity}</span>}
                                {hover.event.service && <span className="text-muted small">{hover.event.service}</span>}
                            </div>
                            <div className="small mt-1">{hover.event.summary || '—'}</div>
                            <div className="small text-muted mt-1">
                                {new Date(hover.event._epoch).toLocaleString()}
                            </div>
                        </>
                    )}
                </div>
            )}
        </div>
    );
};

export default BatchTimelineChart;
