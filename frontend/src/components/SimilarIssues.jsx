/**
 * SimilarIssues — panel showing past resolved issues most like the
 * current one (Item #27). Renders inline on the ChatIssues detail.
 *
 * "We've seen this before" moment — surfaces the exact resolution
 * text from the prior incident so on-call can apply it directly.
 *
 * Empty state = the issue has no embedding yet (still being computed
 * async) OR there are no similar past resolutions. Both are fine to
 * show as "nothing yet" — no distinction needed for the user.
 */

import React, { useEffect, useState } from 'react';
import { Card, Badge, Spinner } from 'react-bootstrap';
import { FaLightbulb, FaClock } from 'react-icons/fa';
import { useTranslation } from 'react-i18next';
import dataService from '../services/data.service';

const formatDate = (iso) => {
    if (!iso) return '—';
    try { return new Date(iso).toLocaleString(); } catch { return iso; }
};

const SimilarIssues = ({ issueId }) => {
    const { t } = useTranslation();
    const [results, setResults] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (!issueId) return;
        let cancelled = false;
        (async () => {
            try {
                setLoading(true);
                const data = await dataService.getSimilarIssues(issueId, 5);
                if (!cancelled) setResults(data?.results || []);
            } catch {
                if (!cancelled) setResults([]);
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => { cancelled = true; };
    }, [issueId]);

    if (!issueId) return null;
    if (loading) return <div className="text-center py-2"><Spinner size="sm" animation="border" /></div>;
    if (results.length === 0) return null;   // hide when nothing to show

    return (
        <Card className="mt-3">
            <Card.Header className="d-flex align-items-center">
                <FaLightbulb className="me-2 text-warning" />
                <span className="fw-bold">{t('similarIssues.title')}</span>
                <Badge bg="light" text="dark" className="ms-2">{results.length}</Badge>
            </Card.Header>
            <Card.Body className="py-2">
                {results.map((r) => (
                    <div key={r.id} className="mb-3 pb-2 border-bottom">
                        <div className="d-flex align-items-center mb-1">
                            <Badge bg="info" className="me-2">
                                {Math.round(r.similarity * 100)}% match
                            </Badge>
                            <span className="text-muted small me-2">
                                {r.issue_type}
                            </span>
                            {r.component && (
                                <span className="text-muted small">· {r.component}</span>
                            )}
                            <span className="ms-auto text-muted small">
                                <FaClock size={10} className="me-1" />
                                {formatDate(r.resolved_at)}
                            </span>
                        </div>
                        {r.root_cause && (
                            <div className="small">
                                <strong>Root cause:</strong> {r.root_cause}
                            </div>
                        )}
                        {r.recommendation && (
                            <div className="small mt-1">
                                <strong>Then-fix:</strong> {r.recommendation}
                            </div>
                        )}
                    </div>
                ))}
            </Card.Body>
        </Card>
    );
};

export default SimilarIssues;
