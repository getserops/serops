/**
 * PostmortemModal — generates + shows the AI-drafted post-mortem for
 * a batch (Item #28). Triggered from the batch detail page.
 *
 * The backend returns markdown; we render as `<pre>` (monospace,
 * preserves headings + lists) with a copy-to-clipboard button.
 *
 * Security: markdown is AI-generated but derived from batch data
 * that already went through PII redaction. Rendered as text
 * content (React auto-escapes) — no HTML interpretation.
 */

import React, { useState } from 'react';
import { Modal, Button, Spinner, Alert } from 'react-bootstrap';
import { FaFileAlt, FaCopy, FaSyncAlt } from 'react-icons/fa';
import { toast } from 'react-toastify';
import { useTranslation } from 'react-i18next';
import dataService from '../services/data.service';

const PostmortemModal = ({ show, onHide, batchId }) => {
    const { t } = useTranslation();
    const [markdown, setMarkdown] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const generate = async () => {
        try {
            setLoading(true);
            setError(null);
            const data = await dataService.generatePostmortem(batchId);
            setMarkdown(data?.markdown || '');
        } catch (err) {
            const msg = err?.response?.data?.error || t('postmortem.generateFailed');
            setError(msg);
        } finally {
            setLoading(false);
        }
    };

    // Kick off generation on first open. Re-runs on demand via the button.
    React.useEffect(() => {
        if (show && !markdown && !loading) {
            generate();
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [show]);

    const handleCopy = async () => {
        try {
            await navigator.clipboard.writeText(markdown);
            toast.success(t('postmortem.copied'));
        } catch {
            toast.info(t('postmortem.copyFallback'));
        }
    };

    return (
        <Modal show={show} onHide={onHide} size="lg" centered>
            <Modal.Header closeButton>
                <Modal.Title>
                    <FaFileAlt className="me-2 text-primary" />
                    {t('postmortem.title')}
                </Modal.Title>
            </Modal.Header>
            <Modal.Body>
                {error && <Alert variant="danger">{error}</Alert>}
                {loading ? (
                    <div className="text-center py-5">
                        <Spinner animation="border" />
                        <div className="mt-2 text-muted small">
                            {t('postmortem.generating')}
                        </div>
                    </div>
                ) : (
                    <pre
                        style={{
                            whiteSpace: 'pre-wrap',
                            maxHeight: '60vh',
                            overflowY: 'auto',
                            fontSize: '0.85rem',
                            background: 'var(--bg-sunken)',
                            color: 'var(--text-primary)',
                            padding: '12px',
                            borderRadius: '4px',
                        }}
                    >{markdown || t('postmortem.empty')}</pre>
                )}
            </Modal.Body>
            <Modal.Footer>
                <Button variant="outline-secondary" onClick={generate} disabled={loading}>
                    <FaSyncAlt className="me-1" /> {t('postmortem.regenerate')}
                </Button>
                <Button variant="primary" onClick={handleCopy} disabled={loading || !markdown}>
                    <FaCopy className="me-1" /> {t('postmortem.copy')}
                </Button>
                <Button variant="secondary" onClick={onHide}>
                    {t('common.close')}
                </Button>
            </Modal.Footer>
        </Modal>
    );
};

export default PostmortemModal;
