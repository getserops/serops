/**
 * Trace Detail — span waterfall + attribute inspector
 *
 * Renders a proportional waterfall of spans within one trace.
 * Each row = one span, indented by parent depth, bar width scaled
 * to duration_ms / trace duration_ms. Click a span to open the
 * attribute + events inspector.
 *
 * Attribute values are user-supplied JSON from the OTLP producer.
 * We render them via ``JSON.stringify`` — no HTML interpolation —
 * so a hostile attribute cannot inject markup.
 */

import PageHeader from "./PageHeader";
import React, { useState, useEffect, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Spinner, Alert, Badge, Button, Table, Card } from 'react-bootstrap';
import { FaArrowLeft, FaExclamationCircle, FaTimes } from 'react-icons/fa';
import { useTranslation } from 'react-i18next';
import TracesService from '../services/traces.service';

const TraceDetail = () => {
    const { t } = useTranslation();
    const { traceId } = useParams();

    const [trace, setTrace] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [selected, setSelected] = useState(null);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                setLoading(true);
                setError(null);
                const data = await TracesService.Traces.get(traceId);
                if (!cancelled) setTrace(data);
            } catch (err) {
                if (!cancelled) {
                    setError(err?.response?.status === 404
                        ? t('traces.detail.notFound')
                        : t('traces.detail.loadFailed'));
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => { cancelled = true; };
    }, [traceId, t]);

    // Compute waterfall layout — offset % + width % for each span.
    const layout = useMemo(() => {
        if (!trace || !trace.spans?.length) return { rows: [], traceStartMs: 0, traceDurationMs: 1 };
        const traceStart = new Date(trace.start_time).getTime();
        const traceEnd = new Date(trace.end_time).getTime();
        const traceDur = Math.max(1, traceEnd - traceStart);

        // Parent → depth lookup, cached to avoid recomputation per row.
        const bySpanId = new Map(trace.spans.map((s) => [s.span_id, s]));
        const depthCache = new Map();
        const depthFor = (span, guard = 0) => {
            if (guard > 64) return 0;   // Cycle protection (untrusted input).
            if (depthCache.has(span.span_id)) return depthCache.get(span.span_id);
            let depth = 0;
            if (span.parent_span_id) {
                const parent = bySpanId.get(span.parent_span_id);
                if (parent) depth = depthFor(parent, guard + 1) + 1;
            }
            depthCache.set(span.span_id, depth);
            return depth;
        };

        const rows = trace.spans.map((span) => {
            const spanStart = new Date(span.start_time).getTime();
            const offsetMs = Math.max(0, spanStart - traceStart);
            const offsetPct = (offsetMs / traceDur) * 100;
            const widthPct = Math.max(0.5, (span.duration_ms / traceDur) * 100);
            return {
                ...span,
                depth: depthFor(span),
                offsetPct,
                widthPct: Math.min(100 - offsetPct, widthPct),
            };
        });

        return { rows, traceStartMs: traceStart, traceDurationMs: traceDur };
    }, [trace]);

    const barColor = (span) => {
        if (span.status_code === 'ERROR') return '#dc3545';
        if (span.service_name && trace?.root_service_name === span.service_name) return '#0d6efd';
        return '#6c757d';
    };

    const formatMs = (ms) => (
        ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`
    );

    if (loading) {
        return (
            <div className="text-center py-5">
                <Spinner animation="border" />
            </div>
        );
    }

    if (error) {
        return (
            <div className="p-4">
                <Link to="/dash/traces" className="btn btn-outline-secondary btn-sm mb-3">
                    <FaArrowLeft className="me-1" /> {t('traces.detail.back')}
                </Link>
                <Alert variant="danger">{error}</Alert>
            </div>
        );
    }

    if (!trace) return null;

    return (
        <div>
            <div className="d-flex justify-content-between align-items-start mb-3 flex-wrap gap-3">
                <PageHeader
                    className="mb-0"
                    crumbs={[
                        { label: t('traces.dashboard.title'), to: '/dash/traces' },
                        { label: trace.trace_id, mono: true },
                    ]}
                    title={trace.root_operation || t('traces.detail.unknownOp')}
                />
                <div className="text-end">
                    <div>
                        <Badge bg={trace.status_code === 'ERROR' ? 'danger' : 'success'} className="me-2">
                            {trace.status_code}
                        </Badge>
                        <span className="fw-bold">{formatMs(trace.duration_ms)}</span>
                    </div>
                    <div className="small text-muted">
                        {trace.span_count} {t('traces.detail.spans')}
                        {trace.error_span_count > 0 && (
                            <span className="text-danger ms-2">
                                <FaExclamationCircle /> {trace.error_span_count} {t('traces.detail.errors')}
                            </span>
                        )}
                    </div>
                </div>
            </div>

            <div className="d-flex gap-3">
                {/* Waterfall */}
                <Card className="flex-grow-1">
                    <Card.Body>
                        <Table borderless size="sm" className="mb-0 traces-waterfall">
                            <thead>
                                <tr>
                                    <th style={{ width: '40%' }}>{t('traces.detail.span')}</th>
                                    <th style={{ width: '10%' }}>{t('traces.detail.duration')}</th>
                                    <th>{t('traces.detail.timeline')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {layout.rows.map((row) => (
                                    <tr
                                        key={row.span_id}
                                        onClick={() => setSelected(row)}
                                        style={{ cursor: 'pointer' }}
                                        className={
                                            selected?.span_id === row.span_id ? 'table-active' : ''
                                        }
                                    >
                                        <td style={{ paddingLeft: `${row.depth * 16 + 8}px` }}>
                                            {row.status_code === 'ERROR' && (
                                                <FaExclamationCircle className="text-danger me-1" />
                                            )}
                                            <span className="text-muted small">{row.service_name || '—'}</span>
                                            {' '}
                                            <span>{row.operation_name}</span>
                                        </td>
                                        <td className="small">{formatMs(row.duration_ms)}</td>
                                        <td>
                                            <div style={{ position: 'relative', height: 18, background: '#f1f3f5', borderRadius: 4 }}>
                                                <div
                                                    style={{
                                                        position: 'absolute',
                                                        left: `${row.offsetPct}%`,
                                                        width: `${row.widthPct}%`,
                                                        top: 2,
                                                        bottom: 2,
                                                        background: barColor(row),
                                                        borderRadius: 3,
                                                    }}
                                                    title={`${row.operation_name} — ${formatMs(row.duration_ms)}`}
                                                />
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </Table>
                    </Card.Body>
                </Card>

                {/* Inspector */}
                {selected && (
                    <Card style={{ width: 380, flexShrink: 0 }}>
                        <Card.Header className="d-flex justify-content-between align-items-center">
                            <span className="text-truncate" title={selected.operation_name}>
                                {selected.operation_name}
                            </span>
                            <Button
                                variant="link"
                                size="sm"
                                className="p-0 text-muted"
                                onClick={() => setSelected(null)}
                            >
                                <FaTimes />
                            </Button>
                        </Card.Header>
                        <Card.Body>
                            <dl className="row small mb-3">
                                <dt className="col-5">{t('traces.detail.service')}</dt>
                                <dd className="col-7">{selected.service_name || '—'}</dd>
                                <dt className="col-5">{t('traces.detail.kind')}</dt>
                                <dd className="col-7">{selected.kind || '—'}</dd>
                                <dt className="col-5">{t('traces.detail.status')}</dt>
                                <dd className="col-7">
                                    {selected.status_code}
                                    {selected.status_message && (
                                        <div className="text-danger small">{selected.status_message}</div>
                                    )}
                                </dd>
                                <dt className="col-5">{t('traces.detail.duration')}</dt>
                                <dd className="col-7">{formatMs(selected.duration_ms)}</dd>
                            </dl>

                            <h6 className="small text-muted">{t('traces.detail.attributes')}</h6>
                            {Object.keys(selected.attributes || {}).length === 0 ? (
                                <p className="text-muted small">{t('traces.detail.noAttributes')}</p>
                            ) : (
                                <pre className="small bg-light p-2 rounded" style={{ maxHeight: 260, overflow: 'auto' }}>
                                    {JSON.stringify(selected.attributes, null, 2)}
                                </pre>
                            )}

                            {selected.events?.length > 0 && (
                                <>
                                    <h6 className="small text-muted mt-3">
                                        {t('traces.detail.events')} ({selected.events.length})
                                    </h6>
                                    <pre className="small bg-light p-2 rounded" style={{ maxHeight: 200, overflow: 'auto' }}>
                                        {JSON.stringify(selected.events, null, 2)}
                                    </pre>
                                </>
                            )}
                        </Card.Body>
                    </Card>
                )}
            </div>
        </div>
    );
};

export default TraceDetail;
