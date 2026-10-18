/**
 * Per-batch traces view.
 *
 * Reads ``batch.data.traces`` — the snapshot written at batch
 * creation time. Same shape whether the source was our native OTLP
 * store or a pull adapter (Jaeger / Zipkin / Datadog APM), so this
 * component stays source-agnostic.
 *
 * When ``batch.data.traces`` is missing (legacy pre-#10.5 batches or
 * a snapshot skipped because of an adapter error) we render an
 * "unavailable" empty state — never a spurious "0 traces" claim.
 */

import PageHeader from "./PageHeader";
import React, { useEffect, useState } from 'react';
import { Container, Card, Table, Badge, Alert, Spinner, Button } from 'react-bootstrap';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
    FaArrowLeft, FaProjectDiagram, FaExclamationCircle, FaStopwatch, FaDatabase,
} from 'react-icons/fa';
import { useTranslation } from 'react-i18next';
import DataService from '../services/data.service';

const formatMs = (ms) => (
    ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`
);

const BatchTraces = () => {
    const { t } = useTranslation();
    const { batchId } = useParams();
    const navigate = useNavigate();

    const [batch, setBatch] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                setLoading(true);
                setError(null);
                const data = await DataService.getBatchDetails(batchId);
                if (!cancelled) setBatch(data);
            } catch {
                if (!cancelled) setError(t('batchTraces.loadFailed'));
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => { cancelled = true; };
    }, [batchId, t]);

    if (loading) {
        return (
            <div className="text-center py-5">
                <Spinner animation="border" />
            </div>
        );
    }

    if (error || !batch) {
        return (
            <Container className="py-4">
                <Button variant="outline-secondary" size="sm" onClick={() => navigate(-1)}>
                    <FaArrowLeft className="me-1" /> {t('common.back')}
                </Button>
                <Alert variant="danger" className="mt-3">{error || t('batchTraces.notFound')}</Alert>
            </Container>
        );
    }

    // batch.data.traces is exactly the shape ai_model.trace_context
    // produces server-side. Any missing key → "unavailable" empty state.
    const summary = batch?.data?.traces;

    return (
        <Container fluid className="px-0">
            <PageHeader
                crumbs={[
                    { label: t('nav.analyses'), to: '/dash/data' },
                    { label: batch.batch_id, to: `/dash/data/details/${batch.batch_id}`, mono: true },
                    { label: t('batchTraces.title') },
                ]}
                title={t('batchTraces.title')}
            />

            {!summary ? (
                <Alert variant="secondary" className="d-flex align-items-center">
                    <FaProjectDiagram className="me-2" />
                    <div>
                        <div className="fw-bold">{t('batchTraces.noSnapshot')}</div>
                        <small>{t('batchTraces.noSnapshotHint')}</small>
                    </div>
                </Alert>
            ) : summary.span_count === 0 ? (
                <Alert variant="info">{t('batchTraces.emptyWindow')}</Alert>
            ) : (
                <>
                    <div className="row g-3 mb-4">
                        <StatCard
                            icon={<FaProjectDiagram />}
                            label={t('batchTraces.traces')}
                            value={summary.trace_count || 0}
                        />
                        <StatCard
                            icon={<FaStopwatch />}
                            label={t('batchTraces.spans')}
                            value={summary.span_count || 0}
                        />
                        <StatCard
                            icon={<FaExclamationCircle className="text-danger" />}
                            label={t('batchTraces.errors')}
                            value={summary.error_span_count || 0}
                            danger={summary.error_span_count > 0}
                        />
                        <StatCard
                            icon={<FaDatabase className="text-secondary" aria-hidden="true" />}
                            label={t('batchTraces.source')}
                            value={summary.source || 'otlp'}
                        />
                    </div>

                    {summary.services_touched?.length > 0 && (
                        <p className="text-muted small mb-3">
                            {t('batchTraces.services')}:{' '}
                            {summary.services_touched.map((svc) => (
                                <Badge bg="light" text="dark" key={svc} className="me-1">{svc}</Badge>
                            ))}
                        </p>
                    )}

                    {summary.top_slow?.length > 0 && (
                        <Card className="mb-3">
                            <Card.Header>{t('batchTraces.topSlow')}</Card.Header>
                            <Card.Body className="p-0 batch-traces-table">
                                <SpanTable rows={summary.top_slow} />
                            </Card.Body>
                        </Card>
                    )}

                    {summary.top_errors?.length > 0 && (
                        <Card className="mb-3">
                            <Card.Header>{t('batchTraces.topErrors')}</Card.Header>
                            <Card.Body className="p-0 batch-traces-table">
                                <SpanTable rows={summary.top_errors} showMessage />
                            </Card.Body>
                        </Card>
                    )}
                </>
            )}
        </Container>
    );
};

const StatCard = ({ icon, label, value, danger }) => (
    <div className="col-md-3">
        <Card className={danger ? 'border-danger' : ''}>
            <Card.Body>
                <div className="d-flex justify-content-between align-items-center">
                    <div>
                        <div className="text-muted small">{label}</div>
                        <div className="h4 mb-0">{value}</div>
                    </div>
                    <div className="fs-3 text-secondary">{icon}</div>
                </div>
            </Card.Body>
        </Card>
    </div>
);

const SpanTable = ({ rows, showMessage }) => (
    <Table hover responsive size="sm" className="mb-0 table-stack">
        <thead>
            <tr>
                <th>Service</th>
                <th>Operation</th>
                {showMessage && <th>Message</th>}
                <th>Duration</th>
                <th>Trace</th>
            </tr>
        </thead>
        <tbody>
            {rows.map((span, i) => (
                <tr key={`${span.trace_id}-${i}`}>
                    <td>{span.service_name || '—'}</td>
                    <td className="text-truncate" style={{ maxWidth: 260 }}>
                        {span.operation_name || '—'}
                    </td>
                    {showMessage && (
                        <td className="text-danger small text-truncate" style={{ maxWidth: 220 }}>
                            {span.status_message || '—'}
                        </td>
                    )}
                    <td>{typeof span.duration_ms === 'number' ? formatMs(span.duration_ms) : '—'}</td>
                    <td>
                        {span.trace_id ? (
                            <Link to={`/dash/traces/${span.trace_id}`} className="text-decoration-none">
                                <code>{String(span.trace_id).slice(0, 12)}…</code>
                            </Link>
                        ) : '—'}
                    </td>
                </tr>
            ))}
        </tbody>
    </Table>
);

export default BatchTraces;
