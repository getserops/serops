/**
 * Batch Timeline — chronological unified event view (Item #12 UI).
 *
 * Renders every event across logs / metrics / code / cicd / traces
 * on a single view. Two tiers:
 *
 * 1. ``BatchTimelineChart`` at the top — SVG time-axis with per-kind
 *    lanes, hover tooltips, pan/zoom, and causal arrows from deploys
 *    to nearby error markers. This is the scan-friendly "what
 *    happened when" view (Batch 40 upgrade).
 * 2. Plain event list underneath — accessible fallback for screen
 *    readers, and a full-detail view for users who want to read
 *    every event's summary + linked resources.
 *
 * The event ``time`` field is the source's own timestamp — untrusted
 * user data — so all rendering paths parse via ``new Date()`` and
 * treat parse failures as "unknown time". React auto-escapes text.
 */

import PageHeader from "./PageHeader";
import React, { useEffect, useState } from 'react';
import { Container, Card, Badge, Alert, Spinner, Button } from 'react-bootstrap';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
    FaArrowLeft, FaClock, FaFileAlt, FaChartLine, FaCodeBranch,
    FaTools, FaProjectDiagram,
} from 'react-icons/fa';
import { useTranslation } from 'react-i18next';
import DataService from '../services/data.service';
import { tracePath } from '../utils/linkTargets';
import BatchTimelineChart from './BatchTimelineChart';
import './BatchTimeline.css';
import { formatAbsolute, formatRelative } from '../utils/dates';

const KIND_META = {
    log: {
        icon: <FaFileAlt />, colour: 'text-secondary', bg: 'bg-secondary',
    },
    metric_anomaly: {
        icon: <FaChartLine />, colour: 'text-warning', bg: 'bg-warning',
    },
    deploy: {
        icon: <FaCodeBranch />, colour: 'text-primary', bg: 'bg-primary',
    },
    cicd: {
        icon: <FaTools />, colour: 'text-danger', bg: 'bg-danger',
    },
    span_error: {
        icon: <FaProjectDiagram />, colour: 'text-danger', bg: 'bg-danger',
    },
};

const severityBadge = (severity) => {
    const map = {
        ERROR: 'danger', WARNING: 'warning', CRITICAL: 'danger',
        FATAL: 'danger', INFO: 'info',
    };
    const bg = map[severity] || 'secondary';
    return <Badge bg={bg} className="ms-2">{severity}</Badge>;
};

const formatTime = (iso) => formatRelative(iso);

const EventRow = ({ event }) => {
    const meta = KIND_META[event.kind] || KIND_META.log;
    return (
        <li className="d-flex mb-3">
            <div className={`me-3 mt-1 ${meta.colour}`} style={{ fontSize: 20 }}>
                {meta.icon}
            </div>
            <div className="flex-grow-1">
                <div className="d-flex justify-content-between align-items-start">
                    <div>
                        <Badge bg="light" text="dark" className="me-2 text-uppercase">
                            {event.kind.replace('_', ' ')}
                        </Badge>
                        {event.service && (
                            <span className="text-muted small me-2">{event.service}</span>
                        )}
                        {severityBadge(event.severity)}
                    </div>
                    <small className="text-muted" title={formatAbsolute(event.time, { fallback: '' })}><FaClock className="me-1" />{formatTime(event.time)}</small>
                </div>
                <div className="mt-1">{event.summary || '—'}</div>
                <EventDetail event={event} />
            </div>
        </li>
    );
};

const EventDetail = ({ event }) => {
    const { t } = useTranslation();
    const d = event.detail || {};
    if (event.kind === 'deploy' && d.sha) {
        return (
            <div className="small text-muted mt-1">
                <code>{d.sha}</code> — {t('timeline.authorOnBranch', { author: d.author, branch: d.branch || 'main' })}
                {d.files_changed ? ` — ${t('timeline.filesChanged', { n: d.files_changed })}` : ''}
            </div>
        );
    }
    if (event.kind === 'span_error' && d.trace_id) {
        return (
            <div className="small text-muted mt-1">
                {t('timeline.trace')}{' '}
                {/* A trace that was not stored has no page to open. */}
                {tracePath(d) ? (
                    <Link to={tracePath(d)} className="text-decoration-none">
                        <code>{String(d.trace_id).slice(0, 12)}…</code>
                    </Link>
                ) : (
                    <code>{String(d.trace_id).slice(0, 12)}…</code>
                )}
                {d.duration_ms != null ? ` — ${d.duration_ms}ms` : ''}
                {d.status_message ? ` — ${d.status_message}` : ''}
            </div>
        );
    }
    if (event.kind === 'metric_anomaly') {
        return (
            <div className="small text-muted mt-1">
                {t('timeline.duration')} {d.duration_seconds ? `${d.duration_seconds}s` : '—'}
            </div>
        );
    }
    if (event.kind === 'cicd' && d.trace_errors) {
        return (
            <div className="small text-muted mt-1 text-truncate" style={{ maxWidth: 700 }}>
                {d.trace_errors}
            </div>
        );
    }
    return null;
};

