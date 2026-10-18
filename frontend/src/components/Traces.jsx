/**
 * Traces Dashboard — list view
 *
 * Shows the most recent traces for the caller's org with filters
 * (service, status, min duration, time range). Rows link to the
 * trace detail waterfall.
 */

import PageHeader from "./PageHeader";
import React, { useState, useEffect, useCallback } from 'react';
import { Table, Form, Button, Spinner, Alert, Badge } from 'react-bootstrap';
import { FaProjectDiagram, FaFilter, FaSyncAlt, FaExclamationCircle } from 'react-icons/fa';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import TracesService from '../services/traces.service';

const EMPTY_FILTERS = {
    service: '',
    status: '',
    min_duration_ms: '',
    since: '',
    until: '',
    page: 1,
};

const Traces = () => {
    const { t } = useTranslation();

    const [traces, setTraces] = useState([]);
    const [pageInfo, setPageInfo] = useState({ count: 0, next: null, previous: null });
    const [services, setServices] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const [filters, setFilters] = useState(EMPTY_FILTERS);

    const load = useCallback(async () => {
        try {
            setLoading(true);
            setError(null);
            const data = await TracesService.Traces.list(filters);
            setTraces(data.results || []);
            setPageInfo({
                count: data.count || 0,
                next: data.next,
                previous: data.previous,
            });
        } catch (err) {
            setError(t('traces.dashboard.loadFailed'));
        } finally {
            setLoading(false);
        }
    }, [filters, t]);

    useEffect(() => { load(); }, [load]);

    useEffect(() => {
        (async () => {
            try {
                const names = await TracesService.Traces.services();
                setServices(Array.isArray(names) ? names : []);
            } catch {
                // Non-fatal — filter dropdown just falls back to text.
            }
        })();
    }, []);

    const applyFilters = (event) => {
        event.preventDefault();
        setFilters((prev) => ({ ...prev, page: 1 }));
        // Effect re-fires from filter dep change.
    };

    const resetFilters = () => setFilters(EMPTY_FILTERS);

    const statusBadge = (status) => {
        const map = {
            OK: { bg: 'success', text: 'OK' },
            ERROR: { bg: 'danger', text: 'ERROR' },
            UNSET: { bg: 'secondary', text: 'UNSET' },
        };
        const meta = map[status] || map.UNSET;
        return <Badge bg={meta.bg}>{meta.text}</Badge>;
    };

    const formatMs = (ms) => (
        ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`
    );

    // Match the rest of the app: relative time for freshness, one
    // format everywhere. Replaces the previous per-row 9/13/2026,
    // 7:24:02 PM absolute stamps that clashed with the "3 days ago"
    // style Issues, Batches and Dashboard use.
    const formatDate = (iso) => {
        if (!iso) return '—';
        try {
            const then = new Date(iso);
            if (Number.isNaN(then.getTime())) return iso;
            const diff = Math.max(1, Math.floor((Date.now() - then.getTime()) / 1000));
            if (diff < 60)    return `${diff}s ago`;
            if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`;
            if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
            if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
            return then.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
        } catch { return iso; }
    };

    return (
        <div>
            <PageHeader
                title={t('traces.dashboard.title')}
                actions={(
                    <Button variant="outline-secondary" onClick={load} disabled={loading}>
                        <FaSyncAlt className={loading ? 'fa-spin' : ''} aria-hidden="true" />
                        {t('traces.dashboard.refresh')}
                    </Button>
                )}
            />

            {error && <Alert variant="danger">{error}</Alert>}

            <div className="ds-card traces-card">
            <Form onSubmit={applyFilters} className="traces-filters">
                <div className="row g-2 align-items-end">
                    <div className="col-md-3">
                        <Form.Label className="mb-1 small" htmlFor="traces-service">{t('traces.dashboard.service')}</Form.Label>
                        <Form.Select id="traces-service"
                            value={filters.service}
                            onChange={(e) => setFilters({ ...filters, service: e.target.value, page: 1 })}
                        >
                            <option value="">{t('traces.dashboard.allServices')}</option>
                            {services.map((s) => <option key={s} value={s}>{s}</option>)}
                        </Form.Select>
                    </div>
                    <div className="col-md-2">
                        <Form.Label className="mb-1 small" htmlFor="traces-status">{t('traces.dashboard.status')}</Form.Label>
                        <Form.Select id="traces-status"
                            value={filters.status}
                            onChange={(e) => setFilters({ ...filters, status: e.target.value, page: 1 })}
                        >
                            <option value="">{t('traces.dashboard.all')}</option>
                            <option value="OK">OK</option>
                            <option value="ERROR">ERROR</option>
                            <option value="UNSET">UNSET</option>
                        </Form.Select>
                    </div>
                    <div className="col-md-2">
                        <Form.Label className="mb-1 small" htmlFor="traces-min-duration">{t('traces.dashboard.minDuration')}</Form.Label>
                        <Form.Control
                            id="traces-min-duration"
                            type="number"
                            min="0"
                            value={filters.min_duration_ms}
                            onChange={(e) => setFilters({ ...filters, min_duration_ms: e.target.value, page: 1 })}
                            placeholder="ms"
                        />
                    </div>
                    <div className="col-md-2">
                        <Form.Label className="mb-1 small" htmlFor="traces-since">{t('traces.dashboard.since')}</Form.Label>
                        <Form.Control
                            id="traces-since"
                            type="datetime-local"
                            value={filters.since}
                            onChange={(e) => setFilters({ ...filters, since: e.target.value, page: 1 })}
                        />
                    </div>
                    <div className="col-md-2">
                        <Form.Label className="mb-1 small" htmlFor="traces-until">{t('traces.dashboard.until')}</Form.Label>
                        <Form.Control
                            id="traces-until"
                            type="datetime-local"
                            value={filters.until}
                            onChange={(e) => setFilters({ ...filters, until: e.target.value, page: 1 })}
                        />
                    </div>
                    <div className="col-md-1 d-grid">
                        <Button variant="outline-secondary" type="button" onClick={resetFilters}
                                aria-label={t('traces.dashboard.resetFilters')} title={t('traces.dashboard.resetFilters')}>
                            <FaFilter />
                        </Button>
                    </div>
                </div>
            </Form>

            {loading ? (
                <div className="text-center py-5">
                    <Spinner animation="border" />
                </div>
            ) : traces.length === 0 ? (
                <div className="text-center py-5 text-muted">
                    <FaProjectDiagram size={48} className="mb-3 opacity-50" />
                    <p>{t('traces.dashboard.empty')}</p>
                    <p className="small">{t('traces.dashboard.emptyHint')}</p>
                </div>
            ) : (
                <>
                    <Table hover responsive className="align-middle table-stack">
                        <thead>
                            <tr>
                                <th>{t('traces.dashboard.trace')}</th>
                                <th>{t('traces.dashboard.service')}</th>
                                <th>{t('traces.dashboard.operation')}</th>
                                <th>{t('traces.dashboard.duration')}</th>
                                <th>{t('traces.dashboard.spans')}</th>
                                <th>{t('traces.dashboard.status')}</th>
                                <th>{t('traces.dashboard.startedAt')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {traces.map((tr) => (
                                <tr key={tr.trace_id}>
                                    <td data-label={t('traces.dashboard.trace')}>
                                        <Link
                                            to={`/dash/traces/${tr.trace_id}`}
                                            className="text-decoration-none"
                                        >
                                            <code>{tr.trace_id.slice(0, 16)}…</code>
                                        </Link>
                                    </td>
                                    <td data-label={t('traces.dashboard.service')}>{tr.root_service_name || '—'}</td>
                                    <td data-label={t('traces.dashboard.operation')} className="text-truncate" style={{ maxWidth: 280 }}>
                                        {tr.root_operation || '—'}
                                    </td>
                                    <td data-label={t('traces.dashboard.duration')}>{formatMs(tr.duration_ms)}</td>
                                    <td data-label={t('traces.dashboard.spans')}>
                                        {tr.span_count}
                                        {tr.error_span_count > 0 && (
                                            <span className="text-danger ms-2 small">
                                                <FaExclamationCircle /> {tr.error_span_count}
                                            </span>
                                        )}
                                    </td>
                                    <td data-label={t('traces.dashboard.status')}>{statusBadge(tr.status_code)}</td>
                                    <td data-label={t('traces.dashboard.startedAt')} className="small text-muted">{formatDate(tr.start_time)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </Table>

                    <div className="ds-table-footer">
                        <span>
                            {t('traces.dashboard.total', { count: pageInfo.count })}
                        </span>
                        <div>
                            <Button
                                variant="outline-secondary"
                                size="sm"
                                className="me-2"
                                disabled={!pageInfo.previous || loading}
                                onClick={() => setFilters({ ...filters, page: (filters.page || 1) - 1 })}
                            >
                                {t('traces.dashboard.prev')}
                            </Button>
                            <Button
                                variant="outline-secondary"
                                size="sm"
                                disabled={!pageInfo.next || loading}
                                onClick={() => setFilters({ ...filters, page: (filters.page || 1) + 1 })}
                            >
                                {t('traces.dashboard.next')}
                            </Button>
                        </div>
                    </div>
                </>
            )}
            </div>
        </div>
    );
};

export default Traces;
