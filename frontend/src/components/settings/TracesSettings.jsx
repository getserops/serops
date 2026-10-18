/**
 * Distributed Traces Settings — Ingest Key management
 *
 * Lists OTLP ingest keys for the caller's organisation. Admins can
 * create new keys (plaintext shown ONCE, GitHub-PAT model) and
 * revoke existing keys (soft-delete, audit trail preserved).
 */

import React, { useState, useEffect, useCallback } from 'react';
import PageHeader from '../PageHeader';
import { Link } from 'react-router-dom';
import { Button, Modal, Form, Spinner, Table, Alert } from 'react-bootstrap';
import {
    FaKey, FaPlus, FaTrash, FaCopy, FaExclamationTriangle, FaCheckCircle,
} from 'react-icons/fa';
import { toast } from 'react-toastify';
import { useTranslation } from 'react-i18next';
import TracesService from '../../services/traces.service';
import './SettingsLayout.css';

const TracesSettings = () => {
    const { t } = useTranslation();

    const [keys, setKeys] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // Create modal state
    const [showCreate, setShowCreate] = useState(false);
    const [newName, setNewName] = useState('');
    const [creating, setCreating] = useState(false);

    // Plaintext reveal state (shown once, after create).
    const [revealed, setRevealed] = useState(null);   // { plaintext, name, prefix }

    // Revoke confirmation state
    const [revoking, setRevoking] = useState(null);   // key row being revoked
    const [revokeBusy, setRevokeBusy] = useState(false);

    const loadKeys = useCallback(async () => {
        try {
            setLoading(true);
            setError(null);
            const data = await TracesService.IngestKeys.list();
            setKeys(Array.isArray(data) ? data : []);
        } catch (err) {
            setError(t('traces.settings.loadFailed'));
        } finally {
            setLoading(false);
        }
    }, [t]);

    useEffect(() => { loadKeys(); }, [loadKeys]);

    const handleCreate = async (event) => {
        event.preventDefault();
        const name = newName.trim();
        if (!name) return;
        try {
            setCreating(true);
            const result = await TracesService.IngestKeys.create(name);
            setRevealed({
                plaintext: result.plaintext,
                name: result.name,
                prefix: result.key_prefix,
            });
            setShowCreate(false);
            setNewName('');
            await loadKeys();
        } catch (err) {
            const detail = err?.response?.data?.error
                || err?.response?.data?.name?.[0]
                || t('traces.settings.createFailed');
            toast.error(detail);
        } finally {
            setCreating(false);
        }
    };

    const handleRevoke = async () => {
        if (!revoking) return;
        try {
            setRevokeBusy(true);
            await TracesService.IngestKeys.revoke(revoking.id);
            toast.success(t('traces.settings.revokeSuccess'));
            setRevoking(null);
            await loadKeys();
        } catch (err) {
            toast.error(t('traces.settings.revokeFailed'));
        } finally {
            setRevokeBusy(false);
        }
    };

    const copyPlaintext = async () => {
        if (!revealed?.plaintext) return;
        try {
            await navigator.clipboard.writeText(revealed.plaintext);
            toast.success(t('traces.settings.copied'));
        } catch {
            // Clipboard denied — user can still copy manually from the field.
            toast.info(t('traces.settings.copyFallback'));
        }
    };

    const formatDate = (iso) => {
        if (!iso) return '—';
        try { return new Date(iso).toLocaleString(); } catch { return iso; }
    };

    return (
        <div className="settings-section">
            <PageHeader
                title={t('traces.settings.title')}
                subtitle={t('traces.settings.subtitle')}
                actions={
                    <>
                    <Link to="/dash/traces" className="btn btn-secondary">
                        {t('traces.settings.viewReceived')}
                    </Link>
                    <Button variant="primary" onClick={() => setShowCreate(true)}>
                        <FaPlus className="me-1" /> {t('traces.settings.newKey')}
                    </Button>
                    </>
                }
            />

            {error && <Alert variant="danger">{error}</Alert>}

            {loading ? (
                <div className="text-center py-4">
                    <Spinner animation="border" size="sm" /> {t('common.loading')}
                </div>
            ) : keys.length === 0 ? (
                <div className="text-center py-5 text-muted">
                    <FaKey size={40} className="mb-2 opacity-50" />
                    <p>{t('traces.settings.noKeys')}</p>
                </div>
            ) : (
                <Table hover responsive className="table-stack settings-table ingest-keys-table">
                    <thead>
                        <tr>
                            <th>{t('traces.settings.name')}</th>
                            <th>{t('traces.settings.prefix')}</th>
                            <th>{t('traces.settings.status')}</th>
                            <th>{t('traces.settings.lastUsed')}</th>
                            <th>{t('traces.settings.created')}</th>
                            <th style={{ width: 80 }} />
                        </tr>
                    </thead>
                    <tbody>
                        {keys.map((k) => (
                            <tr key={k.id} className={k.is_active ? '' : 'text-muted'}>
                                <td>{k.name}</td>
                                <td><code>{k.key_prefix}…</code></td>
                                <td>
                                    {k.is_active
                                        ? <span className="badge bg-success">
                                            {t('traces.settings.active')}
                                        </span>
                                        : <span className="badge bg-secondary">
                                            {t('traces.settings.revoked')}
                                        </span>}
                                </td>
                                <td>{formatDate(k.last_used_at)}</td>
                                <td>{formatDate(k.created_at)}</td>
                                <td>
                                    {k.is_active && (
                                        <Button
                                            variant="outline-danger"
                                            size="sm"
                                            onClick={() => setRevoking(k)}
                                            title={t('traces.settings.revoke')}
                                        >
                                            <FaTrash />
                                        </Button>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </Table>
            )}

            {/* Create Modal */}
            <Modal show={showCreate} onHide={() => setShowCreate(false)} centered>
                <Form onSubmit={handleCreate}>
                    <Modal.Header closeButton>
                        <Modal.Title>{t('traces.settings.newKey')}</Modal.Title>
                    </Modal.Header>
                    <Modal.Body>
                        <Form.Group>
                            <Form.Label>{t('traces.settings.name')}</Form.Label>
                            <Form.Control
                                type="text"
                                value={newName}
                                onChange={(e) => setNewName(e.target.value)}
                                placeholder={t('traces.settings.namePlaceholder')}
                                maxLength={100}
                                autoFocus
                                required
                            />
                            <Form.Text className="text-muted">
                                {t('traces.settings.nameHelp')}
                            </Form.Text>
                        </Form.Group>
                    </Modal.Body>
                    <Modal.Footer>
                        <Button variant="secondary" onClick={() => setShowCreate(false)}>
                            {t('common.cancel')}
                        </Button>
                        <Button
                            variant="primary"
                            type="submit"
                            disabled={creating || !newName.trim()}
                        >
                            {creating
                                ? <><Spinner size="sm" animation="border" /> {t('traces.settings.creating')}</>
                                : t('traces.settings.create')}
                        </Button>
                    </Modal.Footer>
                </Form>
            </Modal>

            {/* Plaintext reveal — GitHub PAT-style one-time display. */}
            <Modal
                show={!!revealed}
                onHide={() => setRevealed(null)}
                centered
                backdrop="static"
            >
                <Modal.Header>
                    <Modal.Title>
                        <FaCheckCircle className="text-success me-2" />
                        {t('traces.settings.createdTitle')}
                    </Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <Alert variant="warning" className="d-flex align-items-start">
                        <FaExclamationTriangle className="me-2 mt-1 flex-shrink-0" />
                        <span>{t('traces.settings.copyWarning')}</span>
                    </Alert>

                    <Form.Label>{revealed?.name}</Form.Label>
                    <div className="d-flex gap-2">
                        <Form.Control
                            type="text"
                            value={revealed?.plaintext || ''}
                            readOnly
                            onFocus={(e) => e.target.select()}
                            style={{ fontFamily: 'monospace' }}
                        />
                        <Button variant="outline-primary" onClick={copyPlaintext}>
                            <FaCopy />
                        </Button>
                    </div>

                    <Form.Text className="text-muted">
                        {t('traces.settings.usageHint')}
                    </Form.Text>
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="primary" onClick={() => setRevealed(null)}>
                        {t('traces.settings.savedIt')}
                    </Button>
                </Modal.Footer>
            </Modal>

            {/* Revoke confirmation */}
            <Modal show={!!revoking} onHide={() => setRevoking(null)} centered>
                <Modal.Header closeButton>
                    <Modal.Title>{t('traces.settings.revokeTitle')}</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <p>{t('traces.settings.revokeConfirm', { name: revoking?.name || '' })}</p>
                    <Alert variant="warning" className="mb-0">
                        {t('traces.settings.revokeWarning')}
                    </Alert>
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="secondary" onClick={() => setRevoking(null)}>
                        {t('common.cancel')}
                    </Button>
                    <Button variant="danger" onClick={handleRevoke} disabled={revokeBusy}>
                        {revokeBusy
                            ? <><Spinner size="sm" animation="border" /> {t('traces.settings.revoking')}</>
                            : t('traces.settings.revoke')}
                    </Button>
                </Modal.Footer>
            </Modal>
        </div>
    );
};

export default TracesSettings;