const BatchTimeline = () => {
    const { t } = useTranslation();
    const { batchId } = useParams();
    const navigate = useNavigate();

    const [payload, setPayload] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    // Set of event indexes that the chart's filters say are currently
    // visible. Null = no filter active (show everything). Populated
    // via the chart's onFilteredIndexesChange callback so the list
    // below the chart narrows in lockstep.
    const [filteredIndexes, setFilteredIndexes] = useState(null);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                setLoading(true);
                setError(null);
                const data = await DataService.getBatchTimeline(batchId);
                if (!cancelled) setPayload(data);
            } catch {
                if (!cancelled) setError(t('timeline.loadFailed'));
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => { cancelled = true; };
    }, [batchId, t]);

    if (loading) {
        return <div className="text-center py-5"><Spinner animation="border" /></div>;
    }
    if (error) {
        return (
            <Container className="py-4">
                <Button variant="outline-secondary" size="sm" onClick={() => navigate(-1)}>
                    <FaArrowLeft className="me-1" /> {t('common.back')}
                </Button>
                <Alert variant="danger" className="mt-3">{error}</Alert>
            </Container>
        );
    }

    const events = payload?.events || [];
    const causalPairs = payload?.causal_pairs || [];
    const listEvents = filteredIndexes
        ? events.map((e, i) => (filteredIndexes.has(i) ? e : null)).filter(Boolean)
        : events;
    const filterActive = filteredIndexes && filteredIndexes.size !== events.length;

    return (
        <Container fluid className="px-0">
            <PageHeader
                crumbs={[
                    { label: t('nav.analyses'), to: '/dash/data' },
                    { label: payload?.batch_id || batchId, to: `/dash/data/details/${payload?.batch_id || batchId}`, mono: true },
                    { label: t('timeline.title') },
                ]}
                title={t('timeline.title')}
                subtitle={(
                    <>
                        {t('timeline.eventCount', { count: events.length })}
                        {causalPairs.length > 0 && (
                            <span className="ms-3">{causalPairs.length === 1 ? t('timeline.causalPair', { n: causalPairs.length }) : t('timeline.causalPairs', { n: causalPairs.length })}</span>
                        )}
                    </>
                )}
            />

            {events.length === 0 ? (
                <div className="ds-card">
                    <div className="ds-empty-state">
                        <div className="ds-empty-state-icon">
                            <FaClock />
                        </div>
                        <div className="ds-empty-state-title">{t('timeline.emptyTitle')}</div>
                        <div className="ds-empty-state-body">
                            {t('timeline.empty')}
                        </div>
                    </div>
                </div>
            ) : (
                <>
                    {/* SVG chart — visual scan surface. */}
                    <Card className="mb-3">
                        <Card.Body>
                            <BatchTimelineChart
                                events={events}
                                causalPairs={causalPairs}
                                onFilteredIndexesChange={setFilteredIndexes}
                            />
                        </Card.Body>
                    </Card>

                    {/* Plain event list — accessibility fallback + detail view.
                        Narrows in lockstep with the chart's filters so the
                        two views never disagree on what the user is looking at. */}
                    <Card>
                        <Card.Header className="d-flex justify-content-between align-items-center py-2">
                            <span className="small text-muted text-uppercase fw-semibold">
                                {t('timeline.eventList', 'Event list')}
                                {filterActive && (
                                    <span className="text-primary ms-2">· {t('timeline.filtered')}</span>
                                )}
                            </span>
                            <span className="small text-muted">
                                {filterActive
                                    ? t('timeline.filteredCount', { shown: listEvents.length, total: events.length })
                                    : t('timeline.eventCount', { count: events.length })}
                            </span>
                        </Card.Header>
                        <Card.Body>
                            {listEvents.length === 0 ? (
                                <div className="text-muted small text-center py-3">
                                    {t('timeline.noMatch')}
                                </div>
                            ) : (
                                <ul className="list-unstyled mb-0">
                                    {listEvents.map((e, i) => (
                                        <EventRow key={`${e.time}-${e.kind}-${i}`} event={e} />
                                    ))}
                                </ul>
                            )}
                        </Card.Body>
                    </Card>
                </>
            )}
        </Container>
    );
};

export default BatchTimeline;
